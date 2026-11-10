# Versión 1.8: validación conjunta de los tipos de los KMZ

La octava herramienta, **Validar todos los tipos de los KMZ**, revisa las fuentes completas y contrasta las 76 clases y 3.340 definiciones de campos de `Datos_Proyecto` con la geodatabase existente. Las siete herramientas anteriores se conservan. El modelo sigue siendo el 11.

Esta etapa precede a cualquier ingesta. Su resultado reúne las decisiones de tipos en un solo lote; no obliga a revisar una clase por ejecución. Los dos datasets restantes, `Datos_Externos` y `Datos_Internos`, mantienen sus propias fuentes y su implementación pendiente conforme al EFT. La revisión de KMZ corresponde a `Datos_Proyecto` y no acredita esos otros datasets.

## Ejecución recomendada

1. Extraiga `Datos_Proyecto_Controlado_v1_8.zip` en una carpeta nueva y cierre los paneles de herramientas anteriores.
2. Agregue el `Datos_Proyecto.pyt` de esa carpeta a ArcGIS Pro.
3. Abra **Validar todos los tipos de los KMZ**.
4. Seleccione su conexión `.sde` existente, base `ArcGisAWS` y propietario `gis`.
5. Deje vacía **Carpeta KMZ** para utilizar el perfil completo incluido en el paquete. Es evidencia de los archivos examinados al preparar la entrega, identificados por SHA-256; no significa que se hayan releído archivos del equipo de destino.
6. Seleccione una carpeta existente para informes y pulse **Ejecutar**.

Si quiere comprobar archivos nuevos o actualizados, indique la carpeta que contiene los 13 KMZ. Se buscan también sus subcarpetas y se rechazan nombres duplicados ambiguos. En este modo se releen las fuentes actuales y se vuelve a calcular el perfil.

No hay selector de clases ni acción de aplicación. Esta herramienta consulta el destino y escribe informes en una carpeta nueva; no cambia columnas, aprueba propuestas ni inserta datos.

## Alcance de la lectura

- Se recorren los miembros KML de los 13 KMZ y todos sus `Placemark`, incluidas rutas sin destino, geometrías mixtas, modelos y elementos sin geometría. Los grupos se reconcilian con las 3.638 rutas del inventario y sus 279.623 elementos.
- Se leen atributos HTML, `Data`, `SimpleData` y las declaraciones de tipos asociadas mediante `SchemaData/schemaUrl`. Una coincidencia de nombre no atribuye un tipo a otra fuente.
- Se conservan las ocurrencias repetidas para detectar conflictos, como las dos oficinas registrales. Las diferencias de mapeo se distinguen de la compatibilidad del tipo.
- Las tablas HTML anidadas conservan su texto completo. El contenedor nativo `description` se mantiene como evidencia y no se confunde con un atributo interno del mismo nombre. Los campos XML explícitos conservan su identidad; no se ejecutan enlaces ni código de las descripciones.
- Se miden longitudes completas en UTF-16, rangos, fracciones, precisión, ceros iniciales, marcadores literales y formatos de fecha. Los ejemplos son una muestra de presentación; las comprobaciones recorren todos los valores observados.
- En la SDE se contrastan nombres, tipos, longitudes, nulabilidad y dominios, junto con dataset, geometría, referencia espacial, Z/M, GlobalID y seguimiento del editor.

Los campos comunes o derivados que no proceden de un atributo KMZ se identifican como entradas o resultados de la futura carga. La ausencia de muestras no se presenta como un tipo original comprobado. Los objetos fuera del inventario y las rutas sin destino aparecen como incidencias o pendientes de alcance.

## Interpretación del resultado

`VALIDACION_TIPOS_COMPLETA_CON_PENDIENTES` indica que la revisión terminó y dejó propuestas o incidencias. No equivale a autorización de ingesta. `VALIDACION_TIPOS_INCOMPLETA` indica diferencias de cobertura con el inventario. `ERROR_DETENIDO` identifica un fallo que impide completar la comprobación. Consulte siempre el resumen, los conteos y el detalle del informe.

Cada ejecución genera `resultado.json`, `informe.md`, `campos.csv`, `campos_fuente.csv`, `cobertura_rutas.csv` e `incidencias.csv`. Cuando se consulta la geodatabase, también genera `campos_destino.csv`.

`campos.csv` presenta el tipo actual, la evidencia del tipo original, el tipo de destino recomendado, el fundamento, la compatibilidad observada y los bloqueos de mapeo. Incluye los 730 campos todavía pendientes en el modelo, además de comprobar los ya confirmados.

La capacidad del campo de destino y la coherencia de la declaración original se informan por separado: un texto puede caber en la columna aunque contradiga una declaración numérica de origen. La longitud recomendada es una capacidad mínima; cualquier ampliación debe usar un almacenamiento admitido por la SDE. No se ejecuta automáticamente `AlterField`.

`CONTENEDOR_XML_SIN_DESTINO` identifica una envoltura de presentación conservada como evidencia; no implica crear una columna. `OBJETO_NO_PLACEMARK` informa de elementos KML fuera del inventario de entidades, como superposiciones o enlaces. Estos registros se distinguen de `ATRIBUTO_SIN_MAPEO`, que sí señala un atributo sin correspondencia aprobada.

## Criterio para cerrar los tipos

El EFT exige preservar atributos, pero no tipifica individualmente los 730 pendientes. Se distingue entre el tipo original declarado y una elección de almacenamiento:

- Una declaración consistente en todas las fuentes, acompañada de valores compatibles, permite proponer un tipo numérico.
- Códigos, fechas ambiguas, precisiones no preservables, fuentes sin definición y campos sin valores útiles reciben una propuesta conservadora de texto con fundamento. Esta propuesta conserva información; no pretende descubrir un tipo original que la fuente no declara.
- Una declaración parcial de un KMZ no se extiende a otros KMZ que comparten el campo.
- Ceros, negativos y marcadores no se reinterpretan automáticamente como ausencia. Las conversiones requieren sus reglas.

La lista admitida para `SimpleField` corresponde a la referencia de KML 2.2; `long` no figura entre esos tipos y no se equipara automáticamente al `LONG` de ArcGIS. Véase la [referencia oficial de KML, apartado Schema](https://developers.google.com/kml/documentation/kmlreference).

La versión 1.8 no cambia el contador de 730 mediante una aprobación automática. La matriz resultante permite decidir y aplicar el lote completo con evidencia, manteniendo aparte los conflictos de mapeo que deben resolverse antes de cargar.

## Evidencia y límites

El perfil incluido está ligado por hashes al modelo, los mapeos y los módulos que lo produjeron. Sus fuentes se registran con nombre y SHA-256. Mezclar archivos de versiones diferentes provoca una detención en vez de reutilizar evidencia incompatible.

Los ensayos en una geodatabase local comprueban la implementación; la ejecución del usuario acredita su conexión SQL Server/SDE. Esta validación no crea relaciones, comprueba códigos de proyecto almacenados, configura branch ni inicia la ingesta. Esos controles conservan su fase propia dentro del cumplimiento integral del EFT.
