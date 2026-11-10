# Cierre de tipos KMZ 1.9

Estado: **INICIADO**

Modo: APLICAR_CIERRE
Modelo objetivo: 12
Tipos provisionales en el modelo: 0
Cambios fisicos pendientes en el destino: None
Cierre fisico verificado: False

La decision confirma 722 columnas TEXT existentes y autoriza ocho cambios numericos. Cero tipos provisionales en el modelo no acredita por si solo la migracion del destino.

| Clase | Campo | Tipo objetivo | Accion |
|---|---|---|---|

## Limites y trabajo de ingesta

- La aprobacion de tipos esta en el modelo distribuido; aplicar no modifica archivos del modelo.
- Solo se permiten ocho AlterField sobre clases existentes y vacias; no se crean ni borran objetos.
- Las tres reglas para <Null> y el mapeo de oficina_registral siguen abiertos; no se convierten valores.
- Las 2601 rutas sin destino, las llaves/relaciones de proyecto y los otros dos datasets conservan su fase propia.
- DDL no es una transaccion atomica. Un error detiene el lote y conserva los cambios ya realizados para reanudar.
- Este resultado no acredita ingesta, relaciones/FK, branch ni cumplimiento integral de los otros datasets.
