# Corrección 1.3.3: verificación de nombres de campos calificados

El lote del usuario llegó a crear varias clases y se detuvo al verificar
`centros_poblados_inei_recorte`, indicando que faltaba `area`. El esquema y el
mapeo original incluyen ese atributo. El error por sí solo no demuestra si el
campo falta físicamente o si ArcGIS lo presenta con un nombre calificado.

Se encontró y corrigió un defecto del verificador: comparaba `Field.name`
directamente con el nombre simple del modelo. Esri documenta que ciertos campos,
entre ellos AREA, pueden aparecer con prefijos de base, esquema y tabla en
geodatabases empresariales. `Field.baseName` proporciona el nombre sin prefijos.

Ahora se usa `baseName` en las comprobaciones de existencia, nombres exactos,
campos adicionales y claves. Se siguen comprobando tipos, longitudes, nulabilidad
y dominios. Dos columnas con el mismo nombre base producen un error de ambigüedad.
`Shape_Area` no sustituye a `area`. Las mayúsculas incompatibles siguen señalándose.

**No cambia ningún nombre, campo, tipo ni relación del esquema 1.3.2.**
No se agrega `src_area`, no se renombra una columna y no se modifica una clase
existente. La huella de `esquema.json` permanece idéntica.

Si un campo realmente falta, la herramienta se detiene y muestra los nombres
completos y nombres base observados para diagnosticar la diferencia.

## Retomar el trabajo

1. Conservar las clases ya creadas y el feature dataset. No borrar el lote.
2. Cerrar ArcGIS Pro y extraer `Datos_Proyecto_Controlado_v1_3_3.zip` en una carpeta
   nueva. Agregar su `Datos_Proyecto.pyt`; la caja indica 1.3.3.
3. Ejecutar **Validar (sin cambios)** seleccionando solamente
   `centros_poblados_inei_recorte`.
4. Si pasa, validar la selección original completa y luego ejecutar **Crear
   clases vacías** con esa selección. Las clases existentes compatibles se
   conservan; se crean las faltantes.
5. Si sigue faltando `area` u otro campo, conservar el nuevo informe. Se necesita
   revisar los campos observados antes de decidir cómo completar el objeto.

La hipótesis del nombre calificado debe confirmarse en la conexión real. La
actualización corrige el defecto demostrado del código, sin afirmar que se haya
inspeccionado la clase remota ni que todas las clases del lote estén completas.

## Pruebas

38 pruebas unitarias y ocho de reglas del inventario. Siete regresiones nuevas
cubren nombres calificados, mayúsculas, tipos/longitudes/nulabilidad/dominios,
campos realmente ausentes, duplicados y columnas extra. Se conserva el cotejo de
nombres local; no equivale a una validación en SDE.

Fuentes: [propiedades de clases de entidad de Esri](https://doc.esri.com/en/arcgis-pro/latest/help/data/geodatabases/overview/defining-feature-class-properties.html)
y [propiedad baseName de Field](https://doc.esri.com/en/arcgis-pro/latest/arcpy/classes/field.html).
