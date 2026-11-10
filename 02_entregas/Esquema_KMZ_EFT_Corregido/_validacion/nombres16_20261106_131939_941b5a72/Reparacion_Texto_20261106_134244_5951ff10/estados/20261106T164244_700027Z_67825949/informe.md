# Datos_Proyecto: informe de ejecucion

Estado: **INICIADO**

Modo: REPARAR_TEXTO
Conexion: `C:\Users\aibecker\Desktop\ENGIE PERU\bbdd\02_entregas\Esquema_KMZ_EFT_Corregido\_validacion\nombres16_20261106_131939_941b5a72\ensayo.gdb`
Modelo SHA256: `2f2a1348d6d5d45379a75f5fd857f215fce3873829261119b8185916b7a4217c`

| Clase | Geometria | Campos definidos | Tipos pendientes | Accion |
|---|---|---:|---:|---|
| predios_inscritos_sunarp_recorte | POLYGON | 81 | 64 | POR_VALIDAR |

## Limites

- Solo sustituye cargas_y_gravamenes en predios SUNARP vacia. No carga datos ni cambia tipos numericos.
- Crea una columna temporal, conserva el original hasta verificar el sustituto y elimina el respaldo vacio.
- El orden fisico de las columnas puede cambiar. No modifica SQL directamente.
- Cerrar uso de la clase e impedir cargas concurrentes durante toda la reparacion.
- Si falla, use el ultimo resultado.json como informe de recuperacion; no borre columnas manualmente.
