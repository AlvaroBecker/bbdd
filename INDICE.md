# Mapline: índice de la carpeta bbdd

## Organización

| Carpeta | Contenido |
|---|---|
| [01_fuentes](01_fuentes/) | Dump MySQL original, rutinas, nueve KMZ de proyecto e inventario recibido de ArcGIS |
| [02_entregas](02_entregas/) | Paquetes de carga SQL Server, restricciones, preparación KMZ, caja ArcGIS y ZIP para compartir |
| [03_scripts](03_scripts/) | Generadores y validadores locales; sus rutas se adaptaron a esta organización |
| [04_documentacion](04_documentacion/) | Plan de extracción y revisión de la exportación |
| [99_historico](99_historico/) | Entregas reemplazadas; no usar para la ejecución actual |

El documento [EFT v2.4](<EFT - ENGIE Mapline ArcGIS Enterprise y ArcGIS Pro_v2.4.docx>) y la carpeta [outputs](outputs/) permanecen en la raíz porque Windows los tenía en uso. Se acordó no moverlos por ahora. No se cerraron procesos ni se eliminaron fuentes.

Los informes e inventarios históricos conservan las rutas que tenían al generarse. No se reescribieron esos datos de auditoría. Los ZIP existentes se movieron sin modificar su contenido.

## Entrega actual: KMZ a ArcGIS/SDE

- [Caja de herramientas Mapline_KMZ_SDE.pyt](02_entregas/KMZ_EFT/carga_sde/Mapline_KMZ_SDE.pyt).
- [Paquete completo para la máquina destino](02_entregas/Mapline_KMZ_Carga_SDE_gis.zip).
- [Instrucciones para agregar la caja y cargar](02_entregas/KMZ_EFT/carga_sde/LEEME.md).
- [Validación local de la entrega](02_entregas/KMZ_EFT/carga_sde/VALIDACION_LOCAL.json).

La caja crea objetos neutrales nuevos en `ArcGisAWS`, esquema `gis`, conserva lo ambiguo y documenta pendientes para ENGIE. El ZIP no incluye los KMZ originales. La copia junto al organizador en `InformaciónMapline` no se modificó con este ordenamiento.

## Fuentes y mapeo KMZ

- [KMZ originales de proyecto](01_fuentes/kmz/).
- [Inventario recibido de ArcGIS](01_fuentes/inventario_ArcGIS_20261103_114443/).
- [Inventario y preparación EFT](02_entregas/KMZ_EFT/LEEME.md).
- [Primer mapeo en Excel](outputs/mapline_kmz_20261103_v1/Mapeo_KMZ_EFT_propuesta_v1.xlsx).
- [Guía del mapeo](02_entregas/KMZ_EFT/mapeo_v1/LEEME.md).
- [Prueba PLS-CADD de Jaén Norte](02_entregas/KMZ_EFT/mapeo_v1/PRUEBA_PLS_CADD_JAENNORTE.md).
- [Inventario comprimido para compartir](02_entregas/Mapline_KMZ_Inventario_EFT.zip).

## Entregas SQL Server

### Esquema KMZ revisado por tema y ruta

- [Versión actual 1.5](02_entregas/Datos_Proyecto_Controlado_v1_5.zip): tipos aprobados de estructuras y actualización controlada de siete campos. [Instrucciones](02_entregas/Esquema_KMZ_EFT_Corregido/CAMBIOS_1_5.md).


- [Histórico: versión 1.3 de Datos_Proyecto](02_entregas/Datos_Proyecto_Controlado_v1_3.zip): nombres normalizados y equivalencias respaldadas por los CSV. [Cambios y límites](02_entregas/Esquema_KMZ_EFT_Corregido/NORMALIZACION_EFT.md).


- [Histórico: versión 1.2 de Datos_Proyecto](02_entregas/Datos_Proyecto_Controlado_v1_2.zip): sin extensiones propias, con campos comunes según el ámbito del EFT. [Detalle de la revisión](02_entregas/Esquema_KMZ_EFT_Corregido/REVISION_CAMPOS_EFT.md).

- [Herramienta para el Datos_Proyecto existente](02_entregas/Esquema_KMZ_EFT_Corregido/GUIA_DATOS_PROYECTO.md) y [ZIP portable](02_entregas/Datos_Proyecto_Controlado.zip): validación previa y creación por selección desde ArcGIS Pro.

- [Paquete corregido](02_entregas/Esquema_KMZ_EFT_Corregido.zip): consolidación temática, recortes y clases migradas, sin carga en SDE.
- [Instrucciones y límites](02_entregas/Esquema_KMZ_EFT_Corregido/LEEME.md).
- [Comparación con las 124 clases anteriores](02_entregas/Esquema_KMZ_EFT_Corregido/cambios_respecto_csv.csv).
- [Catálogo corregido](02_entregas/Esquema_KMZ_EFT_Corregido/catalogo_clases.csv).
- [Reglas reproducibles](03_scripts/reglas_kmz_eft_corregido.py).


- [Carga de origen ArcGisAWS](02_entregas/ArcGisAWS_Carga_Mapline/LEEME.md) y [ZIP](02_entregas/ArcGisAWS_Carga_Mapline.zip).
- [Siete tablas EFT, versión 2](02_entregas/Mapline_7_tablas_EFT_gis_v2.sql), [instrucciones](02_entregas/Mapline_7_tablas_EFT_gis_v2_LEEME.md) y [ZIP](02_entregas/Mapline_7_tablas_EFT_gis_v2.zip).
- [Carga individual de mline_tc_proyecto](02_entregas/Mapline_una_tabla_mline_tc_proyecto_SQLServer.sql).
- [Restricciones PK/FK e índices](02_entregas/ArcGisAWS_Restricciones_EFT_MySQL/LEEME.md) y [ZIP](02_entregas/Mapline_PK_FK_SQLServer_EFT.zip).
- [SQL verificado fechado](02_entregas/03_agregar_PK_FK_VERIFICADO_20261103T125354Z.sql).

## Referencias y herramientas

- [Dump MySQL original](01_fuentes/Mapline_20261030.sql).
- [Rutinas MySQL: no ejecutar en SQL Server](01_fuentes/Mapline_20261030_Rutinas_MySQL_NO_EJECUTAR_EN_SQLServer.sql).
- [Plan de extracción y modelo](04_documentacion/Plan_extraccion_Mapline_modelo_datos.md).
- [Revisión de exportación](04_documentacion/Revision_exportacion_Mapline.json).
- [Generadores y validadores](03_scripts/): no regenerar entregas para ordenar archivos; ejecutarlos únicamente cuando se necesite una nueva generación o validación.
