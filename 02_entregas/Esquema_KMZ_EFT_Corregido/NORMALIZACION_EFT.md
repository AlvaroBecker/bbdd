# Normalización de nombres y alcance del modelo 11

La versión vigente es **1.7**. Conserva los nombres ya normalizados y modifica solo la confirmación de tipos de 1.356 atributos. El siguiente paso es **Validar tipos de texto confirmados**; véase [la guía](GUIA_DATOS_PROYECTO.md). No requiere repetir el renombrado que terminó con `NOMBRES_VERIFICADOS`.

## Fuentes y criterio

La revisión original contrastó cuatro CSV con el EFT v2.4, apartados 5.8.6–5.8.10:

| Fuente histórica | Uso |
|---|---|
| `inventario_kmz_matriz_campos.csv`, 3.507 filas | Descripción temática, atributos y variantes por proyecto. |
| `inventario_kmz_campos.csv`, 9.934 ocurrencias | Escritura original, ruta, ejemplos y relación con el nombre visible. |
| `inventario_kmz_capas.csv`, 3.638 grupos | Contexto y coincidencia de atributos con el nombre KML. |
| `inventario_kmz_resumen.csv`, 13 filas | Archivos inventariados. |

Las huellas y balances históricos se conservan en sus informes. La matriz actual contiene una edición posterior de descripciones. Para reproducir 1.7 se exige la matriz histórica del ZIP y comprobar su SHA-256; el CSV actual editado se conserva. No se adopta silenciosamente una modificación de la fuente como un nuevo mapeo.

El EFT exige conservar atributos propios y unificar equivalencias aplicables. No establece mayúsculas generales ni exige el prefijo `src_`. Por decisión del usuario, los nombres nuevos usan `snake_case`: minúsculas, sin tildes y con `_` como separador. No se adivinan palabras dentro de siglas.

Los nombres de clases se derivan de la descripción o del tema consolidado. La revisión 1.6 quitó artículos y preposiciones prescindibles y sustituyó partes de hash por nombres descriptivos. Esta preferencia no significa que SQL Server prohíba artículos como `de`. `nombres_clases_1_6.csv` conserva las 76 correspondencias: 25 renombres y 51 nombres que se mantuvieron.

Se conservan `Datos_Proyecto`, los nombres oficiales del DDL y los campos nativos, como `OBJECTID`, `Shape` y `GlobalID`. Estas excepciones no se convierten automáticamente a minúsculas. El paquete no crea las capas maestras externas ni internas.

## Qué significa `_recorte`

El sufijo identifica clases destinadas a copias de referencia acotadas al proyecto/análisis. Las 63 clases del grupo conservan su trazabilidad mediante los campos aplicables, incluidos `capa_origen` e `id_origen`. El nombre expresa su papel; no demuestra que se haya ejecutado un recorte geométrico.

Las fuentes maestras y sus destinos deben confirmarse antes de cargar o publicar. Un nombre propuesto en el mapeo no acredita que esa clase maestra exista en la geodatabase.

## Equivalencias documentadas

| Origen | Destino o tratamiento | Fundamento o límite |
|---|---|---|
| `CodigoEnti`, `CodVertice` | `codigo_enti`, `cod_vertice` | Normalización de escritura conservando el significado. |
| `Alternativ`, `Alternativa` | `alternativa` | Variante truncada/completa; comparar con el contexto. |
| Variantes de observaciones | `observaciones` | Equivalencia indicada en EFT 5.8.7. |
| `TENSION_NO`, `Tension Nominal (kV)` | `tension_nominal_kv` o campo DDL aplicable | Verificar unidades y valores antes de cargar. |
| `Nombre` / `Name` | `nombre` solo con equivalencia comprobada por ruta | Evidencia conjunta de campos y capas. |
| Identificadores de fuente aplicables | `id_origen` | Respetar el Ámbito del campo común. |

En Palián se conserva `src_nombre` cuando `Nombre` representa la línea y el nombre visible procede de `CodVertice`. `src_nombre` y `src_fuente` conservan atributos originales que colisionan con un nombre común sin equivalencia demostrada; no son prefijos exigidos por el EFT ni extensiones inventadas.

No se fusionan `east`/`este`/`x` ni `north`/`norte`/`y` solo por parecido: se requieren valores, unidades y sistemas de coordenadas compatibles. Las 359 ocurrencias conservadas en `revision_equivalencias.csv` son casos por contexto, no 359 conflictos comprobados.

Cuando valores distintos converjan en un campo, la carga futura debe detenerse para resolverlos. El conflicto de oficina registral permanece pendiente en 1.7.

## Estructuras: conteo conservado

`estructuras` mantiene **32 campos del modelo y siete de sistema/auditoría: 39 físicos**. La confirmación 1.7 no añade campos.

Los 11 comunes son `proyecto`, `id_analisis`, `disciplina`, `componente`, `alternativa`, `condicion`, `fuente`, `nombre`, `archivo_origen`, `ruta_kml` y `fecha_carga`.

Los 21 propios son `codigo_enti`, `name`, `descripcion`, `src_fuente`, `tipo`, `emp_consultora`, `este`, `norte`, `cod_vertice`, `src_nombre`, `position`, `zone`, `east`, `north`, `utm`, `lat_lon`, `torre`, `vertice`, `x`, `y` y `vano`. Se confirmaron en 1.4: siete DOUBLE y catorce TEXT. Conservar su tipo no convierte unidades.

## Tipos e informes vigentes

El modelo 11 conserva 76 clases y 3.340 definiciones. De los 2.086 campos provisionales anteriores, 1.356 se confirman como TEXT de longitud 4.000 y 730 siguen pendientes. La longitud procede de la definición conservadora y su revisión; no está impuesta por el EFT.

`textos_confirmados_1_7.json` vincula la lista aprobada con el perfil y las huellas del modelo. La nueva herramienta verifica esos campos y sus clases existentes. `campos_por_ruta.csv` conserva el mapeo preciso. `normalizacion_kmz.py` apoya la preparación de nombres y detección de colisiones; no es un cargador.

Los informes anteriores son antecedentes de sus versiones, no certificados del modelo 11 ni referencias para reanudar una versión distinta. Relaciones, destinos pendientes, códigos de proyecto/análisis, branch y carga conservan sus fases de comprobación.
