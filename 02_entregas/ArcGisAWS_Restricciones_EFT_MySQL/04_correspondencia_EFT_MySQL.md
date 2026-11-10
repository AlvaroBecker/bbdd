# Correspondencia de las restricciones: EFT y MySQL

Selección: ocho tablas tabulares ya cargadas en `ArcGisAWS.gis`. El dump aporta las definiciones originales; el EFT determina qué objetos migran y qué referencias se retiran o reemplazan. Esri se consulta únicamente para la compatibilidad técnica.

**Aplicación actual:** ocho PK físicas y once FK físicas entre estas ocho tablas, si continúan sin versionado ni archivado. Las PK impedirán activar branch mientras existan. Este paquete no deja resuelto el estado final branch del EFT.

No hay `AUTO_INCREMENT` en estas ocho tablas del dump. Una PK no convierte su ID en autoincremental. No se crean `IDENTITY`, secuencias ni generadores de IDs.

## Ocho claves primarias

Todas son de una columna `INT NOT NULL`. Se agregan como `PRIMARY KEY NONCLUSTERED`, para conservar la organización clustered que pueda administrar ArcGIS. El nombre `PK_<tabla>` es el nombre técnico para SQL Server; MySQL llama `PRIMARY` a cada una.

| Tabla | Clave de MySQL | Restricción SQL prevista |
|---|---|---|
| `mline_ta_proyecto_estado` | `id_proyecto_estado` | `PK_mline_ta_proyecto_estado` |
| `mline_tc_proyecto` | `id_proyecto` | `PK_mline_tc_proyecto` |
| `mline_td_celda_capa` | `id_celda_capa` | `PK_mline_td_celda_capa` |
| `mline_td_infraestructura_celda` | `id_infraestructura_celda` | `PK_mline_td_infraestructura_celda` |
| `mline_td_proyecto_alternativa` | `id_proyecto_alternativa` | `PK_mline_td_proyecto_alternativa` |
| `mline_td_proyecto_capa` | `id_proyecto_capa` | `PK_mline_td_proyecto_capa` |
| `mline_td_proyecto_componente` | `id_proyecto_componente` | `PK_mline_td_proyecto_componente` |
| `mline_td_proyecto_regla_cfg` | `id_proyecto_regla_cfg` | `PK_mline_td_proyecto_regla_cfg` |

Si ya existe una PK equivalente se conserva. Si la PK actual está sobre ObjectID u otra clave, el script se detiene antes de hacer cambios: SQL Server permite una sola PK por tabla y no se autoriza eliminar la existente.

## Las 27 FK originales, una por una

Las once que se crean conservan la nulabilidad de las columnas, comprueban los datos existentes (`WITH CHECK`) y usan `NO ACTION` al borrar o actualizar. Eso conserva el comportamiento restrictivo de las FK de origen, que no declaran cascadas.

