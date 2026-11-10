# Toolbox Mapline KMZ - EFT 5.8

Esta toolbox aplica al contenido **ya preparado** por `Mapline_KMZ_SDE` una propuesta de estructura y clasificacion segun el EFT v2.4, seccion 5.8. No vuelve a ejecutar `KML To Layer` ni modifica la toolbox neutral de transferencia.

## Archivos

- `Mapline_KMZ_EFT.pyt`: toolbox para ArcGIS Pro.
- `cargar_eft.py`: flujo de ejecucion tambien disponible como CLI.
- `eft_modelo.py`: catalogo EFT, campos, dominios y estructura de geodatabase.
- `eft_reglas.py`: reglas de clasificacion y derivacion de metadatos.
- `eft_atributos.py`: extraccion de ExtendedData y descripciones KML/HTML.
- `eft_mapeo.py`, `eft_supuestos.py`: mapeo editable, balances y registro de preguntas.
- `test_eft.py`: pruebas sin dependencia de ArcGIS.

## Requisitos

- ArcGIS Pro 3.x y su entorno Python `arcgispro-py3`.
- Una carpeta de trabajo creada por `Mapline_KMZ_SDE`, con `informe.json`, `trazabilidad.sqlite`, `intentos\` y las geodatabases locales preparadas.
- Para operaciones SDE, una conexion `.sde` con permisos de propietario de los datos. El usuario debe revisar el resultado y contar con respaldo antes de cargar o retirar entidades.

## Orden de trabajo recomendado

1. Ejecutar `PROPONER`. Se crean `eft\mapeo_eft.csv`, `eft\balance_eft.csv` y `eft\supuestos_y_preguntas.csv/.md`.
2. Revisar y editar `mapeo_eft.csv` en Excel. Confirmar `clase_destino`, `proyecto`, `componente`, `alternativa`, `disciplina`, `condicion` y `fuente`. Un codigo `PROV-*` es marcador provisional y bloquea la carga hasta reemplazarlo por un `co_proyecto` real. Para cargar una fila, usar `incluir=SI`; para excluir una propuesta, usar `incluir=NO` y `estado=EXCLUIDO`.
3. Ejecutar `PREPARAR_LOCAL`. Solo transforma las filas seleccionadas con `incluir=SI`, verifica los conteos y crea/actualiza `eft\EFT_local.gdb`. Una segunda ejecucion reemplaza en la geodatabase local solo las entidades de los SHA seleccionados.
4. Conectar la geodatabase SDE del propietario y ejecutar `ESTRUCTURA_SDE`. Por defecto crea las clases presentes en el mapeo; la opcion de estructura completa crea el catalogo EFT disponible (no crea clases migradas fuera de alcance).
5. Ejecutar `CARGAR_SDE`. Hace `Append` de los SHA seleccionados, limita cada Append por `kz_sha256` y verifica conteos por clase. Si detecta una carga parcial o conteos distintos, se detiene: no borra ni reemplaza filas en SDE.
6. Despues de validar la carga, `VERSIONAR_SDE` registra `Datos_Proyecto` como versionado. Solo continuar con una conexion configurada para Branch Versioning y usuario propietario; la versionacion se deja para el final.
7. `RETIRAR_KMZ` elimina por SHA las filas de los KMZ seleccionados. Requiere seleccion explicita y confirmacion; esta deshabilitado cuando `Datos_Proyecto` esta versionado. No elimina clases, tablas ni otros objetos.

`PROPONER` puede ejecutarse para un KMZ o para todos. Al actualizar, las filas editadas y las filas de KMZ anteriores se conservan; `regenerar` crea una copia `.bak_...csv`, vuelve a proponer las filas seleccionadas y conserva `comentario_revision`.

## Campos y trazabilidad

Las clases usan los datasets `Datos_Externos`, `Datos_Internos` y `Datos_Proyecto`, geometria WGS 84 (EPSG:4326) con Z, GlobalID y Editor Tracking UTC. Las medidas se calculan geodesicamente en metros/hectareas. El catalogo incorpora los campos de negocio y los campos `kz_*` de trazabilidad. Los atributos KML sin equivalencia EFT se conservan en JSON en `kz_atributos`; las tablas originales y balances neutrales de la toolbox 1 no se alteran.

Las capas de referencia se proponen como `<Clase>_Recorte`; no se realiza un recorte geometrico: se conserva la geometria que venia dentro del KMZ. Capas migradas, objetos no vectoriales, CAD no clasificado y geometrias incompatibles quedan pendientes, nunca se descartan automaticamente. La deduplicacion solo afecta geometria/atributos exactos en el conjunto seleccionado; las rutas `Prefinal` se procesan despues para que prevalezca una copia `Final`.

## Preguntas y supuestos

Las decisiones son provisionales y quedan enumeradas en `eft\supuestos_y_preguntas.csv` y `.md`. Entre los casos que requieren atencion estan los codigos de proyecto, disciplina de carpetas mixtas, PLS-CADD, trazos migrados, capas CAD, objetos 3D/overlays, clases de tema ambiguo y anchos de franjas. La hoja de mapeo es la entrada revisable antes de cualquier carga.

## Pruebas y limites de validacion

La validacion local registrada en `VALIDACION_LOCAL.json` se ejecuto con ArcGIS Pro 3.7.1 sobre una fixture de tres KMZ: produjo 3.329 entidades para Chanchamayo y Pucallpa; Jaen Norte no tenia grupos habilitados en el mapeo. Las 17 clases generadas tienen Z, GlobalID, Editor Tracking UTC y los campos de trazabilidad. Pasaron 14 pruebas unitarias y 2 pruebas ArcPy de estructura. Tambien se probo la creacion de parametros del toolbox y que el selector leyera los tres KMZ y el mapeo predeterminado desde el `informe.json`.

Esta comprobacion no prueba la interfaz de ArcGIS Pro, una conexion SDE, Branch Versioning, permisos remotos ni relaciones con tablas de negocio. La fixture no forma parte del paquete. Los supuestos y preguntas de clasificacion siguen pendientes de validacion por ENGIE.

Pruebas unitarias sin ArcGIS:

```powershell
Set-Location 'C:\ruta\carga_eft'
python -m unittest -v test_eft
```

La estructura y la preparacion local deben validarse con la instalacion de ArcGIS Pro usada para operar. La conexion SDE, los permisos, el versionado Branch, la relacion con `mline_tc_proyecto` y la carga remota **no se verifican en esta entrega**. Ejecutar primero en un workspace de prueba y validar con el administrador de la geodatabase.
