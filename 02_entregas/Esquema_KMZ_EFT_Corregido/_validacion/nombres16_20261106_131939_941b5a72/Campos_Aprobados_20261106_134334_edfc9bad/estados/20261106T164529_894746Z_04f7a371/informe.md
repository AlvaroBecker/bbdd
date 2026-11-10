# Datos_Proyecto: informe de ejecucion

Estado: **CAMPOS_VERIFICADOS**

Modo: APLICAR_CAMPOS
Conexion: `C:\Users\aibecker\Desktop\ENGIE PERU\bbdd\02_entregas\Esquema_KMZ_EFT_Corregido\_validacion\nombres16_20261106_131939_941b5a72\ensayo.gdb`
Modelo SHA256: `2f2a1348d6d5d45379a75f5fd857f215fce3873829261119b8185916b7a4217c`

| Clase | Geometria | Campos definidos | Tipos pendientes | Accion |
|---|---|---:|---:|---|
| accesos | POLYLINE | 280 | 267 | CAMPOS_VERIFICADOS |
| limite_departamento_recorte | POLYGON | 34 | 18 | CAMPOS_VERIFICADOS |
| predios_inscritos_sunarp_recorte | POLYGON | 81 | 64 | CAMPOS_VERIFICADOS |

## Limites

- Solo se alteran campos aprobados en clases existentes y vacias de Datos_Proyecto.
- No carga datos, convierte valores o unidades, crea relaciones ni activa versionado.
- DDL no es una transaccion atomica. Un error detiene el lote sin borrar ni recrear objetos; la siguiente ejecucion reconoce tipos y longitudes objetivo ya aplicados.
