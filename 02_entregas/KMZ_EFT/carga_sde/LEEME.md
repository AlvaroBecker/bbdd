# Transferencia de los 13 KMZ a ArcGisAWS, esquema gis

## Qué hace esta entrega

Transfiere las entidades que ArcGIS Pro puede convertir, incluidos los contenidos PLS-CADD ambiguos, a **clases nuevas y neutrales** del esquema `gis`. No necesita resolver antes la clasificación de negocio. Todo queda identificado como `PENDIENTE_ENGIE`; no se presenta como una carga temática EFT aprobada.

No modifica las tablas existentes, no inventa proyectos, análisis, componentes ni alternativas y no convierte todas las líneas PLS-CADD en `Vanos`. No publica servicios ni registra versionado.

La conexión ya está configurada por defecto:

```text
C:\Users\CT6788\Documents\ArcGIS\Projects\MyProject\SQLServer-EEPAWSDBP01-ArcGisAWS(gis).sde
```

El script comprueba la base real y el esquema predeterminado de la conexión; si no son `ArcGisAWS` y `gis`, se detiene. El nombre del archivo `.sde` por sí solo no se considera prueba. La conexión debe tener permisos de creación de datos y el usuario debe estar conectado a ArcGIS Pro con una licencia válida.

## Ejecución en la máquina destino

### Desde ArcGIS Pro: caja de herramientas (recomendado)

1. Descomprimir el paquete y conservar juntos `Mapline_KMZ_SDE.pyt`, `cargar_kmz_sde.py` y `01_archivos.csv`. No es necesario instalar paquetes ni ejecutar comandos.
2. En **Catálogo → Cajas de herramientas → Agregar caja de herramientas** (*Catalog → Toolboxes → Add Toolbox*), seleccionar `Mapline_KMZ_SDE.pyt`.
3. Abrir **Transferir KMZ seleccionados a ArcGisAWS (gis)**.
4. En **Carpetas con KMZ originales**, agregar las carpetas originales de proyectos y de resultados de Mapline. Busca en subcarpetas; no hay que reunir ni separar previamente los KMZ.
5. En **KMZ a procesar**, seleccionar uno o varios archivos de la lista generada desde esas carpetas. Vacío significa exigir los trece originales del inventario, no ignorar los que faltan. Para actualizar la lista después de añadir archivos, quitar y volver a agregar la carpeta de entrada. Solo se admiten contenidos cuyo SHA-256 coincida con el inventario.
6. Elegir **Validar fuentes y conexion (sin cargar)**. Seleccionar la conexión `.sde` y una carpeta de trabajo existente, fuera de las entradas. Si la conexión indicada arriba existe en esa máquina, aparece seleccionada por defecto.
7. Ejecutar y comprobar el resultado `VALIDACION_PREVIA_SIN_CARGA` en los mensajes.
8. Cambiar **Operacion** a **Cargar a SDE (objetos nuevos en gis)** y ejecutar. La preparación y la carga se realizan en esa misma ejecución; no se necesita ejecutar antes el modo de preparación local.

El modo **Preparar solo geodatabases locales (sin SDE)** es opcional: permite revisar las conversiones sin conectarse a la base. No se debe confundir con una carga a SDE.

Sin reanudación, cada ejecución crea automáticamente una subcarpeta nueva en la carpeta de trabajo seleccionada. Los mensajes de progreso, advertencias y errores aparecen en ArcGIS Pro; el historial entrega las rutas del informe y de los resultados como salidas de la herramienta. Se conservan también `ejecucion.log` e `informe.json`. No se agregan automáticamente las clases de trabajo al mapa.

### Continuar una preparación anterior

