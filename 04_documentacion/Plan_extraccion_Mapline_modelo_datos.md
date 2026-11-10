# Plan de extracción de Mapline para el modelo de datos de ENGIE Perú

Fecha: 30 de octubre de 2026  
Base documental: EFT - ENGIE Mapline ArcGIS Enterprise y ArcGIS Pro_v2.4.docx, principalmente secciones 5.8.1 a 5.8.11, con criterios funcionales de 4.1 y entregables de 6.  
Estado: propuesta para revisión técnica y funcional. No se ha accedido a Mapline ni ejecutado una extracción.

## 1. Objetivo y alcance

Obtener un paquete íntegro, trazable y reproducible de los datos de Mapline y de sus fuentes geográficas para poblar el modelo de ArcGIS Enterprise sobre SQL Server. La extracción abarca datos relacionales, geometrías, atributos, configuraciones y evidencias de resultados. Se propone conservar una copia de las 30 tablas en la zona de extracción, aunque solo 14 se migren como tablas o clases de entidad operativas.

La extracción se organiza en cuatro frentes: base Mapline; capas vinculadas mediante servicios y elementos GIS; KMZ internos e históricos; y fuentes externas e internas para el catálogo corporativo. La transformación y carga se incluyen como etapas posteriores para que cada dato extraído tenga un destino y una prueba de aceptación definidos.

La propuesta no contempla sincronización bidireccional ni convivencia operativa permanente, que la especificación deja fuera del alcance base. Una eventual segunda extracción antes del corte será un lote de migración controlado, cuyo alcance deberá acordarse.

## 2. Línea base documental y disponibilidad real

La especificación declara 30 tablas en siete grupos, 27 llaves foráneas entre las tablas consideradas en el modelo migrado y ausencia de geometría en las tablas de origen. Identifica 13 KMZ: nueve internos y cuatro de resultados; refiere 279.623 elementos y más de 3.600 carpetas. Estas cifras son referencias documentales: deberán verificarse contra los archivos efectivamente entregados.

El destino definido es ArcGisAWS sobre SQL Server, con Datos_Externos, Datos_Internos y Datos_Proyecto. El documento establece WGS84 EPSG:4326 como almacenamiento y análisis métricos en la zona UTM del proyecto. La implementación debe confirmar tolerancias, transformaciones y método de carga antes de procesar datos.

En la carpeta revisada únicamente se encontró la especificación Word. No están disponibles el DDL, el volcado de la base, los KMZ, los inventarios CSV mencionados, el Anexo 01 con los servicios ni los accesos al sistema. Por ello, los tipos físicos, conteos, rutas de servicios y correspondencias de campos quedan sujetos a verificación.

## 3. Insumos que debe entregar el equipo

| Insumo | Uso | Responsable propuesto | Condición de inicio |
|---|---|---|---|
| Acceso de lectura o respaldo consistente de Mapline y motor/versión real | Extraer estructura y datos | ENGIE / administrador de origen | Obligatorio para extracción relacional |
| DDL de las 30 tablas, índices, restricciones y objetos relacionados | Confirmar modelo físico y dependencias | ENGIE | Obligatorio para cerrar mapeo |
| Exportación del catálogo de capas con URL, item ID y subcapa | Resolver geometrías ligadas a registros | ENGIE / administrador GIS | Obligatorio para frente GIS |
| Nueve KMZ internos y cuatro de resultados, incluidos históricos | Completar geometrías y atributos | ENGIE | Obligatorio para frente KMZ |
| Inventarios KMZ de capas, campos y matriz de campos | Contrastar alcance y preparar mapeo | ENGIE / INDRA | Recomendado; regenerar si falta |
| Anexos 01 y 03 y formato de configuración Mapline | Validar servicios y vértices | ENGIE | Antes de cerrar reglas de carga |
| Proyecto de referencia con configuración y resultados | Comparación funcional | Key user ENGIE | Antes del piloto |
| Acceso técnico a ArcGisAWS y entorno de prueba | Validar esquema y carga | Telemática / ENGIE | Antes del piloto de carga |

