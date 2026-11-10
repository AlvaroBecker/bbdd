# Correspondencia de restricciones del modelo Mapline

La referencia es el DDL del respaldo original. El destino de estas ocho tablas es ArcGisAWS.gis y el EFT exige branch versioning. Este paquete no crea PK ni FK fisicas de negocio en SQL Server; restaura indices no unicos y prepara reglas de integridad de ArcGIS.

## Identificadores de las ocho tablas

| Tabla | Campo PK original | Tratamiento |
|---|---|---|
| mline_ta_proyecto_estado | id_proyecto_estado | Conservar valores; validar no nulo y unicidad mediante reglas ArcGIS. Sin IDENTITY ni cambios de ID. |
| mline_tc_proyecto | id_proyecto | Conservar valores; validar no nulo y unicidad mediante reglas ArcGIS. Sin IDENTITY ni cambios de ID. |
| mline_td_celda_capa | id_celda_capa | Conservar valores; validar no nulo y unicidad mediante reglas ArcGIS. Sin IDENTITY ni cambios de ID. |
| mline_td_infraestructura_celda | id_infraestructura_celda | Conservar valores; validar no nulo y unicidad mediante reglas ArcGIS. Sin IDENTITY ni cambios de ID. |
| mline_td_proyecto_alternativa | id_proyecto_alternativa | Conservar valores; validar no nulo y unicidad mediante reglas ArcGIS. Sin IDENTITY ni cambios de ID. |
| mline_td_proyecto_capa | id_proyecto_capa | Conservar valores; validar no nulo y unicidad mediante reglas ArcGIS. Sin IDENTITY ni cambios de ID. |
| mline_td_proyecto_componente | id_proyecto_componente | Conservar valores; validar no nulo y unicidad mediante reglas ArcGIS. Sin IDENTITY ni cambios de ID. |
| mline_td_proyecto_regla_cfg | id_proyecto_regla_cfg | Conservar valores; validar no nulo y unicidad mediante reglas ArcGIS. Sin IDENTITY ni cambios de ID. |

Las reglas de unicidad consultan la version/estado visible en ArcGIS. No equivalen a la garantia atomica de una PK fisica SQL ante ediciones concurrentes ni garantizan unicidad entre versiones. La generacion de nuevos ID mediante secuencias y su control de concurrencia debe implementarse antes de habilitar altas en produccion.

## Las 27 relaciones originales salientes

