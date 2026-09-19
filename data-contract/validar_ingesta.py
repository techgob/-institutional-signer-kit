#!/usr/bin/env python3
"""Validador del contrato de datos de ingesta del Presupuesto Participativo.

Capa 1: JSON Schema 2020-12 (estructura, tipos, rangos, reglas condicionales).
Capa 2: reglas semánticas que JSON Schema no expresa (sumas, rangos, alertas obligatorias).
Salida: carga útil con solo los campos x-admision = cadena | cadena_huella, serializada
de forma canónica (claves ordenadas, sin espacios, UTF-8) y su SHA-256.

Uso:
    python3 validar_ingesta.py ejemplo_ordenanza_001-2026-MPT.json
    python3 validar_ingesta.py --pruebas
Requiere: pip install jsonschema
"""
import copy
import hashlib
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

BASE = Path(__file__).resolve().parent
ESQUEMA = json.loads((BASE / "ingesta_documento_pp.schema.json").read_text(encoding="utf-8"))
PATRON_PERSONAL = re.compile(
    r"(?i)(dni|documento_identidad|apellido|nombre_agente|nombre_persona|sexo|domicilio|telefono|correo|firma_manuscrita)"
)
ADMITIDOS = {"cadena", "cadena_huella"}


def resolver(nodo):
    """Resuelve $ref locales conservando las anotaciones hermanas (x-*)."""
    while isinstance(nodo, dict) and "$ref" in nodo:
        destino = ESQUEMA
        for parte in nodo["$ref"].lstrip("#/").split("/"):
            destino = destino[parte]
        hermanos = {k: v for k, v in nodo.items() if k != "$ref"}
        nodo = {**destino, **hermanos}
    return nodo


def tiene_admitidos(esquema, visitados=None):
    visitados = visitados or set()
    if id(esquema) in visitados:
        return False
    visitados.add(id(esquema))
    s = resolver(esquema)
    if s.get("x-admision") in ADMITIDOS:
        return True
    hijos = list(s.get("properties", {}).values())
    if isinstance(s.get("items"), dict):
        hijos.append(s["items"])
    return any(tiene_admitidos(h, visitados) for h in hijos)


def extraer(valor, esquema, ruta, sin_anotar):
    s = resolver(esquema)
    admision = s.get("x-admision")
    if admision in ADMITIDOS:
        return valor, True
    if admision in {"fuera_de_cadena", "prohibido"}:
        return None, False
    if isinstance(valor, dict) and "properties" in s:
        salida = {}
        for clave, sub_valor in valor.items():
            sub_esquema = s["properties"].get(clave)
            if sub_esquema is None:
                continue
            resultado, incluido = extraer(sub_valor, sub_esquema, f"{ruta}.{clave}", sin_anotar)
            if incluido:
                salida[clave] = resultado
        return salida, bool(salida)
    if isinstance(valor, list) and isinstance(s.get("items"), dict):
        if not tiene_admitidos(s["items"]):
            return None, False
        elementos = []
        for i, elemento in enumerate(valor):
            resultado, incluido = extraer(elemento, s["items"], f"{ruta}[{i}]", sin_anotar)
            if incluido:
                elementos.append(resultado)
        return elementos, True
    sin_anotar.append(ruta)  # privacidad por defecto: sin anotación no entra
    return None, False


def extraer_guardas(valor, esquema, ruta, salida):
    """Campos que el contrato lee como estado (x-guarda), en rutas planas."""
    s = resolver(esquema)
    if "x-guarda" in s:
        salida[ruta] = {"guarda": s["x-guarda"], "valor": valor}
        return
    if isinstance(valor, dict) and "properties" in s:
        for clave, sub_valor in valor.items():
            if clave in s["properties"]:
                extraer_guardas(sub_valor, s["properties"][clave], f"{ruta}.{clave}", salida)
    elif isinstance(valor, list) and isinstance(s.get("items"), dict):
        for i, elemento in enumerate(valor):
            extraer_guardas(elemento, s["items"], f"{ruta}[{i}]", salida)


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


