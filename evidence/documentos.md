# Documentos oficiales anclados

Los documentos no se alojan en este repositorio: se referencian por su fuente oficial y su huella. Es la misma regla que aplica el registro.

**Cómo verificar cualquier fila:**

```bash
curl -sL "<url oficial>" -o documento.pdf
sha256sum documento.pdf
```

La huella debe coincidir con la de la tabla. Si no coincide, el documento cambió o la descarga no vino de la fuente oficial.

| Entidad | Documento | Fecha del acto | Fuente oficial | SHA-256 | Verificado contra la fuente |
|---|---|---|---|---|---|
| M. P. de Tocache | Ordenanza Municipal N.° 001-2026-MPT, aprueba el reglamento del presupuesto participativo 2027 | 2026-01-28 | gob.pe, id 7687930 | `ec76ae49026410ffe48478263c9b1396a29f227f973c762c5e3484243359dc24` | No. Huella calculada sobre una copia; pendiente de recalcular sobre la descarga directa |
| M. D. de La Punta | Decreto de Alcaldía N.° 002-2026-MDLP/AL, convoca el proceso 2027 y aprueba el cronograma | 2026-03-13 | gob.pe, id 7865886 | `8e3322a0f0469760d35d78d84f2b7ef89321d3b25229d3d001b74bc9af5c2285` | No. Ídem |

## Perfil técnico de cada documento

| | Tocache | La Punta |
|---|---|---|
| Origen | Escaneado de impreso, con capa OCR | Nativo digital |
| Firmas digitales | Ninguna. Firma manuscrita y sellos | Siete certificados, hash SHA-256 |
| Sello de tiempo cualificado | No aplica | No |
| Datos de validación de largo plazo | No aplica | No |
| Perfil de ingesta | Doble revisión humana | Verificación automática más revisión simple |

Ambos perfiles importan. En Tocache el registro aporta la integridad que no existe; en La Punta, la permanencia que la firma sola no garantiza: sin sello de tiempo cualificado, la hora de firma la declara el reloj del firmante, y la validación de la cadena de certificación exige disponer de la lista de confianza peruana en el momento de la consulta.

## Pendiente

- Recalcular ambas huellas sobre la descarga directa del portal, con doble registro por dos roles distintos.
- Incorporar el acta de acuerdos y compromisos y el cuadro de proyectos priorizados de cada entidad, en versión pública sin columna de documento de identidad.
