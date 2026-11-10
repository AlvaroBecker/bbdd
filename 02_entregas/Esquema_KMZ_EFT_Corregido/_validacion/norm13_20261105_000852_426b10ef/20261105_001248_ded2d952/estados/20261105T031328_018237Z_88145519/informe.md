# Datos_Proyecto: informe de ejecucion

Estado: **ERROR_DETENIDO**

Modo: CREAR
Conexion: `C:\Users\aibecker\Desktop\ENGIE PERU\bbdd\02_entregas\Esquema_KMZ_EFT_Corregido\_validacion\norm13_20261105_000852_426b10ef\ensayo.gdb`
Modelo SHA256: `4a59ddab285a4cf142185aeff8a93137b4ac3bbae08b1d3bf20340782bf33dba`

| Clase | Geometria | Campos definidos | Tipos pendientes | Accion |
|---|---|---:|---:|---|
| estructuras | POINT | 32 | 21 | CREAR |

## Limites

- El catalogo de 76 clases sigue siendo una propuesta funcional, no una aprobacion de INDRA.
- Los atributos marcados pendientes mantienen texto conservador; requieren perfil de valores y unidades antes de cargar.
- Los campos propios no se eliminan por tener nombres parecidos. El informe no certifica la equivalencia de sus valores.
- Esta fase crea clases vacias con GlobalID y auditoria UTC. No carga KMZ, no crea relaciones y no activa branch.
- Las relaciones con proyecto y las relaciones de negocio se validan y crean en una fase posterior.
- DDL ArcGIS no es una transaccion atomica: un fallo puede dejar una clase parcial. Se informa y se detiene, sin borrado automatico.
- TestSchemaLock del contenedor devolvio False; esta comprobacion no es concluyente en el ensayo local. ArcGIS verificara los bloqueos reales durante cada creacion.

## Error

ERROR 000112: Domain does not exist.
Failed to execute (AddCodedValueToDomain).

La comprobacion posterior tampoco confirma la clase completa: Dominio dom_fuente: faltan valores o sus descripciones difieren.

Se detuvo el lote. Consulte clase_en_curso y completadas en resultado.json. No se borro ningun objeto para deshacer operaciones.
