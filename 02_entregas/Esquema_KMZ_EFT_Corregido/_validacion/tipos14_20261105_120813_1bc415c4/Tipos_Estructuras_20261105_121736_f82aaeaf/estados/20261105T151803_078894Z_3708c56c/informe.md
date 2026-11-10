# Datos_Proyecto: informe de ejecucion

Estado: **PREVALIDADO**

Modo: VALIDAR_TIPOS
Conexion: `C:\Users\aibecker\Desktop\ENGIE PERU\bbdd\02_entregas\Esquema_KMZ_EFT_Corregido\_validacion\tipos14_20261105_120813_1bc415c4\ensayo.gdb`
Modelo SHA256: `5fc138d536e6661e5dd45af296d536a02e917d24215f39f771526dbb3fc04b55`

| Clase | Geometria | Campos definidos | Tipos pendientes | Accion |
|---|---|---:|---:|---|
| estructuras | POINT | 32 | 0 | VALIDADA_PARA_TIPOS |

## Limites

- Cambio exclusivo de siete tipos en una clase vacia. Los 14 atributos TEXT conservan sus longitudes.
- No carga datos ni convierte unidades, coordenadas o marcadores <Null>.
- Los cambios DDL no forman una transaccion atomica. Un error puede dejar tipos parcialmente actualizados; la siguiente ejecucion reconoce los DOUBLE ya aplicados.
