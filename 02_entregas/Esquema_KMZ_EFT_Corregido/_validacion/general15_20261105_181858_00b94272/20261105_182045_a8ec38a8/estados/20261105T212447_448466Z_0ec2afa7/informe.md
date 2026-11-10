# Datos_Proyecto: informe de ejecucion

Estado: **CREACION_VERIFICADA**

Modo: CREAR
Conexion: `C:\Users\aibecker\Desktop\ENGIE PERU\bbdd\02_entregas\Esquema_KMZ_EFT_Corregido\_validacion\general15_20261105_181858_00b94272\ensayo.gdb`
Modelo SHA256: `5fc138d536e6661e5dd45af296d536a02e917d24215f39f771526dbb3fc04b55`

| Clase | Geometria | Campos definidos | Tipos pendientes | Accion |
|---|---|---:|---:|---|
| accesos | POLYLINE | 280 | 268 | CREADA_VERIFICADA |
| limite_departamento_recorte | POLYGON | 34 | 19 | CREADA_VERIFICADA |
| predios_inscritos_en_sunarp_recorte | POLYGON | 81 | 66 | CREADA_VERIFICADA |

## Limites

- El catalogo de 76 clases sigue siendo una propuesta funcional, no una aprobacion de INDRA.
- Los atributos marcados pendientes mantienen texto conservador; requieren perfil de valores y unidades antes de cargar.
- Los campos propios no se eliminan por tener nombres parecidos. El informe no certifica la equivalencia de sus valores.
- Esta fase crea clases vacias con GlobalID y auditoria UTC. No carga KMZ, no crea relaciones y no activa branch.
- Las relaciones con proyecto y las relaciones de negocio se validan y crean en una fase posterior.
- DDL ArcGIS no es una transaccion atomica: un fallo puede dejar una clase parcial. Se informa y se detiene, sin borrado automatico.
- TestSchemaLock del contenedor devolvio False; esta comprobacion no es concluyente en el ensayo local. ArcGIS verificara los bloqueos reales durante cada creacion.
