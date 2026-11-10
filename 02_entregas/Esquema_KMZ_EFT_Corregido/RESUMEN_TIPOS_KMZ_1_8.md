# Resultado de la revisión completa de tipos

La lectura de las fuentes se completó el 9 de noviembre de 2026. Se reconciliaron los **13 KMZ, 3.638 rutas y 279.623 elementos** del inventario, sin diferencias de conteo. Se observaron los **7.110 vínculos esperados entre rutas, atributos y campos de destino**.

La revisión incluye las **3.340 definiciones de campos de las 76 clases** de `Datos_Proyecto`. Se analizaron 12.171 combinaciones de ruta, atributo, ocurrencia y canal de origen, incluidas las que no tienen destino. Los campos comunes, derivados y de DDL sin atributo KMZ se identifican por separado; sus reglas de generación corresponden a la preparación de carga.

## Propuestas para los 730 pendientes

| Tipo recomendado | Cantidad | Fundamento |
|---|---:|---|
| LONG | 6 | Declaración `int` completa y valores compatibles |
| DOUBLE | 2 | Declaración `double` completa y valores compatibles |
| TEXT | 722 | Conservación documentada del contenido; detalle debajo |

Las 722 propuestas TEXT se distribuyen en **539** campos sin declaración original completa, **181** sin valores útiles, **1** con declaración `long` no admitida por el criterio KML 2.2 y **1** con un conflicto de mapeo. La recomendación de texto permite conservar la representación disponible; no demuestra un tipo original que la fuente no declara.

Los ocho candidatos numéricos son:

| Clase | Campo | Destino propuesto |
|---|---|---|
| suelos_recorte | p_aui_suel | LONG |
| sitios_arqueologicos_poligono_recorte | alt_mode | LONG |
| sitios_arqueologicos_poligono_recorte | clamped | LONG |
| sitios_arqueologicos_poligono_recorte | extruded | LONG |
| sitios_arqueologicos_poligono_recorte | base | DOUBLE |
| sitios_arqueologicos_punto_recorte | alt_mode | LONG |
| sitios_arqueologicos_punto_recorte | has_label | LONG |
| sitios_arqueologicos_punto_recorte | base | DOUBLE |

Los valores cero o negativos se conservan. No se deduce que los campos sean booleanos ni se asignan unidades por su nombre.

## Cuatro incidencias de valores o mapeo

| Clase y campo | Hallazgo | Decisión necesaria antes de cargar |
|---|---|---|
| lineas_transmision_existentes_osinergmin_recorte.longitud_subterranea | `<Null>` en 6 de 14 entidades | Definir conversión del marcador a nulo en el campo DOUBLE |
| lineas_transmision_existentes_osinergmin_recorte.maxima_tension_operativa | `<Null>` en 3 de 14 entidades | Definir conversión del marcador a nulo en el campo DOUBLE |
| subestacion_poligono.src_area_ha | `<Null>` en 14 de 18 entidades | Definir conversión del marcador a nulo en el campo DOUBLE |
| predios_inscritos_sunarp_recorte.oficina_registral | Valores distintos confluyen en el mismo campo en 253 entidades | Resolver la correspondencia; TEXT tiene capacidad, pero no decide qué valor corresponde |

El lector distingue el HTML envolvente del atributo `description` y conserva el texto de tablas anidadas. Las falsas colisiones de esas representaciones no forman parte de estas cuatro incidencias.

Además, **11 grupos de atributos de origen declaran `long`**, fuera de la lista KML 2.2 usada para esta comprobación. Se mantienen como observaciones de declaración; no se convierten por nombre a LONG de ArcGIS. La capacidad del destino y la coherencia de la declaración original figuran en columnas separadas. Los tipos previamente confirmados también se revisaron y sus observaciones siguen en la matriz.

El indicador de campos que requieren decisión suma **737**: los 730 pendientes del modelo y 7 ya tipificados que tienen observaciones adicionales (los tres casos de nulo y cuatro campos TEXT con declaración `long` de origen). Esto no significa que existan 737 cambios físicos por ejecutar.

## Alcance de mapeo aún pendiente

El inventario contiene **2.601 rutas, con 140.319 elementos, sin clase de destino asignada**. Se leyeron y perfilaron, pero no quedan habilitadas para carga por terminar esta revisión de tipos. Será necesario resolver sus correspondencias o exclusiones justificadas conforme al EFT; no se crean tablas automáticamente por cada ruta.

`CONTENEDOR_XML_SIN_DESTINO` informa de envolturas conservadas como evidencia. No exige crear columnas. Los atributos sin correspondencia y los objetos KML ajenos a Placemark se identifican por códigos distintos en el informe completo.

## Ejecución siguiente

Abra la octava herramienta **Validar todos los tipos de los KMZ** con su conexión SDE, base `ArcGisAWS`, propietario `gis` y carpeta KMZ vacía. Consulte [los pasos de ejecución](GUIA_DATOS_PROYECTO.md).

El perfil incluido permite consultar la SDE sin trasladar otra vez los KMZ. La [matriz incluida](REVISION_TIPOS_KMZ_1_8.csv) procede de las fuentes revisadas y todavía no acredita el esquema de su servidor. La ejecución en CT6788 agrega esa comprobación física y produce `campos_destino.csv`.

El modelo sigue en versión 11 con **730 pendientes**. Estas son propuestas para resolver conjuntamente; todavía no se han aplicado ni aprobado tipos nuevos y no se han cargado registros. El resultado de esta fase es `VALIDACION_TIPOS_COMPLETA_CON_PENDIENTES`.

Los ensayos del paquete se documentan en `VALIDACION_PERFIL_COMPLETO_1_8.json`, `VALIDACION_TIPOS_1_8_ARCGIS.json` y `VALIDACION_UNITARIA_1_8.json`. El ensayo nativo utiliza una geodatabase local; la preservación se comprueba con hashes de todos sus archivos salvo bloqueos transitorios. No sustituye la ejecución sobre SQL Server/SDE.

`Datos_Externos` y `Datos_Internos` mantienen su implementación pendiente y sus fuentes propias. El cierre de tipos de KMZ corresponde a `Datos_Proyecto`.
