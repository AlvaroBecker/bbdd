# Creación de clases KMZ y relación con proyecto según el EFT

**Revisión vigente:** [Esquema_KMZ_EFT_Corregido](../Esquema_KMZ_EFT_Corregido/LEEME.md) consolida temas y rutas, conserva nombres nuevos en snake_case y respeta las clases migradas. Este paquete conserva el catálogo anterior basado en nombres del EFT.

Este paquete crea mediante ArcGIS Pro la estructura espacial del catálogo explícito del EFT v2.4, con sus campos comunes y la relación `mline_tc_proyecto.co_proyecto → clase.proyecto`. Incluye un script por clase. Se usa ArcPy porque `CREATE TABLE` de SQL Server, por sí solo, no crea los feature datasets, dominios, GlobalID ni relationship classes de una geodatabase.

**Estado de la entrega:** definiciones generadas, seis pruebas automáticas aprobadas y cuatro clases con sus relaciones creadas y verificadas en una geodatabase local mediante ArcGIS Pro 3.7.1. Se comprobó también la segunda ejecución sin duplicación y el rechazo de códigos padre duplicados. No se han ejecutado en ArcGisAWS ni se ha probado branch versioning. Se requiere ejecutar desde el entorno Python de una instalación de ArcGIS Pro con licencia activa. El resultado está en `VALIDACION.json`.

## Alcance y pendientes reales

- 100 clases: 94 del catálogo espacial explícito del EFT, incluidas sus variantes geométricas y recortes, y las seis clases `mline_*` migradas.
- 59 relaciones de proyecto, una por clase de `Datos_Proyecto`. Las clases maestras de `Datos_Externos` y `Datos_Internos` no reciben `proyecto` ni una relación con el proyecto.
- Los campos propios reconocidos en la matriz se incorporan a las clases de recorte/proyecto propuestas. Las clases maestras tienen el bloque común; sus atributos definitivos deben contrastarse con el servicio oficial o entrega interna, no con un recorte de KMZ.
- La matriz contiene 3.507 filas de campos en 125 grupos de descripción/geometría. No es un DDL: no define los tipos, longitudes ni todos los destinos EFT. Se conserva una fila de trazabilidad por cada una.
- Los 3.638 grupos de `inventario_kmz_capas.csv` suman 279.623 elementos. El mapeo propone destino para 58.523 y mantiene 221.100 pendientes. **Pendiente no significa excluido ni eliminado.** Incluye grandes grupos genéricos de PLS-CADD, temas fuera de la lista explícita, geometrías incompatibles y clases cuyo significado depende de la ruta.
- El EFT 5.8.6 deja la lista definitiva de clases a INDRA y 5.8.8 exige revisar el mapeo antes de cargar. Por ello esta entrega no convierte automáticamente los 125 grupos de la matriz en 125 tablas ni presenta las propuestas como aprobaciones de carga.

El paquete crea estructura vacía. No convierte KMZ, no carga geometrías, no asigna códigos por semejanza de nombres, no migra las ocho tablas de negocio y no reemplaza objetos existentes. Las relaciones entre componente, alternativa, trazado, vértice y demás objetos migrados pertenecen al modelo MapLine completo y no quedan resueltas por la relación al proyecto de este paquete.

## Archivos

| Archivo | Uso |
|---|---|
| `esquema.json` | Definición de cada clase, campos, geometría, dataset y relación de proyecto |
| `por_clase/*.py` | Un script de creación por clase; usa `crear_esquema.py` y `esquema.json` del mismo paquete |
| `crear_esquema.py` | Prevalidación y creación conjunta o por clase; segunda fase de relaciones |
| `catalogo_clases.csv` | Clases, cantidad de campos y elementos propuestos por archivo/proyecto |
| `campos_matriz_a_esquema.csv` | Las 3.507 filas originales y su destino, omisión técnica o pendiente |
| `mapeo_capas_revision.csv` | Todas las rutas originales y sus conteos, con columnas vacías para revisar destino, inclusión, proyecto y análisis |
| `temas_pendientes.csv` | Grupos sin destino unívoco y motivo concreto |
| `validacion_inventario.json` | Balance de filas, campos y elementos |

Los conteos de `catalogo_clases.csv` proceden de `elementos` en el inventario de capas. Los números de las columnas de proyecto de la matriz de campos no se suman como entidades: describen apariciones del campo, no el número de entidades de la futura clase. Los conteos propuestos aún pueden cambiar por la revisión y transformación de geometrías.

