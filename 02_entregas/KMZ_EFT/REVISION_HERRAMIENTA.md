# Revisión del organizador KMZ existente

Se revisaron `KMZ_Organizador.py`, `Organizador_KMZ_ArcGIS.pyt`, `separar_chanchamayo.py` y su LEEME en `C:\Users\aibecker\Desktop\ENGIE PERU\InformaciónMapline`. No se modificó ni ejecutó esa herramienta.

## Qué puede aprovecharse

- El organizador general copia las ramas seleccionadas, estilos y recursos del KMZ y verifica el balance XML de sus secciones.
- La caja de ArcGIS llama a `KML To Layer` y genera GDB/LYRX locales para inspección y conversión intermedia.
- La separación por categorías puede facilitar la revisión visual de archivos grandes. No es una condición para definir los datasets finales.
- Las rutas, descripciones y `ExtendedData` conservadas en los originales son insumos de la trazabilidad y del mapeo de atributos.

## Qué falta para cumplir el modelo del EFT

| Aspecto | Comportamiento actual | Preparación requerida |
|---|---|---|
| Organización | Una carpeta/GDB por KMZ o categoría | Tres datasets del EFT y clases por tema y tipo de geometría |
| Carpetas | Se separa el primer nivel con varias ramas | Distinguir disciplina, tema, componente, alternativa y carpetas de presentación |
| Proyecto | Aparece en nombres y jerarquías | Confirmar `co_proyecto` y los vínculos con los registros de MySQL/SQL Server |
| Atributos | Se preserva HTML y XML; se convierte con KML To Layer | Extraer los atributos y revisar sus equivalencias con los campos de destino |
| Geometrías | Se conserva XML y se delega la conversión | Conciliar Placemarks, multipartes, partes y filas GIS; comprobar Z, modos de altitud y modelos |
| Resultado correcto | Se comprueba la existencia de la GDB | Comparar conteos, geometrías y atributos reales de salida contra el inventario |
| Simbología | Copia estilos y genera LYRX | Revisar estilos externos, referencias y la representación en las capas finales |
| Carga empresarial | No hay carga a SDE | Consolidar y validar antes de cargar las clases finales |

El punto de organización está en `KMZ_Organizador.py`, función `split_one`: separa las carpetas del primer nivel que se ramifica. En `Organizador_KMZ_ArcGIS.pyt`, `convert_kmz_tree` crea GDB/LYRX por archivo y llama a `arcpy.conversion.KMLToLayer`; no realiza el mapeo temático del EFT ni las equivalencias del DDL.

`safe_name` sanea nombres de archivos Windows; no sustituye la definición de nombres físicos únicos para las clases de geodatabase. Clases genéricas como Points/Lines/Polygons de distintas conversiones todavía deben clasificarse y consolidarse.

El script específico `separar_chanchamayo.py` fija un proyecto y tiene menos comprobaciones que el organizador general. Para continuar conviene aprovechar la herramienta general, sin extender ese caso particular como cargador final.

## Hallazgos de los archivos reales

- Los trece KMZ suman aproximadamente 1,43 GB de XML descomprimido. Palián tiene un `doc.kml` de aproximadamente 515 MB: se requiere lectura por partes para inventariar sin cargar todos los documentos a memoria.
- El inventario completo encuentra 279.623 Placemarks. Una cantidad importante usa `MultiGeometry`; no debe equipararse un componente geométrico con un nuevo registro de negocio.
- En la muestra de Chanchamayo, Huaraz y cuatro resultados, 6.293 de 6.726 Placemarks guardan tablas HTML en `description`. Convertir solamente coordenadas deja una parte sustancial de los atributos sin normalizar.
- Hay `ExtendedData` en formatos `Data/value` y `SchemaData/SimpleData`. No se debe suponer que `PopupInfo` siempre está completo: los 22 valores `SimpleData` llamados `PopupInfo` encontrados en Huaraz estaban vacíos.
- Chanchamayo y Huaraz contienen referencias a `xsi` sin declarar ese prefijo. El inventario agrega su declaración exclusivamente en la copia de lectura en memoria. El indicador del reporte significa que se agregó una declaración; no implica por sí mismo que todo archivo marcado fuera inválido originalmente.
- Hay coordenadas Z y modos de altitud que necesitan revisión; no se eliminan automáticamente.
- Poroma incluye cuatro recursos `.dae` y cuatro geometrías Model. El tratamiento de esos objetos se revisa como excepción.

El organizador actual es una pieza aprovechable del proceso. Lo que requiere incorporarse es la preparación **entre la conversión de archivos y la carga definitiva**: mapeo, atributos, claves, consolidación y conciliación.

## Referencias técnicas

- [Esri: KML To Layer](https://doc.esri.com/en/arcgis-pro/latest/tool-reference/conversion/kml-to-layer.html): clases por geometría, información de carpetas/popups y salida LYRX; incluye un ejemplo separado de extracción de tablas HTML.
- [Esri: atributos KML conservados en popups](https://support.esri.com/en-us/knowledge-base/faq-why-are-kml-attributes-not-auto-populated-to-attrib-000032102): la conversión puede dejar atributos en formato HTML en `PopupInfo`.

Las capacidades exactas de conversión deben comprobarse con la versión de ArcGIS Pro instalada. Esta revisión no afirma que una llamada a KML To Layer preserve automáticamente todos los elementos KML ni las reglas de negocio del modelo Mapline.
