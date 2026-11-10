# Datos_Proyecto: informe de ejecucion

Estado: **VALIDACION_OK_SIN_CAMBIOS**

Modo: VALIDAR_NOMBRES
Conexion: `C:\Users\aibecker\Desktop\ENGIE PERU\bbdd\02_entregas\Esquema_KMZ_EFT_Corregido\_validacion\nombres16_20261106_131939_941b5a72\ensayo.gdb`
Modelo SHA256: `2f2a1348d6d5d45379a75f5fd857f215fce3873829261119b8185916b7a4217c`

| Clase | Geometria | Campos definidos | Tipos pendientes | Accion |
|---|---|---:|---:|---|
| accesos | POLYLINE | 280 | 267 | VALIDACION_OK_SIN_CAMBIOS |
| limite_departamento_recorte | POLYGON | 34 | 18 | VALIDACION_OK_SIN_CAMBIOS |
| predios_inscritos_sunarp_recorte | POLYGON | 81 | 64 | VALIDACION_OK_SIN_CAMBIOS |

## Limites

- Solo renombra clases existentes y ajusta aliases aprobados; no cambia columnas ni carga datos.
- Cerrar el uso de las clases e impedir cargas concurrentes durante el procedimiento.
- Un error detiene el lote sin deshacer nombres ya aplicados; reejecutar reconoce el estado actual.
- El renombrado no actualiza automaticamente referencias de mapas, servicios o consultas externas.
