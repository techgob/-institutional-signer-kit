# Protección de datos: la regla de admisión

Este registro anclará documentos de entidades públicas durante años. Si la regla que decide qué entra a la cadena no es explícita y verificable por código, tarde o temprano entra algo que no debía.

## Marco aplicable

Ley N.° 29733, Ley de Protección de Datos Personales del Perú, y su reglamento aprobado por Decreto Supremo N.° 016-2024-JUS.

## La regla

**Solo se ancla lo que es público por mandato legal y de publicidad permanente.** Todo lo demás queda fuera.

Tres consecuencias operativas:

1. **Nunca se ancla la huella de un identificador personal.** Ni un DNI, ni con sal, ni transformado. Una huella de un dato de dominio acotado es reversible por fuerza bruta.
2. **Las claves pertenecen a roles y ciclos, no a personas.** La clave que firma es la de "Alcaldía, ciclo 2027", no la de un individuo. Eso resuelve además la rotación de autoridades.
3. **Cuando un documento público contiene datos personales, se ancla su versión pública.** Las plantillas del presupuesto participativo de Tocache incluyen columna de DNI en la matriz de priorización y en el cuadro de proyectos priorizados. De esos documentos se ancla la versión sin esa columna; la versión íntegra se conserva fuera de la cadena.

## Cómo se hace cumplir en el código

El contrato de datos no la deja como recomendación. Cada campo del esquema declara su regla de admisión:

| Valor | Significado |
|---|---|
| `cadena` | Forma parte de la carga comprometida y anclada |
| `cadena_huella` | Solo se ancla la huella del documento referido |
| `fuera_de_cadena` | Se conserva en el backend; nunca se publica |
| `prohibido` | No puede existir en el registro de ingesta |

Tres mecanismos lo refuerzan:

- **Privacidad por defecto.** Un campo sin anotación se trata como `fuera_de_cadena`. Un olvido del desarrollador no termina publicando un dato.
- **Rechazo estructural.** El esquema no admite campos no declarados, y falla si un nombre de campo coincide con el patrón de datos personales: documento de identidad, apellido, sexo, domicilio, teléfono o correo.
- **Verificación en dos capas.** El validador recorre además todo el documento en busca de nombres de campo sospechosos, incluso anidados, antes de generar la carga que se ancla.

## Cómo comprobarlo

```bash
python3 data-contract/validar_ingesta.py --pruebas
```

El caso `caso_01_dato_personal_en_proyecto` agrega deliberadamente un campo con documento de identidad a un proyecto ficticio. El resultado esperado es que la validación falle. Si alguna vez pasa, la regla está rota.

## Qué queda fuera del alcance

El registro no sustituye la evaluación de impacto en protección de datos que corresponde a cada entidad, ni la resolución de su propia oficina competente. Aporta el mecanismo técnico; la decisión sobre qué documentos son públicos la toma la entidad conforme a su marco normativo.
