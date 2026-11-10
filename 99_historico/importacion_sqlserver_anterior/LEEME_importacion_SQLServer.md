# Importación de prueba de Mapline en SQL Server

Archivo principal: Mapline_20261030_SQLServer.sql.

1. Conectarse al SQL Server de prueba desde SSMS con una cuenta que pueda crear bases de datos.
2. Abrir el archivo principal y activar Consulta > Modo SQLCMD. El archivo utiliza GO y :ON ERROR EXIT; no ejecutarlo mediante un cliente que ignore estas instrucciones.
3. Ejecutar. Se creará Mapline_Migracion_Prueba_20261030. El script se detiene si la base ya existe; no elimina ni sobrescribe bases o tablas.
4. Revisar errores y el mensaje final de carga y validación completadas. El script comprueba conteos por tabla y crea las claves foráneas con validación. Si aparece un error, conservar el mensaje y no volver a ejecutar sobre la misma base: puede haber una carga parcial.

El archivo pesa aproximadamente 184 MB. Para evitar cargarlo en el editor, también puede ejecutarse con sqlcmd usando autenticación integrada, sustituyendo SERVIDOR por la instancia autorizada:

    sqlcmd -S SERVIDOR -E -b -f 65001 -i "Mapline_20261030_SQLServer.sql"

No se ha ejecutado ni probado contra una instancia SQL Server. Se validaron el inventario, la estructura reconocida, el número de valores por fila y los conteos durante la conversión. Estos controles no sustituyen una restauración de prueba ni la conciliación con la base MySQL.

## Alcance y diferencias

- Copia relacional de las 30 tablas; 1.110.585 filas. Las tres tablas vacías se crean sin datos.
- 62 índices secundarios y 62 claves foráneas, además de claves primarias definidas en origen.
- Textos Unicode y conversión de escapes MySQL; lotes de hasta 500 filas para respetar el límite de INSERT VALUES de SQL Server.
- varchar/char se convierten a nvarchar/nchar; varchar(10000) y longtext a nvarchar(max). Fechas datetime pasan a datetime2(0). No se añade IDENTITY porque el DDL de origen no declara AUTO_INCREMENT.
- DEFAULT CURRENT_TIMESTAMP pasa a SYSUTCDATETIME: validar la política UTC del destino antes de uso operativo.
- La intercalación de prueba Latin1_General_100_CI_AI_SC no garantiza una equivalencia exacta de comparación y ordenación con MySQL utf8mb4_0900_ai_ci.
- Comentarios de columnas y tablas y opciones físicas MySQL permanecen en el respaldo original, no se implementaron como propiedades extendidas.
- Los 143 procedimientos se conservan en Mapline_20261030_Rutinas_MySQL_NO_EJECUTAR_EN_SQLServer.sql; requieren adaptación funcional a T-SQL y no se ejecutan en el archivo principal. Ese archivo conserva la sección final de rutinas del dump original.
- No se crean geometrías ni capacidades de geodatabase. Esta base de prueba no sustituye el diseño final ArcGIS ni debe ejecutarse sobre ArcGisAWS.

El archivo Mapline_20261030_Conversion_SQLServer.json contiene los conteos esperados por tabla y el hash SHA-256 del original. convertir_mapline_sqlserver.mjs reproduce la conversión y se niega a sobrescribir el archivo principal existente.
