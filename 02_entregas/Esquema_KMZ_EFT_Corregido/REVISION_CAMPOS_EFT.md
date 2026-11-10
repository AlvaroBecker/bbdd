# Campos de la versión 1.2 conforme al ámbito indicado en el EFT

Informe histórico de 1.2. Para nombres y conteos actuales, consulte [versión 1.3](NORMALIZACION_EFT.md).


Se revisó el documento `EFT - ENGIE Mapline ArcGIS Enterprise y ArcGIS Pro_v2.4.docx`,
en particular la tabla de campos comunes de 5.8.7, el párrafo de atributos propios,
el apartado de polígonos de estudio de 5.8.6 y las relaciones de 5.8.10.

Esta revisión retira extensiones de la definición de clases nuevas. No borra
campos ni datos en una geodatabase existente. La herramienta detecta esas
diferencias y detiene el lote para revisarlas.

| Campo | Corrección | Fundamento |
|---|---|---|
| `descripcion_origen` | Retirado de las 76 clases | Era una extensión propia sin requisito expreso. La descripción sigue en el inventario y el mapeo. |
| `tipo_tema` | Retirado de las 76 clases | Era una extensión propia. Los informes de revisión no se convierten automáticamente en columnas de las clases. |
| `codigo_estacion` | Retirado de 75 clases; permanece en `area_estudio_campo` | EFT 5.8.6 exige que Área de Estudio de Campo conserve el código de estación. No es un campo común. |
| `tema` | Retirado como campo común de las 10 clases nuevas de diseño/campo | La tabla de 5.8.7 lo aplica a Datos_Externos, Datos_Internos y recortes. Las tres clases migradas ya lo excluían. |
| `id_origen` | Retirado como campo común de las 13 clases de diseño/campo y migradas | La tabla de 5.8.7 lo aplica a recortes y Datos_Externos. Se mantiene en los 63 recortes. |

Se retiraron 250 definiciones de campo en total. No se eliminó ningún atributo
propio del KMZ: se conservan las 2.238 definiciones de atributos de origen,
las 9.934 ocurrencias del inventario y las 3.507 filas de la matriz.

## Estructuras

El bloque común aplicable queda en 11 campos:

`proyecto`, `id_analisis`, `disciplina`, `componente`, `alternativa`, `condicion`,
`fuente`, `nombre`, `archivo_origen`, `ruta_kml` y `fecha_carga`.

A ellos se suman los mismos 23 atributos originales del KMZ, sin añadir ninguno.
Son 34 campos del modelo y 7 de sistema/auditoría: 41 campos físicos en total.
GlobalID y los campos de auditoría son capacidades nativas necesarias para la
edición y el versionado previsto; el EFT exige Editor Tracking y branch.

## Controles y límites

El generador ya no crea extensiones por defecto. Cada campo debe estar sustentado
en el bloque común aplicable, en un atributo de origen, en el DDL migrado o en un
requisito específico del EFT (código de estación o llave del trazado).

Conservar los atributos propios aunque no estén enumerados individualmente en el
EFT cumple su instrucción explícita de 5.8.7. Eso no autoriza a crear nuevos
atributos auxiliares. El código de estación sí tiene respaldo específico para
Área de Estudio de Campo; fue incorrecto tratarlo como extensión general.

Esta revisión no certifica la clasificación completa, tipos, longitudes, unidades
ni equivalencias de los datos. El EFT fija tipos generales en su tabla, pero no
todas las longitudes físicas. Las longitudes de texto del paquete son decisiones
técnicas anteriores, no cifras prescritas por el EFT. Los 23 atributos de
`estructuras` continúan con tipo provisional; deben revisarse antes de poblarlos.

La definición final de clases y el mapeo siguen pendientes según 5.8.6 y 5.8.8.
Las relaciones y branch pertenecen a fases posteriores. No se cambió el número
de clases en esta revisión.