1. Conservar completa la carpeta anterior, incluidas las GDB, los originales y la trazabilidad.
2. Indicar las carpetas de fuentes y seleccionar los KMZ deseados.
3. En **Continuar en una carpeta de ejecucion anterior**, elegir la subcarpeta `Mapline_KMZ_FECHA` que contiene `informe.json` y `trazabilidad.sqlite`, no su carpeta padre. La carpeta de trabajo nueva queda deshabilitada.
4. Elegir preparación local o carga a SDE. Se comprueban los hashes de originales, conteos, esquema, claves y balance de las clases ya preparadas seleccionadas. Si falta o fue alterado un checkpoint, se detiene: no se reutiliza silenciosamente. Esta comprobación de reanudación no certifica que las coordenadas no hayan sido editadas; no editar las GDB de preparación.
5. Se reutilizan las preparaciones completas y se vuelven a preparar las fuentes incompletas o nuevas. Los archivos de intentos fallidos no se borran: las nuevas conversiones quedan en `intentos\FECHA\...`. También se admite la estructura de preparación de versiones anteriores.

La selección limita **el lote actual**, incluidas sus tablas de atributos y balance. El informe conserva también los checkpoints de otras fuentes preparadas anteriormente. Por ejemplo, se pueden seleccionar los seis proyectos ya preparados antes del fallo de Pariñas y cargarlos sin reconvertirlos; otro lote puede contener únicamente los restantes.

Una carpeta con cargas a SDE **solo se reanuda si todos sus destinos anteriores figuran `VERIFICADO`**. Si alguno quedó `INICIADO` o `ERROR`, la herramienta se detiene y muestra esos objetos: revisarlos primero con el administrador GIS. En una carpeta reanudable, seleccionar solamente los KMZ que aún no se cargaron. Si la selección incluye un KMZ ya cargado desde esa carpeta, o se deja vacía (los trece), se detiene antes de convertir o copiar nada y lista los que hay que quitar. Además, cualquier destino existente, con nombre nuevo o anterior, bloquea la carga: nunca se sobrescribe ni se duplica.

Por ejemplo, en la carpeta donde ya se cargó Chanchamayo, se cargan los doce restantes reanudando esa misma carpeta y seleccionando esos doce KMZ. Sus preparaciones verificadas se reutilizan sin reconvertir.

Antes de continuar se archiva el informe anterior. Una validación sin carga sobre una carpeta previa entrega `validacion_FECHA.json` y conserva el checkpoint operativo; los errores al reanudar entregan `error_FECHA.json`. La salida de ArcGIS apunta al informe del intento actual.

La carpeta se protege con `.ejecucion.lock` para impedir usos simultáneos. Si una caída deja ese archivo, comprobar que el proceso anterior terminó antes de retirarlo manualmente. Nunca retirarlo mientras siga trabajando.

**Memoria:** esta versión no impone un límite de RAM ni garantiza resolver el error 000582. Ese control quedó pospuesto. Esperar a que el servidor tenga memoria disponible antes de reintentar los KMZ grandes. Seleccionar uno por vez reduce el trabajo del lote, pero no limita la memoria de `KML To Layer` durante una conversión.

### Renombrar objetos cargados con nombres anteriores

Las versiones anteriores creaban nombres del tipo `kmz_2d83ff1278ed_puntos`. La operación **Renombrar objetos ya cargados a nombres legibles** los cambia a los nombres actuales, por ejemplo `chanchamayo_puntos`, sin copiar, modificar ni borrar datos.

1. Quitar de todos los mapas las capas y tablas de esos objetos y cerrar otras sesiones que los usen. Renombrar requiere un bloqueo exclusivo.
2. Elegir **Operacion → Renombrar objetos ya cargados a nombres legibles**. Las carpetas de KMZ, la selección y la carpeta de trabajo nueva quedan deshabilitadas.
3. Seleccionar la conexión `.sde` y, en **Continuar en una carpeta de ejecucion anterior**, la subcarpeta `Mapline_KMZ_FECHA` desde la que se cargaron.
4. Ejecutar y comprobar `RENOMBRADO: N objetos` en los mensajes.

Antes de renombrar, se comprueba cada objeto: debe existir exactamente con uno de los dos nombres, conservar el conteo verificado, coincidir con su preparación local y no estar en uso. Si un objeto falla, no se renombra ninguno. El informe anterior se archiva como `informe_anterior_FECHA.json`. Luego se renombra uno por uno y `informe.json` registra cada cambio confirmado (`renamed_from`). Si se interrumpe, volver a ejecutar continúa desde lo pendiente; una ejecución sin pendientes informa `RENOMBRADO: 0`. El renombrado de ArcGIS también cambia el alias.

