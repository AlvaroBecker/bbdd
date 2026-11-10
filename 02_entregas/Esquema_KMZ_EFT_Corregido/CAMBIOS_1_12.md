# Versión 1.12: propuesta para preparar el catálogo padre

## Diagnóstico real recibido

`resultado_registrar_proyectos.json`, SHA-256 `66f62e403351b9a36248a51a8c63dd56f21153c4fcef4784c4af0a6391bc8f03`, acredita 40 proyectos, identificador máximo 40, tabla no versionada, Editor Tracking desactivado y ausencia de dominios asignados a `id_tipo_proyecto` e `id_estado_proyecto`. La ejecución 1.11 no inició transacción ni creó filas. Las previsiones 41/42 siguen siendo propuestas.

La herramienta 12 **Preparar catálogo de proyectos para altas** presenta y, con la aprobación correspondiente, aplica una preparación limitada a esas condiciones. No registra los proyectos ni carga KMZ. Las once herramientas anteriores conservan su implementación y parámetros.

## Dominios completos

| Campo | Dominio | Códigos y etiquetas originales |
|---|---|---|
| `id_tipo_proyecto` | `mline_proyecto_tipo` | 7 Central de Generación; 8 Línea de Transmisión |
| `id_estado_proyecto` | `mline_proyecto_estado` | 3 Registrado; 4 Con malla; 5 Finalizado; 6 Cancelado |

Son LONG/CODED, procedentes de `mline_tp_parametro` en el respaldo MySQL. Los 40 proyectos históricos utilizan ambos tipos y los cuatro estados: crear solamente 8/3 sería incompleto. La herramienta comprueba los valores actuales, crea o completa el dominio canónico compatible y lo asigna únicamente a los dos campos del padre. Un dominio alternativo ya asignado solo se reutiliza si es completamente equivalente. No borra códigos ni sustituye descripciones incompatibles.

## Fechas históricas y decisión pendiente

El origen declara `fe_creacion` y `fe_actualizacion` como DATETIME; las rutinas de alta/actualización usan NOW(). El generador de carga conserva los literales en datetime2(0), sin conversión. El ajuste de zona de la sesión de exportación no prueba la zona original de esos valores DATETIME. Las funciones UTC de fechas de procesos no acreditan por sí solas la auditoría del padre. El usuario indicó que desconoce la zona histórica.

Esri indica que los valores de un campo de fecha existente deben corresponder al estándar temporal elegido para el rastreo. Para conservar los datos históricos sin reinterpretarlos, esta implementación propone cuatro campos separados: `created_user` TEXT255, `created_date` DATE0, `last_edited_user` TEXT255 y `last_edited_date` DATE0. ArcGIS mantiene la nueva auditoría en UTC; los cuatro legados permanecen intactos. Los registros anteriores no reciben valores de auditoría inventados. Véase [Introducción a Editor Tracking](https://doc.esri.com/en/arcgis-pro/latest/help/data/geodatabases/overview/introduction-to-editor-tracking.html).

El EFT exige auditoría nativa en tablas editables, pero no prescribe literalmente estos nombres ni cuatro columnas adicionales. **La propuesta requiere aprobación por la instrucción previa del usuario de no añadir campos extra.** No se presenta como un requisito de columnas de sistema equivalente a ObjectID. La herramienta mantiene la autorización desactivada por defecto y rechaza Aplicar antes de cualquier cambio si esa aprobación falta.

Si los campos propuestos ya existen, se verifican sus tipos, longitudes, precisión, nulabilidad, dominios y valores. No se apropia de campos con valores cuyo significado no esté acreditado. Si el rastreo ya está activo en otra configuración, se detiene en lugar de deshabilitarlo. La activación usa [Enable Editor Tracking](https://doc.esri.com/en/arcgis-pro/latest/tool-reference/data-management/enable-editor-tracking.html) con NO_ADD_FIELDS después de crear explícitamente solo los campos faltantes.

## Conservación y recuperación

La prevalidación es de lectura. Aplicar guarda una copia JSON de todos los atributos/filas originales, registra cada operación antes de intentarla y verifica su resultado. Compara todos los valores históricos y la definición de sus columnas después de cada paso; solo admite los dos cambios de dominio previstos y los cuatro campos de auditoría. No altera IDs, códigos, nombres, estados, IP, fechas o eliminaciones existentes.

Las operaciones de esquema ArcGIS no se presentan como una transacción con rollback automático. Un error informa los pasos ejecutados y el último intentado. La repetición consulta el estado real y continúa solamente si lo existente es compatible. Nunca elimina campos o dominios como supuesto rollback. Una vez que la configuración queda verificada, se vuelve al flujo 1.11 de Validar altas y Crear proyectos faltantes.

## Evidencia y límites

`configuracion_proyecto_1_12.json` identifica los valores propuestos, la aprobación pendiente y las fuentes con SHA-256. `VALIDACION_UNITARIA_1_12.json` registra las pruebas del código final. `VALIDACION_CONFIGURACION_1_12_ARCGIS.json` identifica el ensayo real en una GDB nueva con 40 proyectos sintéticos y auditoría histórica poblada: validación sin cambios, rechazo sin aprobación, configuración completa, conservación de los valores originales, repetición sin cambios y validación posterior del alta 1.11 sin incidencias.

La prueba es del runtime y ArcPy reales en una geodatabase local. El contrato del toolbox se verifica por separado; no se afirma ejecución nativa de su interfaz, acceso a SDE, certificación de relaciones/branch/servicios ni prueba de SQL Server. La estructura de las 76 clases y el modelo 12 permanecen intactos. Todavía no se cargan datos KMZ ni se resuelven FELAM completo, PUCALLPA, análisis o los otros datasets.
