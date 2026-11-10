# Revisión de los 2086 campos provisionales

La validación comunicada por el usuario confirmó las 76 clases del modelo actual. El contador de tipos provisionales coincide con las 2086 definiciones pendientes de `esquema.json`, repartidas en 70 clases. Todas conservan actualmente `TEXT(4000)` en el modelo.

Se cruzó el perfil anterior de 2185 campos con los nombres actuales. Los 99 campos excluidos son exactamente los cambios ya aprobados. Las huellas SHA-256 de los 13 KMZ coinciden con las usadas por el perfil. Este cruce no vuelve a analizar las rutas que todavía no tienen destino aprobado.

| Grupo de revisión | Campos | Tratamiento propuesto |
|---|---:|---|
| Evidencia útil para conservar texto, sin conflictos de valores | 1356 | Candidatos a confirmar como texto, sin cambios físicos. |
| Números cuyo significado no está confirmado | 474 | Revisar códigos, magnitudes, unidades y precisión antes de convertir. |
| Sin valores útiles | 187 | Conservar texto provisional hasta disponer de evidencia suficiente. |
| Posibles fechas con valores | 47 | Revisar todos los formatos y textos especiales antes de convertir. |
| Valores con ceros iniciales | 21 | Preservar su representación y verificar si son códigos. |
| Conflicto de mapeo de `oficina_registral` | 1 | Conservar las dos ocurrencias de origen mediante un mapeo explícito. |
| **Total** | **2086** | |

El JSON adjunto identifica cada clase y campo, su grupo, cobertura, recuentos y fundamento histórico. **Es un borrador de revisión: ningún campo se ha aprobado automáticamente ni se ha modificado el modelo o la geodatabase.**

Los campos restantes no exceden las 4000 unidades UTF-16 medidas por el perfil. El problema anterior de texto largo pertenece al lote de 99 y ya fue reparado según el resultado comunicado por el usuario. Eso no resuelve por sí solo los mapeos de carga o la interpretación de los valores.

## La doble etiqueta OFICINA REGISTRAL

En FELAM y PARIÑAS, 288 entidades tienen dos ocurrencias de `OFICINA REGISTRAL`; 253 contienen valores diferentes. Elegir la primera o la última descartaría información.

Se verificaron también los 71 polígonos SUNARP de MUYURINA (22) y PALIAN (49): todos tienen `OFICINA_RE` en el contexto de partida del predio/antecedente y `OFICINA__1` entre `PARTIDA_JU` y `JUNTA_DIRE`. En 42 de esos 71 registros ambas oficinas son diferentes. El segundo contexto coincide con el observado en las 288 entidades de FELAM y PARIÑAS.

El esquema actual ya contiene `oficina_1`, procedente de `OFICINA__1`. Por ello, hay una propuesta sustentada para mantener la primera ocurrencia de FELAM/PARIÑAS en `oficina_registral` y mapear la segunda al campo existente `oficina_1`, sin añadir `oficina_registral_2`. Esta equivalencia debe quedar documentada y controlada por ruta, contexto y ocurrencia; todavía no se aplicó a un proceso de carga. Si dos atributos distintos confluyen con valores incompatibles en un destino, la carga debe detenerse para revisar el registro.

## Cobertura y siguiente etapa

El perfil de tipos abarca 961 rutas asignadas y 127725 asignaciones de geometría. El inventario completo tiene más rutas, incluidas rutas sin destino; esta revisión no declara lista la carga completa de los KMZ.

El siguiente trabajo es cerrar el diccionario de tipos empezando por los candidatos textuales y resolver las reglas de mapeo. Para una prueba acotada, `estructuras` de CHANCHAMAYO tiene 53 puntos en tres rutas y sus tipos ya fueron revisados, pero todavía deben completarse y comprobarse el código real de proyecto, el identificador de análisis y el mapeo de esas rutas antes de cargar.
