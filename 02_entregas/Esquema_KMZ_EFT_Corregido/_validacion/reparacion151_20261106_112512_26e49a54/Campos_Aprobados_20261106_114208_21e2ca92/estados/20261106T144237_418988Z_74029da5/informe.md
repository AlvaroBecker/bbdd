# Datos_Proyecto: informe de ejecucion

Estado: **PREVALIDADO**

Modo: APLICAR_CAMPOS
Conexion: `C:\Users\aibecker\Desktop\ENGIE PERU\bbdd\02_entregas\Esquema_KMZ_EFT_Corregido\_validacion\reparacion151_20261106_112512_26e49a54\ensayo.gdb`
Modelo SHA256: `3a819d55272930e3bc812ca278a58acfa18adecce61791350d9354af2a5e793d`

| Clase | Geometria | Campos definidos | Tipos pendientes | Accion |
|---|---|---:|---:|---|
| accesos | POLYLINE | 280 | 267 | VALIDADA_PARA_CAMPOS |
| limite_departamento_recorte | POLYGON | 34 | 18 | VALIDADA_PARA_CAMPOS |
| predios_inscritos_en_sunarp_recorte | POLYGON | 81 | 64 | VALIDADA_PARA_CAMPOS |

## Limites

- Solo se alteran campos aprobados en clases existentes y vacias de Datos_Proyecto.
- No carga datos, convierte valores o unidades, crea relaciones ni activa versionado.
- DDL no es una transaccion atomica. Un error detiene el lote sin borrar ni recrear objetos; la siguiente ejecucion reconoce tipos y longitudes objetivo ya aplicados.
