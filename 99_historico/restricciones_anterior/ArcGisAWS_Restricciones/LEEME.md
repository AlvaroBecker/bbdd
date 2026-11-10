# Restricciones de las ocho tablas Mapline en ArcGisAWS

Este paquete completa parte de la integridad y los índices de las **ocho tablas tabulares ya existentes en ArcGisAWS.gis**, después de registrarlas en la geodatabase. No crea ni vuelve a cargar tablas, no elimina objetos, no cambia identificadores de negocio y no activa el versionado.

El destino del EFT es branch versioning. Por esa razón este paquete **no agrega PRIMARY KEY ni FOREIGN KEY físicas de negocio en SQL Server**. Mantiene las claves y sus valores, recupera los índices secundarios no únicos y prepara restricciones mediante reglas de ArcGIS. El tratamiento de cada definición original figura en **04_correspondencia_restricciones.md**; no se debe interpretar que todas las restricciones originales se hayan restaurado físicamente en SQL Server.

## Archivos y orden

| Archivo | Función | Dónde se ejecuta |
|---|---|---|
| 01_diagnostico_sql.sql | Consultar tablas, campos, PK/FK actuales, índices, duplicados y referencias | SSMS |
| 02_restaurar_indices_no_unicos.sql | Planificar y restaurar índices secundarios físicos faltantes | SSMS |
| 02b_restaurar_indices_arcgis.py | Alternativa preferida para administrar esos índices desde ArcGIS | Python de ArcGIS Pro |
| 03_configurar_reglas_arcgis.py | Validar datos y configurar dominios y reglas de restricción | Python de ArcGIS Pro |
| 04_correspondencia_restricciones.md | Comparar cada PK, FK e índice original con su tratamiento | Lectura |
| modelo_restricciones.json | Definiciones recuperadas del respaldo y clasificación por EFT | Lo leen los scripts |

Usar **una** de las dos vías para los índices, SQL o ArcGIS. Ambos revisan los índices existentes y evitan duplicar una cobertura equivalente. El diagnóstico SQL es de solo lectura respecto de los datos del modelo. Las tablas variables usadas por los scripts SQL son temporales de la sesión, no tablas nuevas de negocio.

## Paso 1 Diagnóstico

Abrir **01_diagnostico_sql.sql** en SSMS y ejecutarlo completo. Usa la base ArcGisAWS y el esquema gis que ya existe. No necesita modo SQLCMD.

Revisar las ocho tablas y sus campos, claves físicas actuales y estados de los índices. Los conteos de filas originales son referencias del respaldo, no una condición de que la base deba seguir inmóvil. Los duplicados y huérfanos SQL se cuentan sobre tablas físicas; si ya hay datos versionados, pueden incluir historia y no representan por sí solos errores en la versión de edición. El script informa un marcador estructural branch, pero la confirmación del registro y tipo de versionado se hace con ArcGIS.

Las referencias cuyo padre espacial todavía no existe se mostrarán pendientes. Los parámetros y maestros se reemplazan de acuerdo con el EFT y no se crean para satisfacer una FK antigua.

## Paso 2 Índices

El inventario contiene **27 índices secundarios originales**. Dos de proyectos normalmente ya están cubiertos; el resto puede necesitar hasta 25 creaciones. El plan real depende de lo que exista en la base.

**Desde SSMS:** ejecutar **02_restaurar_indices_no_unicos.sql** con `@Aplicar = 0` para ver el plan. Para crear exclusivamente los que falten, cambiar esa variable a `1` y ejecutar de nuevo el archivo completo en una ventana sin transacciones previas. No crea índices únicos, no borra ni sustituye los existentes y no toca índices de ObjectID/GlobalID. Si un nombre ya existe con otra definición, se detiene para evitar reemplazarlo.

**Desde ArcGIS, vía preferida para tablas registradas:** abrir el entorno Python de ArcGIS Pro en la carpeta descomprimida y usar una conexión `.sde` del propietario **gis** a **ArcGisAWS**. La ruta de conexión de los ejemplos es ilustrativa; sustituirla por la real.

    python 02b_restaurar_indices_arcgis.py --connection "C:\Conexiones\gis.sde" --report plan_indices.json

Después de revisar el plan:

    python 02b_restaurar_indices_arcgis.py --connection "C:\Conexiones\gis.sde" --apply --report resultado_indices.json

El SQL administra el índice físico de SQL Server; no promete actualizar metadatos de diseño de ArcGIS. La alternativa ArcPy utiliza **Add Attribute Index**. No se cambia la unicidad, filtro, columnas INCLUDE ni definición de un índice existente: una cobertura no idéntica se informa o detiene según el conflicto.

## Paso 3 Reglas y dominios de ArcGIS

Terminar primero el registro de las ocho tablas con **Register With Geodatabase**, dejando vacío Object ID Field para tener un ObjectID independiente de `id_proyecto`, `id_proyecto_capa` y demás ID de negocio. Cerrar vistas de tabla y sesiones de edición que mantengan bloqueos de esquema. La conexión debe ser del propietario gis; no se incluyen ni se solicitan contraseñas en este paquete.

