# Datos Proyecto 1.6.1

El diagnóstico se integra como **sexta herramienta de `Datos_Proyecto.pyt`**, con el nombre **Diagnosticar renombrado (solo lectura)**. Las cinco herramientas anteriores conservan su funcionamiento y sus parámetros. El esquema, el mapeo de nombres y las aprobaciones de tipos siguen siendo los de 1.6.

## Qué ejecutar ahora

1. Extraer `Datos_Proyecto_Controlado_v1_6_1.zip` en una carpeta nueva del equipo donde está la conexión SQL Server.
2. Cerrar el panel de la herramienta anterior y agregar el nuevo `Datos_Proyecto.pyt`. La caja debe mostrar **Datos Proyecto - esquema controlado 1.6.1** y seis herramientas. Si ArcGIS Pro conserva la versión anterior en memoria, reiniciar Pro y abrir la caja nueva.
3. Abrir **Diagnosticar renombrado (solo lectura)**.
4. Elegir la misma conexión `.sde` utilizada para renombrar. Mantener `ArcGisAWS` y `gis` como base de datos y propietario.
5. Conservar `resultado_origen.json` como informe original. El paquete incluye una copia exacta del JSON que proporcionaste, correspondiente al fallo en `mapa_nacional_ecosistemas_minam_recorte`.
6. Elegir una carpeta existente para los informes y ejecutar.
7. Revisar y compartir el `resultado.json` y `diferencias.csv` generados antes de volver a aplicar el renombrado.

El diagnóstico no tiene selector de aplicar: solo consulta la geodatabase y escribe los informes en una carpeta nueva. Conserva el estado previo del JSON como referencia, incluidos los aliases de campo. Consulta las 76 clases del informe, empezando por la clase donde se detuvo el proceso.

## Estado del problema

El informe original confirma 44 clases verificadas y el cambio de nombre ya aplicado a `mapa_nacional_ecosistemas_minam_recorte`. El alias anterior de su campo `area` incluía el nombre antiguo de la tabla; es una posible explicación pendiente de comprobar con la lectura actual. Esta versión añade el diagnóstico, **no da por resuelta esa discrepancia**.

No repetir todavía **Aplicar nombres aprobados**: la comparación debe conservar como referencia la primera ejecución. No hace falta borrar ni recrear las clases.

## Resultados y pruebas

- `DIFERENCIAS_DETECTADAS`: las propiedades actuales difieren de las guardadas en el informe original; el CSV detalla los valores anterior y actual.
- `SIN_DIFERENCIAS_ACTUALES`: no hay diferencias ahora en lo comparado; no explica por sí solo un fallo transitorio anterior.
- `DIAGNOSTICO_INCOMPLETO`: no se pudo consultar alguna clase o sección; revisar las incidencias del JSON.

La entrega incluye pruebas automatizadas de la comparación y de la integración en la misma toolbox, más un ensayo nativo de la sexta herramienta en ArcGIS Pro con una geodatabase local existente y APIs limitadas a lectura. Los informes de validación 1.6 y anteriores se conservan como antecedentes de los componentes que no cambiaron. No se ha probado esta integración contra la conexión SQL Server del equipo CT6788.