| FK original | Referencia | Tratamiento |
|---|---|---|
| mline_pryctoestdo_prmtro02_fk | mline_ta_proyecto_estado.id_estado_proyecto_inicial → mline_tp_parametro.id_parametro | Dominio y regla de pertenencia con los codigos originales: PROYECTO.ESTADO |
| mline_pryctoestdo_prmtro03_fk | mline_ta_proyecto_estado.id_estado_proyecto_final → mline_tp_parametro.id_parametro | Dominio y regla de pertenencia con los codigos originales: PROYECTO.ESTADO |
| mline_pryctoestdo_prycto01_fk | mline_ta_proyecto_estado.id_proyecto → mline_tc_proyecto.id_proyecto | Reglas ArcGIS de referencia y NO ACTION; sin FK fisica SQL |
| mline_prycto_prmtro01_fk | mline_tc_proyecto.id_tipo_proyecto → mline_tp_parametro.id_parametro | Dominio y regla de pertenencia con los codigos originales: PROYECTO.TIPO |
| mline_prycto_prmtro02_fk | mline_tc_proyecto.id_estado_proyecto → mline_tp_parametro.id_parametro | Dominio y regla de pertenencia con los codigos originales: PROYECTO.ESTADO |
| mline_pryctocldacpa_pryctoclda01_fk | mline_td_celda_capa.id_proyecto_celda → mline_td_proyecto_celda.id_proyecto_celda | Pendiente de la clase espacial padre y su validacion |
| mline_pryctocldacpa_pryctocpa02_fk | mline_td_celda_capa.id_proyecto_capa → mline_td_proyecto_capa.id_proyecto_capa | Reglas ArcGIS de referencia y NO ACTION; sin FK fisica SQL |
| mline_infracapa_pryctoaltrntiva01_fk | mline_td_infraestructura_celda.id_proyecto_infraestructura → mline_td_proyecto_infraestructura.id_proyecto_infraestructura | Pendiente de la clase espacial padre y su validacion |
| mline_infracapa_pryctocel02_fk | mline_td_infraestructura_celda.id_proyecto_celda → mline_td_proyecto_celda.id_proyecto_celda | Pendiente de la clase espacial padre y su validacion |
| mline_pryctoaltrntiva_prmtro04_fk | mline_td_proyecto_alternativa.id_estado_alternativa → mline_tp_parametro.id_parametro | Dominio y regla de pertenencia con los codigos originales: PROYECTO.ALTERNATIVA.ESTADO |
| mline_pryctoaltrntiva_prmtro05_fk | mline_td_proyecto_alternativa.id_tipo_fuente_infraestructura → mline_tp_parametro.id_parametro | Dominio y regla de pertenencia con los codigos originales: PROYECTO.ALTERNATIVA.FUENTE |
| mline_pryctoaltrntiva_pryctoaltrntiva03_fk | mline_td_proyecto_alternativa.id_alternativa_origen → mline_td_proyecto_alternativa.id_proyecto_alternativa | Reglas ArcGIS de referencia y NO ACTION; sin FK fisica SQL |
| mline_pryctoaltrntiva_pryctocmpnnte01_fk | mline_td_proyecto_alternativa.id_proyecto_componente → mline_td_proyecto_componente.id_proyecto_componente | Reglas ArcGIS de referencia y NO ACTION; sin FK fisica SQL |
| mline_pryctoaltrntiva_pryctocpa02_fk | mline_td_proyecto_alternativa.id_proyecto_capa_alternativa → mline_td_proyecto_capa.id_proyecto_capa | Referencia sin uso; debe permanecer NULL segun EFT |
| mline_pryctoaltrntiva_pryctocpa06_fk | mline_td_proyecto_alternativa.id_proyecto_capa_resultante → mline_td_proyecto_capa.id_proyecto_capa | Reglas ArcGIS de referencia y NO ACTION; sin FK fisica SQL |
| mline_pryctocpa_cpa02_fk | mline_td_proyecto_capa.id_capa → mline_tm_capa.id_capa | Pendiente de equivalencia Portal o campo de evaluacion |
| mline_pryctocpa_prycto01_fk | mline_td_proyecto_capa.id_proyecto → mline_tc_proyecto.id_proyecto | Reglas ArcGIS de referencia y NO ACTION; sin FK fisica SQL |
| mline_pryctocmpnnte_prycto01_fk | mline_td_proyecto_componente.id_proyecto → mline_tc_proyecto.id_proyecto | Reglas ArcGIS de referencia y NO ACTION; sin FK fisica SQL |
| mline_pryctocmpnnte_pryctocpa02_fk | mline_td_proyecto_componente.id_proyecto_capa_componente → mline_td_proyecto_capa.id_proyecto_capa | Referencia sin uso; debe permanecer NULL segun EFT |
| mline_td_proyecto_componente_ibfk_1 | mline_td_proyecto_componente.id_proyecto_capa_vertices → mline_td_proyecto_capa.id_proyecto_capa | Referencia sin uso; debe permanecer NULL segun EFT |
| mline_pryctorglacfg_cpaprpiedad04_fk | mline_td_proyecto_regla_cfg.id_capa_propiedad → mline_tm_capa_propiedad.id_capa_propiedad | Pendiente de equivalencia Portal o campo de evaluacion |
| mline_pryctorglacfg_prmtro05_fk | mline_td_proyecto_regla_cfg.id_tipo_funcion_espacial → mline_tp_parametro.id_parametro | Dominio y regla de pertenencia con los codigos originales: PROYECTO.REGLA_CFG.FUNCION_ESPACIAL |
| mline_pryctorglacfg_prmtro07_fk | mline_td_proyecto_regla_cfg.id_valor_ponderacion → mline_tp_parametro.id_parametro | Dominio y regla de pertenencia con los codigos originales: PROYECTO.REGLA_CFG.PONDERACION |
| mline_pryctorglacfg_prycto01_fk | mline_td_proyecto_regla_cfg.id_proyecto → mline_tc_proyecto.id_proyecto | Reglas ArcGIS de referencia y NO ACTION; sin FK fisica SQL |
| mline_pryctorglacfg_pryctocpa02_fk | mline_td_proyecto_regla_cfg.id_proyecto_capa_origen → mline_td_proyecto_capa.id_proyecto_capa | Reglas ArcGIS de referencia y NO ACTION; sin FK fisica SQL |
| mline_pryctorglacfg_pryctocpa06_fk | mline_td_proyecto_regla_cfg.id_proyecto_capa_resultante → mline_td_proyecto_capa.id_proyecto_capa | Reglas ArcGIS de referencia y NO ACTION; sin FK fisica SQL |
| mline_pryctorglacfg_pryctorglacfg03_fk | mline_td_proyecto_regla_cfg.id_proyecto_regla_cfg_origen → mline_td_proyecto_regla_cfg.id_proyecto_regla_cfg | Reglas ArcGIS de referencia y NO ACTION; sin FK fisica SQL |