Cada tabla anterior `kmz_<lote>_atributos` o `kmz_<lote>_balance` solo se renombra si su lote corresponde a un único KMZ, como en la carga de Chanchamayo. Si una tabla mezcla varios KMZ, la herramienta se detiene sin renombrar nada.

**Pendiente de prueba:** el renombrado se probó en geodatabase de archivos, no en la SDE remota. Si ArcGIS no acepta el nombre nuevo calificado, la herramienta reintenta automáticamente con el nombre sin calificar.

**No mover únicamente el `.pyt`:** el script y el inventario deben permanecer a su lado. La caja se agrega igual que el organizador existente, pero es independiente y no lo modifica. La carga seguirá creando objetos neutrales nuevos bajo `gis`, no reemplazará las clases definitivas ni resolverá automáticamente el mapeo pendiente.

### Alternativa por archivos CMD o terminal

1. Copiar esta carpeta completa a esa máquina y descomprimirla si se recibió como ZIP.
2. Crear una subcarpeta llamada `kmz` junto al script. Copiar dentro **los 13 KMZ originales**: los nueve de proyectos y los cuatro de resultados de Mapline. Se admiten subcarpetas y copias duplicadas; solo se procesa una copia de cada SHA-256.
3. Ejecutar `VALIDAR.cmd`. Revisa fuentes y conexión, pero no convierte ni crea objetos en SDE. Debe terminar con código 0 y `VALIDACION_PREVIA_SIN_CARGA`.
4. Ejecutar `CARGAR.cmd`. Prepara las conversiones localmente y luego carga los objetos nuevos a SDE. No abrir las GDB de trabajo durante la ejecución para evitar bloqueos.
5. Revisar la ruta del `informe.json` mostrada en pantalla. El resultado esperado es `CARGADO_SDE_CON_PENDIENTES_ENGIE`, con todos los objetos destino en estado `VERIFICADO`.

No pegar el script entero en la ventana Python de ArcGIS. Los `.cmd` usan el entorno de ArcGIS Pro de la instalación habitual. Si ArcGIS Pro está instalado en otra ruta, usar su **Python Command Prompt**:

```bat
python "D:\EntregaKMZ\cargar_kmz_sde.py" --entrada "D:\EntregaKMZ\kmz"
python "D:\EntregaKMZ\cargar_kmz_sde.py" --entrada "D:\EntregaKMZ\kmz" --aplicar
```

Se pueden indicar carpetas separadas sin reunir los KMZ:

```bat
python "D:\EntregaKMZ\cargar_kmz_sde.py" --entrada "D:\Fuentes\CapasInternas" --entrada "D:\Fuentes\Resultados de Mapline" --aplicar
```

Las rutas `D:\...` son ejemplos. Para cambiar la conexión o el directorio de trabajo:

```bat
python "D:\EntregaKMZ\cargar_kmz_sde.py" --entrada "D:\Fuentes" --sde "C:\otra\ruta\conexion.sde" --salida "D:\TrabajoKMZ\lote01" --aplicar
```

La salida debe ser una carpeta **nueva**, fuera de las entradas. Por defecto se crea `ejecuciones\FECHA_UTC` junto al script. Reservar varios GB libres para los originales, las copias derivadas, las GDB de conversión y las GDB preparadas. No se requiere instalar paquetes adicionales: ArcPy y biblioteca estándar de Python.

Para seleccionar archivos por terminal, repetir `--kmz` con sus rutas completas. Para continuar, usar `--reanudar` en lugar de `--salida`:

```bat
python "D:\EntregaKMZ\cargar_kmz_sde.py" --entrada "D:\Fuentes" --kmz "D:\Fuentes\Proyecto PARIÑAS.kmz" --reanudar "D:\TrabajoKMZ\Mapline_KMZ_FECHA" --solo-preparar
```

Para renombrar los objetos cargados con nombres anteriores (sin `--entrada`, `--kmz`, `--sha`, `--aplicar` ni `--solo-preparar`):

```bat
python "D:\EntregaKMZ\cargar_kmz_sde.py" --reanudar "D:\TrabajoKMZ\Mapline_KMZ_FECHA" --renombrar
```

