# Datos_Proyecto: informe de ejecucion

Estado: **ERROR_DETENIDO**

Modo: CREAR
Conexion: `C:\Users\aibecker\Desktop\ENGIE PERU\bbdd\02_entregas\Esquema_KMZ_EFT_Corregido\_validacion\eft12_20261104_232530_758673c4\ensayo.gdb`
Modelo SHA256: `5e368094dc0e1991f2ef80f50f9b49e9a22fe3fb8df60dcd35b9139d296340de`

| Clase | Geometria | Campos definidos | Tipos pendientes | Accion |
|---|---|---:|---:|---|
| area_estudio_campo | POLYGON | 17 | 4 | CREAR |
| estructuras | POINT | 34 | 23 | CREAR |

## Limites

- El catalogo de 76 clases sigue siendo una propuesta funcional, no una aprobacion de INDRA.
- Los atributos marcados pendientes mantienen texto conservador; requieren perfil de valores y unidades antes de cargar.
- Los campos propios no se eliminan por tener nombres parecidos. El informe no certifica la equivalencia de sus valores.
- Esta fase crea clases vacias con GlobalID y auditoria UTC. No carga KMZ, no crea relaciones y no activa branch.
- Las relaciones con proyecto y las relaciones de negocio se validan y crean en una fase posterior.
- DDL ArcGIS no es una transaccion atomica: un fallo puede dejar una clase parcial. Se informa y se detiene, sin borrado automatico.
- TestSchemaLock del contenedor devolvio False; esta comprobacion no es concluyente en el ensayo local. ArcGIS verificara los bloqueos reales durante cada creacion.

## Error

ERROR 000229: Cannot open 
Failed to execute (AddFields).

La comprobacion posterior tampoco confirma la clase completa: C:\Users\aibecker\Desktop\ENGIE PERU\bbdd\02_entregas\Esquema_KMZ_EFT_Corregido\_validacion\eft12_20261104_232530_758673c4\ensayo.gdb\Datos_Proyecto\area_estudio_campo: falta proyecto. Revisar migracion; no se modifica el objeto existente.

Se detuvo el lote. Consulte clase_en_curso y completadas en resultado.json. No se borro ningun objeto para deshacer operaciones.
