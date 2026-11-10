# Versión 1.11: altas de proyectos que existen solo en KMZ

La prevalidación anterior confirmó 13 fuentes y el esquema de 76 clases, pero JAENNORTE y POROMA no aparecen en el catálogo recibido. El usuario autorizó registrarlos si siguen ausentes, continuar la secuencia y ejecutarlo sin otros usuarios utilizando la base. Esta versión añade la herramienta 11 al mismo toolbox para hacer ese paso en la base real.

| Archivo | no_proyecto | de_proyecto |
|---|---|---|
| Proyecto JAENNORTE.kmz | Proyecto JAENNORTE | LT 220 kV Caclic-Jaen Norte |
| Proyecto POROMA.kmz | Proyecto POROMA | LT 220 kV Ica-Poroma |

Las descripciones provienen de las raíces KML del informe de fuentes. Los valores tipo 8 = Línea de Transmisión, estado 3 = Registrado y registro activo `1` se contrastan con los dominios efectivos. ObjectID, GlobalID y Editor Tracking quedan a cargo de ArcGIS. No se inventan IP, usuarios históricos, alternativas ni análisis.

## Secuencia y preservación

El EFT 5.8.7 dispone que los proyectos nuevos, incluidos los que solo existen en KMZ, continúen la secuencia. La rutina histórica deriva `co_proyecto` de `id_proyecto` mediante `PRY-` y ocho dígitos. Se comprueba esa correlación en todas las filas del catálogo, incluyendo inactivas, antes de usar MAX+1. El JSON recibido solo mostraba código máximo 40: no certificaba el máximo de `id_proyecto`. Los números 41/42 se confirman únicamente al ejecutar contra el destino.

Los nombres se comparan normalizando tildes, separadores y el prefijo Proyecto. Solo se reutilizan identidades inequívocas; coincidencias parciales o contradictorias detienen el plan completo. Los registros existentes conservan todos sus atributos, incluso estado de eliminación. No se reutilizan huecos, se reactiva ni se renumera.

## Ruta de escritura y límites

Se usa ArcPy Editor + InsertCursor, nunca INSERT SQL directo. La ruta requiere tabla no versionada ni archivada, Editor Tracking y dominios compatibles, sin reglas de atributos/subtipos/adjuntos que necesiten una política diferente. No habilita o deshabilita esas capacidades, no cambia el esquema ni añade índices. La observación de relaciones existentes no constituye una certificación de las relaciones, branch, servicios o cumplimiento global del EFT.

El catálogo entregado no tiene restricciones UNIQUE sobre las claves de negocio. Por eso MAX+1 requiere la ventana **sin otras altas** confirmada por el usuario. La sesión de edición permite revertir el lote, pero no bloquea a otros escritores. Se relee antes de insertar, se preservan exactamente todas las filas previas y se verifica el resultado antes y después de guardar. Una respuesta incierta durante commit se distingue de un rollback verificado; un error de informe posterior al commit no se presenta como reversión.

## Correspondencias de ingesta

El CSV incluido es una copia exacta de la revisión por `no_proyecto` ya acordada (SHA-256 `5d8bbcc54afc6c6e4b657d025667da3c1a58f1891251d882158ce2fda879b16f`). Nueve asociaciones permanecen confirmadas. Al aplicar correctamente las dos altas se genera otro CSV con los códigos efectivamente leídos: normalmente 11 confirmadas y 2 pendientes. FELAM completo y PUCALLPA no se resuelven automáticamente. Sin CSV de entrada, el resultado contiene solo las dos asociaciones de esta operación.

Se conservan los pendientes anteriores: análisis, rutas fuera del destino, conservación de atributos y proyectos inactivos. Esta versión no ingiere registros KMZ ni modifica los otros dos datasets.

## Verificación

`VALIDACION_UNITARIA_1_11.json` identifica las pruebas y hashes del código final. `VALIDACION_ALTAS_1_11_ARCGIS.json` registra el ensayo real del runtime en una geodatabase local nueva con 40 proyectos sintéticos: validación sin cambios, fallo inducido después de una inserción con reversión, alta de los dos proyectos con auditoría/GlobalID nativos y repetición sin duplicarlos. No es una prueba sobre SDE/SQL Server ni de concurrencia. El contrato de los parámetros del toolbox se prueba por separado; las diez herramientas anteriores se comparan por AST y permanecen intactas. Los manifiestos conservan el modelo 12 y los archivos anteriores sin cambios fuera del alcance documentado.

Referencias técnicas: [Editor de ArcPy](https://pro.arcgis.com/en/pro-app/latest/arcpy/data-access/editor.htm), [InsertCursor](https://doc.esri.com/en/arcgis-pro/latest/arcpy/data-access/insertcursor-class.html) y [propiedades de Editor Tracking](https://doc.esri.com/en/arcgis-pro/latest/arcpy/functions/editor-tracking-properties.html). El EFT local y la rutina histórica son la fuente del criterio de negocio.
