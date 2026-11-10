# Datos_Proyecto: preparar carga inicial, versión 1.13

Las fuentes y las asociaciones de los 13 KMZ ya quedaron verificadas. Para el siguiente paso:

1. Extraiga `Datos_Proyecto_Controlado_v1_13.zip` en una carpeta nueva del equipo con ArcGIS Pro.
2. Agregue el `Datos_Proyecto.pyt` de esa carpeta al proyecto. Compruebe que la etiqueta diga **1.13**.
3. Abra **Preparar carga inicial de los KMZ**. Es la nueva herramienta del mismo toolbox.
4. Seleccione la conexión `SQLServer-EEPAWSDBP01-ArcGisAWS(gis).sde` y la carpeta raíz que contiene los **13 KMZ**, incluidos los cuatro G1.
5. Mantenga el CSV `confirmar_proyectos_13_confirmados.csv` que viene seleccionado. Use `ArcGisAWS` y `gis` como base y propietario.
6. Elija una carpeta de informes fuera de la geodatabase y ejecute.
7. Revise `informe.txt` y `resultado.json`. Este último reúne cobertura, claves de negocio, SUNARP, descripciones y reglas de campos comunes. Los CSV facilitan revisar las rutas y las identidades pendientes.

La ejecución **no crea tablas ni carga registros**. Si termina con `PREPARACION_CON_PENDIENTES`, las lecturas están completas, pero el plan todavía requiere cerrar los tratamientos indicados. `PREPARACION_INCOMPLETA` permite identificar una tabla ausente, una lectura incompleta o una fuente distinta sin declarar listo el destino.

El resultado esperado con las referencias actuales contiene **152 reglas comunes definidas y cuatro identidades pendientes**. Las 91 propuestas de destino y la clase `vanos` se entregan para revisión, sin aplicarse automáticamente. No repita las herramientas de creación, cierre de tipos, auditoría o alta de proyectos que ya finalizaron correctamente.

Consulte [CAMBIOS_1_13.md](CAMBIOS_1_13.md) para alcance y validación. Los apartados siguientes describen operaciones anteriores y se conservan como referencia histórica; no son pasos pendientes de esta ejecución.

## Referencia histórica: configuración del catálogo en 1.12

El informe real del alta encontró tres pendientes en `gis.mline_tc_proyecto`: Editor Tracking desactivado y los dos dominios sin asignar. La secuencia real termina en 40. Antes de registrar JAENNORTE y POROMA hay que preparar ese catálogo. No repita las migraciones de Datos_Proyecto.

## Revisar la propuesta de configuración 1.12

La zona horaria de `fe_creacion` y `fe_actualizacion` no está acreditada por el origen. Son DATETIME alimentados con NOW() y se migraron sin conversión. Por ello **no se reutilizan esas fechas como UTC ni se convierten por suposición**.

La propuesta conserva `us_creacion`, `fe_creacion`, `us_actualizacion` y `fe_actualizacion` intactos, y utiliza estos cuatro campos para la auditoría futura:

| Campo | Tipo | Uso |
|---|---|---|
| `created_user` | TEXT 255 | Usuario que crea el registro |
| `created_date` | DATE, precisión baja | Fecha de creación UTC |
| `last_edited_user` | TEXT 255 | Último editor |
| `last_edited_date` | DATE, precisión baja | Fecha de última edición UTC |

Son campos administrados por ArcGIS. El EFT exige la capacidad de auditoría, pero no ordena literalmente estos nombres ni cuatro columnas adicionales. **Dada su instrucción de no agregar campos extra, esta decisión requiere su aprobación.** La casilla está desmarcada por defecto. No se reconstruye retrospectivamente auditoría para las 40 filas existentes.

1. Extraiga `Datos_Proyecto_Controlado_v1_12.zip` en una carpeta nueva de CT6788 y agregue su `Datos_Proyecto.pyt`.
2. Abra **Preparar catálogo de proyectos para altas**, herramienta 12. Indique su conexión SDE, base `ArcGisAWS`, propietario `gis` y carpeta de informes.
3. Ejecute **Validar configuración (sin cambios)**. Si los campos aún faltan y no ha aprobado la propuesta, el estado será `CONFIGURACION_PENDIENTE_APROBACION_AUDITORIA`. Revise los campos y operaciones de `plan_previo.json`; ese estado no constituye un error de ejecución ni una aprobación.
4. **Solo si aprueba la propuesta**, marque **Autorizar cuatro campos de auditoría ArcGIS separados del histórico** y ejecute **Aplicar configuración aprobada**. Sin esa casilla, el intento de aplicar se detiene antes de cualquier cambio.
5. El estado esperado es `CONFIGURACION_PROYECTO_VERIFICADA`. Se asignan los dominios completos `mline_proyecto_tipo` (7/8) y `mline_proyecto_estado` (3/4/5/6), y se activa la auditoría UTC separada. No se crean proyectos en este paso.
6. Continúe con **Registrar proyectos faltantes de los KMZ**, siguiendo las instrucciones de abajo.