def reglas_semanticas(doc):
    errores, avisos = [], []
    errores += [f"Nombre de campo con posible dato personal: {r}" for r in claves_personales(doc)]

    proyectos = doc.get("proyectos", [])
    for p in proyectos:
        suma = sum(p["criterios"])
        if suma != p["puntaje_total"]:
            errores.append(f"{p['codigo_pp']}: puntaje_total {p['puntaje_total']} no coincide con la suma de criterios ({suma})")
    if proyectos:
        rangos = sorted(p["rango"] for p in proyectos)
        if rangos != list(range(1, len(proyectos) + 1)):
            errores.append(f"Rangos no consecutivos o repetidos: {rangos}")
        ordenados = sorted(proyectos, key=lambda p: p["rango"])
        for a, b in zip(ordenados, ordenados[1:]):
            if a["puntaje_total"] < b["puntaje_total"]:
                errores.append(f"Rango invertido: {a['codigo_pp']} ({a['puntaje_total']}) antes que {b['codigo_pp']} ({b['puntaje_total']})")
            elif a["puntaje_total"] == b["puntaje_total"] and doc["reglas_proceso"]["matriz_priorizacion"]["regla_desempate"] is None:
                avisos.append(f"Empate sin regla de desempate: {a['codigo_pp']} y {b['codigo_pp']} ({a['puntaje_total']} pts). Saltar rango exigirá motivo y firma del Comité (G10).")

    techo = doc["reglas_proceso"]["techo_presupuestal_soles"]
    total_principal = sum(p["monto_asignado_soles"] or 0 for p in proyectos if p["condicion"] == "principal")
    if techo is not None and total_principal > techo:
        errores.append(f"Montos principales (S/ {total_principal:,.2f}) superan el techo (S/ {techo:,.2f})")
    elif techo is None and proyectos:
        avisos.append("Sin techo presupuestal: no se puede verificar el tope de montos asignados.")

    alertas = set(doc["evento"]["alertas"])
    if doc["identificacion"]["vigencia"]["fecha_publicacion_legal"] is None and "ALERTA_VIGENCIA" not in alertas:
        errores.append("Falta ALERTA_VIGENCIA: no hay fecha de publicación legal acreditada (G7).")

    fecha_acto = date.fromisoformat(doc["evento"]["fecha_acto"])
    fecha_val = datetime.fromisoformat(doc["validacion"]["fecha_validacion"]).date()
    if fecha_acto < fecha_val and not doc["evento"]["retroactivo"]:
        errores.append("retroactivo debe ser true: el acto es anterior al registro (G6).")

    fuentes_por_transicion = {}
    for fila in doc["reglas_proceso"]["cronograma"]:
        t = fila.get("transicion_asociada")
        if t:
            fuentes_por_transicion.setdefault(t, set()).add((fila["fuente"], fila["periodo_declarado"]))
    conflictos = [t for t, f in fuentes_por_transicion.items() if len({x[0] for x in f}) > 1]
    if conflictos and "ALERTA_FECHA_EN_CONFLICTO" not in alertas:
        errores.append(f"Falta ALERTA_FECHA_EN_CONFLICTO; transiciones con fechas de fuentes distintas: {conflictos}")
    return errores, avisos


def validar(doc):
    validador = Draft202012Validator(ESQUEMA, format_checker=FormatChecker())
    errores_esquema = sorted(
        f"{'/'.join(map(str, e.absolute_path)) or '$'}: {e.message}" for e in validador.iter_errors(doc)
    )
    if errores_esquema:
        return errores_esquema, [], []
    errores_sem, avisos = reglas_semanticas(doc)
    return [], errores_sem, avisos