Las responsabilidades anteriores son propuestas de coordinación; las asignaciones de personas y accesos deben confirmarse.

## 4. Paquete de extracción y controles transversales

Cada extracción tendrá un id_lote, fecha de corte, ambiente, herramienta y versión, responsable, alcance y resultado. La copia de origen será inmutable y separada de los datos transformados. No se eliminarán ni modificarán datos del sistema de origen.

Estructura propuesta del paquete:

- 00_control: manifiesto, fecha de corte, hashes SHA-256, conteos, incidencias y decisiones.
- 01_modelo_origen: DDL y diccionario de campos, claves y relaciones.
- 02_relacional: copia nativa de respaldo cuando esté disponible y exportaciones por tabla con esquema explícito.
- 03_gis: metadatos de elementos y servicios, geometrías y atributos por capa.
- 04_kmz: originales e inventario por archivo, carpeta, tema y geometría.
- 05_mapeos: equivalencias de identificadores, campos, dominios y rutas KMZ.
- 06_transformado: datos preparados para carga, separados por lote y destino.
- 07_validacion: conciliaciones, rechazos y comparación con Mapline.

El manifiesto identificará por objeto: fuente, filtro, conteo previo, conteo exportado, conteo rechazado, ruta del archivo, hash, sistema de coordenadas, fecha de extracción y estado. Los conteos se medirán con el mismo alcance y corte. Cada registro debe quedar cargado, excluido justificadamente o en rechazo identificado; no se admitirán pérdidas silenciosas.

## 5. Matriz de extracción de las 30 tablas

Los nombres siguientes usan el prefijo mline_, salvo net_log. Deben contrastarse con el DDL real. Las agrupaciones de una fila representan varias tablas y no reducen el inventario de 30.

| Grupo | Tablas de origen | Extracción | Destino operativo según EFT |
|---|---|---|---|
| Parámetros | tp_tipoparametro; tp_parametro | Completa, códigos, descripciones y auditoría | Dominios codificados y subtipos cuando corresponda |
| Maestros GIS | tm_fuente_gis; tm_capa; tm_capa_propiedad | Completa, con referencias a servicios y campos | Catálogo del Portal, metadatos y campos de clases |
| Maestros GIS | tm_capa_aspecto_punto; tm_capa_aspecto_polilinea; tm_capa_aspecto_poligono; tm_capa_aspecto_etiqueta | Completa | Simbología y etiquetado en capas y archivos .lyrx |
| Importación | tc_fuente_gis_importacion; td_capa_importacion | Completa para trazabilidad | Archivo histórico de extracción; nueva operación con herramientas de carga |
| Proyecto | tc_proyecto | Completa, incluidos estados y borrado lógico | Tabla mline_tc_proyecto |
| Proyecto | ta_proyecto_estado | Completa | Tabla de historial de estados |
| Proyecto | td_proyecto_componente | Completa | Tabla de componentes |
| Proyecto | td_proyecto_ltransmision | Completa y resolución de geometría externa | Feature class de línea |
| Proyecto | td_proyecto_cgeneracion | Completa y resolución de geometría externa | Feature class de polígono |
| Proyecto | td_proyecto_capa | Completa, conservando referencias antiguas | Tabla con correspondencia a elementos del Portal destino |
| Proyecto | td_proyecto_regla_cfg | Completa, incluidos orígenes, filtros, anchos y ponderaciones | Tabla de configuración con referencias convertidas |
| Proyecto | td_proyecto_tematico | Completa, rangos, colores y acciones | Renderer clasificado y evidencia de equivalencia funcional |
| Espacial | td_proyecto_area_interes; td_proyecto_envelope; td_proyecto_celda | Completa y resolución de geometrías vinculadas | Tres feature classes de polígono |
| Espacial | td_celda_capa | Completa | Tabla de calificación por capa y celda |
| Alternativas | td_proyecto_alternativa | Completa, incluida alternativa de origen | Tabla de alternativas |
| Alternativas | td_proyecto_infraestructura | Completa y resolución de geometría vinculada | Feature class de línea |
| Alternativas | td_infraestructura_celda | Completa | Tabla de interferencias |
| Procesos | tc_proceso; tc_proceso_arcgis; td_proceso_log; net_log | Completa, sin suponer PK en los logs | Archivo histórico; nueva operación con geoprocesamiento y registros ArcGIS |

