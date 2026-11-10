# Correccion 1.5.1: texto largo en SQL Server

**Version vigente: 1.6.** Se revisaron las 76 clases: 25 renombres y 51 nombres conservados; sin hashes. Siga primero [CAMBIOS_1_6.md](CAMBIOS_1_6.md) y consulte [el mapeo completo](nombres_clases_1_6.csv). Las indicaciones de versiones anteriores que siguen son antecedentes.

Esta version corrige el fallo 001624/003644 al intentar ampliar
`predios_inscritos_en_sunarp_recorte.cargas_y_gravamenes` mediante AlterField.
El objetivo sigue siendo conservar texto de al menos 10.000 caracteres. El
perfil KMZ contiene un valor de 8.084: reducir la longitud a 8.000 no sirve.
El modelo, los 76 nombres de clase y los 99 cambios aprobados de 1.5 se conservan.

## Que cambia

Se agrega **Reparar texto largo de predios**, una herramienta independiente y
limitada a ese campo. La accion predeterminada es de solo lectura.

Al ejecutar **Reparar campo vacio aprobado**, comprueba destino, clase vacia,
GlobalID, auditoria UTC, esquema, indices, bloqueos y ausencia de dependencias
incompatibles. Crea un campo temporal con AddField y longitud 10.000. En SDE
comprueba directamente que SQL Server lo almacene como **NVARCHAR(MAX)** antes
de tocar el original. Conserva el original renombrado como respaldo hasta
verificar el nuevo campo bajo su nombre definitivo; entonces retira el respaldo
vacio. Usa exclusivamente herramientas ArcGIS para los cambios. Las consultas
SQL son SELECT de metadatos.

El campo conserva nombre, alias y nulabilidad. Su posicion fisica puede pasar
al final de la tabla. No se cambia ninguna clase ni se cargan registros; al
terminar no quedan columnas adicionales. Rechaza clases con filas, versionado,
relaciones, reglas de atributos, subtipos u otras dependencias detectadas que
requieran un procedimiento distinto. Cierre el uso de la clase y evite cargas
concurrentes durante la reparacion.

La herramienta general deja de intentar AlterField(10000) sobre un campo SDE
todavia de 4.000: indica que se ejecute primero esta reparacion y detiene la
aplicacion antes de modificar el lote.

## Pasos para el error de la version 1.5

1. Extraiga `Datos_Proyecto_Controlado_v1_5_1.zip` completo en una carpeta nueva.
   Reinicie ArcGIS Pro y agregue el `Datos_Proyecto.pyt` de esa carpeta.
2. Abra **Reparar texto largo de predios**. Use la misma conexion `.sde`, base
   `ArcGisAWS`, propietario `gis` y una carpeta local existente para informes.
   Deje vacio **JSON de reparacion interrumpida**: el informe del error de 1.5
   no es un informe de esta reparacion.
3. Ejecute **Validar (sin cambios)**. Debe terminar en
   `VALIDACION_OK_SIN_CAMBIOS`. Esta validacion comprueba las condiciones previas;
   la capacidad de la columna nueva se comprobara cuando se cree.
4. Con los mismos parametros ejecute **Reparar campo vacio aprobado**. El estado
   final esperado es `TEXTO_LARGO_VERIFICADO`. Conserve el informe JSON.
5. Abra **Actualizar campos aprobados de Datos_Proyecto**, seleccione las
   42 clases del lote y ejecute **Validar (sin cambios)**, seguido de
   **Aplicar actualizacion aprobada**. La herramienta reconoce los tipos ya
   aplicados y el texto reparado. El estado final esperado es `CAMPOS_VERIFICADOS`.
   Los 69 aplicados / 30 pendientes del mensaje anterior eran el conteo al inicio
   de aquella ejecucion; el nuevo informe determinara cuantos faltan ahora.
6. En **Validar o crear clases en Datos_Proyecto**, seleccione las 76 clases y
   ejecute **Validar (sin cambios)**. Debe terminar en `VALIDACION_OK_SIN_CAMBIOS`.
   Seguiran existiendo 2.086 definiciones de campos con tipo provisional; esta
   reparacion no cierra esa revision ni autoriza cargar los KMZ.

## Si se interrumpe la reparacion

No borre columnas ni clases. Conserve el ultimo `resultado.json` de
**Reparar texto largo de predios** y seleccionelo en **JSON de reparacion
interrumpida** al volver a ejecutar esa misma herramienta. Valide primero y
despues aplique. Se cotejan conexion, modelo, aprobacion, campos, indices y
etapa. Solo se reconocen estados previstos; un cambio ajeno detiene la ejecucion.
Las operaciones de esquema no son una transaccion unica. Si el campo temporal
se crea con almacenamiento o capacidad incorrectos, el original se conserva
y la herramienta se detiene para revision: ese estado no se recupera
automaticamente ni se elimina el temporal sin revisar el informe.

## Evidencia y limites

`VALIDACION_UNITARIA_1_5_1.json` registra las pruebas, incluidas interrupciones
antes y despues de cada paso y reanudacion. `VALIDACION_REPARACION_1_5_1_ARCGIS.json`
registra el ensayo nativo en una copia local de una GDB de archivos, la
preservacion de otras columnas, GlobalID, auditoria e indices, y una prueba de
lectura/escritura de 8.084 caracteres con tildes en una tabla de ensayo separada.
No tenemos acceso a la conexion SDE del equipo CT6788: **el ensayo local no
certifica SQL Server**. La comprobacion real de NVARCHAR(MAX) se hace durante
la ejecucion en ese equipo, antes de sustituir el campo original.

Referencias oficiales:

- [Tipos SQL Server admitidos por ArcGIS](https://doc.esri.com/en/arcgis-pro/latest/help/data/geodatabases/manage-sql-server/data-types-sqlserver.html):
  creacion de TEXT de 4.001 caracteres o mas como NVARCHAR(MAX) cuando
  UNICODE_STRING es TRUE.
- [Add Field](https://doc.esri.com/en/arcgis-pro/latest/tool-reference/data-management/add-field.html).
- [Alter Field](https://doc.esri.com/en/arcgis-pro/latest/tool-reference/data-management/alter-field-properties.html).

Los informes de 1.5 y versiones anteriores se incluyen como antecedentes y no
deben interpretarse como pruebas de esta nueva reparacion.
