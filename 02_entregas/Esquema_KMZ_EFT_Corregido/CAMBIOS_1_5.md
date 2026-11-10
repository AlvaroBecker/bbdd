# Versión 1.5: segunda actualización de campos de Datos_Proyecto

**Version vigente: 1.5.1.** Para el fallo de texto largo en SQL Server, siga primero [CAMBIOS_1_5_1.md](CAMBIOS_1_5_1.md). Incluye una reparacion especifica y reanudacion del lote 1.5. Las instrucciones de versiones anteriores que siguen son antecedentes.

El perfil completo de los 13 KMZ respaldó este lote: **99 operaciones en
42 clases**, sin agregar columnas ni cambiar nombres o geometrías.

| Cambio | Cantidad |
|---|---:|
| TEXT a DOUBLE | 97 campos |
| TEXT a LONG | 1 campo: `limite_departamento_recorte.poblacion` |
| Ampliación TEXT de 4.000 a 10.000 | 1 campo: `predios_inscritos_en_sunarp_recorte.cargas_y_gravamenes` |

La ampliación cubre los 8.084 caracteres observados con margen. Se mantienen
los cambios de `estructuras` de 1.4, las 76 clases y sus nombres actuales.
El modelo pasa a versión 9; quedan **2.086 definiciones de campos provisionales**.
Los códigos, las fechas ambiguas y los otros atributos pendientes conservan TEXT.
No se convierten unidades, coordenadas ni valores durante este cambio de esquema.

`plan_actualizacion_1_5.csv` enumera las 99 operaciones. La configuración y la
evidencia están en `campos_aprobados_1_5.json` y `PERFIL_GENERAL_ORIGEN.json`.

## Ejecutar en ArcGIS Pro

1. Cerrar Pro y extraer `Datos_Proyecto_Controlado_v1_5.zip` en una carpeta nueva.
   Agregar su `Datos_Proyecto.pyt`; la caja indica **1.5**.
2. Abrir **Actualizar campos aprobados de Datos_Proyecto**. Esta es la tercera
   herramienta de la caja. Mantener las 42 clases preseleccionadas para el lote
   completo, o elegir un subconjunto si se prefiere avanzar por grupos.
3. Usar la conexión SDE habitual, base `ArcGisAWS`, propietario `gis` y una
   carpeta local de informes. Ejecutar **Validar (sin cambios)**.
4. Revisar `plan.csv` y `resultado.json`. El plan indica tipos/longitudes reales,
   objetivo, cambios pendientes y campos ya actualizados.
5. Si la validación pasa, elegir **Aplicar actualizacion aprobada** y ejecutar
   con la misma selección. El estado final esperado es **CAMPOS_VERIFICADOS**.
6. Una vez completadas las 42 clases, ejecutar el validador general de las
   76 clases en **Validar (sin cambios)**. El resultado esperado es
   **VALIDACION_OK_SIN_CAMBIOS**, con 2.086 tipos provisionales restantes.

Si se trabaja por grupos, validar después únicamente las clases terminadas.
El validador general del modelo 1.5 rechazará los tipos anteriores de los grupos
todavía no migrados. Esto no requiere borrar ni recrear clases.

## Controles de la actualización

Antes de escribir se valida el lote completo: conexión y propietario, dataset,
existencia de cada clase, geometría y referencia, campos, GlobalID, auditoría UTC,
tabla padre, cero registros y ausencia de versionado. Se admiten exclusivamente
TEXT(4000) anterior o el tipo/longitud objetivo ya aplicado. Una longitud intermedia,
un tercer tipo, un índice dependiente, un default o dominio incompatibles bloquean
el lote. No se modifican campos requeridos.

Antes de cada escritura se vuelven a comprobar cero registros, bloqueo de esquema
en la clase y conservación de sus campos e índices. Después se comprueba el tipo
o capacidad y las propiedades restantes. Los informes son estados inmutables.

En SQL Server, la ampliación también consulta metadatos de `sys.columns` y
`sys.types`: exige NVARCHAR antes y NVARCHAR(MAX) después. Son consultas SELECT;
la escritura la realiza `AlterField` de ArcGIS. Si el campo usa VARCHAR o no se
pueden verificar los metadatos, se detiene para revisión. La capacidad física MAX
puede mostrarse con un tamaño superior a los 10.000 solicitados.

Los cambios DDL no son una transacción atómica. Ante un fallo se registra
`clase_en_curso`, `campo_en_curso`, `completadas` y el estado observado. Al repetir,
los tipos y longitudes ya actualizados se conservan; no se borra ni reconstruye
la clase para forzar la migración. Si hay bloqueos, cerrar vistas y procesos que
usen las clases antes de volver a validar.

## Oficinas registrales: decisión de carga pendiente

En 288 predios de FELAM/PARIÑAS hay dos etiquetas `OFICINA REGISTRAL` en la misma
tabla HTML. La primera está entre `PARTIDA REGISTRAL` y `ANTECEDENTE REGISTRAL`;
la segunda, entre `PARTIDA JURÍDICA` y `JUNTA DIRECTIVA`. En 253 entidades difieren;
en otras 35 coinciden. No hay nombres físicos originales en Schema/ExtendedData
que permitan recuperar una distinción inequívoca.

El contexto sugiere dos oficinas de partidas diferentes, pero no se toma esa
interpretación como definición oficial. Se necesita un mapeo explícito de ambas
ocurrencias antes de cargar esas rutas. No se descarta `No aplica`, no se elige
primer/último valor y no se concatenan valores sin estructura. Este lote 1.5 no
agrega columnas para resolverlo ni carga datos. El diagnóstico aparte conserva
las 288 entidades y ejemplos de su contexto HTML.

## Pruebas y alcance

Las pruebas unitarias cubren el lote, selección, guardas, conservación, errores
parciales, reanudación y comprobaciones SQL Unicode/MAX. El ensayo ArcGIS utiliza
una copia local aislada y **tres clases representativas**, con cuatro operaciones
que cubren DOUBLE, LONG y ampliación TEXT. No se presenta como ensayo de las
99 operaciones en SDE. El detalle está en `VALIDACION_ACTUALIZACION_1_5_ARCGIS.json`.

Fuentes técnicas: [Alter Field](https://doc.esri.com/en/arcgis-pro/latest/tool-reference/data-management/alter-field-properties.html),
[tipos SQL Server admitidos por ArcGIS](https://doc.esri.com/en/arcgis-pro/latest/help/data/geodatabases/manage-sql-server/data-types-sqlserver.html)
y [sys.columns de Microsoft](https://learn.microsoft.com/en-us/sql/relational-databases/system-catalog-views/sys-columns-transact-sql).
