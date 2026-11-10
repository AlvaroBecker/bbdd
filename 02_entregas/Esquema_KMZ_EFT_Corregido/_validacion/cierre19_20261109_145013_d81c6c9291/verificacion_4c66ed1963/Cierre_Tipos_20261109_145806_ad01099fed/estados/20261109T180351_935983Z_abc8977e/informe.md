# Cierre de tipos KMZ 1.9

Estado: **TIPOS_CERRADOS_CON_PENDIENTES_DE_INGESTA**

Modo: APLICAR_CIERRE
Modelo objetivo: 12
Tipos provisionales en el modelo: 0
Cambios fisicos pendientes en el destino: 0
Cierre fisico verificado: True

La decision confirma 722 columnas TEXT existentes y autoriza ocho cambios numericos. Cero tipos provisionales en el modelo no acredita por si solo la migracion del destino.

| Clase | Campo | Tipo objetivo | Accion |
|---|---|---|---|
| sitios_arqueologicos_poligono_recorte | alt_mode | LONG | ALTERADA_VERIFICADA |
| sitios_arqueologicos_poligono_recorte | base | DOUBLE | ALTERADA_VERIFICADA |
| sitios_arqueologicos_poligono_recorte | clamped | LONG | ALTERADA_VERIFICADA |
| sitios_arqueologicos_poligono_recorte | extruded | LONG | ALTERADA_VERIFICADA |
| sitios_arqueologicos_punto_recorte | alt_mode | LONG | ALTERADA_VERIFICADA |
| sitios_arqueologicos_punto_recorte | base | DOUBLE | ALTERADA_VERIFICADA |
| sitios_arqueologicos_punto_recorte | has_label | LONG | ALTERADA_VERIFICADA |
| suelos_recorte | p_aui_suel | LONG | ALTERADA_VERIFICADA |

## Limites y trabajo de ingesta

- La aprobacion de tipos esta en el modelo distribuido; aplicar no modifica archivos del modelo.
- Solo se permiten ocho AlterField sobre clases existentes y vacias; no se crean ni borran objetos.
- Las tres reglas para <Null> y el mapeo de oficina_registral siguen abiertos; no se convierten valores.
- Las 2601 rutas sin destino, las llaves/relaciones de proyecto y los otros dos datasets conservan su fase propia.
- DDL no es una transaccion atomica. Un error detiene el lote y conserva los cambios ya realizados para reanudar.
- Este resultado no acredita ingesta, relaciones/FK, branch ni cumplimiento integral de los otros datasets.
