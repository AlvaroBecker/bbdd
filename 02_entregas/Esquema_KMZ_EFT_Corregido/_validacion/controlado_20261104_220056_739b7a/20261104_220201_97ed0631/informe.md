# Datos_Proyecto: informe de ejecucion

Estado: **ERROR_DETENIDO**

Modo: CREAR
Conexion: `C:\Users\aibecker\Desktop\ENGIE PERU\bbdd\02_entregas\Esquema_KMZ_EFT_Corregido\_validacion\controlado_20261104_220056_739b7a\ensayo.gdb`
Modelo SHA256: `3272f5cd016a16982bbb5e2cdfcaaa862bc51614b0426ec01c50ae6d25b2ba66`

| Clase | Geometria | Campos definidos | Tipos pendientes | Accion |
|---|---|---:|---:|---|
| accesos | POLYLINE | 285 | 268 | CREAR |
| estructuras | POINT | 39 | 23 | CREAR |
| red_vial_nacional_mtc_recorte | POLYLINE | 319 | 301 | CREAR |
| subestacion_poligono | POLYGON | 32 | 15 | CREAR |

## Limites

- El catalogo de 76 clases sigue siendo una propuesta funcional, no una aprobacion de INDRA.
- Los atributos marcados pendientes mantienen texto conservador; requieren perfil de valores y unidades antes de cargar.
- Los campos propios no se eliminan por tener nombres parecidos. El informe no certifica la equivalencia de sus valores.
- Esta fase crea clases vacias con GlobalID y auditoria UTC. No carga KMZ, no crea relaciones y no activa branch.
- Las relaciones con proyecto y las relaciones de negocio se validan y crean en una fase posterior.
- DDL ArcGIS no es una transaccion atomica: un fallo puede dejar una clase parcial. Se informa y se detiene, sin borrado automatico.
- TestSchemaLock del contenedor devolvio False; esta comprobacion no es concluyente en el ensayo local. ArcGIS verificara los bloqueos reales durante cada creacion.

## Error

ERROR 160385: Workspace or data source is read only. [GDB_Items]
Failed to execute (EnableEditorTracking).


Se detuvo el lote. Consulte clase_en_curso y completadas en resultado.json. No se borro ningun objeto para deshacer operaciones.
