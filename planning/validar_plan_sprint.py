#!/usr/bin/env python3
"""Validador del contrato de datos del plan de sprint.

Capa 1: JSON Schema 2020-12.
Capa 2: reglas semánticas (aritmética de capacidad, calendario, dependencias,
        burndown, punto de control, hoja de ruta, alineación con el contrato de ingesta).
Salida: hito público del sprint (solo campos x-admision = cadena | cadena_huella),
        serializado de forma canónica, con su SHA-256.

Uso:
    python3 validar_plan_sprint.py sprint_S01_2026-09-21.json
    python3 validar_plan_sprint.py --pruebas
Requiere: pip install "jsonschema[format]"
"""
import copy
import hashlib
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

BASE = Path(__file__).resolve().parent
ESQUEMA = json.loads((BASE / "plan_sprint_pp.schema.json").read_text(encoding="utf-8"))
ESQUEMA_INGESTA = BASE.parent / "data-contract" / "ingesta_documento_pp.schema.json"
ADMITIDOS = {"cadena", "cadena_huella"}
PATRON_PERSONAL = re.compile(r"(?i)(nombre|apellido|correo|email|telefono|dni|documento_identidad|tarifa|sueldo|honorario|remuneracion)")
DIAS = ["lun", "mar", "mie", "jue", "vie", "sab", "dom"]


# ---------- utilidades de esquema ----------
def resolver(nodo):
    while isinstance(nodo, dict) and "$ref" in nodo:
        destino = ESQUEMA
        for parte in nodo["$ref"].lstrip("#/").split("/"):
            destino = destino[parte]
        nodo = {**destino, **{k: v for k, v in nodo.items() if k != "$ref"}}
    return nodo


def tiene_admitidos(esquema, vistos=None):
    vistos = vistos or set()
    if id(esquema) in vistos:
        return False
    vistos.add(id(esquema))
    s = resolver(esquema)
    if s.get("x-admision") in ADMITIDOS:
        return True
    hijos = list(s.get("properties", {}).values())
    if isinstance(s.get("items"), dict):
        hijos.append(s["items"])
    return any(tiene_admitidos(h, vistos) for h in hijos)


def extraer(valor, esquema):
    s = resolver(esquema)
    adm = s.get("x-admision")
    if adm in ADMITIDOS:
        return valor, True
    if adm in {"fuera_de_cadena", "prohibido"}:
        return None, False
    if isinstance(valor, dict) and "properties" in s:
        salida = {}
        for k, v in valor.items():
            if k in s["properties"]:
                r, inc = extraer(v, s["properties"][k])
                if inc:
                    salida[k] = r
        return salida, bool(salida)
    if isinstance(valor, list) and isinstance(s.get("items"), dict) and tiene_admitidos(s["items"]):
        return [r for r, inc in (extraer(e, s["items"]) for e in valor) if inc], True
    return None, False  # privacidad por defecto


