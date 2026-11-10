# Versión 1.9: cierre de tipos de Datos_Proyecto

Esta versión incorpora la novena herramienta **Cerrar tipos de Datos_Proyecto** en la misma `Datos_Proyecto.pyt`. Aplica el lote autorizado después de revisar los dos informes del usuario: 722 confirmaciones de almacenamiento TEXT y ocho cambios numéricos. El modelo objetivo es el **12**, con cero campos de tipo provisional.

Los informes anteriores comprobaron las 76 clases y las 3.340 definiciones esperadas en la SDE. La herramienta vuelve a comprobar el destino actual antes de aplicar cambios; el informe histórico no sustituye esa comprobación.

## Alcance exacto

| Clase | Campos | Tipo objetivo |
|---|---|---|
| sitios_arqueologicos_poligono_recorte | alt_mode, clamped, extruded | LONG |
| sitios_arqueologicos_poligono_recorte | base | DOUBLE |
| sitios_arqueologicos_punto_recorte | alt_mode, has_label | LONG |
| sitios_arqueologicos_punto_recorte | base | DOUBLE |
| suelos_recorte | p_aui_suel | LONG |

Estos ocho campos pasan de TEXT(4000) al tipo indicado. Los 722 textos conservan sus columnas, longitudes, nombres, alias, nulabilidad y dominios. Su confirmación es una decisión de almacenamiento documentada; no atribuye una declaración textual a fuentes que no la proporcionan.

`oficina_registral` queda confirmado como TEXT(4000). Su capacidad de almacenamiento y el conflicto de valores son asuntos distintos: el mapeo permanece abierto.

No se agregan atributos físicos, clases ni datasets. El lote tampoco renombra, borra, reconstruye ni carga objetos.

## Modelo aprobado y estado real de la SDE

`esquema.json` contiene el modelo **objetivo** 12. Por eso su contador de provisionales es cero desde la distribución. Eso no afirma que la SDE ya tenga los ocho tipos nuevos.

El cierre solo se acredita cuando el informe de ejecución indica simultáneamente:

- `estado: TIPOS_CERRADOS_CON_PENDIENTES_DE_INGESTA`
- `campos_pendientes_modelo: 0`
- `cambios_pendientes_destino: 0`
- `cierre_verificado: true`
- `destino_despues.verificado: true`, con 3.340 campos verificados.

Antes de aplicar, `CIERRE_VALIDADO_SIN_CAMBIOS` muestra los cambios físicos todavía pendientes. Una ejecución interrumpida puede mostrar menos de ocho: se reconocen los campos que ya alcanzaron el tipo objetivo.

## Controles de aplicación

La herramienta prevalida todo el lote y el esquema esperado de las 76 clases antes del primer cambio. Las tres clases afectadas deben estar vacías; sus campos deben conservar las propiedades autorizadas y estar libres de dependencias incompatibles e índices sobre los candidatos. Se comprueba la disponibilidad del bloqueo de esquema al aplicar.

La restricción de tabla vacía corresponde al cambio de tipo mediante [Alter Field de Esri](https://doc.esri.com/en/arcgis-pro/latest/tool-reference/data-management/alter-field-properties.html).

Cada operación usa `AlterField` sobre una de las ocho columnas autorizadas. Se comparan las propiedades antes y después, y se guarda un informe nuevo por etapa. Al terminar se verifica otra vez el esquema completo. Si se interrumpe, se conserva el diagnóstico y se vuelve a leer el estado real al reintentar; no se ejecuta un borrado para deshacer cambios.

## Evidencia conservada

- `esquema_anterior_1_8.json`: modelo 11 original, idéntico al ZIP 1.8.
- `cierre_tipos_1_9.json` y `PLAN_CIERRE_TIPOS_1_9.csv`: las 730 decisiones, sus fundamentos y los ocho cambios físicos.
- `PERFIL_COMPLETO_KMZ_1_8.json`: evidencia original completa de los 13 KMZ.
- `PERFIL_COMPLETO_KMZ_1_9.json`: esa misma evidencia de valores, reevaluada con el modelo 12. Se comprobaron nuevamente los hashes de los 13 archivos; no se afirma una nueva lectura de su XML.
- Pruebas del modelo, del perfil, de las herramientas y del ensayo nativo identificadas en el manifiesto.

Los analizadores de valores y el lector de KMZ conservan sus reglas; se verificó que los valores perfilados y los vínculos de rutas no cambiaron. El verificador histórico de los 1.356 textos y la herramienta de revisión completa admiten el modelo 12. Las otras operaciones históricas conservan su alcance.

El generador histórico que termina en modelo 11 queda protegido contra sobrescribir un modelo 12. La preparación reproducible de este cierre está en `03_scripts/preparar_cierre_tipos_1_9.py` dentro del proyecto de desarrollo.

## Pendientes de ingesta

El cierre de tipos conserva abiertos:

- Las reglas para convertir `<Null>` en tres columnas DOUBLE ya tipificadas.
- La correspondencia de `oficina_registral` en las 253 entidades con valores en conflicto.
- Las 2.601 rutas, con 140.319 elementos, sin destino asignado.
- La comprobación de los cuatro G1 que no fueron incorporados en la lectura de carpeta de CT6788. El perfil incluido sí contiene los 13 originales.
- Los controles de llaves, relaciones/FK y versionado, y la implementación de `Datos_Externos` y `Datos_Internos` conforme al EFT.

La herramienta no autoriza ni inicia ingesta. El estado incluye expresamente **CON_PENDIENTES_DE_INGESTA** para mantener visible esa diferencia.

Los ensayos locales comprueban la implementación; el resultado sobre SQL Server/SDE se obtiene cuando el usuario ejecuta la herramienta con su conexión.
