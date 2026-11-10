# Configuracion del catalogo de proyectos 1.12

Estado: **CONFIGURACION_PROYECTO_VERIFICADA**.

Se preservan las filas, IDs, codigos y fechas de auditoria heredadas. No se registra ningun proyecto.
La auditoria UTC propuesta usa created_user, created_date, last_edited_user y last_edited_date. Son campos administrados por ArcGIS, no nombres expresamente ordenados por el EFT. Se requiere aprobacion para esta decision de implementacion.

Dominios completos: tipo 7/8 y estado 3/4/5/6. No se sustituye un dominio incompatible.

Las operaciones de esquema son pasos independientes, no una transaccion con rollback automatico. El diario documenta el ultimo paso intentado/verificado; una repeticion revisa el estado real.

Despues de CONFIGURACION_PROYECTO_VERIFICADA, repetir Registrar proyectos faltantes: Validar altas y luego Crear proyectos faltantes durante la ventana sin otros escritores.

Error: 

```json
{
  "tabla": "C:\\Users\\aibecker\\Desktop\\ENGIE PERU\\bbdd\\02_entregas\\Esquema_KMZ_EFT_Corregido\\_validacion\\configuracion112_20261109_175230_b75b819bc5cf\\ensayo.gdb\\mline_tc_proyecto",
  "registros": 40,
  "operaciones": [],
  "dominios": [
    {
      "campo": "id_tipo_proyecto",
      "nombre": "mline_proyecto_tipo",
      "codigos": {
        "7": "Central de Generación",
        "8": "Línea de Transmisión"
      }
    },
    {
      "campo": "id_estado_proyecto",
      "nombre": "mline_proyecto_estado",
      "codigos": {
        "3": "Registrado",
        "4": "Con malla",
        "5": "Finalizado",
        "6": "Cancelado"
      }
    }
  ],
  "tracking_previamente_activo": true,
  "campos_auditoria_propuestos": [
    {
      "nombre": "created_user",
      "tipo": "TEXT",
      "longitud": 255
    },
    {
      "nombre": "created_date",
      "tipo": "DATE",
      "longitud": null
    },
    {
      "nombre": "last_edited_user",
      "tipo": "TEXT",
      "longitud": 255
    },
    {
      "nombre": "last_edited_date",
      "tipo": "DATE",
      "longitud": null
    }
  ],
  "requiere_aprobacion_auditoria": false,
  "zona_historica_acreditada": false,
  "conversion_fechas_historicas": false,
  "metadata_destino": {
    "tabla": "C:\\Users\\aibecker\\Desktop\\ENGIE PERU\\bbdd\\02_entregas\\Esquema_KMZ_EFT_Corregido\\_validacion\\configuracion112_20261109_175230_b75b819bc5cf\\ensayo.gdb\\mline_tc_proyecto",
    "geodatabase_remota": false,
    "versionada": false,
    "editor_tracking": true,
    "campos_auditoria": {
      "creatorFieldName": "created_user",
      "createdAtFieldName": "created_date",
      "editorFieldName": "last_edited_user",
      "editedAtFieldName": "last_edited_date"
    },
    "dominios": [
      {
        "campo": "id_tipo_proyecto",
        "dominio": "mline_proyecto_tipo",
        "codigo": 8,
        "etiqueta": "Línea de Transmisión"
      },
      {
        "campo": "id_estado_proyecto",
        "dominio": "mline_proyecto_estado",
        "codigo": 3,
        "etiqueta": "Registrado"
      }
    ],
    "relaciones_observadas": [],
    "incidencias": []
  }
}
```