Resultado esperado: 14 objetos operativos migrados, seis espaciales y ocho tabulares. Las otras 16 tablas se extraen como insumo de conversión o conservación histórica, sin crear automáticamente equivalentes operativos en destino. El historial nuevo de ArcGIS no sustituye retrospectivamente los registros antiguos.

## 6. Procedimiento de extracción relacional

1. Identificar el motor y versión efectivos. La EFT señala scripts de MySQL Workbench; esto no basta para confirmar la plataforma productiva.
2. Obtener DDL, claves, índices, tipos, longitudes, precisión, valores por defecto, codificación, zona horaria y reglas de nulabilidad. Inventariar objetos adicionales y justificar su inclusión si son necesarios para interpretar los datos.
3. Acordar un corte consistente. Usar respaldo o mecanismo de lectura consistente adecuado al motor; si no está disponible, acordar una ventana controlada. Evitar que proyectos, reglas y resultados correspondan a instantes distintos.
4. Extraer las 30 tablas completas. Conservar PK, FK, códigos, es_registro y todos los campos de usuario, IP y fecha de creación, actualización y eliminación. No filtrar borrados lógicos en la copia de origen.
5. Separar las decisiones de inclusión operativa del volcado original. Documentar cómo se cargarán registros inactivos, eliminados y proyectos históricos, preservando las dependencias.
6. Conservar los campos es_proceso, fe_inicio_proc, fe_avance_proc, fe_fin_proc y de_mensaje_usuario, y los campos de reportes que existan. Registrar ejecuciones inconclusas y acordar su estado al migrar; no reactivar automáticamente procesos heredados.
7. Conciliar filas por tabla y por proyecto, duplicados de PK, nulos en claves y huérfanos. En tablas sin PK, conservar duplicados y añadir solo un identificador técnico de extracción, sin presentarlo como clave de negocio.
8. Producir el diccionario y mapeo MySQL/SQL Server, cuando se confirme el motor: fechas, precisión decimal, textos, booleanos, autoincrementales y valores incompatibles. Mantener el dato original y registrar conversiones rechazadas.

## 7. Extracción de geometrías y vínculo con Mapline

Para cada registro de td_proyecto_capa, resolver la referencia disponible hacia elemento, servicio y subcapa. Capturar URL, identificador antiguo, esquema, campos, referencia espacial, conteos, extensión, renderers y metadatos necesarios. Identificar cuál ambiente conserva los datos: la EFT indica que ArcGIS Online actual no contiene datos productivos; no debe suponerse que allí siguen disponibles todas las capas históricas.

Extraer geometría y atributos de cada fuente accesible. Si la extracción se realiza por consultas a un servicio, verificar sus límites y capacidades y aplicar paginación o partición adecuada. Conciliar el conjunto completo con el conteo de origen al mismo corte, detectando registros repetidos o ausentes. No aceptar una descarga parcial como capa completa.

Construir una tabla de correspondencia: tabla y PK de negocio → id_proyecto_capa antiguo → servicio/subcapa → identificador de entidad de origen → clase y clave destino. La unión se debe demostrar con atributos y referencias verificables; no se debe unir por posición de fila o por OBJECTID nuevo.

Las seis clases espaciales migradas requieren un control de cobertura de geometría por registro: línea de transmisión, central de generación, área de interés, envelope, celda e infraestructura. Cuando falte geometría, registrar la incidencia y evaluar una fuente KMZ inequívoca. Una geometría reconstruida o un resultado recalculado se identifica como tal y no se presenta como extracción del resultado histórico.

Conservar en el paquete de control los identificadores de sistema de origen para conciliación. No cargarlos como OBJECTID o GlobalID del destino; usar id_origen y las equivalencias pertinentes. Conservar los ID de negocio mientras el modelo lo permita.

## 8. Extracción y transformación de los KMZ

