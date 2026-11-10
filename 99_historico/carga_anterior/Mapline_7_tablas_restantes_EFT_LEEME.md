# Carga de las siete tablas tabulares restantes del EFT

Ejecutar **Mapline_7_tablas_restantes_EFT_SQLServer.sql** en SSMS conectado a la instancia que contiene **ArcGisAWS**. No requiere modo SQLCMD ni crea esquemas: usa el esquema predeterminado del usuario, igual que el archivo de proyectos. El SQL no crea, modifica ni vuelve a cargar `mline_tc_proyecto`.

| Tabla | Registros |
|---|---:|
| mline_ta_proyecto_estado | 50 |
| mline_td_proyecto_componente | 120 |
| mline_td_proyecto_capa | 2.311 |
| mline_td_proyecto_regla_cfg | 1.578 |
| mline_td_proyecto_alternativa | 8 |
| mline_td_celda_capa | 589.015 |
| mline_td_infraestructura_celda | 2.767 |
| Total | 595.849 |

Antes de ejecutar, `mline_tc_proyecto` debe existir y ninguna de estas siete tablas debe existir con el nombre resuelto por la conexión. El archivo se detiene si detecta una tabla existente; no implementa recarga de tablas ya registradas o versionadas. Usa la misma cuenta y base que utilizaste para importar proyectos; en la captura esa tabla se encontraba en el esquema `gis`.

El script carga las siete tablas en una transacción y comprueba conteos y unicidad de los identificadores. Después del mensaje final, revisa que los siete conteos coincidan con esta lista. Si se produce un error, conserva el mensaje y revisa el estado de la transacción antes de intentar otra ejecución. No se ha ejecutado este archivo contra el servidor.

Se preservan los ID de negocio y se usan índices no únicos, para su posterior configuración con branch versioning. No se crean claves foráneas SQL a parámetros, catálogos o clases espaciales pendientes. Las referencias vigentes se conservan. Las cuatro referencias a capas de geometría que el EFT declara sin uso se dejan vacías en los objetos recién creados: componente.id_proyecto_capa_componente, componente.id_proyecto_capa_vertices, alternativa.id_proyecto_capa_alternativa y alternativa.id_proyecto_capa_vertices. Sus valores originales siguen en el respaldo MySQL.

Esta es la carga de estructura y datos alfanuméricos. Faltan el registro de estas tablas en la geodatabase, ObjectID, GlobalID, Editor Tracking, dominios, correspondencias del Portal y filtros, relaciones GIS y branch versioning. Las tablas `celda_capa` e `infraestructura_celda` conservan referencias a las clases espaciales que deben cargarse después; importarlas no completa esas relaciones.

Los seis objetos restantes del EFT son clases de entidad y requieren carga de geometría desde ArcGIS: línea de transmisión, central de generación, infraestructura, área de interés, envelope y celdas. No están sustituidos por tablas SQL vacías en este archivo.

El archivo de validación adjunto comprueba que las líneas de valores de los INSERT coinciden con la conversión del respaldo previamente validada y registra por separado las cuatro columnas vaciadas después de insertar. El original MySQL no se modifica.
