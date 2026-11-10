# KMZ de Mapline: inventario y preparación según el EFT

La herramienta existente puede aprovecharse para **convertir a geodatabases temporales**. Su salida por archivo/categoría no constituye todavía el modelo final del EFT. Esta carpeta aporta la etapa previa de inventario y una matriz editable para definir los destinos.

## Transferencia autorizada a SDE sin clasificación definitiva

Para avanzar sin esperar las respuestas de negocio, usar la [entrega de carga a SDE](carga_sde/LEEME.md). Transfiere lo convertible de los trece KMZ a clases neutrales nuevas en `ArcGisAWS`, esquema `gis`, con trazabilidad por Placemark y atributos originales. Los contenidos ambiguos no se excluyen por falta de clasificación; las preguntas se documentan para ENGIE.

Esta vía conserva información en SDE, pero no sustituye la revisión requerida para consolidar el modelo temático definitivo. Los overlays y los originales sin salida geométrica quedan expresamente registrados y preservados, no declarados como entidades cargadas.

## Resultado del inventario

- 22 archivos físicos corresponden a **13 KMZ únicos**: nueve internos y cuatro de resultados.
- Los nueve de `bbdd/kmz` son copias byte a byte de los nueve de `InformaciónMapline/CapasInternas`. Se leen una sola vez por SHA-256; no se borran las copias.
- Se inventariaron **279.623 Placemarks**, coincidiendo con la cifra del EFT.
- Hay **3.655 grupos de contenedor y tipo de geometría**. Son filas para el mapeo; no son 3.655 capas finales.
- Se detectaron **141.520 Placemarks con MultiGeometry**. Contar sus partes geométricas como si fueran registros independientes alteraría el balance de entidades.
- También hay imágenes superpuestas, elementos de pantalla y cuatro modelos 3D. Requieren un tratamiento específico; no se convierten automáticamente en clases del modelo.

El conteo estructural es 3.146 nodos `Folder` y 254 `Document`. El EFT refiere más de 3.600 carpetas: esa cifra no coincide con este conteo XML y queda como diferencia de definición o inventario que debe aclararse. No se sustituye ese conteo por el número de grupos del mapeo.

## Qué abrir primero

1. **[inventario/01_archivos.csv](inventario/01_archivos.csv):** los trece archivos, conteos y hashes.
2. **[inventario/05_resumen_candidatos.csv](inventario/05_resumen_candidatos.csv):** resumen por geometría y tema candidato.
3. **[inventario/03_matriz_mapeo_EFT.csv](inventario/03_matriz_mapeo_EFT.csv):** revisión detallada y asignación del destino.

Los CSV usan punto y coma y UTF-8 con BOM. Se pueden abrir en Excel. Si aparecen en una sola columna, usar Datos → Desde texto/CSV y elegir `;` como delimitador.

## Cómo usar la matriz

Cada fila identifica archivo, KML interno, contenedor, geometría, conteo de Placemarks y partes, campos de `ExtendedData` y etiquetas HTML candidatas.

Las columnas `dataset_candidato`, `clase_candidata` y `motivo_candidato` contienen **pistas de revisión**, no decisiones de carga. Los candidatos de clase solo usan coincidencias de nombre/geometría con temas expresos del EFT. Un nombre como “franja” no demuestra por sí solo que sea una franja de servidumbre. No se presupone un código de proyecto a partir del nombre del archivo.

Todas las filas comienzan con `estado_revision = PENDIENTE` y los campos de aprobación vacíos. Para cerrar el mapeo se completan:

- `incluir_aprobado`, `dataset_aprobado` y `clase_aprobada`.
- `co_proyecto_validado` y, cuando correspondan, componente y alternativa.
- `id_analisis_validado` para la carga inicial.
- Observaciones y estado de revisión.

La regla general de la carga inicial del EFT ubica los KMZ en `Datos_Proyecto`. Las excepciones de capas corporativas/complementos de consultores hacia `Datos_Internos` se revisan en la misma matriz. Los recortes públicos de los KMZ se conservan por proyecto; las capas públicas completas se obtienen de los servicios oficiales.

`ruta_componentes_json` conserva los niveles reales de la jerarquía. No reconstruirlos separando `ruta_kml` por `/`: algunos nombres originales contienen barras. El número de contenedor distingue carpetas distintas aunque compartan el mismo texto.

Las etiquetas HTML son una extracción heurística para inspección: pueden incluir títulos y valores de presentación. **No son un diccionario de campos aprobado.** El HTML y los valores originales permanecen en los KMZ; la equivalencia de campos, tipos y unidades se define antes de la conversión final.

## Flujo de trabajo propuesto

1. **Inventario — realizado:** conservar originales, identificar copias exactas, rutas, geometrías y atributos.
2. **Mapeo — pendiente:** revisar la matriz, agrupar por tema y geometría, y vincular cada contenido con las claves de Mapline. El EFT exige una tabla de mapeo revisada antes de la carga.
3. **Conversión temporal:** reutilizar `Organizador_KMZ_ArcGIS.pyt` para obtener GDB/LYRX locales. No importar su organización por KMZ/categoría como estructura final de SQL Server.
4. **Preparación de atributos:** extraer `description`/`PopupInfo`, `Data/value` y `SchemaData/SimpleData`; aplicar equivalencias revisadas sin perder atributos. Mantener procedencia y claves de negocio.
5. **Consolidación temática:** reunir, por ejemplo, las estructuras de todos los proyectos en la clase `Estructuras`, diferenciándolas por proyecto/análisis. Los temas con distintos tipos geométricos necesitan clases físicas diferentes.
6. **Validación y carga:** conciliar registros, partes, atributos y claves; comprobar geometría y referencia espacial. Cargar las clases finales de `ArcGisAWS` después de cerrar el mapeo y sus condiciones de edición.

El inventario no valida geometrías de ArcGIS, no asigna IDs de negocio, no aprueba filas y no modifica SQL Server. Tampoco convierte la malla o las interferencias de los KMZ en resultados históricos de Mapline: su procedencia y función deben comprobarse conforme al EFT.

## Herramienta existente e insumos adicionales

Consultar [REVISION_HERRAMIENTA.md](REVISION_HERRAMIENTA.md) para conocer qué se aprovecha y qué falta en el organizador actual.

En `InformaciónMapline/CapasExternas/CapasExternas.qgz` se identificaron 134 referencias remotas: 130 FeatureServer, tres MapServer y una WMS. Ese proyecto de QGIS es un catálogo adicional para revisar contra el alcance; no demuestra que las capas estén descargadas ni que todas deban migrarse. No se consultaron esos servicios.

## Reproducir el inventario

`01_inventariar_kmz.py` utiliza Python estándar; no necesita ArcPy. El inventario ya está generado. Para otro lote, ejecutar **como archivo desde una terminal**, no pegar su contenido en la ventana Python de ArcGIS:

```bat
py -3 01_inventariar_kmz.py --input "C:\ruta\KMZ_originales" --output "C:\ruta\Inventario_nuevo"
```

Se puede repetir `--input` para varias carpetas. El destino debe ser nuevo y estar fuera de las entradas; así no se sobrescribe una matriz que ya fue revisada. No se descargan NetworkLinks ni recursos externos.

Fuentes: EFT v2.4, secciones 5.8.2, 5.8.5–5.8.11, y los trece KMZ inventariados. La documentación de Esri se usa únicamente para describir el funcionamiento de las herramientas GIS.