## Criterios del esquema

1. Tres feature datasets en WGS84, EPSG:4326: `Datos_Externos`, `Datos_Internos`, `Datos_Proyecto`.
2. Una geometría por clase. Donde el EFT enumera varias geometrías se usan sufijos `Pto`, `Lin`, `Pol`. Los recortes terminan en `_Recorte`; los nombres son únicos dentro de la geodatabase.
3. `proyecto`: Texto de longitud 12, obligatorio. Debe coincidir con el `co_proyecto` de la tabla real. El DDL disponible define `nchar(12)`; ArcGIS expone ambos como texto. La herramienta comprueba la longitud al encontrar la tabla padre y se detiene si difiere.
4. `id_analisis`: Texto, obligatorio. Para carga inicial debe definirse un identificador reservado. No representa una versión branch.
5. GlobalID generado por ArcGIS. Editor Tracking UTC en clases de proyecto. Soporte Z habilitado para conservar cotas de las geometrías de entrada; una cota ausente no debe inventarse durante la carga.
6. `longitud_m` y `area_ha` son Double para medidas geodésicas. Los campos comunes siguen EFT 5.8.7. Las longitudes de texto que el EFT no especifica son decisiones de implementación y están visibles en `esquema.json`.
7. Los atributos de negocio sin tipo documentado se conservan como **Texto de 4.000 caracteres**, sin inferir números o fechas a partir del nombre del campo. Antes de cargar hay que comprobar longitudes en todos los valores; no truncar. Si requieren uso numérico/fecha, revisar el tipo y conversión antes de crear la clase definitiva.
8. Los nombres de campo se normalizan para ArcGIS. Una colisión con un campo común se conserva como `src_<nombre>`: por ejemplo, un área declarada en la fuente no se convierte automáticamente en `area_ha` geodésica.
9. Los campos de sistema heredados FID, OBJECTID, SHAPE, GLOBALID y derivados se omiten de los campos de negocio. El original permanece en los CSV/KMZ; si un identificador de origen debe preservarse, se mapea expresamente a `id_origen`. `ID` y campos de auditoría de fuente no se eliminan solo porque el inventario los marque como técnicos.
10. Las seis clases migradas conservan los campos del modelo MapLine disponible. Los decimales se representan como Double en ArcGIS; su precisión debe verificarse en la geodatabase destino. No se crea una PK/UNIQUE SQL en esos campos de negocio.

## Paso 1: revisar sin conectarse a una base de datos

Abra `catalogo_clases.csv`, `campos_matriz_a_esquema.csv` y `temas_pendientes.csv`. Las columnas editables del mapeo sirven para registrar decisiones; **editar los CSV no actualiza automáticamente `esquema.json` ni ejecuta una carga**. Las nuevas clases o equivalencias confirmadas deben incorporarse a la definición y regenerarse con el generador del proyecto.

En Python Command Prompt de ArcGIS Pro, situado en esta carpeta:

```bat
python crear_esquema.py
python por_clase\PredioSUNARP_Recorte.py
```

Estos comandos muestran lo que se crearía y no importan ArcPy si no se indica workspace.

## Paso 2: crear una clase en una geodatabase local de prueba

Indique una carpeta existente. El script crea la `.gdb` si falta:

```bat
python por_clase\PredioSUNARP_Recorte.py --workspace "C:\trabajo\EFT_prueba.gdb" --aplicar
```

Para crear las 100 clases:

```bat
python crear_esquema.py --workspace "C:\trabajo\EFT_prueba.gdb" --aplicar
```

Después revise la clase en Catálogo: geometría, EPSG:4326, campos, dominios, GlobalID y Editor Tracking. Una geodatabase de archivos permite comprobar el esquema, pero no branch versioning. Este paquete no crea una tabla padre ficticia para aparentar una relación con datos reales.

## Paso 3: crear en ArcGisAWS

Use una conexión del propietario `gis`. Antes de agregar clases, `Datos_Proyecto` debe estar sin versionar. Si el dataset ya está versionado, o existe una tabla con el nombre reservado para una clase migrada, se debe resolver su migración con el administrador antes de ejecutar el paquete. No ejecutar a ciegas sobre las tablas cargadas anteriormente.

Prevalidación de una clase:

```bat
python por_clase\PredioSUNARP_Recorte.py --workspace "C:\conexiones\ArcGisAWS_gis.sde"
```

Creación:

```bat
python por_clase\PredioSUNARP_Recorte.py --workspace "C:\conexiones\ArcGisAWS_gis.sde" --aplicar
```

