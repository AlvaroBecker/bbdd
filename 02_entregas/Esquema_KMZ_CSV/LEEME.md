# Esquema con nombres tomados de descripcion del CSV

**Reemplazado por la revisión temática:** [Esquema_KMZ_EFT_Corregido](../Esquema_KMZ_EFT_Corregido/LEEME.md), que consolida temas, aplica `_recorte` y usa las clases migradas de MapLine. Este paquete conserva la versión anterior de una clase por descripción/geometría.

Esta revisión sustituye el criterio de nombres del paquete `Esquema_KMZ_EFT`. La fuente de cada nombre es exclusivamente `descripcion` en `inventario_kmz_matriz_campos.csv`, combinada con `geometria` para separar clases de entidad. Se conserva el CSV original.

## Reglas de nombres

- Minúsculas y `snake_case`: cada secuencia de espacios o signos se reemplaza por un guion bajo.
- Vocales con tilde o diéresis pasan a su letra simple y `ñ` pasa a `n`.
- Se eliminan guiones bajos al inicio y final.
- Si una descripción tiene más de una geometría, todas sus clases llevan el sufijo `_punto`, `_linea` o `_poligono`.
- El límite de implementación es 50 caracteres para reservar espacio al prefijo `rel_proyecto_` de la relación. Los nombres más largos conservan un comienzo legible, un identificador de ocho caracteres y, si corresponde, el sufijo geométrico. La descripción y el nombre normalizado sin abreviar quedan en el catálogo.
- Si dos textos diferentes producen el mismo nombre, un identificador estable distingue la colisión.

Ejemplos:

| Descripcion | Nombre |
|---|---|
| Áreas naturales protegidas (SERNANP) | `areas_naturales_protegidas_sernanp` |
| Predios inscritos en SUNARP | `predios_inscritos_en_sunarp` |
| Geología (INGEMMET), geometría Línea | `geologia_ingemmet_linea` |
| Geología (INGEMMET), geometría Polígono | `geologia_ingemmet_poligono` |

## Resultado

Hay 100 descripciones y 125 combinaciones de descripción/geometría. Se generan 124 clases y 124 relaciones al proyecto. El grupo `Conflictos sociales (Defensoría del Pueblo)` tiene geometría `Mixta`: su nombre propuesto se conserva en el catálogo pero no se crea una clase hasta separar sus geometrías.

Este catálogo contiene solo los grupos presentes en la matriz indicada. Las capas sin correspondencia en esa matriz permanecen identificadas como `NO_FIGURA_EN_MATRIZ` en el mapeo complementario. No se crean las clases maestras o migradas del paquete anterior por el solo hecho de que existan en el catálogo EFT.

Las clases nuevas se ubican en `Datos_Proyecto`, conforme a la regla de carga inicial del EFT, y se relacionan por `mline_tc_proyecto.co_proyecto → proyecto`. Los datasets `Datos_Externos` y `Datos_Internos` también se preparan como contenedores vacíos. Se conserva la configuración de campos comunes, dominios, WGS84, GlobalID y auditoría del motor anterior.

**La nueva convención modifica el diseño generado, no renombra objetos existentes en SQL Server.** Los nombres de las tablas MapLine existentes, incluida `mline_tc_proyecto`, permanecen como referencias del modelo. Las correspondencias con componentes, alternativas y clases migradas requieren revisión antes de cargar: una descripción del inventario no demuestra por sí sola equivalencia de negocio.

Los atributos propios siguen tomando sus nombres de `campo_normalizado` con las reglas de la versión anterior. Esta revisión no solicita ni aplica una conversión general de los atributos a minúsculas. Los campos sin tipo documentado siguen como texto de 4.000 caracteres y los campos de sistema heredados se omiten. El mapeo de cada fila puede revisarse en `campos_matriz_a_esquema.csv`.

## Archivos para validar

1. `catalogo_nombres.csv`: descripción original, geometría, nombre completo normalizado, nombre físico, abreviaciones, estado y conteos del inventario de capas por proyecto.
2. `campos_matriz_a_esquema.csv`: atributo de origen y campo/clase de destino para las 3.507 filas de la matriz.
3. `esquema.json`: definiciones que utilizan los scripts.
4. `por_clase/*.py`: un script por clase.
5. `mapeo_capas_revision.csv`: todas las rutas originales, sin aprobar su inclusión ni asignar códigos de proyecto.

## Ejecución

Desde Python Command Prompt de ArcGIS Pro, en esta carpeta:

```bat
python por_clase\predios_inscritos_en_sunarp.py
```

Sin workspace, este comando solo muestra la definición. Para crear una clase en una geodatabase local nueva, indicando una carpeta que ya exista:

```bat
python por_clase\predios_inscritos_en_sunarp.py --workspace "C:\trabajo\Revision_CSV.gdb" --aplicar
```

Para prevalidar contra una conexión del propietario:

```bat
python crear_esquema.py --workspace "C:\conexiones\ArcGisAWS_gis.sde"
```

La creación requiere `--aplicar`. La fase de relaciones usa `--accion relacionar`, primero sin `--aplicar` para comprobar llaves y después con ese argumento para crearlas. La tabla padre debe estar registrada en la misma geodatabase, con `co_proyecto` de texto de longitud 12 y códigos únicos. Padre e hija deben tener el mismo versionado. El motor se detiene ante estructuras existentes incompatibles y no las altera silenciosamente.

El registro branch sigue siendo una fase posterior en ArcGIS Pro, con el modelo y datos revisados. Este paquete no activa versionado, no crea FK SQL y no carga KMZ. Una relationship class no sustituye todas las comprobaciones de integridad de una FK SQL.

Se verificaron estáticamente normalización, ausencia de colisiones, cobertura de campos y referencias de los scripts. Este catálogo nuevo no se ha ejecutado en una geodatabase; las pruebas locales del paquete anterior corresponden al motor y al catálogo anterior.