def canonico(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def claves_personales(obj, ruta="$"):
    hallazgos = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if PATRON_PERSONAL.search(k):
                hallazgos.append(f"{ruta}.{k}")
            hallazgos += claves_personales(v, f"{ruta}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            hallazgos += claves_personales(v, f"{ruta}[{i}]")
    return hallazgos


# ---------- calendario ----------
def dias_habiles(inicio, fin, laborables, feriados):
    d, salida = inicio, []
    while d <= fin:
        if DIAS[d.weekday()] in laborables and d not in feriados:
            salida.append(d)
        d += timedelta(days=1)
    return salida


def siguiente_habil(d, laborables, feriados):
    d += timedelta(days=1)
    while DIAS[d.weekday()] not in laborables or d in feriados:
        d += timedelta(days=1)
    return d


# ---------- reglas semánticas ----------
def reglas_semanticas(doc):
    E, A = [], []  # errores, avisos
    E += [f"Campo con posible dato personal: {r}" for r in claves_personales(doc)]

    cal = doc["calendario"]
    laborables = cal["dias_laborables"]
    feriados = {date.fromisoformat(f["fecha"]) for f in cal["feriados"]}
    sp, cap = doc["sprint"], doc["capacidad"]
    ini, fin = date.fromisoformat(sp["fecha_inicio"]), date.fromisoformat(sp["fecha_fin"])
    habiles = dias_habiles(ini, fin, laborables, feriados)

    # S1 calendario del sprint
    if len(habiles) != sp["dias_habiles"]:
        E.append(f"S1 dias_habiles declarados {sp['dias_habiles']} ≠ calculados {len(habiles)}")
    if len(habiles) < 10 and not sp["excepcion_duracion"]["es_excepcion"]:
        E.append("S1 sprint menor a dos semanas sin declararse como excepción")

    # S2 aritmética de capacidad
    brutas = len(habiles) * cap["horas_por_dia"]
    ceremonias = sum(c["horas"] for c in cap["ceremonias"])
    if cap["horas_brutas"] != brutas:
        E.append(f"S2 horas_brutas {cap['horas_brutas']} ≠ {brutas}")
    if cap["horas_netas"] != cap["horas_brutas"] - ceremonias:
        E.append(f"S2 horas_netas {cap['horas_netas']} ≠ brutas − ceremonias ({cap['horas_brutas'] - ceremonias})")
    if abs(cap["colchon_horas"] - cap["horas_netas"] * cap["colchon_porcentaje"]) > 1:
        E.append(f"S2 colchón {cap['colchon_horas']} h no corresponde a {cap['colchon_porcentaje']:.0%} de {cap['horas_netas']} h")
    if cap["horas_comprometidas"] != cap["horas_netas"] - cap["colchon_horas"]:
        E.append("S2 horas_comprometidas ≠ netas − colchón")

    historias = {h["id"]: h for h in doc["backlog"]}
    comprometidas = {i: h for i, h in historias.items() if h["comprometida"]}
    if sum(h["horas_estimadas"] for h in comprometidas.values()) != cap["horas_comprometidas"]:
        E.append(f"S2 suma de historias comprometidas ({sum(h['horas_estimadas'] for h in comprometidas.values())}) ≠ horas_comprometidas ({cap['horas_comprometidas']})")

    # S3 plan diario: fechas, carga y ceremonias
    plan = doc["plan_diario"]
    fechas_plan = [date.fromisoformat(d["fecha"]) for d in plan]
    if fechas_plan != habiles:
        E.append(f"S3 el plan diario no cubre exactamente los días hábiles del sprint: {[str(f) for f in fechas_plan]}")
    for d in plan:
        carga = sum(a["horas"] for a in d["asignaciones"]) + sum(c["horas"] for c in d["ceremonias"])
        if carga > cap["horas_por_dia"]:
            E.append(f"S3 sobrecarga el {d['fecha']}: {carga} h > {cap['horas_por_dia']} h")
        for a in d["asignaciones"]:
            if a["historia"] not in comprometidas:
                E.append(f"S3 {d['fecha']}: {a['historia']} no existe o no está comprometida")
    for tipo in {c["tipo"] for c in cap["ceremonias"]} | {c["tipo"] for d in plan for c in d["ceremonias"]}:
        en_plan = sum(c["horas"] for d in plan for c in d["ceremonias"] if c["tipo"] == tipo)
        en_cap = sum(c["horas"] for c in cap["ceremonias"] if c["tipo"] == tipo)
        if en_plan != en_cap:
            E.append(f"S3 ceremonia {tipo}: {en_plan} h en el plan ≠ {en_cap} h en capacidad")

    # S4 horas por historia
    dias_de = {i: [] for i in historias}
    for n, d in enumerate(plan):
        for a in d["asignaciones"]:
            if a["historia"] in dias_de:
                dias_de[a["historia"]].append((n, a["horas"]))
    for i, h in comprometidas.items():
        asignadas = sum(x[1] for x in dias_de[i])
        if asignadas != h["horas_estimadas"]:
            E.append(f"S4 {i}: {asignadas} h asignadas ≠ {h['horas_estimadas']} h estimadas")

    # S5 dependencias: existencia, ciclos y orden
    for i, h in historias.items():
        for dep in h["depende_de"]:
            if dep not in historias:
                E.append(f"S5 {i} depende de {dep}, que no existe")
    estado = {}

    def visitar(n, pila):
        if estado.get(n) == 1:
            E.append(f"S5 ciclo de dependencias: {' → '.join(pila + [n])}")
            return
        if estado.get(n) == 2:
            return
        estado[n] = 1
        for dep in historias.get(n, {}).get("depende_de", []):
            visitar(dep, pila + [n])
        estado[n] = 2
    for i in historias:
        visitar(i, [])
    for i in comprometidas:
        if not dias_de[i]:
            continue
        inicio_i = min(x[0] for x in dias_de[i])
        for dep in historias[i]["depende_de"]:
            if dep in comprometidas and dias_de[dep] and inicio_i < max(x[0] for x in dias_de[dep]):
                E.append(f"S5 {i} empieza en {plan[inicio_i]['dia']} antes de que termine {dep} ({plan[max(x[0] for x in dias_de[dep])]['dia']})")
            if dep in historias and not historias[dep]["comprometida"]:
                E.append(f"S5 {i} (comprometida) depende de {dep}, que no está comprometida")

    # S6 burndown recalculado
    total = cap["horas_comprometidas"]
    esperado = [("inicio", total, total)]
    restante = total
    for n, d in enumerate(plan, start=1):
        restante -= sum(a["horas"] for a in d["asignaciones"])
        esperado.append((d["fecha"], restante, round(total - total * n / len(plan), 2)))
    declarado = [(b["corte"], b["horas_restantes"], b["ideal"]) for b in doc["burndown_planificado"]]
    if len(declarado) != len(esperado):
        E.append("S6 burndown con distinta cantidad de cortes que el plan")
    for dec, esp in zip(declarado, esperado):
        if dec[0] != esp[0] or dec[1] != esp[1] or abs(dec[2] - esp[2]) > 0.01:
            E.append(f"S6 burndown declarado {dec} ≠ recalculado {esp}")

    # S7 punto de control
    pc = doc["punto_control"]
    cortes = {e[0]: e[1] for e in esperado}
    if pc["fecha"] not in cortes:
        E.append("S7 la fecha del punto de control no es un día del plan")
    elif pc["umbral_horas_restantes"] != cortes[pc["fecha"]]:
        E.append(f"S7 umbral {pc['umbral_horas_restantes']} h ≠ burndown al {pc['fecha']} ({cortes[pc['fecha']]} h)")
    if not any("punto_control" in d["hitos"] and d["fecha"] == pc["fecha"] for d in plan):
        E.append("S7 el hito punto_control no está en el día declarado")
    for r in pc["plan_b"]:
        h = historias.get(r["historia"])
        if not h or r["horas_nuevas"] >= h["horas_estimadas"]:
            E.append(f"S7 el plan B de {r['historia']} no reduce horas")
    for i, h in historias.items():
        for c in h["criterios_aceptacion"]:
            if c["id"][3:5] != i[3:5]:
                E.append(f"S7 criterio {c['id']} no corresponde a {i}")

    # S8 hoja de ruta
    hr = doc["hoja_ruta"]
    if hr[0]["sprint"] != sp["id"] or hr[0]["fecha_inicio"] != sp["fecha_inicio"] or hr[0]["fecha_fin"] != sp["fecha_fin"]:
        E.append("S8 el primer sprint de la hoja de ruta no coincide con la sección sprint")
    cubiertas = []
    for n, s in enumerate(hr):
        si, sf = date.fromisoformat(s["fecha_inicio"]), date.fromisoformat(s["fecha_fin"])
        calc = len(dias_habiles(si, sf, laborables, feriados))
        if calc != s["dias_habiles"]:
            E.append(f"S8 {s['sprint']}: {s['dias_habiles']} días hábiles declarados ≠ {calc} calculados")
        if n and si != siguiente_habil(date.fromisoformat(hr[n - 1]["fecha_fin"]), laborables, feriados):
            E.append(f"S8 {s['sprint']} no empieza el día hábil siguiente al fin de {hr[n - 1]['sprint']}")
        cubiertas += s["transiciones"]
        if "T9_incorporado_pia" in s["transiciones"] and sf >= date(doc["proyecto"]["ciclo_id"]["anio_fiscal"] - 1, 12, 31):
            E.append(f"S8 T9 llega el {sf}, sin margen antes de la aprobación del PIA")
    faltantes = [t for t in resolver({"$ref": "#/$defs/transicion"})["enum"] if t not in cubiertas]
    if faltantes:
        A.append(f"S8 transiciones sin sprint asignado: {faltantes}")
    for dep in doc["dependencias_externas"]:
        if dep["bloquea_sprint_actual"]:
            A.append(f"S8 {dep['id']} bloquea el sprint actual: {dep['solicitud']}")
        destino = next((s for s in hr if s["sprint"] == dep["necesaria_para_sprint"]), None)
        if destino is None:
            E.append(f"S8 {dep['id']} apunta a {dep['necesaria_para_sprint']}, que no está en la hoja de ruta")
        elif not set(dep["transiciones"]) <= set(destino["transiciones"]) | set(cubiertas):
            E.append(f"S8 {dep['id']}: transiciones no planificadas")
        proximo = hr[1]["sprint"] if len(hr) > 1 else None
        if dep.get("estado") == "por_solicitar" and destino and destino["sprint"] == proximo:
            A.append(f"S8 {dep['id']} se necesita en el próximo sprint y aún no se solicita")

    # S9 alineación con el contrato de ingesta
    if ESQUEMA_INGESTA.exists():
        ing = json.loads(ESQUEMA_INGESTA.read_text(encoding="utf-8"))
        if ing["$defs"]["transicion"]["enum"] != ESQUEMA["$defs"]["transicion"]["enum"]:
            E.append("S9 el enum de transiciones difiere del contrato de ingesta")
        if doc["proyecto"]["esquema_ingesta_version"] != ing["properties"]["version_esquema"]["const"]:
            E.append("S9 versión del esquema de ingesta distinta de la declarada")
    else:
        A.append("S9 no se encontró el contrato de ingesta para comprobar alineación")

    return E, A


def validar(doc):
    v = Draft202012Validator(ESQUEMA, format_checker=FormatChecker())
    err = sorted(f"{'/'.join(map(str, e.absolute_path)) or '$'}: {e.message}" for e in v.iter_errors(doc))
    if err:
        return err, [], []
    e, a = reglas_semanticas(doc)
    return [], e, a


def informe(ruta):
    doc = json.loads(Path(ruta).read_text(encoding="utf-8"))
    err, sem, avisos = validar(doc)
    print(f"== {Path(ruta).name}")
    print(f"Capa 1 (esquema): {'OK' if not err else f'{len(err)} error(es)'}")
    for e in err:
        print(f"   - {e}")
    if err:
        return 1
    print(f"Capa 2 (semántica): {'OK' if not sem else f'{len(sem)} error(es)'}")
    for e in sem:
        print(f"   - {e}")
    for a in avisos:
        print(f"   aviso: {a}")
    hito, _ = extraer(doc, ESQUEMA)
    b = canonico(hito)
    salida = BASE / f"hito_publico_{doc['sprint']['id']}.json"
    salida.write_text(json.dumps({"compromiso_sha256": hashlib.sha256(b).hexdigest(), "hito": hito}, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(f"Hito público: {len(b)} bytes · SHA-256 {hashlib.sha256(b).hexdigest()} → {salida.name}")
    return 1 if sem else 0


# ---------- casos de prueba ----------
def generar_casos():
    base = json.loads((BASE / "sprint_S00_preparacion_postulacion.json").read_text(encoding="utf-8"))
    casos = {}

    def caso(nombre, esperado, mutar):
        c = copy.deepcopy(base)
        mutar(c)
        casos[nombre] = (c, esperado)

    caso("p01_dato_personal_en_equipo", "falla_esquema", lambda c: c["equipo"][0].update(nombre_desarrollador="(persona)"))
    caso("p02_red_mainnet", "falla_esquema", lambda c: c["proyecto"].update(red="mainnet"))
    caso("p03_must_diferida", "falla_esquema", lambda c: c["backlog"][0].update(estado="diferida"))
    caso("p04_verificador_verde_sin_evidencia", "falla_esquema", lambda c: c["seguimiento"]["evidencia_incremento"].update(verificador_resultado="verde"))
    caso("p05_terminada_con_criterio_pendiente", "falla_esquema", lambda c: c["backlog"][1].update(estado="terminada"))

    def horas_no_suman(c):
        c["plan_diario"][1]["asignaciones"][0]["horas"] = 5
    caso("p06_horas_plan_no_suman", "falla_semantica", horas_no_suman)

    def fin_de_semana(c):
        c["plan_diario"][2]["fecha"] = "2026-10-03"
    caso("p07_dia_en_fin_de_semana", "falla_semantica", fin_de_semana)

    caso("p08_ciclo_de_dependencias", "falla_semantica", lambda c: c["backlog"][0]["depende_de"].append("HU-02"))

    def sobrecarga(c):
        c["plan_diario"][1]["asignaciones"][0]["horas"] = 8
    caso("p09_sobrecarga_diaria", "falla_semantica", sobrecarga)

    caso("p10_burndown_mal_declarado", "falla_semantica", lambda c: c["burndown_planificado"][2].update(horas_restantes=20))

    def dependencia_desordenada(c):
        c["plan_diario"][0]["asignaciones"] = [{"historia": "HU-01", "horas": 4}]
        c["plan_diario"][1]["asignaciones"] = [{"historia": "HU-00", "horas": 4}, {"historia": "HU-01", "horas": 2}]
    caso("p11_historia_antes_que_su_dependencia", "falla_semantica", dependencia_desordenada)

    carpeta = BASE / "casos_prueba"
    carpeta.mkdir(exist_ok=True)
    for nombre, (doc, _) in casos.items():
        (carpeta / f"{nombre}.json").write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return casos


def pruebas():
    fallos = 0
    print(f"{'caso':40} {'esperado':16} {'obtenido':16} resultado")
    for nombre, (doc, esperado) in generar_casos().items():
        err, sem, avisos = validar(doc)
        obtenido = "falla_esquema" if err else "falla_semantica" if sem else "pasa"
        ok = obtenido == esperado
        fallos += not ok
        print(f"{nombre:40} {esperado:16} {obtenido:16} {'OK' if ok else 'FALLO'}")
        motivo = (err or sem)[:1]
        if motivo:
            print(f"   └ {motivo[0][:140]}")
    return fallos


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--pruebas":
        sys.exit(1 if pruebas() else 0)
    sys.exit(max(informe(r) for r in sys.argv[1:]) if len(sys.argv) > 1 else 0)