1. Inventariar los 13 archivos entregados, sus hashes, proyectos, carpetas, cantidad de elementos, geometrías y atributos. Contrastar con las cifras documentales y explicar diferencias.
2. Conservar los KMZ originales. Extraer jerarquías, nombres, coordenadas, atributos ExtendedData si existen y tablas HTML de descripción/PopupInfo. No considerar suficiente una importación que deje los atributos de negocio encerrados en un texto HTML.
3. Crear una matriz editable con archivo_origen, ruta_kml, proyecto, componente, alternativa, disciplina, tema, geometría, clase_destino, incluir, regla de campos, justificación y estado de revisión. INDRA revisa el mapeo antes de la carga.
4. Separar cada tema por tipo de geometría. Para temas mixtos, acordar nombres físicos únicos en toda la geodatabase. La lista de clases de la EFT es orientativa, no un esquema físico cerrado.
5. Normalizar campos mediante equivalencias aprobadas y conservar todos los atributos de negocio. Mapear tensión a me_nivel_tension, longitud a me_longitud, subestaciones a no_subestacion_salida/no_subestacion_llegada y potencia a me_potencia cuando corresponda.
6. Asignar proyecto y un id_analisis reservado para carga inicial. Conservar co_proyecto en proyectos existentes; asignar nuevos códigos desde un mecanismo correlativo controlado para proyectos solo presentes en KMZ, evitando colisiones.
7. Separar área de estudio general hacia td_proyecto_area_interes y áreas por estación hacia AreaEstudioCampo. La incorporación al área de interés exige verificar componente y equivalencia semántica; no sustituir automáticamente un buffer histórico por cualquier polígono de estudio.
8. Procesar PLS-CADD por separado para Estructuras y Vanos, recuperando origen, destino, circuito, tensión y conductor cuando estén presentes. Enviar nombres no interpretables a revisión.
9. Generar Vertices desde trazos cuando corresponda. Definir códigos, orden, tramo y padre; validar huérfanos, duplicados y ciclos. Estos vértices son derivados, no la recuperación del historial de edición perdido.
10. Revisar copias CAD, textos y modelos 3D. Excluir únicamente con decisión registrada. Deduplicar solo copias demostradas del mismo contenido, preservando trazabilidad; nunca deduplicar indiscriminadamente entre proyectos o alternativas.

Las capas públicas contenidas en KMZ se cargan como recortes históricos de Datos_Proyecto, sin deduplicarlas entre proyectos. Las capas públicas completas se obtienen de su servicio oficial para Datos_Externos. Según la EFT, configuración de reglas, malla e interferencias no se recuperan desde los KMZ: se extraen de Mapline y de las fuentes vinculadas, o se regeneran como nuevos resultados identificados.

Existe una decisión pendiente en la EFT: afirma que todos los KMZ pertenecen a Datos_Proyecto, pero también ubica ciertos complementos de consultores en Datos_Internos. Se propone preservar inicialmente su pertenencia y procedencia de proyecto y promover una copia corporativa a Datos_Internos únicamente tras validar su alcance, mantenimiento y prevalencia con ENGIE.

## 9. Conversión al modelo de destino

| Elemento | Regla propuesta de conversión | Evidencia requerida |
|---|---|---|
| Parámetros | Convertir códigos y valores utilizados a dominios; subtipos solo donde proceda | Campo consumidor, código antiguo, código destino y descripción |
| Catálogo | Crear equivalencias entre capa antigua y elemento del Portal destino | ID antiguo, URL/subcapa, clase destino e id_capa_arcgis nuevo |
| Filtros | Sustituir referencias a propiedades por campos físicos y criterios válidos | Regla original, campo destino, expresión convertida y resultado de prueba |
| Temático y aspectos | Transformar rangos, colores, etiquetas y acciones | Comparación con representación original; validar acciones no cubiertas solo por renderer |
| Auditoría | Conservar auditoría propia y configurar Editor Tracking sin sobrescribir la historia | Campos heredados y campos nuevos distinguidos |
| Identificadores | Mantener claves de negocio; regenerar campos de sistema de geodatabase | Tabla de correspondencia y pruebas de integridad |
| Geometría | Almacenar según EPSG:4326 definido en EFT y analizar en UTM del proyecto | CRS de entrada/salida, transformación aplicada y controles de medida |
| Relaciones | Reproducir dependencias validadas del DDL y definir relaciones GIS compatibles | Matriz padre/hija y prueba de navegación e integridad |