| FK del dump | Hija.campo | Padre.campo | Tratamiento de este paquete |
|---|---|---|---|
| `mline_infracapa_pryctoaltrntiva01_fk` | `mline_td_infraestructura_celda.id_proyecto_infraestructura` | `mline_td_proyecto_infraestructura.id_proyecto_infraestructura` | Pendiente de la clase espacial padre y su clave; no crear FK a un objeto todavía no integrado. |
| `mline_infracapa_pryctocel02_fk` | `mline_td_infraestructura_celda.id_proyecto_celda` | `mline_td_proyecto_celda.id_proyecto_celda` | Pendiente de la clase espacial padre y su clave; no crear FK a un objeto todavía no integrado. |
| `mline_prycto_prmtro01_fk` | `mline_tc_proyecto.id_tipo_proyecto` | `mline_tp_parametro.id_parametro` | Pendiente de dominios conforme EFT 5.8.11; no crear tabla de parámetros para recuperar esta FK. |
| `mline_prycto_prmtro02_fk` | `mline_tc_proyecto.id_estado_proyecto` | `mline_tp_parametro.id_parametro` | Pendiente de dominios conforme EFT 5.8.11; no crear tabla de parámetros para recuperar esta FK. |
| `mline_pryctoaltrntiva_prmtro04_fk` | `mline_td_proyecto_alternativa.id_estado_alternativa` | `mline_tp_parametro.id_parametro` | Pendiente de dominios conforme EFT 5.8.11; no crear tabla de parámetros para recuperar esta FK. |
| `mline_pryctoaltrntiva_prmtro05_fk` | `mline_td_proyecto_alternativa.id_tipo_fuente_infraestructura` | `mline_tp_parametro.id_parametro` | Pendiente de dominios conforme EFT 5.8.11; no crear tabla de parámetros para recuperar esta FK. |
| `mline_pryctoaltrntiva_pryctoaltrntiva03_fk` | `mline_td_proyecto_alternativa.id_alternativa_origen` | `mline_td_proyecto_alternativa.id_proyecto_alternativa` | Crear FK SQL (o conservar equivalente habilitada/confiable). |
| `mline_pryctoaltrntiva_pryctocmpnnte01_fk` | `mline_td_proyecto_alternativa.id_proyecto_componente` | `mline_td_proyecto_componente.id_proyecto_componente` | Crear FK SQL (o conservar equivalente habilitada/confiable). |
| `mline_pryctoaltrntiva_pryctocpa02_fk` | `mline_td_proyecto_alternativa.id_proyecto_capa_alternativa` | `mline_td_proyecto_capa.id_proyecto_capa` | No recrear: referencia retirada por EFT 5.8.4; conservar campo, sin cambiar datos. |
| `mline_pryctoaltrntiva_pryctocpa06_fk` | `mline_td_proyecto_alternativa.id_proyecto_capa_resultante` | `mline_td_proyecto_capa.id_proyecto_capa` | Crear FK SQL (o conservar equivalente habilitada/confiable). |
| `mline_pryctocldacpa_pryctoclda01_fk` | `mline_td_celda_capa.id_proyecto_celda` | `mline_td_proyecto_celda.id_proyecto_celda` | Pendiente de la clase espacial padre y su clave; no crear FK a un objeto todavía no integrado. |
| `mline_pryctocldacpa_pryctocpa02_fk` | `mline_td_celda_capa.id_proyecto_capa` | `mline_td_proyecto_capa.id_proyecto_capa` | Crear FK SQL (o conservar equivalente habilitada/confiable). |
| `mline_pryctocmpnnte_prycto01_fk` | `mline_td_proyecto_componente.id_proyecto` | `mline_tc_proyecto.id_proyecto` | Crear FK SQL (o conservar equivalente habilitada/confiable). |
| `mline_pryctocmpnnte_pryctocpa02_fk` | `mline_td_proyecto_componente.id_proyecto_capa_componente` | `mline_td_proyecto_capa.id_proyecto_capa` | No recrear: referencia retirada por EFT 5.8.4; conservar campo, sin cambiar datos. |
| `mline_pryctocpa_cpa02_fk` | `mline_td_proyecto_capa.id_capa` | `mline_tm_capa.id_capa` | Pendiente de equivalencia Portal/campo conforme EFT; no inventar padre sustituto. |
| `mline_pryctocpa_prycto01_fk` | `mline_td_proyecto_capa.id_proyecto` | `mline_tc_proyecto.id_proyecto` | Crear FK SQL (o conservar equivalente habilitada/confiable). |
| `mline_pryctoestdo_prmtro02_fk` | `mline_ta_proyecto_estado.id_estado_proyecto_inicial` | `mline_tp_parametro.id_parametro` | Pendiente de dominios conforme EFT 5.8.11; no crear tabla de parámetros para recuperar esta FK. |
| `mline_pryctoestdo_prmtro03_fk` | `mline_ta_proyecto_estado.id_estado_proyecto_final` | `mline_tp_parametro.id_parametro` | Pendiente de dominios conforme EFT 5.8.11; no crear tabla de parámetros para recuperar esta FK. |
| `mline_pryctoestdo_prycto01_fk` | `mline_ta_proyecto_estado.id_proyecto` | `mline_tc_proyecto.id_proyecto` | Crear FK SQL (o conservar equivalente habilitada/confiable). |
| `mline_pryctorglacfg_cpaprpiedad04_fk` | `mline_td_proyecto_regla_cfg.id_capa_propiedad` | `mline_tm_capa_propiedad.id_capa_propiedad` | Pendiente de equivalencia Portal/campo conforme EFT; no inventar padre sustituto. |
| `mline_pryctorglacfg_prmtro05_fk` | `mline_td_proyecto_regla_cfg.id_tipo_funcion_espacial` | `mline_tp_parametro.id_parametro` | Pendiente de dominios conforme EFT 5.8.11; no crear tabla de parámetros para recuperar esta FK. |
| `mline_pryctorglacfg_prmtro07_fk` | `mline_td_proyecto_regla_cfg.id_valor_ponderacion` | `mline_tp_parametro.id_parametro` | Pendiente de dominios conforme EFT 5.8.11; no crear tabla de parámetros para recuperar esta FK. |
| `mline_pryctorglacfg_prycto01_fk` | `mline_td_proyecto_regla_cfg.id_proyecto` | `mline_tc_proyecto.id_proyecto` | Crear FK SQL (o conservar equivalente habilitada/confiable). |
| `mline_pryctorglacfg_pryctocpa02_fk` | `mline_td_proyecto_regla_cfg.id_proyecto_capa_origen` | `mline_td_proyecto_capa.id_proyecto_capa` | Crear FK SQL (o conservar equivalente habilitada/confiable). |
| `mline_pryctorglacfg_pryctocpa06_fk` | `mline_td_proyecto_regla_cfg.id_proyecto_capa_resultante` | `mline_td_proyecto_capa.id_proyecto_capa` | Crear FK SQL (o conservar equivalente habilitada/confiable). |
| `mline_pryctorglacfg_pryctorglacfg03_fk` | `mline_td_proyecto_regla_cfg.id_proyecto_regla_cfg_origen` | `mline_td_proyecto_regla_cfg.id_proyecto_regla_cfg` | Crear FK SQL (o conservar equivalente habilitada/confiable). |
| `mline_td_proyecto_componente_ibfk_1` | `mline_td_proyecto_componente.id_proyecto_capa_vertices` | `mline_td_proyecto_capa.id_proyecto_capa` | No recrear: referencia retirada por EFT 5.8.4; conservar campo, sin cambiar datos. |