Para todas, sustituya `por_clase\PredioSUNARP_Recorte.py` por `crear_esquema.py`. Una clase existente se valida; no se agregan ni cambian campos silenciosamente. Si su estructura difiere, la herramienta se detiene. Si ArcGIS falla durante una creación puede quedar un objeto incompleto: se reporta el error y se debe revisar ese objeto antes de reintentar. No hay rollback automático de DDL.

## Paso 4: crear la relación al proyecto

`mline_tc_proyecto` debe existir en la misma geodatabase y propietario, estar registrada con ArcGIS y contener códigos válidos y únicos a nivel lógico. No se agrega un índice UNIQUE físico. El padre y la clase hija deben tener el mismo estado de versionado.

Primero prevalidar y después aplicar:

```bat
python por_clase\PredioSUNARP_Recorte.py --workspace "C:\conexiones\ArcGisAWS_gis.sde" --accion relacionar
python por_clase\PredioSUNARP_Recorte.py --workspace "C:\conexiones\ArcGisAWS_gis.sde" --accion relacionar --aplicar
```

Equivalente manual con **Create Relationship Class**:

| Parámetro | Valor |
|---|---|
| Origin Table | `gis.mline_tc_proyecto` |
| Destination Table | `gis.PredioSUNARP_Recorte` |
| Output Relationship Class | `rel_proyecto_PredioSUNARP_Recorte` en la misma geodatabase |
| Relationship Type | Simple |
| Forward Label | `PredioSUNARP_Recorte` |
| Backward Label | `Proyecto` |
| Message Direction | None |
| Cardinality | One to many |
| Attributed | No |
| Origin Primary Key | `co_proyecto` |
| Origin Foreign Key | `proyecto` de la clase hija |

La relationship class es el vínculo de geodatabase requerido por el EFT; no equivale a una FK SQL que rechaza automáticamente toda escritura huérfana. La validación comprueba códigos duplicados, proyectos inexistentes e `id_analisis` vacío antes de relacionar. La carga y edición futura deben mantener esos controles.

## Paso 5: completar el modelo y activar branch

La activación se hace en SDE después de comprobar estructura, relaciones y carga inicial. Este paquete no activa branch automáticamente sobre una base cuyo estado se desconoce.

1. Completar la migración de las ocho tablas de negocio y seis clases espaciales, incluidas las relaciones de componente, alternativa, área, envelope, celda y trazado de EFT 5.8.10. Ver el paquete `ArcGisAWS_Carga_Mapline` del proyecto para ese modelo.
2. Comprobar GlobalID y Editor Tracking UTC en todos los participantes editables.
3. Revisar índices únicos/PK y restricciones SQL existentes con el administrador. El paquete anterior de PK/FK físicas advierte expresamente que es un estado sin versionado; no puede asumirse compatible con branch. No eliminar restricciones sin preparar su sustitución y revisar dependencias.
4. En las propiedades de la conexión de base de datos, establecer **Versioning Type = Branch**.
5. Registrar mediante **Register As Versioned** `Datos_Proyecto` y las tablas migradas del modelo, manteniendo el mismo tipo de versionado entre participantes. Seguir el orden/dependencias de las relaciones que ArcGIS presente y verificar que todos terminen como branch.
6. Mantener `Datos_Externos` y `Datos_Internos` sin versionar. Sus recortes apuntan a la fuente por `capa_origen` e `id_origen`, sin relationship class entre estados de versionado distintos.

No se declara terminada la migración EFT hasta resolver el mapeo pendiente, poblar los atributos, conservar relaciones de negocio y verificar la estructura en SDE.

## Fuentes

- EFT v2.4 de este proyecto, secciones 5.8.3–5.8.11.
- `inventario_kmz_resumen/inventario_kmz_matriz_campos.csv` y `inventario_kmz_capas.csv`. Los hashes originales se guardan en `esquema.json`.
- `ArcGisAWS_Carga_Mapline/modelo_eft.json`: campos de las seis clases migradas.
- [Create Relationship Class](https://doc.esri.com/en/arcgis-pro/latest/tool-reference/data-management/create-relationship-class.html).
- [Requisitos de branch versioning](https://doc.esri.com/en/arcgis-pro/latest/help/data/geodatabases/overview/register-a-dataset-as-branch-versioned.html).
- [Editor Tracking UTC](https://doc.esri.com/en/arcgis-pro/latest/arcpy/functions/editor-tracking-properties.html).