Ejecutar primero la validación sin cambios:

    python 03_configurar_reglas_arcgis.py --connection "C:\Conexiones\gis.sde" --report plan_reglas.json

El reporte enumera las acciones previstas y las dependencias pendientes. Si encuentra datos incompatibles, dominios distintos o reglas con el mismo nombre y otra definición, se detiene antes de aplicar. No corrige ni vacía datos automáticamente.

Para aplicar la configuración validada:

    python 03_configurar_reglas_arcgis.py --connection "C:\Conexiones\gis.sde" --apply --report resultado_reglas.json

Este paso puede agregar **GlobalID**, como campo administrado por ArcGIS, si falta. Después crea o reutiliza dominios equivalentes y agrega reglas. No agrega campos de negocio, secuencias, IDENTITY, auditoría adicional ni relationship classes. No registra branch ni publica servicios.

La configuración prevista contiene:

- Ocho reglas de identificador obligatorio y unicidad lógica.
- Once validaciones de referencias vigentes entre estas tablas.
- Once protecciones de padre para conservar el comportamiento NO ACTION de actualización/borrado.
- Diez validaciones de pertenencia a parámetros, mediante ocho dominios con 28 códigos originales.
- Cuatro reglas para mantener NULL las referencias que el EFT retira.

En total son **44 reglas de restricción**. Las FK que originalmente admitían NULL siguen admitiéndolo. Las filas con borrado lógico se incluyen, igual que en las restricciones físicas originales. Las autorreferencias se validan mediante reglas y no se crean relationship classes recursivas.

Los códigos numéricos de parámetros se conservan como códigos de dominio. El valor real de ponderación no es el ID de parámetro: su correspondencia está en `domain_numeric_values` del manifiesto y debe usarse al completar el procesamiento del análisis.

## Qué permanece pendiente

Las reglas se aplican durante operaciones de edición de ArcGIS. **No son PK/FK físicas SQL**, no protegen cambios SQL directos que eviten ArcGIS y sus consultas de unicidad no garantizan exclusión atómica entre sesiones o versiones concurrentes. La generación controlada de nuevos ID mediante secuencias y la validación al conciliar/integrar versiones deben completarse antes de habilitar altas en producción. Este paquete no activa ese mecanismo ni altera los ID actuales.

Quedan documentadas cinco dependencias salientes pendientes: tres hacia clases espaciales y dos hacia equivalencias de Portal/campos. También faltan cuatro protecciones de padres respecto de hijos espaciales futuros. No se declara completa la integridad de los 14 objetos del modelo. Al publicar, las tablas consultadas por las reglas deben estar accesibles en el servicio y debe probarse la edición real por ese servicio.

Las reglas recuperan la semántica de las referencias originales dentro del alcance actual. No añaden otras validaciones funcionales, como impedir relaciones entre proyectos distintos, validar estados cerrados o construir geometrías. Las relaciones GIS GlobalID/GUID siguen siendo un paso del modelo futuro.

## Comprobación después de aplicar

Verificar el reporte de cada script y la vista **Attribute Rules** de ArcGIS Pro. Probar en un entorno controlado: rechazo de ID duplicado, rechazo de referencia no existente, aceptación de FK NULL permitida, rechazo de borrado de un padre con hijos y comportamiento de las dos autorreferencias. Las pruebas de alta necesitan definir primero cómo se asignará el ID de negocio; estas reglas no lo generan.

Los cambios de esquema ArcGIS no se revierten con una transacción SQL conjunta. Si una herramienta falla después de agregar algún dominio, GlobalID o regla, el reporte enumera lo realizado; no se ejecuta una eliminación automática. No se sobrescriben reglas o dominios distintos con el mismo nombre. Una configuración ya completa e idéntica puede volver a validarse sin duplicarla.

## Validación local y fuentes

Se verificaron las definiciones del respaldo, los conteos del inventario y la correspondencia entre reglas e índices. Se ejecutaron pruebas unitarias y de ArcPy simulado; falta ejecutar y validar las herramientas con la conexión real y probar las expresiones Arcade en ArcGIS Pro/Enterprise. No se ha modificado la base remota.

- [Branch versioning y restricciones de índices únicos](https://doc.esri.com/en/arcgis-pro/latest/help/data/geodatabases/overview/register-a-dataset-as-branch-versioned.html).
- [Add Attribute Rule y requisito de GlobalID](https://doc.esri.com/en/arcgis-pro/latest/tool-reference/data-management/add-attribute-rule.html).
- [Reglas de restricción y eventos de edición](https://doc.esri.com/en/arcgis-pro/latest/help/data/geodatabases/overview/constraint-attribute-rules.html).
- [Add Attribute Index](https://pro.arcgis.com/en/pro-app/3.4/tool-reference/data-management/add-attribute-index.htm).
- [Restricciones y validación de datos en SQL Server](https://learn.microsoft.com/en-us/sql/t-sql/statements/alter-table-table-constraint-transact-sql).