Conservar `01_archivos.csv` junto al script. Sus rutas históricas son informativas: el cargador busca dentro de `--entrada` y reconoce los archivos por SHA-256, sin necesitar aquellas rutas. Los KMZ grandes pueden tardar varios minutos; la consola y `ejecucion.log` muestran el avance.

## Objetos creados

En la raíz de la geodatabase empresarial, bajo el propietario `gis`:

- `<nombre>_puntos`
- `<nombre>_lineas`
- `<nombre>_poligonos`
- `<nombre>_multipatch`
- `<nombre>_multipuntos`, únicamente si la conversión genera esa geometría.
- `<nombre>_atributos`: atributos originales del KMZ en JSON dividido en partes.
- `<nombre>_balance`: una fila por objeto original inventariado del KMZ y su número de entidades convertidas.

`<nombre>` se toma de la columna `nombre_sde` de `01_archivos.csv`:

| KMZ | `nombre_sde` |
|---|---|
| Proyecto CHANCHAMAYO.kmz | `chanchamayo` |
| Proyecto FELAM.kmz | `felam` |
| Proyecto HUARAZ.kmz | `huaraz` |
| Proyecto JAENNORTE.kmz | `jaennorte` |
| Proyecto MUYURINA.kmz | `muyurina` |
| Proyecto PALIAN.kmz | `palian` |
| Proyecto PARIÑAS.kmz | `parinas` |
| Proyecto POROMA.kmz | `poroma` |
| Proyecto PUCALLPA.kmz | `pucallpa` |
| G1 Enlace 500 kV Miguel Grau - Pariñas.kmz | `g1_miguelgrau_parinas` |
| G1 LT 220 kV Felam – Tierras Nuevas – Salitral (1).kmz | `g1_felam_salitral` |
| G1 LT 220 kV Muyurina – Mollepata.kmz | `g1_muyurina_mollepata` |
| G1 Nueva SE Palián 22060 kV y LT.kmz | `g1_palian_se_lt` |

Se pueden cambiar antes de cargar editando esa columna. Cada valor debe empezar con una letra minúscula y contener solo minúsculas, números y `_`, con un máximo de 40 caracteres. No debe empezar con `sde_`, `gdb_`, `delta_` ni `kmz_`, ni repetirse. Un valor inválido detiene la herramienta antes de convertir. Si la columna está vacía, el nombre se deriva del archivo, sin tildes ni el prefijo `Proyecto`. No cambiar un nombre de un KMZ ya cargado: para ese caso no se vuelve a renombrar automáticamente.

Solo se crean los tipos de entidad que realmente existan. El hash y el archivo de cada objeto figuran en `informe.json`, `KZ_SHA256` y `KZ_ARCHIVO`. Son clases de transferencia, deliberadamente fuera de los datasets temáticos definitivos, para no confundir una conservación técnica con una clasificación aprobada.

Los nombres son estables para las mismas fuentes. Si alguno ya existe, o si el KMZ ya existe con el nombre anterior `kmz_<hash>`, el script **se detiene antes de cargar**. No actualiza, agrega filas a objetos previos ni los borra. Esto evita duplicar una transferencia al volver a ejecutar.

## Trazabilidad y atributos

Para no depender de nombres repetidos o rutas ambiguas, el script crea una **copia derivada** de cada KMZ y sustituye temporalmente el nombre de cada Placemark por una clave determinista. ArcGIS convierte esa copia. Cada entidad convertida debe recuperar esa clave exactamente; si no la recupera, la ejecución falla antes de cargar.

Los originales se copian sin modificaciones a `originales\<SHA256>.kmz` y se vuelve a verificar su hash. Las imágenes y demás recursos originales quedan allí preservados. La copia derivada mantiene los recursos y no es una nueva fuente de negocio.

Campos añadidos a las entidades:

| Campo | Contenido |
|---|---|
| `KZ_PM_ID` | Identificador exacto del Placemark original; admite varias entidades de salida para el mismo Placemark |
| `KZ_SHA256` | SHA-256 del KMZ original |
| `KZ_ARCHIVO` | Archivo del inventario |
| `KZ_NOMBRE` | Vista del nombre original, hasta 1.000 caracteres |
| `KZ_ESTADO` | `PENDIENTE_ENGIE` |

