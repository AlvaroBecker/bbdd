# Corrección 1.3.1: nombres reservados en SQL Server

La prevalidación en la conexión del usuario rechazó
`mline_td_proyecto_infraestructura.begin`. El esquema 1.3 comprobaba snake_case
pero no excluía previamente las palabras reservadas de Transact-SQL.
La comprobación final de ArcGIS sí detectó el problema antes de crear objetos.

Se revisó el catálogo completo: 76 clases y 3.340 definiciones de campos.
Dos nombres coinciden con las palabras reservadas actuales de SQL Server:

| Clase | Nombre 1.3 | Nombre 1.3.1 |
|---|---|---|
| `mline_td_proyecto_infraestructura` | `begin` | `src_begin` |
| `mline_td_proyecto_infraestructura` | `end` | `src_end` |

Son los mismos atributos originales del KMZ, con un nombre físico admisible.
No son campos adicionales ni una nueva exigencia del EFT. El prefijo evita la
palabra reservada y mantiene snake_case. Se actualizan el generador, el esquema,
los mapeos por ruta y las equivalencias. No cambia el número de clases o campos,
los tipos ni las relaciones declaradas. `estructuras` permanece sin cambios.

La prevalidación usa `ValidateTableName` y `ValidateFieldName` con el workspace
real y ahora reúne todos los nombres incompatibles del lote en un solo error,
incluyendo la propuesta de ArcGIS. No aplica renombrados automáticos en la base.

## Actualización

1. Cerrar el panel de la herramienta y reiniciar ArcGIS Pro para descargar los
   módulos de Python de la versión anterior.
2. Extraer `Datos_Proyecto_Controlado_v1_3_1.zip` en una carpeta nueva.
3. Agregar el `Datos_Proyecto.pyt` de esa carpeta.
4. Ejecutar **Validar (sin cambios)** con las clases que se desean crear.
5. Si la validación termina correctamente, ejecutar **Crear clases vacías**
   con la misma selección.

Conservar `Datos_Proyecto` y la tabla real de proyectos. Este error no requiere
borrar más objetos. La herramienta no migra clases existentes ni carga datos.

## Verificación y límites

Pasaron 30 pruebas unitarias y ocho pruebas de reglas del inventario. Se conserva
la cobertura de las 9.934 ocurrencias de atributos y de las 3.507 filas de la matriz.
`VALIDACION_NOMBRES_SQLSERVER.json` registra el cotejo estático de palabras
reservadas y la validación nativa de nombres en una geodatabase local. No es una
prueba contra SQL Server/SDE; la validación con la conexión del usuario continúa
siendo necesaria. Los informes nativos de 1.3 y anteriores son históricos.

La lista implementada corresponde a palabras reservadas actuales de Transact-SQL;
no trata las listas de ODBC ni de palabras futuras como prohibiciones actuales.
La validación de ArcGIS sobre el destino real se mantiene como comprobación final.

Fuentes técnicas: [palabras reservadas de Microsoft SQL Server](https://learn.microsoft.com/en-us/sql/t-sql/language-elements/reserved-keywords-transact-sql)
y [ValidateFieldName de Esri](https://doc.esri.com/en/arcgis-pro/latest/arcpy/functions/validatefieldname.html).
