# Carga de Mapline en ArcGisAWS conforme al EFT

Este paquete usa la base **ArcGisAWS ya existente**, indicada en la sección 3.1 del EFT en el servidor EEPAWSDBP01. No crea otra base ni sobrescribe tablas existentes. La migración operativa del apartado 5.8 requiere ocho tablas y seis clases de entidad, con geometría, relaciones, GlobalID, Editor Tracking y branch versioning. El SQL de origen no contiene esas geometrías.

## Qué ejecutar primero

Llevar **01_cargar_origen_en_ArcGisAWS.sql** al SQL Server de destino. Es el archivo SQL correcto de este paquete para importar el respaldo a la base existente. No ejecutar el anterior Mapline_20261030_SQLServer.sql: ese crea una base de prueba y no corresponde a esta carga.

1. Conectarse a la instancia que contiene ArcGisAWS con SSMS y una cuenta con permisos para crear el esquema de carga y sus tablas. El SQL no crea usuarios ni asigna permisos de servidor.
2. Abrir 01_cargar_origen_en_ArcGisAWS.sql y activar **Consulta > Modo SQLCMD**. La extensión sigue siendo .sql. El modo se usa para detenerse ante errores mediante :ON ERROR EXIT.
3. Ejecutar una vez. Crea el esquema **mapline_carga_20261030** y allí guarda las 30 tablas del respaldo: estructura y 1.110.585 registros. Las tablas de parámetros y maestros se conservan aquí como insumo de conversión; no pasan por ello a ser parte del modelo operativo.
4. Revisar los resultados de conteos y referencias huérfanas. Los conteos exactos se exigen antes de COMMIT; los huérfanos heredados se informan para su resolución. En esta zona no se imponen las claves foráneas del legado. No omitir errores ni volver a ejecutar sobre un esquema existente.
5. Si falla, detener la ejecución y cerrar la conexión para revertir cualquier transacción pendiente. Si se conserva la misma sesión de SSMS, comprobar @@TRANCOUNT y ejecutar ROLLBACK TRANSACTION si queda una transacción abierta. Revisar el error antes de reiniciar. El script no elimina ni reemplaza un esquema existente.

Alternativa desde consola, con autenticación integrada, sustituyendo SERVIDOR por la instancia autorizada y usando la ruta real:

    sqlcmd -S SERVIDOR -d ArcGisAWS -E -b -f 65001 -i "01_cargar_origen_en_ArcGisAWS.sql"

El servidor no se configura automáticamente desde el nombre del EFT: la conexión debe apuntar a la instancia real. El script sí fija USE [ArcGisAWS]. El tamaño del SQL es aproximadamente 184 MB. La carga mantiene una transacción hasta la conciliación final; el administrador debe prever el espacio del log para el lote.

**Al terminar este primer paso, el respaldo estará importado en SQL Server. El modelo operativo de ArcGIS se configura en el segundo paso.** Los datos del esquema de carga permanecen sin versionar y no deben confundirse con los objetos de producción.

## Segundo paso desde ArcGIS Pro

02_cargar_modelo_arcgis.py crea y carga los **14 objetos migrados del modelo Mapline** mediante ArcPy. No instala ArcGIS, no publica servicios y no migra los 143 procedimientos de MySQL. Antes de ejecutar se necesitan las fuentes geográficas y los mapeos reales.

Completar config_carga.json:

- source_sde: ruta al archivo de conexión .sde que lee las tablas ArcGisAWS.mapline_carga_20261030. El usuario lector necesita SELECT sobre ese esquema.
- destination_sde: conexión .sde a ArcGisAWS como propietario de los datos del modelo final. En las propiedades de conexión de ArcGIS Pro, configurar **Versioning Type = Branch**.
- destination_owner: propietario/esquema real de las tablas y clases finales, coincidente con el usuario y esquema autorizado de la conexión. No se presupone dbo ni sde.
- geometry_sources: una fuente por cada una de las seis clases, con path, key_field y analysis_field. Cada fuente debe estar validada en EPSG:4326, tener el mismo tipo geométrico y una correspondencia uno a uno entre su clave histórica y todos los registros del respaldo. No unir por número de fila ni por OBJECTID regenerado.
- portal_mappings: ruta a un JSON con equivalencias por id_proyecto_capa antiguo hacia item_id del Portal destino, layer_id, class_name. Una capa retirada solo se acepta con retired=true y reason cuando no tiene usos operativos vigentes. Los identificadores no se publican ni se verifican remotamente por este script.
- filter_mappings: ruta a un JSON por id_proyecto_regla_cfg que necesite conversión, con field_name, filter_code y validation_path para comprobar el campo físico de evaluación. Los filtros no se reinterpretan automáticamente sin revisión funcional.

Ejemplo de estructura de una equivalencia Portal; sustituir todos los valores por los reales:

    {"ID_ANTIGUO": {"item_id": "ID_REAL_DE_32_HEXADECIMALES", "layer_id": 0, "class_name": "CLASE_REAL"}}

Ejemplo de estructura de una equivalencia de filtros:

    {"ID_REGLA": {"field_name": "CAMPO_REAL", "filter_code": "CODIGO_REVISADO", "validation_path": "RUTA_REAL_A_LA_CAPA"}}

Los JSON de mapeo se entregan vacíos porque no se dispone de las referencias del Portal destino ni de las capas para demostrar las equivalencias. Las rutas .sde también quedan vacías; no se incluyeron credenciales.

Usar el entorno Python de ArcGIS Pro. Primero ejecutar la validación, que no crea ni carga objetos de destino:

    python 02_cargar_modelo_arcgis.py --config config_carga.json --report validacion_previa.json

