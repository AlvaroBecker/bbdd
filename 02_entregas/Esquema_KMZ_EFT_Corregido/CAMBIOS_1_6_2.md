# Datos Proyecto 1.6.2 — reanudar el renombrado

El diagnóstico ejecutado en SQL Server encontró una sola diferencia y ninguna incidencia de lectura: el alias del campo `area` cambió de `GIS.mapa_nacional_de_ecosistemas_minam_recorte.area` a `GIS.mapa_nacional_ecosistemas_minam_recorte.area`. El nombre nuevo de la clase ya estaba aplicado.

La verificación 1.6.2 reconoce ese cambio de calificación: mismo propietario, misma columna y sustitución exacta del nombre anterior por el nombre aprobado de la tabla. No ignora los aliases ni modifica el alias físico del campo. Una diferencia de tipo, longitud, dominio, nulabilidad, valor predeterminado, precisión, escala u otra propiedad continúa deteniendo el proceso. Los aliases reconocidos quedan registrados con sus valores anterior y actual.

## Pasos para esta ejecución detenida

1. Extraer `Datos_Proyecto_Controlado_v1_6_2.zip` en una carpeta nueva y agregar su `Datos_Proyecto.pyt`. La caja muestra **Datos Proyecto - esquema controlado 1.6.2** y las mismas seis herramientas. Reiniciar ArcGIS Pro si mantiene en memoria la versión anterior.
2. Abrir **Normalizar nombres de Datos_Proyecto** (quinta herramienta).
3. Seleccionar la misma conexión `.sde`, mantener las 76 clases, base `ArcGisAWS`, propietario `gis` y una carpeta existente para los informes.
4. En el nuevo parámetro **Informe JSON original para reanudar**, conservar `resultado_origen.json`, incluido en el paquete. Es la copia exacta de la primera ejecución detenida que proporcionaste. No seleccionar aquí el JSON del diagnóstico: tiene otra estructura y finalidad.
5. Ejecutar **Validar (sin cambios)**. Debe terminar en `VALIDACION_OK_SIN_CAMBIOS` y registrar el alias cualificado reconocido. Revisar el informe y el plan de nombres.
6. Con los mismos parámetros y el mismo informe original, ejecutar **Aplicar nombres aprobados**. Reconoce las clases ya renombradas y completa los nombres y aliases de clase pendientes. El resultado esperado es `NOMBRES_VERIFICADOS`.

No es necesario borrar ni recrear clases. Evitar cambios de esquema o cargas concurrentes durante el procedimiento. Si aparece una nueva diferencia, conservar el nuevo informe para revisarla.

## Referencia y alcance

Cuando se proporciona el informe original, la herramienta verifica su conexión, propietario, base, modelo, mapeo y aprobación de tipos. Compara todas las clases seleccionadas contra esa referencia antes de escribir y la conserva durante la ejecución. Las rutas de referencia se guardan separadas del plan que va mostrando el avance.

El parámetro es opcional para trabajos nuevos sin una ejecución anterior. **Para este caso debe mantenerse seleccionado el informe original**. El diagnóstico de la sexta herramienta sigue mostrando las diferencias literales de los aliases, incluso cuando el renombrador ya reconoce esa actualización como compatible; no cambia su criterio para ocultarlas.

Esta versión conserva el modelo de 76 clases y el mapeo 1.6. No carga registros ni cambia campos o tipos. Incluye pruebas automatizadas del alias y de la reanudación, además de un ensayo nativo sobre una geodatabase local con APIs limitadas a lectura. El ensayo local no sustituye la validación sobre tu conexión SQL Server.
