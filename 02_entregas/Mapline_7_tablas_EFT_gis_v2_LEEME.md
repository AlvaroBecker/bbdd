# Carga de siete tablas en gis por bloques

Usar **Mapline_7_tablas_EFT_gis_v2.sql** en una ventana nueva de SSMS conectada a la instancia que contiene **ArcGisAWS**. Abrir el archivo SQL descomprimido y ejecutar todo el contenido, sin dejar seleccionado un fragmento. No requiere modo SQLCMD.

Esta versión especifica el esquema **gis** que ya existe. No crea esquemas ni modifica `gis.mline_tc_proyecto`. Se detiene si encuentra cualquiera de las siete tablas de destino existentes; no implementa sobrescritura, recarga ni cambios sobre objetos registrados o versionados.

El archivo anterior enviaba toda la carga como un solo bloque grande. Esta versión divide los INSERT en **1.272 bloques**, de hasta 500 filas, y ejecuta cada uno mediante `sp_executesql` dentro de un control de errores. La división reduce el tamaño compilado por bloque y muestra mensajes de avance; no demuestra cuál fue la causa del intento anterior.

En **Messages / Mensajes** deben aparecer:

1. `INICIO Mapline EFT7 v2` y datos de servidor, base y usuario.
2. `Las 7 tablas GIS fueron creadas`.
3. Mensajes `Procesado` durante la carga.
4. `COMPLETADO: 7 tablas en GIS; COMMIT ejecutado y conteos validados` y siete resultados con conteos.

Si falla un bloque, se revierte la transacción, se registra la fase y el error y los bloques siguientes no cargan datos. Los errores muestran número, línea y detalle. El cierre verifica el orden completo de bloques, los conteos y la unicidad de los ID antes de confirmar. Un error de conexión o cancelación puede impedir que se ejecute el control final: cerrar esa conexión antes de reintentar y no confirmar manualmente una carga incompleta.

La tabla temporal `#MaplineEFT7Control` solo existe en esa sesión y mantiene el estado de ejecución. No es una tabla permanente adicional del modelo. Usar una ventana nueva para cada intento evita reutilizar ese estado o una transacción anterior.

La carga contiene 595.849 registros en las siete tablas: estados de proyecto, componentes, capas de proyecto, reglas, alternativas, relación celda/capa y relación infraestructura/celda. Se mantienen las mismas conversiones del paquete previo: índices no únicos, sin FK SQL y cuatro referencias obsoletas vaciadas según el EFT. Los datos originales permanecen en el respaldo MySQL.

Esta carga relacional todavía requiere el registro y configuración de ArcGIS, los dominios, mapeos Portal/filtros, relaciones y versionado, y las seis clases espaciales con su geometría. No modifica el diseño funcional ni añade generación automática de ID.

Se verificaron los 1.272 bloques y la conservación de sus valores por comparación de hashes después de desescapar el SQL dinámico. No se ha ejecutado el archivo contra SQL Server; queda pendiente la validación en el entorno destino.

[Control de errores de SQL Server](https://learn.microsoft.com/en-us/sql/t-sql/language-elements/try-catch-transact-sql) explica por qué se usa SQL dinámico para capturar también errores de compilación de los bloques inferiores.
