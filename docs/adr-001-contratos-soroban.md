# ADR-001 — Usar contratos Soroban en lugar de solo primitivas nativas

**Estado:** aceptada · **Fecha:** septiembre de 2026 · **Reemplaza:** decisión de "Capa 1, cero contratos" de la Hoja de Ruta v5 (agosto de 2026)

## Contexto

La versión 5 de la hoja de ruta resolvió construir el registro **sin desplegar contratos**, usando solo primitivas nativas de Stellar: el número de secuencia de la cuenta para garantizar la completitud de la serie, el campo memo de tipo hash para anclar documentos, la multifirma nativa con pesos y umbrales, las reservas patrocinadas y el fee-bump para que la municipalidad no necesitara mantener XLM.

Esa decisión tenía una ventaja fuerte: nada que auditar, nada que mantener, ninguna renta de estado. Y dejaba abierta la puerta: "si más adelante se decidiera que las transiciones deben además rechazarse en la red, ese refuerzo puede añadirse con contratos sin rehacer lo construido".

## Decisión

Activar ese refuerzo. El registro se implementa con contratos Soroban.

## Razones

**1. Detectar no es lo mismo que impedir.** Con primitivas nativas, una transición inválida se ancla igual y su invalidez se comprueba después, fuera de la cadena. Con un contrato, la transacción falla en consenso. Para un registro cuyo propósito es que un compromiso público no se altere ni se salte pasos, esa diferencia es el producto.

**2. Las reglas del proceso son verificables.** La matriz de priorización de Tocache tiene 13 criterios con valores acotados y un rango de 13 a 71 puntos. El contrato puede recalcular el puntaje y exigir que una sustitución elija al alternativo de mayor rango. Eso no se puede hacer con un memo.

**3. El ecosistema evalúa impacto en red.** Una postulación que solo usa primitivas clásicas no constituye avance en Soroban, y el componente que queremos aportar —la separación entre firmante y pagador empaquetada como pieza reutilizable— vive precisamente en el modelo de autorización de Soroban.

## Costos que asumimos

- **Renta de estado y archivado.** Es el riesgo dominante. Las entradas persistentes se archivan al vencer su tiempo de vida, y un registro plurianual necesita una política de extensión y un presupuesto perpetuo. Se documenta y se prueba como entregable.
- **Código que auditar.** Se mitiga reutilizando módulos auditados de OpenZeppelin Stellar Contracts y postulando al Soroban Security Audit Bank antes de cualquier despliegue en mainnet.
- **Gobernanza de claves de administración.** La capacidad de actualizar el contrato es potente y peligrosa: exige multifirma y demora programada.
- **Dependencia de la madurez de la plataforma.** Se mitiga fijando versiones y permaneciendo en testnet durante las dos primeras iteraciones.

## Lo que no cambia

El principio operativo de la v5 se mantiene y se profundiza: **la municipalidad firma, el operador paga**. En la v5 eso se lograba con fee-bump y reservas patrocinadas; en Soroban, con entradas de autorización firmadas de forma independiente. La entidad sigue sin necesitar XLM.

También se mantienen las cuatro propiedades que ordenan el diseño: integridad, no repudio, completitud de la serie y auditoría ciudadana autónoma. Y la regla de protección de datos, que no admite excepciones.

## Umbrales que revertirían esta decisión

- Que no se obtenga auditoría antes de mainnet.
- Que no se pueda garantizar la renta de estado en un horizonte de diez a veinte años.
- Que el volumen real de transiciones sea tan bajo que la multifirma nativa con revisión humana baste, lo que convertiría al contrato en sobreingeniería.