No se retirarán tablas reemplazadas ni referencias antiguas del paquete de extracción. En el esquema destino, la retirada de llaves declaradas sin uso se hará después de validar la migración geométrica completa, según la EFT. El DDL real prevalece sobre relaciones inferidas de diagramas o catálogos.

## 10. Orden de carga y dependencias

La extracción puede ejecutarse por frentes, pero debe compartir un corte y manifiesto coherentes. El siguiente orden corresponde a carga lógica y debe ajustarse con el grafo del DDL real:

1. Crear esquema aprobado, dominios, campos y tablas de correspondencia. Preparar clases generales y catálogo de destino.
2. Cargar mline_tc_proyecto; después historial de estados y componentes.
3. Cargar clases de línea de transmisión y central de generación con sus componentes.
4. Cargar catálogo de capas por proyecto, resolviendo referencias al Portal cuando esté disponible el elemento destino.
5. Cargar reglas en orden de dependencia; resolver autorreferencias en un segundo paso cuando sea necesario.
6. Cargar área de interés → envelope → celdas → relación celda/capa.
7. Cargar alternativas y resolver alternativa de origen → infraestructura → relación infraestructura/celda. Las dependencias con celdas deben estar satisfechas antes de cargar interferencias.
8. Cargar clases adicionales KMZ, recortes y vértices con proyecto, análisis y relaciones definidas.
9. Configurar relaciones, auditoría, servicios y branch versioning mediante un procedimiento validado para el entorno destino; definir antes del piloto en qué momento se registra cada objeto y qué vía de carga se utilizará.
10. Conciliar y ejecutar comparación funcional antes de habilitar el uso.

La EFT define branch versioning para Datos_Proyecto y las tablas migradas, y ausencia de versionado para Datos_Externos/Datos_Internos. La compatibilidad concreta de claves y relationship classes debe probarse en el piloto. No usar Truncate en clases versionadas.

## 11. Validaciones y criterios de aceptación

| Control | Criterio propuesto | Evidencia |
|---|---|---|
| Cobertura de extracción | Las 30 tablas y todas las fuentes inventariadas tienen estado final | Manifiesto firmado por responsable técnico |
| Conciliación relacional | Conteo origen = extraído al mismo corte; toda diferencia de carga está justificada | Reporte por tabla, proyecto y estado lógico |
| Integridad | Cero duplicados de clave o huérfanos nuevos introducidos por migración | Consultas y reporte de excepciones heredadas |
| Geometría | Todo registro espacial incluido tiene geometría válida o excepción resuelta | Conciliación registro/geometría, tipos y extensión |
| KMZ | Cada elemento queda cargado, excluido justificadamente o rechazado | Balance por archivo, ruta y geometría |
| Campos | Sin truncamientos ni conversiones silenciosas; atributos conservados según mapeo | Reporte de longitudes, nulos y valores fuera de dominio |
| Trazabilidad | Cada elemento cargado puede remontarse a su fuente y lote | Mapeos, hashes y campos de procedencia |
| Capas completas externas | Igual cantidad de entidades que el servicio para el mismo alcance y corte | Conteo y cobertura de identificadores |
| Área de interés | Coincidencia con referencia para igual trazo y ancho, con tolerancia geométrica acordada | Comparación espacial y medidas |
| Intersecciones | Cantidad de elementos por capa coincide con proyecto de referencia | Reporte comparativo Mapline/destino |
| Malla | Distribución de ponderaciones dentro de tolerancia acordada con ENGIE | Comparación por celda o correspondencia espacial validada |
| Alternativas | Interferencias y ponderaciones reproducibles con igual configuración | Comparación por alternativa y tramo |
| Representación | Rangos, colores, etiquetas y comportamiento requerido preservados | Revisión funcional y visual |