Cuando la validación sea correcta y se haya revisado el mapeo, ejecutar la carga inicial:

    python 02_cargar_modelo_arcgis.py --config config_carga.json --apply --report resultado_carga_arcgis.json

La carga se detiene si los objetos finales ya existen. No implementa recarga ni merge de una geodatabase ya poblada. Un error durante creación/carga ArcPy puede dejar objetos parciales; el reporte lo identifica y no se realiza borrado automático. Debe revisarse el estado antes de volver a ejecutar.

## Transformaciones del modelo

- Las seis clases migradas se crean en Datos_Proyecto: mline_td_proyecto_ltransmision y mline_td_proyecto_infraestructura como líneas; mline_td_proyecto_cgeneracion, mline_td_proyecto_area_interes, mline_td_proyecto_envelope y mline_td_proyecto_celda como polígonos.
- Las ocho tablas son mline_tc_proyecto, mline_ta_proyecto_estado, mline_td_proyecto_componente, mline_td_proyecto_capa, mline_td_proyecto_regla_cfg, mline_td_proyecto_alternativa, mline_td_celda_capa y mline_td_infraestructura_celda.
- Se preservan los ID de negocio. ArcGIS administra sus propios ObjectID y GlobalID. Las relaciones GIS usan GlobalID del padre y campos GUID adicionales del hijo; las claves de negocio se mantienen para trazabilidad y control. Las autorreferencias de alternativa y regla conservan campos y validaciones, sin crear relationship classes recursivas, que ArcGIS no admite. No se trasladan al modelo final los índices únicos de negocio que impiden el registro branch; la unicidad de los valores se valida antes de la carga.
- Los campos que apuntaban a capas geométricas sustituidas se conservan vacíos en el modelo final; su valor original permanece en el esquema de carga. No se eliminan prematuramente.
- Parámetros se convierten a dominios manteniendo id_parametro como código. El valor numérico de ponderación se materializa en valor_ponderacion para no confundir el ID de parámetro con su peso.
- El catálogo apunta a los nuevos elementos del Portal y los filtros a campos físicos validados. Los ID heredados permanecen como trazabilidad, sin crear FKs hacia las tablas reemplazadas.
- La auditoría original se conserva. Los campos nuevos de Editor Tracking se mantienen separados y registran en UTC. Se crean relaciones de geodatabase y se registra branch tras cargar y verificar los datos, mediante las herramientas de ArcGIS.

Las características anteriores corresponden a la carga inicial de los 14 objetos migrados. Las clases adicionales de KMZ, Vertices, Estructuras, Vanos, recortes, capas externas/internas, dominios temáticos, simbología, servicios, seguridad y publicación requieren sus respectivos insumos y pasos del plan. Este paquete no declara completado todo el modelo del EFT.

## Pendientes que el respaldo no puede resolver

El SQL contiene 496.066 filas de celdas sin geometría, 96 áreas de interés, 96 envelopes, 114 líneas de transmisión, seis centrales y seis infraestructuras. Se requiere recuperar sus geometrías y demostrar la correspondencia con las claves del legado. No basta crear clases vacías ni recalcular celdas y considerarlas resultados históricos.

id_analisis no existe en las tablas de origen. Su valor debe venir de una correspondencia revisada con los datos de análisis o de una decisión explícita de snapshot de migración, diferenciada de un análisis histórico recuperado y de la carga inicial KMZ. El cargador exige un campo de análisis en las fuentes y no inventa ese historial.

El EFT menciona 27 llaves entre tablas migradas. El DDL del respaldo recibido contiene 26 entre los 14 objetos y diez referencias adicionales a grupos que se reemplazan. El modelo_eft.json usa las relaciones físicas verificadas, separando las obsoletas. La discrepancia debe incorporarse al ajuste documental.

## Verificación realizada

Se compararon de forma independiente todos los valores decodificados de cada INSERT MySQL con los valores T-SQL generados, por tabla y en el mismo orden: **1.110.585 filas coinciden**. El reporte validacion_conversion.json incluye hashes de valores, columnas, conteos y lotes. Las tres tablas vacías coinciden con la confirmación del usuario. El original no se modificó.

No se ha ejecutado la carga contra SQL Server ni ArcGIS Enterprise, ni se ha verificado conectividad, permisos o fuentes geométricas. La compilación de Python y las validaciones locales no sustituyen esa comprobación en el entorno destino.

## Fuentes técnicas

- EFT de la carpeta, secciones 3.1 y 5.8.1 a 5.8.11.
- [Requisitos de branch versioning](https://pro.arcgis.com/en/pro-app/3.3/help/data/geodatabases/overview/register-a-dataset-as-branch-versioned.htm).
- [Register As Versioned y conexión del propietario](https://pro.arcgis.com/en/pro-app/3.2/tool-reference/data-management/register-as-versioned.htm).
- [Creación de relationship classes](https://pro.arcgis.com/en/pro-app/3.3/tool-reference/data-management/create-relationship-class.htm).
- [Tipos y precisión de campos ArcGIS](https://doc.esri.com/en/arcgis-pro/latest/tool-reference/data-management/add-field.html).

- [Limitaciones de relaciones recursivas](https://doc.esri.com/en/arcgis-pro/latest/help/data/relationships/geodatabase-relationship-class-fundamentals.html).
- [GlobalID y edición de servicios branch](https://support.esri.com/en-us/knowledge-base/error-error-code-400-invalid-request-layer-does-not-sup-000030282).
