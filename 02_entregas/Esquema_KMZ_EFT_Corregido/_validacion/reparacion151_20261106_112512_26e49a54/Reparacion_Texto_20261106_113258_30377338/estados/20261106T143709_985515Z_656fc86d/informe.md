# Datos_Proyecto: informe de ejecucion

Estado: **TEXTO_LARGO_VERIFICADO**

Modo: REPARAR_TEXTO
Conexion: `C:\Users\aibecker\Desktop\ENGIE PERU\bbdd\02_entregas\Esquema_KMZ_EFT_Corregido\_validacion\reparacion151_20261106_112512_26e49a54\ensayo.gdb`
Modelo SHA256: `3a819d55272930e3bc812ca278a58acfa18adecce61791350d9354af2a5e793d`

| Clase | Geometria | Campos definidos | Tipos pendientes | Accion |
|---|---|---:|---:|---|
| predios_inscritos_en_sunarp_recorte | POLYGON | 81 | 64 | TEXTO_LARGO_VERIFICADO |

## Limites

- Solo sustituye cargas_y_gravamenes en predios SUNARP vacia. No carga datos ni cambia tipos numericos.
- Crea una columna temporal, conserva el original hasta verificar el sustituto y elimina el respaldo vacio.
- El orden fisico de las columnas puede cambiar. No modifica SQL directamente.
- Cerrar uso de la clase e impedir cargas concurrentes durante toda la reparacion.
- Si falla, use el ultimo resultado.json como informe de recuperacion; no borre columnas manualmente.
