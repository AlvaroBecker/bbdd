# PK y FK físicas de las ocho tablas Mapline

Este paquete prepara **ocho PRIMARY KEY y once FOREIGN KEY físicas** en las tablas existentes de **ArcGisAWS.gis**. Usa las claves del dump `Mapline_20261030.sql` y selecciona las relaciones vigentes según el EFT v2.4. Sustituye al paquete anterior para este paso.

**Condición de aplicación:** las tablas deben estar registradas en la geodatabase, pero continuar **sin versionado y sin archivado**. El registro que ya hiciste no equivale a activar branch. Las PK crearán índices únicos y **mientras existan impedirán activar branch**, previsto por el EFT. Este paquete atiende la creación física solicitada ahora; no resuelve ese cambio posterior de arquitectura. [Requisitos de Esri para branch](https://doc.esri.com/en/arcgis-pro/latest/help/data/geodatabases/overview/register-a-dataset-as-branch-versioned.html).

No se ha ejecutado ningún cambio en la base real al preparar estos archivos.

## Archivos

| Archivo | Función |
|---|---|
| `00_verificar_estado_arcgis.py` | Consulta el registro, versionado y archivado; genera una copia del SQL habilitada para el servidor comprobado. No modifica la base. |
| `01_diagnostico_sql.sql` | Consulta columnas, restricciones actuales, índices, duplicados y referencias. |
| `02_restaurar_indices_no_unicos.sql` | Recupera los índices secundarios originales que falten. No crea PK/FK. |
| `03_agregar_PK_FK_SQLServer.sql` | SQL base para crear las ocho PK y once FK. La aplicación queda bloqueada hasta comprobar el estado con el archivo 00. |
| `04_correspondencia_EFT_MySQL.md` | Enumera cada PK, las 27 FK originales y su tratamiento, y los 27 índices secundarios. |
| `modelo_restricciones.json` | Inventario de origen y clasificación según el EFT. |
| `05_verificacion_local.json` | Resultado de las comprobaciones de archivos; no es una ejecución en SQL Server. |

## Ejecutar las PK y FK

1. Cerrar las sesiones de edición y las vistas/servicios que mantengan bloqueos de las ocho tablas. Usar una conexión `.sde` del propietario **gis** a **ArcGisAWS**.

2. En **Python Command Prompt de ArcGIS Pro**, situarse en la carpeta descomprimida y ejecutar, sustituyendo la ruta de conexión por la real:

   ```bat
   python 00_verificar_estado_arcgis.py --connection "C:\Conexiones\gis.sde"
   ```

   Este es el único Python necesario para este paso. Lee propiedades de ArcGIS porque SQL no identifica de manera completa el versionado tradicional mirando solamente las columnas de la tabla. No crea reglas, dominios, campos ni restricciones. Si detecta versionado o archivado, se detiene sin generar un SQL habilitado.

3. El verificador informa la ruta del nuevo **`03_agregar_PK_FK_VERIFICADO.sql`** y del reporte de estado. Si ya existe una salida predeterminada, utiliza un nombre nuevo con fecha. Abrir **el SQL que indique esa ejecución** en SSMS y ejecutarlo **completo**, en una ventana sin transacciones previas. No requiere modo SQLCMD ni importar un archivo `.sqlcmd`.

   El SQL generado viene con **`@Aplicar = 1`**: crea las restricciones faltantes. La verificación vale 15 minutos y corresponde al mismo servidor/base. Ejecutarlo inmediatamente después del verificador, sin registrar versionado, archivar, recrear tablas ni cambiar su estructura entre ambos pasos. Si pasa ese tiempo, repetir el archivo 00. No cambiar a mano el indicador `@EstadoArcGISVerificado`.

4. Al terminar debe informar **ocho PK y once FK físicas verificadas**. El resultado distingue las creadas de las equivalentes que ya existían. Ejecutar `01_diagnostico_sql.sql` para consultar el estado final desde el catálogo de SQL Server.

La aplicación de PK/FK usa una sola transacción: valida primero el conjunto de datos, crea las PK antes que las FK, comprueba las definiciones finales y hace `COMMIT`. Si falla ese paso, hace `ROLLBACK` de todas las restricciones que intentó agregar. No modifica datos para forzar la validación.

## Índices originales

`02_restaurar_indices_no_unicos.sql` contiene los **27 índices secundarios no únicos** del dump para estas ocho tablas. Algunos pueden estar cubiertos por índices actuales. Para crearlos, cambiar **`@Aplicar` de `0` a `1`** y ejecutar ese archivo completo en SSMS. Con `0` muestra solamente el plan.

Los índices son independientes de la creación de PK/FK del archivo 03. No imponer unicidad es correcto para esos índices secundarios; las ocho PK del archivo 03 sí imponen unicidad. No se eliminan ni cambian los índices existentes.

## Qué se conserva y qué queda pendiente

- **Ocho PK:** el ID de negocio original, `INT NOT NULL`, como `PRIMARY KEY NONCLUSTERED`. Si ya existe una PK equivalente, se conserva. Si una tabla ya tiene PK sobre ObjectID u otra columna, se detiene el conjunto; no elimina esa PK.
- **Once FK:** las relaciones vigentes entre las ocho tablas, incluidas las dos autorreferencias. Usa `WITH CHECK` y `ON DELETE/UPDATE NO ACTION`, sin cascadas, sin `NOCHECK` y sin excepciones para replicación.
- **Las otras 16 FK del dump:** tres referencias retiradas por el EFT; ocho a parámetros que pasan a dominios; dos a maestros que pasan a equivalencias del Portal; tres hacia clases espaciales pendientes. Están identificadas una por una en el archivo 04. Este paquete no las presenta como creadas ni crea tablas auxiliares para satisfacerlas.

Una PK existente diferente, una FK incompatible, claves nulas/duplicadas, referencias huérfanas o falta de permisos detienen el proceso. Las restricciones equivalentes se conservan por su definición, aunque tengan otro nombre. Las restricciones deshabilitadas, no confiables o con acciones diferentes requieren revisión; no se sobrescriben automáticamente.

Ninguno de los ocho IDs tenía `AUTO_INCREMENT` en MySQL. Agregar una PK **no vuelve autoincremental** el ID: no se crea `IDENTITY`, una secuencia ni un generador nuevo. Se conservan los atributos de negocio, ObjectID, GlobalID y sus valores.

La validación local contrasta las definiciones con el dump y revisa el código. La sintaxis y la ejecución completa en tu SQL Server/ArcGIS quedan por comprobar al ejecutar estos archivos; no se ha usado una conexión a esa base durante su preparación.
