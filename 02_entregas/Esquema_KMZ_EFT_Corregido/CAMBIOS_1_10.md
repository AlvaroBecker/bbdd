# Versión 1.10: prevalidación de ingesta

Después del cierre de tipos, falta comprobar las correspondencias de origen y proyecto antes de insertar. La décima herramienta, **Prevalidar ingesta de los KMZ**, reúne esas comprobaciones en un plan de solo lectura. Conserva el modelo 12 y las nueve herramientas anteriores.

## Fuentes actuales

Busca recursivamente los KMZ de la carpeta elegida e inventaría todos los archivos encontrados. Identifica las 13 fuentes del perfil completo por SHA-256; un cambio de nombre, tilde o guion no equivale a un cambio de contenido. Detecta faltantes, duplicados, archivos inesperados y nombres conocidos cuyo contenido cambió. Vuelve a comprobar las huellas al terminar para detectar cambios durante la ejecución.

Solo reutiliza como evidencia actual los valores del perfil 1.9 cuando están cubiertos los 13 hashes originales. Un resultado incompleto sigue mostrando el plan de referencia con evidencia actual no acreditada. No se analiza otra vez el XML de archivos idénticos.

## Proyectos

Lee `mline_tc_proyecto` localizada en la conexión del propietario indicado, con su clave `co_proyecto` y nombres reales. Comprueba registro en geodatabase, tipos, longitudes, nulos y duplicados. Usa cursores de consulta de [ArcPy SearchCursor](https://doc.esri.com/en/arcgis-pro/latest/arcpy/data-access/searchcursor-class.html).

Los nombres generan candidatos explicables. Para confirmar una correspondencia se utiliza un CSV explícito con `archivo_kmz;co_proyecto;confirmado`, validado contra el catálogo actual. No se inventan códigos ni se toma el SQL histórico como si fuera el estado actual de la SDE. Las fechas de eliminación observadas se conservan para revisar el estado del proyecto.

## Rutas y valores

El plan cuenta cada Placemark por ruta y geometría, sin sumarlo otra vez por sus atributos: 3.638 rutas / 279.623 elementos en las fuentes de referencia. De ellas, 1.037 rutas / 139.304 elementos tienen destino; 2.601 / 140.319 siguen sin destino. No se crean tablas para resolver automáticamente esa diferencia.

Define tres reglas exactas de `<Null>` a nulo para campos DOUBLE que admiten nulos: `longitud_subterranea`, `maxima_tension_operativa` y `src_area_ha` en sus clases identificadas. Son 23 ocurrencias de valores, no necesariamente 23 entidades distintas. La regla no altera ceros, cadenas vacías ni otros marcadores y no se aplica a registros en esta herramienta.

El EFT 5.8.7 indica: «Cada capa conserva todos sus atributos» y exige unificar nombres con una tabla de equivalencias. Las dos oficinas registrales del KMZ deben conservarse separadas por su significado: inmueble y persona jurídica. El plan registra la reconciliación de columnas y correspondencias necesaria, sin introducirla en el modelo cerrado ni perder uno de los valores. El EFT no prescribe estos dos nombres físicos; `snake_case` responde a la instrucción del usuario.

También conserva las 59 descripciones útiles sin correspondencia en rutas con destino. Distingue estos datos de los contenedores HTML de presentación. No agrega columnas por el mero hecho de encontrar XML o HTML.

## Resultado y límites

`PLAN_INGESTA_CON_PENDIENTES` indica un plan generado con consultas y fuentes comprobadas. Las asociaciones de proyecto, atributos sin correspondencia, campos obligatorios y otros requisitos de preparación pueden seguir pendientes. `PREVALIDACION_INGESTA_INCOMPLETA` identifica comprobaciones de fuentes o destino que no se acreditaron. `ERROR_DETENIDO` conserva el motivo y los resultados parciales en una carpeta nueva.

El informe siempre mantiene `ingesta_autorizada=false` y `registros_insertados=0`. No hay botón Aplicar ni API de escritura en la fachada utilizada. Los informes se crean en carpetas únicas sin reemplazar los resultados anteriores.

La lectura de relaciones existentes no equivale a certificar FK, reglas de relación o configuración de servicios. La reparación geométrica, la deduplicación, la asignación de `id_analisis` y las reglas de otros campos obligatorios siguen siendo controles previos a la carga. Los otros dos datasets quedan fuera de esta ejecución.

## Verificación

`VALIDACION_UNITARIA_1_10.json` registra las pruebas y huellas del código ensayado. `VALIDACION_PREINGESTA_1_10_ARCGIS.json` registra la ejecución de la toolbox en ArcGIS Pro sobre una copia local del esquema cerrado, con catálogo sintético identificado. Comprueba las fuentes reales y preserva la GDB, modelo y KMZ. Este ensayo no sustituye la ejecución sobre la SDE del usuario.
