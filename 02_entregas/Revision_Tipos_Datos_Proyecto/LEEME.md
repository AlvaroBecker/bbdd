# Revisión de tipos de las otras clases de Datos_Proyecto

El perfil usa los 13 KMZ originales de `01_fuentes`, incluidos los cuatro G1 de
la raíz y los nueve proyectos de `01_fuentes/kmz`. Se limita a las 75 clases
distintas de `estructuras` y al mapeo vigente del modelo 1.4.

Se revisan 2.185 definiciones provisionales en 961 rutas, con 127.725
asignaciones de geometría esperadas y observadas. No se deduplican copias por
proyecto ni se incluyen rutas cuyo destino sigue sin resolver.

## Archivos

- `revision_2185_campos.csv`: propuesta por clase y campo, cobertura, valores,
  rangos, longitudes completas, ceros iniciales y cuestiones pendientes.
- `cambios_tipos_candidatos.csv`: subconjunto de candidatos numéricos para
  revisar antes de preparar una actualización de esquema.
- `resumen_75_clases.csv`: resultados agrupados por clase.
- `cobertura_rutas.csv`: comparación con cada grupo del inventario.
- `incidencias.csv`: valores múltiples no vacíos que convergen en un campo y
  atributos no mapeados, si aparecen.
- `resultado.json`: fuentes y huellas SHA-256, balances y límites del perfil.

Las propuestas no son tipos aprobados. Los códigos y etiquetas conservan su
tratamiento textual aunque contengan números. Las fechas se revisan por contexto;
no se aplica una interpretación global día/mes o mes/día. Los ejemplos del informe
se limitan a 250 caracteres, pero las longitudes se miden sobre valores completos.
Las cabeceras HTML «Field Name / Field Value» se reconocen como cabeceras cuando
no hay un atributo inventariado con ese nombre.

## Casos que deben resolverse antes de cargar

`predios_inscritos_en_sunarp_recorte.cargas_y_gravamenes` llega a 8.084 caracteres,
frente a los 4.000 actuales. Debe definirse y comprobarse una ampliación compatible
con la geodatabase. El perfil no recorta ni carga ese contenido.

En la misma clase, 253 registros de FELAM/PARIÑAS contienen dos valores distintos
bajo la etiqueta original `OFICINA REGISTRAL`, por ejemplo «Chiclayo» y «No aplica».
El perfil conserva el conflicto; no elige un valor para sobrescribir el otro.

También corresponde confirmar unidades/significado de algunos rangos observados,
como `canales_recorte.fin_altitud`, `canales_recorte.caudal_oper` y
`uso_actual_de_la_tierra_recorte.src_area_ha`. El carácter numérico no demuestra
por sí solo que los valores tengan unidades o contenido correctos.

Este análisis no modifica SDE, `esquema.json`, los KMZ ni los CSV de inventario.
La herramienta 1.4 sigue siendo la versión vigente para creación/validación y
la actualización ya aplicada a `estructuras`.