Las once referencias vigentes entre las ocho tablas incluyen dos autorreferencias. Se comprueba existencia del padre para insercion/actualizacion del hijo y se bloquea borrar o cambiar una clave de padre que todavia tiene hijos. Se permiten FK NULL, como en el DDL. Estas reglas se ejecutan en ArcGIS; un cambio SQL directo las evita. No se crean relationship classes recursivas ni se supone que una relacion SIMPLE equivale por si sola a NO ACTION.

Ademas de los ocho campos con FK fisica hacia parametros, el EFT usa dominios para id_estado_componente e id_estado_regla_cfg. El paquete incluye esos dos consumidores y conserva los codigos historicos.

## Dependencias futuras desde clases espaciales

| Hijo pendiente | Padre actual | Campo |
|---|---|---|
| mline_td_proyecto_area_interes | mline_td_proyecto_componente | id_proyecto_componente |
| mline_td_proyecto_cgeneracion | mline_td_proyecto_componente | id_proyecto_componente |
| mline_td_proyecto_infraestructura | mline_td_proyecto_alternativa | id_proyecto_alternativa |
| mline_td_proyecto_ltransmision | mline_td_proyecto_componente | id_proyecto_componente |

La proteccion de esos padres frente a sus hijos espaciales debe completarse cuando dichas clases esten disponibles. El paquete no declara terminada la integridad del conjunto de 14 objetos.

## Indices secundarios originales