def informe(ruta):
    doc = json.loads(Path(ruta).read_text(encoding="utf-8"))
    err_esq, err_sem, avisos = validar(doc)
    print(f"== {Path(ruta).name}")
    print(f"Capa 1 (esquema): {'OK' if not err_esq else f'{len(err_esq)} error(es)'}")
    for e in err_esq:
        print(f"   - {e}")
    if err_esq:
        return 1
    print(f"Capa 2 (semántica): {'OK' if not err_sem else f'{len(err_sem)} error(es)'}")
    for e in err_sem:
        print(f"   - {e}")
    for a in avisos:
        print(f"   aviso: {a}")
    sin_anotar = []
    carga, _ = extraer(doc, ESQUEMA, "$", sin_anotar)
    bytes_carga = canonico(carga)
    compromiso = hashlib.sha256(bytes_carga).hexdigest()
    guardas = {}
    extraer_guardas(doc, ESQUEMA, "$", guardas)
    bytes_guardas = canonico(guardas)
    print(f"Estado de ingesta: {doc['validacion']['estado']}")
    print(f"Compromiso (carga admitida, publicada fuera de la cadena): {len(bytes_carga)} bytes · SHA-256 {compromiso}")
    print(f"Estado del contrato (campos x-guarda): {len(guardas)} campos · {len(bytes_guardas)} bytes")
    if sin_anotar:
        print(f"   campos sin anotación (excluidos por defecto): {sin_anotar}")
    prefijo = f"{doc['evento']['transicion'].split('_')[0]}_{Path(ruta).stem}"
    (BASE / f"carga_admitida_{prefijo}.json").write_text(
        json.dumps(carga, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    (BASE / f"transaccion_{prefijo}.json").write_text(json.dumps({
        "compromiso_sha256": compromiso,
        "estado_contrato": guardas,
        "nota": "compromiso_sha256 va a la cadena; carga_admitida se publica en el portal para que cualquiera recalcule la huella.",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"   escritos carga_admitida_{prefijo}.json y transaccion_{prefijo}.json")
    return 1 if err_sem else 0


PROYECTO_FICTICIO = {
    "codigo_pp": "PP2027-001", "cui": "0000001", "nombre_proyecto": "Proyecto ficticio A (caso de prueba)",
    "centro_poblado": None, "linea_estrategica": 3,
    "criterios": [5, 5, 1, 1, 8, 1, 5, 5, 1, 5, 1, 1, 5], "puntaje_total": 44, "rango": 1,
    "condicion": "principal", "monto_asignado_soles": 350000, "beneficiarios": 1200, "nivel_estudio": "perfil",
}


def generar_casos():
    base = json.loads((BASE / "ejemplo_ordenanza_001-2026-MPT.json").read_text(encoding="utf-8"))
    casos = {}

    c = copy.deepcopy(base); p = copy.deepcopy(PROYECTO_FICTICIO); p["dni_agente"] = "00000000"
    c["proyectos"] = [p]; casos["caso_01_dato_personal_en_proyecto"] = (c, "falla_esquema")

    c = copy.deepcopy(base); p = copy.deepcopy(PROYECTO_FICTICIO); p["criterios"][4] = 4
    c["proyectos"] = [p]; casos["caso_02_criterio_nbi_fuera_de_rango"] = (c, "falla_esquema")

    c = copy.deepcopy(base); c["validacion"]["estado"] = "aprobado_para_anclaje"
    c["validacion"]["revisores"] = ["ogpp", "comite_vigilancia"]
    casos["caso_03_aprobado_con_bloqueante"] = (c, "falla_esquema")

    c = copy.deepcopy(base); c["evento"]["transicion"] = "T9_incorporado_pia"
    c["identificacion"]["tipo_norma"] = "acuerdo_concejo"; p = copy.deepcopy(PROYECTO_FICTICIO); p["cui"] = None
    c["proyectos"] = [p]; casos["caso_04_T9_sin_cui"] = (c, "falla_esquema")

    c = copy.deepcopy(base); c["evento"]["transicion"] = "T11_sustituido"
    c["identificacion"]["tipo_norma"] = "decreto_alcaldia"
    casos["caso_05_T11_sin_resolucion_alcaldia"] = (c, "falla_esquema")

    c = copy.deepcopy(base); p = copy.deepcopy(PROYECTO_FICTICIO); p["puntaje_total"] = 50
    c["evento"]["transicion"] = "T5_priorizado"; c["identificacion"]["tipo_norma"] = "informe_tecnico"
    c["proyectos"] = [p]; casos["caso_06_puntaje_no_coincide"] = (c, "falla_semantica")

    c = copy.deepcopy(base); c["evento"]["transicion"] = "T5_priorizado"
    c["identificacion"]["tipo_norma"] = "informe_tecnico"
    a = copy.deepcopy(PROYECTO_FICTICIO)
    b = copy.deepcopy(PROYECTO_FICTICIO)
    b.update(codigo_pp="PP2027-002", cui="0000002", nombre_proyecto="Proyecto ficticio B (caso de prueba)",
             criterios=[1, 1, 5, 5, 8, 5, 5, 1, 5, 1, 5, 1, 1], rango=2, condicion="alternativo",
             monto_asignado_soles=None)
    b["puntaje_total"] = sum(b["criterios"])
    a["puntaje_total"] = sum(a["criterios"])
    c["proyectos"] = [a, b]; casos["caso_07_valido_con_empate"] = (c, "pasa_con_avisos")

    carpeta = BASE / "casos_prueba"
    carpeta.mkdir(exist_ok=True)
    for nombre, (doc, _) in casos.items():
        (carpeta / f"{nombre}.json").write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return casos


def pruebas():
    fallos = 0
    print(f"{'caso':42} {'esperado':18} {'obtenido':18} resultado")
    for nombre, (doc, esperado) in generar_casos().items():
        err_esq, err_sem, avisos = validar(doc)
        obtenido = "falla_esquema" if err_esq else "falla_semantica" if err_sem else "pasa_con_avisos" if avisos else "pasa"
        ok = obtenido == esperado
        fallos += not ok
        print(f"{nombre:42} {esperado:18} {obtenido:18} {'OK' if ok else 'FALLO'}")
        motivo = (err_esq or err_sem or avisos)[:1]
        if motivo:
            print(f"   └ {motivo[0][:150]}")
    return fallos


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--pruebas":
        sys.exit(1 if pruebas() else 0)
    sys.exit(max(informe(r) for r in sys.argv[1:]) if len(sys.argv) > 1 else 0)
