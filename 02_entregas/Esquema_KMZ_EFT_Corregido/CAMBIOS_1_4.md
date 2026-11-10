# Versión 1.4: tipos aprobados de estructuras

El usuario aprobó confirmar los tipos de los 21 atributos propios de
`estructuras`, después del perfil de 11.579 elementos en 76 rutas de seis KMZ.
El cambio físico afecta exclusivamente siete campos, de TEXT a DOUBLE:
`este`, `norte`, `east`, `north`, `x`, `y` y `vano`.

Los otros 14 conservan TEXT y longitud 4.000. No se reducen longitudes ni se
agregan campos. Se conservan las 76 clases y los nombres actuales, incluidos
los sufijos con hash. `estructuras` sigue teniendo 32 campos del modelo y
39 físicos. Sus 21 atributos dejan de figurar con tipo provisional; quedan
2.185 definiciones provisionales en las demás clases.

La evidencia y la autorización están en `tipos_estructuras_aprobados.json` y
`decision_tipos_estructuras.csv`. Las unidades y el datum no se convierten.
Los marcadores literales `<Null>` no se limpian durante este cambio de esquema.

## Ejecutar en ArcGIS Pro

1. Cerrar ArcGIS Pro y extraer `Datos_Proyecto_Controlado_v1_4.zip` en una carpeta
   nueva. Agregar el `Datos_Proyecto.pyt` de esa carpeta. La caja indica **1.4**.
2. Abrir la herramienta nueva **Actualizar tipos de estructuras**. Esta fase usa
   esa herramienta, porque la clase existente conserva los tipos TEXT anteriores.
3. Indicar la conexión SDE habitual, base `ArcGisAWS`, propietario `gis`, una
   carpeta de informes local y **Validar (sin cambios)**. No hay selección de
   otras clases: el alcance está fijado a `estructuras`.
4. Revisar el plan de los siete campos. La validación requiere clase vacía,
   sin versionar, con estructura y auditoría compatibles. Si se informa falta de
   bloqueo, cerrar vistas de campos/tablas y otros usos de `estructuras`.
5. Elegir **Aplicar tipos aprobados** y ejecutar. El resultado esperado es
   **TIPOS_VERIFICADOS**. La herramienta registra las propiedades antes/después.
6. Volver a **Validar o crear clases en Datos_Proyecto**, seleccionar `estructuras`
   y ejecutar **Validar (sin cambios)**. Debe informar cero tipos provisionales
   para esta clase y aceptar los siete DOUBLE.

La versión 1.4 del modelo y la herramienta de actualización se distribuyen
juntas. Antes de aplicar, el validador general señalará como incompatibles los
siete TEXT antiguos: eso no se resuelve recreando las clases.

## Comprobaciones durante el cambio

- Conexión, propietario, dataset, geometría, Z/M, GlobalID, auditoría UTC y tabla
  padre real se validan mediante las comprobaciones existentes.
- Solo se admiten TEXT del esquema anterior o DOUBLE ya aplicado en esos siete
  campos. Un tercer tipo, campos ausentes o cambios ajenos bloquean la operación.
- La clase debe tener cero registros, también antes de cada modificación.
- Se requiere bloqueo de esquema en la clase concreta para cada cambio. La
  comprobación previa no garantiza que otro proceso no adquiera un bloqueo después.
- No se alteran campos requeridos ni candidatos con dominios, defaults o índices
  dependientes que requieran revisión adicional.
- Tras cada `AlterField` se verifica el tipo y la conservación de nombres,
  alias, nulabilidad, dominios, defaults y campos ajenos.

Los siete cambios no son una transacción atómica. Si una operación falla, se
detiene y se conserva el informe con `campo_en_curso`, `completadas` y el estado
observado. Al repetir, reconoce los campos ya DOUBLE y continúa los TEXT
pendientes. No borra ni reconstruye la clase para forzar la migración.

## Alcance de las pruebas

Las pruebas unitarias cubren validación sin escrituras, clase poblada, bloqueos,
tipos y propiedades incompatibles, preservación, fallos parciales y reanudación.
El ensayo nativo usa exclusivamente una copia aislada de una geodatabase local;
su resultado está en `VALIDACION_TIPOS_ESTRUCTURAS_ARCGIS.json`.
No certifica permisos ni comportamiento en la conexión SDE del usuario.

Fuentes técnicas: [Alter Field de Esri](https://doc.esri.com/en/arcgis-pro/latest/tool-reference/data-management/alter-field-properties.html)
y [TestSchemaLock](https://doc.esri.com/en/arcgis-pro/latest/arcpy/functions/testschemalock.html).