La configuración no borra ni reemplaza dominios incompatibles, ni altera un rastreo ya configurado de otra forma. Consulta primero los campos reales y reutiliza los cuatro propuestos solo si son compatibles y no contienen valores de significado desconocido. Las operaciones de esquema no son una transacción única: cada paso queda registrado y verificado. Si falla alguno, el informe indica lo que llegó a ejecutarse y no afirma una reversión automática. Una nueva validación revisa lo que realmente existe.

## Registrar JAENNORTE y POROMA

1. Utilice el mismo paquete 1.12. Mantenga juntos sus archivos.
2. Abra **Registrar proyectos faltantes de los KMZ**, la herramienta 11.
3. Seleccione su conexión `SQLServer-EEPAWSDBP01-ArcGisAWS(gis).sde`, base `ArcGisAWS`, propietario `gis` y una carpeta existente para informes.
4. En **CSV de proyectos confirmados para completar**, seleccione `confirmar_proyectos_por_nombre.csv`, incluido en el paquete. Contiene las nueve asociaciones ya confirmadas y cuatro pendientes; no contiene códigos inventados para los nuevos proyectos.
5. Ejecute **Validar altas (sin cambios)**. El resultado esperado es `ALTAS_VALIDADAS_SIN_CAMBIOS`. Revise los dos nombres, el máximo actual y los códigos propuestos en `plan_previo.json`. No quedan reservados. Si aparece `ALTAS_BLOQUEADAS_SIN_CAMBIOS`, el informe indica las condiciones reales del padre que faltan; no se debe pasar a Crear todavía.
6. Como confirmó que nadie más utiliza la base, marque **Sin otras altas simultáneas durante esta ejecución** y cambie la acción a **Crear proyectos faltantes**. Ejecute mientras siga sin otras altas.
7. El resultado esperado es `ALTAS_PROYECTOS_VERIFICADAS`. Use el nuevo **`confirmar_proyectos.csv` de esta ejecución** para repetir la prevalidación de ingesta indicada abajo.

Si los identificadores reales llegan a 40 y ambos proyectos siguen ausentes, se asignan `PRY-00000041` a JAENNORTE y `PRY-00000042` a POROMA. La herramienta calcula los números al ejecutarse; incluye proyectos inactivos al obtener el máximo y no reutiliza huecos. Si el proyecto ya existe de forma inequívoca, conserva su código y estado. Repetir la herramienta no vuelve a insertarlo.

El alta requiere tabla registrada no versionada, Editor Tracking activo y dominios que acrediten tipo 8 = Línea de Transmisión y estado 3 = Registrado. Si falta esa configuración o existen reglas/subtipos que requieren otra ruta, se informa sin cambiar el esquema ni el versionado. La herramienta no añade campos ni manipula tablas de sistema.

ArcGIS genera ObjectID, GlobalID cuando existe, usuarios y fechas de auditoría. Los campos heredados de IP/eliminación/alternativa permanecen nulos en las altas cuando no los gestiona la auditoría nativa. La operación usa una sesión de edición: un fallo previo al guardado revierte el lote y comprueba la reversión. No establece un bloqueo global: la ausencia de otras altas es una condición operativa. Si se pierde la respuesta durante el guardado, informa `ESTADO_INCIERTO` para verificar la tabla antes de reintentar.

Con el CSV incluido, el resultado normal tendrá 11 asociaciones confirmadas y 2 pendientes: el KMZ completo FELAM y PUCALLPA. No se eligen sus códigos por descarte. Las asociaciones a proyectos inactivos ya existentes no los reactivan. Todavía no se cargan geometrías ni registros de los KMZ.

## Repetir la prevalidación de ingesta

1. Utilice el mismo paquete 1.12 ya agregado.
2. Abra **Prevalidar ingesta de los KMZ**, la décima herramienta.
3. Complete los parámetros:

| Parámetro | Valor |
|---|---|
| Conexión | Su archivo `SQLServer-EEPAWSDBP01-ArcGisAWS(gis).sde` |
| Carpeta raíz con los 13 KMZ | La carpeta de CT6788 que contiene los nueve Proyecto y los cuatro G1; incluye subcarpetas |
| CSV de proyectos confirmados | El nuevo `confirmar_proyectos.csv` generado por el alta verificada |
| Base de datos | `ArcGisAWS` |
| Propietario | `gis` |
| Carpeta de informes | Una carpeta existente donde pueda escribir |

4. Ejecute. Esta herramienta no tiene acción Aplicar y no inserta, renombra ni cambia columnas.

La carpeta que debe elegir es la del equipo donde ejecuta ArcGIS, no la ruta `C:\Users\aibecker` del equipo de desarrollo. Un KMZ con nombre distinto se reconoce por su SHA-256 si su contenido es idéntico. Los archivos ausentes, adicionales, modificados o duplicados aparecen en el informe.

## Leer el resultado

**PLAN_INGESTA_CON_PENDIENTES** significa que las fuentes y la estructura pudieron comprobarse, pero quedan decisiones de correspondencia y preparación. No significa que ya se pueda cargar. **PREVALIDACION_INGESTA_INCOMPLETA** identifica fuentes o consultas que no se pudieron acreditar; revise el informe antes de continuar.

| Archivo | Para qué sirve |
|---|---|
| `resultado.json` e `informe.md` | Resultado completo y resumen de la ejecución |
| `fuentes_kmz.csv` y `correspondencia_kmz.csv` | Inventario actual y correspondencia con los 13 KMZ originales |
| `catalogo_proyectos.csv` | Proyectos leídos de la tabla real, sin inventar códigos |
| `asociaciones_proyecto.csv` | Correspondencias confirmadas o candidatos por nombre |
| `confirmar_proyectos.csv` | Plantilla editable para confirmar archivo y código |
| `plan_rutas.csv` | Archivo, ruta, geometría, clase, proyecto, recuento e incidencias |
| `rutas_sin_destino.csv` | Rutas que aún necesitan una decisión de inclusión y destino |
| `reglas_valores.csv` | Conversión prevista del literal `<Null>` a nulo en tres campos |
| `ajustes_esquema_propuestos.csv` | Conservación separada de las dos oficinas registrales; ajuste aún no aplicado |
| `campos_obligatorios.csv` | Reglas pendientes para proyecto, id_analisis y otras claves obligatorias |
| `incidencias.csv` | Conflictos y observaciones, con su nivel y alcance |

## Confirmar proyectos

Revise el catálogo real y las propuestas. En `confirmar_proyectos.csv` conserve `archivo_kmz` y complete `co_proyecto` con el código exacto existente y `confirmado` con `si`. Guarde el CSV y vuelva a ejecutar esta misma herramienta seleccionándolo en el parámetro opcional. Las columnas están separadas por punto y coma y el archivo usa UTF-8.

No se confirma una asociación solo por semejanza del nombre. Varios KMZ pueden corresponder al mismo proyecto si la relación se confirma explícitamente. Si falta un proyecto en el catálogo, queda pendiente su alta según el EFT; esta herramienta no crea códigos correlativos ni registros padre.

## Oficinas registrales y EFT

El apartado 5.8.7 dice: «Cada capa conserva todos sus atributos» y «Los nombres se unifican con una tabla de equivalencias». En los KMZ existen dos etiquetas OFICINA REGISTRAL con contextos diferentes: una del inmueble y otra de la persona jurídica. El plan mantiene ambas como atributos distintos y registra la reconciliación de columnas y equivalencias necesaria. No selecciona una oficina ni concatena valores para ocultar el conflicto.

El cierre de tipos anterior verificó el modelo existente. Esta revisión de correspondencias puede identificar atributos de origen que el modelo no representó correctamente. La 1.10 documenta esos ajustes; conserva intacto el modelo 12 y no añade columnas.

## Alcance y siguientes decisiones

El perfil de referencia contiene 3.638 rutas y 279.623 Placemarks: 139.304 tienen clase de destino y 140.319 no la tienen. Estos son recuentos de origen, no una promesa del número de filas finales después de tratar geometrías.

La prevalidación utiliza los valores del perfil completo solo si los archivos actuales tienen exactamente los mismos bytes. Consulta en vivo los 3.340 campos y los proyectos de la SDE. No certifica aún integridad geométrica, deduplicación entre archivos, FK/relaciones, branch, servicios ni la implementación de Datos_Externos y Datos_Internos. Esos controles se conservan como requisitos de la carga.