El atributo `Name` generado por la conversión contiene la clave de trazabilidad. El nombre original se consulta en `KZ_NOMBRE`; el nombre íntegro y los atributos se conservan en la tabla de atributos y en el KMZ original.

Cada `KZ_PM_ID` identifica también las filas de atributos. Para recuperar el JSON completo, filtrar por ID, ordenar por `KZ_PARTE` y concatenar `KZ_JSON` desde 1 hasta `KZ_TOTAL`. No interpretar cada parte como un objeto distinto. El JSON contiene el nombre íntegro, los componentes reales de la ruta, los atributos XML del objeto, sus hijos XML no geométricos (incluidos `description`, `ExtendedData`, estilos y tiempos) y un resumen geométrico. El XML geométrico y los recursos completos permanecen en el original preservado.

No se interpretan las tablas HTML ni se convierten sus etiquetas en campos de negocio sin reglas aprobadas. Se conserva su contenido para la decisión posterior.

## Balance, limitaciones y pendientes para ENGIE

La conversión de ArcGIS puede producir cero, una o varias entidades por Placemark. El script no equipara esos conteos: registra los vínculos exactos y deja los originales sin salida en `balance`, estado `SIN_ENTIDAD_REVISAR`. Los overlays también figuran allí y en atributos.

`GroundOverlay`, `ScreenOverlay` y `PhotoOverlay` **no se cargan como ráster**; se conservan en el KMZ y en atributos. Los modelos 3D dependen de la compatibilidad del conversor y quedan registrados en el balance aunque no produzcan entidad. No se consultan `NetworkLink`: su presencia produce un error explícito.

El script comprueba referencia espacial 4326, conserva Z de la conversión y contabiliza geometrías vacías. La conversión no certifica que las alturas sean válidas ni normaliza sus modos de altitud. Tampoco ejecuta reparaciones geométricas automáticas.

Se mantienen documentados para ENGIE:

1. Identificación de proyecto, componente, alternativa e `id_analisis`, incluidos Jaén Norte, Poroma y las correspondencias ambiguas.
2. Clasificación en los datasets y clases definitivos del EFT.
3. Diferencia entre `Section`, vano, conductor y geometría de presentación; significado de Set, fase y circuito.
4. Revisión de fuentes sin entidad, multipartes, geometrías vacías, modelos 3D, overlays y modos de altitud.
5. Revisión de aparentes duplicados y de archivos con contenido de varios proyectos.

Estas decisiones **no bloquean la transferencia neutral de las entidades convertibles**, pero sí su aprobación como modelo definitivo. El estado final expresa esa distinción.

## Errores y cargas parciales

Si Windows devuelve `WinError 5` al reemplazar `informe.json`, la herramienta reintenta
cinco veces con espera creciente (seis intentos en total). Si el bloqueo persiste,
se detiene, conserva el informe anterior y el nuevo `informe.json.tmp`, y muestra
el error original en los mensajes y en `ejecucion.log`. Un error adicional al
guardar el informe de fallo no oculta el primero.

En ese caso, cierre cualquier visor de los informes y pruebe una carpeta local
de trabajo fuera del Escritorio o de carpetas sincronizadas, por ejemplo una
carpeta nueva en Documentos. Verifique que su usuario tenga permisos de escritura,
renombrado y eliminación allí. No es necesario ejecutar ArcGIS como administrador
ni desactivar protecciones. El código de error por sí solo no identifica qué
programa o política impide el reemplazo.

La carga de varios objetos no es una única transacción. Un error de geoprocesamiento o de verificación durante la copia de un objeto queda registrado como `ERROR` y se continúa con los demás. Al final, cualquier error hace terminar la ejecución con código 1 y estado `ERROR_REVISAR_CARGA_PARCIAL`, nunca como una carga exitosa. Un corte inesperado puede dejar un objeto en estado `INICIADO`.

