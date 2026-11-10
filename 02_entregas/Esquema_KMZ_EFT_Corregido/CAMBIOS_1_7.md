# Versión 1.7: confirmar y validar 1.356 campos de texto

La versión **1.7** incorpora **Validar tipos de texto confirmados** como séptima herramienta de `Datos_Proyecto.pyt`. Su nombre técnico es `ValidarTextosConfirmados`.

El usuario informó la finalización del renombrado, la reparación de texto largo, los 99 cambios de tipos aprobados y la validación global de las 76 clases. Este paso comprueba el lote de textos confirmado sin repetir esas operaciones.

## Del modelo 10 al modelo 11

Se confirman **1.356 campos propios de KMZ en 70 clases** como **TEXT de longitud 4.000**. Solo cambia su metadata: `origen` pasa a `Atributo KMZ; tipo TEXT confirmado por perfil y decision 1.7` y se agrega `tipo_confirmado: true`.

El catálogo mantiene **76 clases y 3.340 definiciones de campos**. Se conservan nombres, alias, tipos físicos, longitudes, nulabilidad, dominios, geometrías y relaciones declaradas. Este paso no ejecuta DDL, carga datos ni crea relaciones; las herramientas anteriores mantienen sus acciones específicas.

La evidencia procede de los perfiles de las rutas asignadas de los 13 KMZ y de la decisión posterior del usuario sobre este lote. La longitud 4.000 no es una exigencia del EFT: se conserva porque los candidatos aprobados son texto y la evidencia de longitud cabe en la definición existente.

| Grupo que sigue pendiente | Campos |
|---|---:|
| Revisar el significado de valores numéricos | 474 |
| Sin valores Útiles | 187 |
| Fechas con valores | 47 |
| Códigos con ceros iniciales | 21 |
| Conflicto de mapeo de oficina registral | 1 |
| **Total** | **730** |

La versión no resuelve `predios_inscritos_sunarp_recorte.oficina_registral` ni aprueba automáticamente esos grupos.

## Pasos en ArcGIS Pro

1. Extraiga `Datos_Proyecto_Controlado_v1_7.zip` en una carpeta nueva. Mantenga juntos sus archivos y cierre los paneles de las herramientas anteriores.
2. Agregue su `Datos_Proyecto.pyt` desde **Catálogo → Cajas de herramientas → Agregar caja de herramientas**.
3. Abra **Validar tipos de texto confirmados**.
4. Elija la conexión `.sde` existente, **Base de datos esperada** `ArcGisAWS`, **Propietario esperado** `gis` y una carpeta existente para informes.
5. Pulse **Ejecutar**. No hay acción **Aplicar** ni selección parcial del lote.
6. Compruebe **TEXTOS_CONFIRMADOS_VERIFICADOS**, `campos_verificados: 1356` y `campos_pendientes_modelo: 730` en el JSON final.

Opcionalmente, ejecute después **Validar o crear clases en Datos_Proyecto** con **Validar (sin cambios)** y las **76 clases**. El resultado esperado es **VALIDACION_OK_SIN_CAMBIOS**, con 730 pendientes. Los parámetros completos están en [la guía](GUIA_DATOS_PROYECTO.md).

## Comprobaciones e informes

`textos_confirmados_1_7.json` contiene la lista cerrada, tipo, longitud, máximos observados en unidades UTF-16, valores Útiles, cobertura, propuesta histórica y huellas de revisión/modelo.

Antes de consultar ArcGIS se verifican versiones, hash del modelo objetivo, los 1.356 campos sin duplicados y los 730 pendientes conservados. En destino se comprueban conexión, propietario, dataset, propiedades espaciales de las clases afectadas, GlobalID y auditoría UTC. Cada columna requiere nombre exacto, tipo `String`, capacidad mínima de 4.000 y nulabilidad/dominio coincidentes con el modelo.

Cada ejecución genera una carpeta nueva `Textos_Confirmados_<ejecución>` con:

- `resultado.json`: estado, alcance, conteos, hashes y diferencias.
- `campos_verificados.csv`: propiedades esperadas y observadas.
- `diferencias.csv`: incidencias que deben resolverse.
- `informe.md`: explicación y límites.

No sobrescribe informes anteriores. Una discrepancia o lectura incompleta produce **ERROR_DETENIDO**; no cambia columnas para corregirla.

## Procedencia y reproducción

La revisión histórica de los 2.086 pendientes se conserva como borrador sin alterar sus aprobaciones originales. La decisión posterior sobre los 1.356 textos se registra en la configuración separada de 1.7. La generación comprueba fuentes y huellas, incluidos los 13 KMZ y el modelo histórico 10.

La matriz CSV actual contiene una edición posterior de descripciones. Para regenerar esta versión se exige la copia histórica del ZIP, verificada por SHA-256 antes de generar. El CSV actual editado se conserva: no se sobrescribe ni se usa silenciosamente para cambiar clases o atributos.

Los informes anteriores conservan su valor como antecedentes, con su versión y hash de modelo originales. No son referencias intercambiables para reanudar operaciones en el modelo 11.

## Límites

La herramienta consulta el esquema del lote aprobado. No lee registros de `tc_proyecto`, no valida los otros campos y no comprueba datos cargados. La verificación global sigue disponible en la primera herramienta.

El perfil cubre las rutas asignadas de los campos revisados; no resuelve las rutas sin destino. Un resultado satisfactorio no certifica toda la carga ni el cumplimiento integral del EFT. Los ensayos locales tampoco acreditan la conexión SQL Server/SDE del usuario; esa evidencia corresponde a la ejecución en su equipo.
