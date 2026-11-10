# Diagnóstico de renombrado 1.6 — solo lectura

Esta entrega compara la geodatabase actual con los campos e índices guardados **antes** del renombrado. Sirve para investigar el error «Se modificaron campos durante el renombrado». No sustituye la toolbox 1.6 ni corrige automáticamente diferencias.

## Lo que confirma el informe recibido

La ejecución del 6 de noviembre de 2026 se detuvo en `mapa_nacional_ecosistemas_minam_recorte`, después de ejecutar `Rename`. El inventario guardado al detenerse encuentra el nombre nuevo y no encuentra `mapa_nacional_de_ecosistemas_minam_recorte`. Hay 44 clases marcadas como verificadas.

El campo `area` tenía el alias `GIS.mapa_nacional_de_ecosistemas_minam_recorte.area`. Es una pista de un posible cambio de alias al renombrar la tabla, **no una causa confirmada**. El informe anterior no guardó las propiedades observadas después del error.

La comparación conserva todas las propiedades originales, incluidos los aliases. No ignora diferencias de tipo, longitud, dominio, valor predeterminado, nulabilidad, precisión, escala, geometría o auditoría.

## Ejecución en ArcGIS Pro

1. Extraer `Diagnostico_Renombrado_1_6.zip` en una carpeta nueva del equipo donde se ejecutó el renombrado. Conservar juntos todos sus archivos.
2. Agregar `Diagnostico_Renombrado.pyt` a las cajas de herramientas del proyecto.
3. Abrir **Comparar con el informe original de renombrado**.
4. En **Conexión .sde / geodatabase de la ejecución original**, elegir:

   ```text
   C:\Users\CT6788\Documents\ArcGIS\Projects\MyProject\SQLServer-EEPAWSDBP01-ArcGisAWS(gis).sde
   ```

5. En **Resultado JSON original del renombrado**, dejar `resultado_origen.json`. Es una copia exacta del archivo que proporcionaste. También se puede seleccionar el `resultado.json` original de la ejecución fallida, siempre que sea el mismo informe.
6. Mantener **Base de datos esperada = ArcGisAWS** y **Propietario esperado = gis**. Elegir una carpeta existente para los informes.
7. Ejecutar. La herramienta consulta todas las clases del informe original y crea una carpeta nueva con el diagnóstico JSON, un CSV de diferencias y un informe de lectura.
8. Revisar primero las diferencias de `mapa_nacional_ecosistemas_minam_recorte` y compartir el diagnóstico generado para resolver la discrepancia antes de volver a aplicar el renombrado.

Durante la lectura, evitar ejecutar otras herramientas que cambien el esquema o carguen datos. No hace falta borrar ni recrear las clases.

## Interpretación

- `DIFERENCIAS_DETECTADAS`: se pudo comparar, pero hay diferencias exactas respecto del estado original. El CSV identifica clase, campo, propiedad y valor anterior/actual.
- `SIN_DIFERENCIAS_ACTUALES`: no se observan diferencias ahora en las propiedades comparadas. No demuestra qué ocurrió en el momento del fallo ni autoriza por sí solo a reanudar.
- `DIAGNOSTICO_INCOMPLETO`: alguna clase o sección no pudo leerse. El JSON conserva los resultados obtenidos y los errores de lectura.

Los nombres y aliases de **clase** se presentan como avance de la migración, separados de las propiedades de los **campos**: el cambio de alias de clase estaba previsto. El recuento se contrasta con cero porque la prevalidación 1.6 exigía clases vacías; ese recuento original no fue guardado como dato independiente en el informe.

No ejecutar nuevamente «Aplicar nombres aprobados» hasta revisar este diagnóstico: la 1.6 toma una nueva referencia de los campos al empezar, por lo que una repetición podría ocultar la diferencia respecto de la primera ejecución.

## Alcance y verificación

La herramienta solo consulta metadatos y recuentos. No ejecuta renombrados, cambios de campos, cargas ni SQL de modificación. Sus únicas escrituras son los archivos del diagnóstico en la carpeta elegida. Verifica que el modelo, el mapeo, la aprobación de tipos y el destino correspondan al informe original.

Se incluyen evidencias de pruebas automatizadas y un ensayo con ArcGIS Pro sobre una geodatabase local existente, con las APIs disponibles limitadas a lectura. La conexión SQL Server del equipo CT6788 no está disponible en el equipo de desarrollo; la comparación real debe ejecutarse allí.

La documentación de Esri diferencia el [renombrado de un dataset y su alias](https://doc.esri.com/en/arcgis-pro/latest/tool-reference/data-management/rename.html) de las [propiedades de cada campo](https://doc.esri.com/en/arcgis-pro/latest/arcpy/classes/field.html). Esa documentación no permite concluir por sí sola qué propiedad provocó este fallo.
