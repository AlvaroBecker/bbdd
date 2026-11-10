# Corrección 1.3.2: COUNT rechazado por ArcGIS/SDE

La validación del usuario del 5 de noviembre de 2026, 07:07, rechazó
`zonas_de_vida_holdridge_recorte.count` y propuso `count_`. La comprobación
local de 1.3.1 no reprodujo esa restricción del destino SDE. La lista de palabras
reservadas de Transact-SQL no cubre todas las restricciones de ArcGIS/SDE.

Se corrige el nombre físico a **`src_count`**, manteniendo snake_case sin un
guion bajo final. Es el mismo atributo original `COUNT`, presente en tres
ocurrencias del inventario; no se añade un campo ni se elimina información.
El generador y los archivos de equivalencias conservan ese mapeo.

Este es el único campo modificado respecto de 1.3.1. Se mantienen 76 clases,
3.340 definiciones de campos, todos los tipos y las relaciones declaradas.
`estructuras` no cambia. Las correcciones `src_begin` y `src_end` se conservan.

La regla adicional se documenta como restricción observada de ArcGIS/SDE;
no se presenta COUNT como palabra reservada de la lista Transact-SQL utilizada.
La validación agrupada sobre el destino real sigue activa y no altera objetos.

## Actualizar

1. Cerrar ArcGIS Pro.
2. Extraer `Datos_Proyecto_Controlado_v1_3_2.zip` en una carpeta nueva y agregar
   su `Datos_Proyecto.pyt` al volver a abrir Pro.
3. Ejecutar **Validar (sin cambios)** con la selección deseada.
4. Si termina correctamente, ejecutar **Crear clases vacías** con esa selección.

No hace falta borrar objetos por este error: el intento se detuvo durante la
prevalidación. Esta versión no renombra clases existentes ni carga datos.

## Verificación

31 pruebas unitarias y ocho de reglas del inventario. Se incluye una regresión
para COUNT y la conservación del atributo de origen. Los cuatro CSV originales
permanecen sin cambios; se reconcilian las 9.934 ocurrencias y las 3.507 filas
de la matriz. `VALIDACION_NOMBRES_SQLSERVER.json` registra la comprobación nativa
de nombres en una geodatabase local. No acredita el resultado en SQL Server/SDE:
la validación con la conexión real sigue siendo necesaria.