| Tabla | Indice original | Columnas |
|---|---|---|
| mline_ta_proyecto_estado | mline_pryctoestdo_prmtro02_fk | id_estado_proyecto_inicial |
| mline_ta_proyecto_estado | mline_pryctoestdo_prmtro03_fk | id_estado_proyecto_final |
| mline_ta_proyecto_estado | mline_pryctoestdo_prycto01_fk | id_proyecto |
| mline_tc_proyecto | mline_prycto_prmtro01_fk | id_tipo_proyecto |
| mline_tc_proyecto | mline_prycto_prmtro02_fk | id_estado_proyecto |
| mline_td_celda_capa | mline_pryctocldacpa_pryctoclda01_fk | id_proyecto_celda |
| mline_td_celda_capa | mline_pryctocldacpa_pryctocpa02_fk | id_proyecto_capa |
| mline_td_infraestructura_celda | mline_infracapa_pryctoaltrntiva01_fk | id_proyecto_infraestructura |
| mline_td_infraestructura_celda | mline_infracapa_pryctocel02_fk | id_proyecto_celda |
| mline_td_proyecto_alternativa | mline_pryctoaltrntiva_prmtro04_fk | id_estado_alternativa |
| mline_td_proyecto_alternativa | mline_pryctoaltrntiva_prmtro05_fk | id_tipo_fuente_infraestructura |
| mline_td_proyecto_alternativa | mline_pryctoaltrntiva_pryctoaltrntiva03_fk | id_alternativa_origen |
| mline_td_proyecto_alternativa | mline_pryctoaltrntiva_pryctocmpnnte01_fk | id_proyecto_componente |
| mline_td_proyecto_alternativa | mline_pryctoaltrntiva_pryctocpa02_fk | id_proyecto_capa_alternativa |
| mline_td_proyecto_alternativa | mline_pryctoaltrntiva_pryctocpa06_fk | id_proyecto_capa_resultante |
| mline_td_proyecto_capa | mline_pryctocpa_cpa02_fk | id_capa |
| mline_td_proyecto_capa | mline_pryctocpa_prycto01_fk | id_proyecto |
| mline_td_proyecto_componente | mline_pryctcmpnt_pryctcpvrt_fk | id_proyecto_capa_vertices |
| mline_td_proyecto_componente | mline_pryctocmpnnte_prycto01_fk | id_proyecto |
| mline_td_proyecto_componente | mline_pryctocmpnnte_pryctocpa02_fk | id_proyecto_capa_componente |
| mline_td_proyecto_regla_cfg | mline_pryctorglacfg_cpaprpiedad04_fk | id_capa_propiedad |
| mline_td_proyecto_regla_cfg | mline_pryctorglacfg_prmtro05_fk | id_tipo_funcion_espacial |
| mline_td_proyecto_regla_cfg | mline_pryctorglacfg_prmtro07_fk | id_valor_ponderacion |
| mline_td_proyecto_regla_cfg | mline_pryctorglacfg_prycto01_fk | id_proyecto |
| mline_td_proyecto_regla_cfg | mline_pryctorglacfg_pryctocpa02_fk | id_proyecto_capa_origen |
| mline_td_proyecto_regla_cfg | mline_pryctorglacfg_pryctocpa06_fk | id_proyecto_capa_resultante |
| mline_td_proyecto_regla_cfg | mline_pryctorglacfg_pryctorglacfg03_fk | id_proyecto_regla_cfg_origen |

Son 27 definiciones no unicas: las dos de proyectos suelen estar cubiertas por la carga anterior y faltan hasta 25 en las otras tablas. Se comprueba la definicion real antes de crear cada indice para no duplicar coberturas. Se conservan tambien los tres indices sobre referencias obsoletas, sin ocultar su existencia en el origen; esos tres campos estan vacios y pueden no aportar utilidad actual. No se modifican indices de ObjectID, GlobalID ni otros indices de sistema.

## Fuentes

- Respaldo original Mapline_20261030.sql; hash SHA-256 ea9fc0fafa0f0f9cd1688cd4777901f45fbe9db307ee1d2e2272edefca0c63dd.
- EFT, secciones 5.8.4, 5.8.5, 5.8.10 y 5.8.11.
- [Restricciones de branch versioning](https://doc.esri.com/en/arcgis-pro/latest/help/data/geodatabases/overview/register-a-dataset-as-branch-versioned.html).
- [Reglas de restriccion](https://doc.esri.com/en/arcgis-pro/latest/help/data/geodatabases/overview/constraint-attribute-rules.html).
- [Requisitos de Add Attribute Rule](https://doc.esri.com/en/arcgis-pro/latest/tool-reference/data-management/add-attribute-rule.html).
- [Indices de atributos](https://pro.arcgis.com/en/pro-app/3.4/tool-reference/data-management/add-attribute-index.htm).