De las once FK SQL, dos son autorreferencias: `mline_td_proyecto_alternativa.id_alternativa_origen` y `mline_td_proyecto_regla_cfg.id_proyecto_regla_cfg_origen`. SQL Server sí permite estas FK; se mantienen como relaciones a la propia tabla, sin cascada.

Los campos `id_estado_componente` e `id_estado_regla_cfg` aparecen en el mapeo de dominios del EFT, pero no tienen FK física en el dump. No se les inventan FK nuevas.

Los cuatro vínculos entrantes desde las futuras clases espaciales quedan fuera de este paso. No se agrega ninguna FK para ellos sin cargar y comprobar esas clases.

## Los 27 índices secundarios originales

El archivo `02_restaurar_indices_no_unicos.sql` conserva las columnas y nombres originales; crea únicamente los que falten y omite una cobertura equivalente. **Estos índices no son PK ni FK y no imponen unicidad.** Las PK del archivo 03 son restricciones distintas.

| Tabla | Índice de MySQL | Columnas |
|---|---|---|
| `mline_ta_proyecto_estado` | `mline_pryctoestdo_prmtro02_fk` | `id_estado_proyecto_inicial` |
| `mline_ta_proyecto_estado` | `mline_pryctoestdo_prmtro03_fk` | `id_estado_proyecto_final` |
| `mline_ta_proyecto_estado` | `mline_pryctoestdo_prycto01_fk` | `id_proyecto` |
| `mline_tc_proyecto` | `mline_prycto_prmtro01_fk` | `id_tipo_proyecto` |
| `mline_tc_proyecto` | `mline_prycto_prmtro02_fk` | `id_estado_proyecto` |
| `mline_td_celda_capa` | `mline_pryctocldacpa_pryctoclda01_fk` | `id_proyecto_celda` |
| `mline_td_celda_capa` | `mline_pryctocldacpa_pryctocpa02_fk` | `id_proyecto_capa` |
| `mline_td_infraestructura_celda` | `mline_infracapa_pryctoaltrntiva01_fk` | `id_proyecto_infraestructura` |
| `mline_td_infraestructura_celda` | `mline_infracapa_pryctocel02_fk` | `id_proyecto_celda` |
| `mline_td_proyecto_alternativa` | `mline_pryctoaltrntiva_prmtro04_fk` | `id_estado_alternativa` |
| `mline_td_proyecto_alternativa` | `mline_pryctoaltrntiva_prmtro05_fk` | `id_tipo_fuente_infraestructura` |
| `mline_td_proyecto_alternativa` | `mline_pryctoaltrntiva_pryctoaltrntiva03_fk` | `id_alternativa_origen` |
| `mline_td_proyecto_alternativa` | `mline_pryctoaltrntiva_pryctocmpnnte01_fk` | `id_proyecto_componente` |
| `mline_td_proyecto_alternativa` | `mline_pryctoaltrntiva_pryctocpa02_fk` | `id_proyecto_capa_alternativa` |
| `mline_td_proyecto_alternativa` | `mline_pryctoaltrntiva_pryctocpa06_fk` | `id_proyecto_capa_resultante` |
| `mline_td_proyecto_capa` | `mline_pryctocpa_cpa02_fk` | `id_capa` |
| `mline_td_proyecto_capa` | `mline_pryctocpa_prycto01_fk` | `id_proyecto` |
| `mline_td_proyecto_componente` | `mline_pryctcmpnt_pryctcpvrt_fk` | `id_proyecto_capa_vertices` |
| `mline_td_proyecto_componente` | `mline_pryctocmpnnte_prycto01_fk` | `id_proyecto` |
| `mline_td_proyecto_componente` | `mline_pryctocmpnnte_pryctocpa02_fk` | `id_proyecto_capa_componente` |
| `mline_td_proyecto_regla_cfg` | `mline_pryctorglacfg_cpaprpiedad04_fk` | `id_capa_propiedad` |
| `mline_td_proyecto_regla_cfg` | `mline_pryctorglacfg_prmtro05_fk` | `id_tipo_funcion_espacial` |
| `mline_td_proyecto_regla_cfg` | `mline_pryctorglacfg_prmtro07_fk` | `id_valor_ponderacion` |
| `mline_td_proyecto_regla_cfg` | `mline_pryctorglacfg_prycto01_fk` | `id_proyecto` |
| `mline_td_proyecto_regla_cfg` | `mline_pryctorglacfg_pryctocpa02_fk` | `id_proyecto_capa_origen` |
| `mline_td_proyecto_regla_cfg` | `mline_pryctorglacfg_pryctocpa06_fk` | `id_proyecto_capa_resultante` |
| `mline_td_proyecto_regla_cfg` | `mline_pryctorglacfg_pryctorglacfg03_fk` | `id_proyecto_regla_cfg_origen` |