El script no elimina nada. Revisar el informe con el administrador GIS antes de repetir: una reejecución se detendrá si detecta objetos existentes. No borrar objetos existentes sin identificar primero su procedencia y su estado.

Se verifican conteos, una huella independiente del orden de los atributos locales/destino, tipo geométrico, referencia espacial, Z/M, vértices, partes y geometrías vacías. También se compara una huella de las secuencias de coordenadas por Placemark, usando la resolución XY/Z/M del origen para evitar diferencias de representación binaria de números. Un cambio de coordenadas por encima de esa resolución o de orden de vértices se reporta como error de verificación, sin reparar ni borrar el destino. Esto no sustituye la comprobación topológica ni una inspección visual. La conexión remota de la máquina destino debe validarse allí: no está disponible en la máquina de preparación de esta entrega.

## Validación de esta entrega

Se prepararon los trece originales con ArcGIS Pro 3.7.1:

- 279.623 Placemarks y 350 overlays conservados en la auditoría.
- 285.819 entidades convertidas en 43 clases locales, más las dos tablas de auditoría.
- 902 Placemarks no produjeron entidad geométrica en el conversor. Sus atributos y originales se conservaron; no se declaran como geometrías cargadas.
- Se compararon las 502.304 partes JSON exportadas contra los atributos de origen, sin diferencias, y se verificaron los trece hashes originales.
- Ocho pruebas unitarias aprobadas. El piloto de Jaén Norte también pasó la copia real a otra GDB, la reconstrucción íntegra de atributos y la comparación de coordenadas, incluidos multipatches. Un desplazamiento introducido deliberadamente en una copia de prueba fue detectado.
- La caja `.pyt` pasó además dos pruebas con ArcGIS real: importación y parámetros; ejecución de la herramienta dos veces, con mensajes y salidas correctos, sin acumular manejadores de log ni alterar la extensión, proyección o política de sobrescritura del entorno del usuario. Diez pruebas en total aprobadas.

La actualización de selección y reanudación pasó **20 pruebas**. Incluye ejecución real de la caja con selección parcial, reutilización en la misma carpeta, recuperación de una fuente incompleta, auditoría limitada a la selección y rechazo de vínculos alterados. También se probaron el bloqueo de concurrencia, la conservación del checkpoint al validar y el rechazo de reanudación con intentos previos de SDE. Las cifras del lote completo anterior se mantienen como evidencia histórica: no se volvió a convertir el lote de trece para esta actualización.

La actualización de nombres legibles y renombrado pasó **27 pruebas**. Cubren nombres válidos y únicos, tablas de atributos y balance por KMZ, y el bloqueo de cargas duplicadas con nombres nuevos o anteriores. También cubren la reanudación tras cargas verificadas, los argumentos de `--renombrar` y la operación de la caja. Con ArcPy real en geodatabase de archivos, se probó el renombrado de objetos con nombres anteriores. Una alteración de datos lo detuvo sin cambios. La repetición quedó en cero y se recuperó un renombrado interrumpido. En una prueba simulada, un objeto en uso detuvo la operación sin cambios.

La preparación completa tardó aproximadamente treinta minutos en la máquina de ensayo; la duración real y el tiempo adicional de carga a SDE dependen del equipo y de la conexión. **No se ejecutó la carga a la conexión SDE remota**. El detalle está en [VALIDACION_LOCAL.json](VALIDACION_LOCAL.json).

## Prueba local opcional

Para preparar la misma transferencia sin conectarse a SDE:

```bat
python "D:\EntregaKMZ\cargar_kmz_sde.py" --entrada "D:\Fuentes" --solo-preparar
```

Para un piloto, añadir `--sha` seguido del hash completo de un archivo de `01_archivos.csv`, o `--kmz` con su ruta (no combinar ambas opciones). Sin ninguna selección, se exigen los trece archivos. La validación no trata los nombres de archivo como identidad: un archivo renombrado se reconoce si su hash coincide.

Las pruebas unitarias se ejecutan desde esta carpeta:

```bat
python -m unittest -v test_cargar_kmz_sde.py
```

Las pruebas de importación y ejecución real de la caja requieren el Python de ArcGIS Pro:

```bat
python -m unittest -v test_toolbox_arcgis.py
```
