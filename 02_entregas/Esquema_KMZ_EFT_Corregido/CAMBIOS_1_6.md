# Version 1.6: nombres claros para todas las clases de Datos_Proyecto

Se revisaron las 76 clases existentes: **25 cambian de nombre y 51 conservan
su nombre**. Se eliminan los 10 hashes. Las 73 clases nuevas reciben un alias
descriptivo; las 3 clases migradas conservan sus nombres y aliases del modelo
original. El inventario original, los datos KMZ y las 3.340 definiciones de
campos permanecen intactos.

La correspondencia completa esta en `nombres_clases_1_6.csv`. Tambien se
actualizaron el modelo, los catalogos, mapeos por ruta, aprobaciones de tipos y
las herramientas. La version no fusiona clases ni entidades.

## Convencion

- Nombres fisicos en minusculas y snake_case, sin tildes ni hashes.
- Se retiran articulos y preposiciones prescindibles mediante un mapeo
  explicito, sin borrar palabras por una regla indiscriminada.
- Se conservan tema, fuente y geometria cuando distinguen clases.
- Se conserva `_recorte` segun el EFT, normalizado a minusculas.
- Las descripciones originales permanecen completas como evidencia; los
  aliases permiten mostrar nombres legibles en ArcGIS.
- Se conservan los nombres oficiales del DDL migrado, los campos de sistema
  y los feature datasets del EFT. Las capas oficiales externas futuras no
  forman parte de este renombrado.

El antiguo limite de 50 caracteres era una decision del generador. Los
nombres finales tienen hasta 55 caracteres y se validan en el workspace real.
Las relaciones futuras con proyectos usan nombres declarados `rel_proy_...`
de hasta 64 caracteres; esta herramienta no crea ni cambia relaciones.

## Orden de ejecucion para las 76 clases que ya creaste

1. Extrae `Datos_Proyecto_Controlado_v1_6.zip` completo en una carpeta nueva.
   Reinicia ArcGIS Pro y agrega el `Datos_Proyecto.pyt` de esa carpeta.
2. Cierra las tablas y vistas que usen las clases. Evita ediciones o cargas
   concurrentes durante el procedimiento.
3. Abre **Normalizar nombres de Datos_Proyecto**. Conserva las 76 clases
   seleccionadas; el selector muestra los nombres finales y la herramienta
   busca tanto los nombres anteriores como los ya aplicados.
4. Indica tu misma conexion `.sde`, base `ArcGisAWS`, propietario `gis` y
   una carpeta local existente para los informes. Ejecuta
   **Validar (sin cambios)**. El estado esperado es
   `VALIDACION_OK_SIN_CAMBIOS`. Revisa `plan_nombres.csv` del informe.
5. Ejecuta **Aplicar nombres aprobados** con los mismos parametros. Debe
   terminar en **NOMBRES_VERIFICADOS**. Conserve el informe JSON.
6. Si sigue pendiente el texto largo, usa **Reparar texto largo de predios**
   de este paquete: primero **Validar (sin cambios)** y despues
   **Reparar campo vacio aprobado**. Ahora trabaja sobre
   `predios_inscritos_sunarp_recorte`. Si ya estaba reparado, lo reconoce
   y no repite la sustitucion. Estado esperado: `TEXTO_LARGO_VERIFICADO`.
7. En **Actualizar campos aprobados de Datos_Proyecto**, conserva las 42 clases,
   valida y ejecuta **Aplicar actualizacion aprobada**. Reconoce los tipos
   pendientes o ya aplicados y usa los nombres nuevos. Estado esperado:
   `CAMPOS_VERIFICADOS`.
8. Finalmente, en **Validar o crear clases en Datos_Proyecto**, selecciona
   las 76 clases y ejecuta **Validar (sin cambios)**. Estado esperado:
   `VALIDACION_OK_SIN_CAMBIOS`. Se mantienen **2.086 definiciones de campos
   con tipo provisional**, cuya revision sigue pendiente antes de cargar.

Tras renombrar, usa las herramientas 1.6. Las versiones anteriores conservan
referencias a los nombres antiguos. Los mapas, servicios o consultas externas
que usen esos nombres deben actualizar sus referencias. El cambio de nombre
se realiza mediante ArcGIS, con la conexion propietaria; no mediante SQL DDL.

## Protecciones y reanudacion

La herramienta exige clases existentes, vacias, sin versionado y sin
dependencias incompatibles. Valida todo el lote antes de escribir y vuelve a
verificar cada clase. Compara campos, indices, geometria, GlobalID y auditoria
UTC antes y despues. Si existen simultaneamente el nombre anterior y el nuevo,
se detiene: no fusiona, borra ni reemplaza clases.

Si se interrumpe **Normalizar nombres**, conserva el informe y vuelve a
validar/aplicar la misma seleccion: reconoce los nombres y aliases ya
aplicados. No requiere un JSON de recuperacion como entrada. El renombrado de
un lote no es una transaccion unica.

Si una reparacion de texto 1.5.1 quedo interrumpida con campos temporales,
completala primero con esa version y su ultimo JSON. El renombrado no acepta
columnas temporales fuera del modelo. El JSON de esa reparacion no se reutiliza
en 1.6 porque esta ligado al modelo y al nombre anteriores.

## Comprobaciones y alcance

- `VALIDACION_NOMBRES_1_6_ESTATICA.json`: cobertura de 76 clases, eliminacion
  de hashes, ausencia de colisiones, preservacion de 3.340 campos y repeticion
  identica de la generacion.
- `VALIDACION_UNITARIA_1_6.json`: pruebas de errores, colisiones, dependencias,
  recuperacion parcial, nombres SQL antiguos/nuevos y proteccion contra crear
  duplicados desde el toolbox o los scripts por clase.
- `VALIDACION_NOMBRES_1_6_ARCGIS.json`: validacion nativa de los 76 nombres y
  las relaciones propuestas; renombrado y aliases sobre 3 clases de una copia
  local, reejecucion sin escrituras y compatibilidad de las herramientas de
  texto/tipos con los nombres nuevos.

No se ha conectado a SQL Server del equipo CT6788. El ensayo local no certifica
SDE: las comprobaciones de nombres, permisos y NVARCHAR(MAX), cuando corresponde,
se ejecutan en tu destino al usar la herramienta. Los informes de versiones
anteriores incluidos en el paquete son antecedentes, no pruebas del modelo 10.

Referencias oficiales: [Rename](https://doc.esri.com/en/arcgis-pro/latest/tool-reference/data-management/rename.html),
[AlterAliasName](https://doc.esri.com/en/arcgis-pro/latest/arcpy/functions/alteraliasname.html).
