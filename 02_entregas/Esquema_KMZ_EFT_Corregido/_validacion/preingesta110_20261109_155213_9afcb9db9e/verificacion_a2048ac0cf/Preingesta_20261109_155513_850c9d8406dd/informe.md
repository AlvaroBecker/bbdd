# Prevalidación de ingesta 1.10

Estado: **PLAN_INGESTA_CON_PENDIENTES**

Esta ejecución genera un plan; no inserta registros ni modifica la geodatabase.

KMZ esperados: 13. Fuentes actuales verificadas: True.
Esquema de destino verificado: True.
Correspondencias de proyecto verificadas: False.

## Cómo revisar el resultado

1. Revise fuentes_kmz.csv y correspondencia_kmz.csv. Se buscan KMZ recursivamente y se comparan sus SHA-256 con las 13 fuentes del perfil completo. Un nombre distinto se documenta. Ausencias, duplicados, cambios de contenido y archivos adicionales quedan visibles.
2. Revise asociaciones_proyecto.csv y catalogo_proyectos.csv. Complete confirmar_proyectos.csv con el código real y confirmado=si para cada asociación revisada. Los candidatos por nombre no se confirman automáticamente. Vuelva a ejecutar con ese CSV si quiere validar la asociación.
3. Revise plan_rutas.csv, rutas_sin_destino.csv, reglas_valores.csv e incidencias.csv. Los recuentos son Placemarks agrupados por ruta/geometría del perfil, no filas prometidas para una carga que todavía debe resolver geometrías y correspondencias.
4. Revise ajustes_esquema_propuestos.csv: las oficinas registrales del inmueble y de la persona jurídica son atributos distintos que el EFT 5.8.7 requiere conservar. El modelo actual tiene una sola columna; el ajuste se documenta para prepararlo y verificarlo antes de cargar. Complete también los atributos sin correspondencia y los campos obligatorios, incluido id_analisis.

## Alcance de la evidencia

Los valores se reutilizan del perfil completo 1.9 solo después de comprobar que los 13 archivos actuales tienen exactamente los mismos bytes. No se repite el análisis XML. Un cambio de contenido impide usar esa evidencia como comprobación de las fuentes actuales.
El catálogo de proyectos, los tipos de campo y los recuentos del destino se consultan en vivo. Observar relaciones existentes no certifica FK, reglas de relación, publicación, branch ni permisos de un servicio. Tampoco se certifican geometrías reparadas ni los otros dos datasets.

Ninguna ruta se declara lista para insertar en esta herramienta. El cierre de tipos 1.9 se conserva; los pendientes de este plan son de carga y correspondencia.

## Resumen del plan

```json
{
  "rutas": 3638,
  "rutas_inventariadas": 3638,
  "rutas_no_inventariadas": 0,
  "elementos": 279623,
  "rutas_con_destino": 1037,
  "rutas_sin_destino": 2601,
  "elementos_con_destino": 139304,
  "elementos_sin_destino": 140319,
  "campos_con_incidencias": 1,
  "reglas_null_definidas": 3,
  "ocurrencias_null_con_regla": 23,
  "campos_obligatorios_con_regla_pendiente": 156,
  "observaciones_fuente": 1621
}
```