El cierre exige cero rechazos sin decisión de tratamiento. Las tolerancias geométricas y numéricas se acuerdan antes del piloto; no se presume una equivalencia exacta sin definir precisión, redondeo y método de cálculo.

## 12. Fases y entregables de ejecución

| Fase | Actividades | Salida verificable | Dependencia |
|---|---|---|---|
| F0 Preparación | Accesos, insumos, alcance histórico y fecha de corte | Checklist de disponibilidad y acta de alcance | ENGIE y proveedores |
| F1 Inventario | DDL, perfiles de datos, fuentes GIS y KMZ | Inventario y diccionario de origen | F0 por cada frente |
| F2 Extracción | Copia consistente de tablas, capas y archivos | Paquete de origen con hashes y conteos | F1 |
| F3 Mapeo | Claves, campos, dominios, geometrías y clasificación KMZ | Matriz origen/destino revisada | F2 |
| F4 Piloto | Un proyecto de referencia y casos especiales representativos | Carga piloto y reporte comparativo | F3 y entorno disponible |
| F5 Carga completa | Ejecutar reglas aprobadas para históricos y demás proyectos | Modelo poblado y balance de carga | Piloto aceptado |
| F6 Corte y cierre | Confirmar cambios desde el corte, ejecutar lote final acordado y conciliar | Acta de aceptación y paquete de recuperación | F5 y decisión de corte |

La especificación organiza entregables por sprints de tres semanas. La duración de cada fase y su distribución en sprints se estimarán después del inventario y piloto, considerando accesos, volumen real y calidad de fuentes; no se establece aquí una fecha contractual sin esos datos.

Entregables mínimos: manifiesto de extracción; diccionario físico; matriz de 30 tablas; matriz de geometrías y capas; mapeo KMZ y campos; equivalencias de dominios y claves; paquete original; scripts o herramientas reproducibles; reporte de calidad; evidencia funcional del piloto; procedimiento de carga y recuperación; acta de conciliación final.

## 13. Decisiones que deben cerrarse antes de la carga completa

| Decisión | Motivo | Responsable propuesto |
|---|---|---|
| Motor, ambiente fuente y mecanismo de corte | Evitar extraer de un ambiente incompleto | ENGIE / administrador de base |
| Ubicación real de geometrías históricas | La base no contiene geometría y AGOL actual se declara sin datos productivos | ENGIE / administrador GIS |
| DDL canónico y nomenclatura física | El texto alterna nombres con y sin prefijo mline_ | INDRA / ENGIE |
| Claves y tipos de relación GIS | Confirmar compatibilidad del modelo relacional con la geodatabase | INDRA / Telemática |
| Alcance de borrados lógicos e históricos | Conservar la historia y evitar perder dependencias | ENGIE |
| Tratamiento de complementos de consultores y prevalencia | Hay una ambigüedad entre Datos_Proyecto y Datos_Internos | ENGIE / INDRA |
| Identidad y cobertura de id_analisis | No confundir corrida de análisis con versión de edición | INDRA / key user ENGIE |
| Separación de clases mixtas y longitudes de campos | La lista temática no define todo el modelo físico | INDRA |
| CRS de entrada, tolerancias y unidades | El almacenamiento geográfico requiere análisis métricos controlados | INDRA / key user ENGIE |
| Resultado histórico faltante frente a recálculo | No confundir conservación con generación de un análisis nuevo | ENGIE |
| Preservación de acciones del temático y auditoría antigua | Un renderer o historial nuevo podría no cubrir toda la función anterior | INDRA / ENGIE |
| Ventana de corte, recuperación y acceso al legado | Completar migración sin pérdida de cambios entre lotes | ENGIE / Telemática / INDRA |

## 14. Primera acción ejecutable

Solicitar el DDL y una copia consistente de las 30 tablas, el catálogo con las referencias GIS, los 13 KMZ y un proyecto de referencia. Con esos insumos, ejecutar F1 y producir el mapeo físico campo a campo. El primer hito de revisión será un inventario conciliado que demuestre qué registros tienen geometría recuperable, cuáles se completan desde KMZ y cuáles requieren decisión de ENGIE.