Los tres índices de referencias retiradas siguen en el inventario porque existen en MySQL; recrear su índice de búsqueda no recrea su FK ni vuelve a poblar el campo. No se eliminan índices previos ni se duplican los equivalentes.

## Fuentes y límites

- EFT v2.4, 5.8.2: migración de claves/relaciones compatibles; reemplazo de Parámetros y Maestros GIS por funciones nativas.
- EFT v2.4, 5.8.4: referencias retiradas, conservando sus campos vacíos hasta completar la transición.
- EFT v2.4, 5.8.10–5.8.11: vínculos del modelo futuro y parámetros que pasan a dominios.
- Dump MySQL: `Mapline_20261030.sql`; SHA-256 `ea9fc0fafa0f0f9cd1688cd4777901f45fbe9db307ee1d2e2272edefca0c63dd`.
- [Esri: requisitos de branch](https://doc.esri.com/en/arcgis-pro/latest/help/data/geodatabases/overview/register-a-dataset-as-branch-versioned.html): el versionado branch no admite índices únicos de usuario.
- [Microsoft: PRIMARY KEY y FOREIGN KEY](https://learn.microsoft.com/en-us/sql/relational-databases/tables/primary-and-foreign-key-constraints): la PK crea un índice único; la FK exige una clave candidata única en el padre.

La comprobación local valida archivos y correspondencia con el dump. No demuestra que se hayan aplicado restricciones a la base real; eso se confirma al ejecutar el SQL y consultar el diagnóstico.
