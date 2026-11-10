from pathlib import Path
import json

ROOT = Path(__file__).resolve().parent / 'ArcGisAWS_Restricciones'
m = json.loads((ROOT / 'modelo_restricciones.json').read_text(encoding='utf-8'))
domain_fields = {(d['table'], d['field']): d['parameter_type'] for d in m['domain_fields']}
treatments = {
    'arcgis_constraint': 'Reglas ArcGIS de referencia y NO ACTION; sin FK fisica SQL',
    'coded_domain': 'Dominio y regla de pertenencia con los codigos originales',
    'obsolete_null': 'Referencia sin uso; debe permanecer NULL segun EFT',
    'pending_portal_field_mapping': 'Pendiente de equivalencia Portal o campo de evaluacion',
    'pending_spatial_parent': 'Pendiente de la clase espacial padre y su validacion',
}
lines = ['# Correspondencia de restricciones del modelo Mapline', '',
    'La referencia es el DDL del respaldo original. El destino de estas ocho tablas es ArcGisAWS.gis y el EFT exige branch versioning. Este paquete no crea PK ni FK fisicas de negocio en SQL Server; restaura indices no unicos y prepara reglas de integridad de ArcGIS.', '',
    '## Identificadores de las ocho tablas', '',
    '| Tabla | Campo PK original | Tratamiento |', '|---|---|---|']
for t in m['tables']:
    lines.append(f"| {t['name']} | {t['primary_key'][0]} | Conservar valores; validar no nulo y unicidad mediante reglas ArcGIS. Sin IDENTITY ni cambios de ID. |")
lines += ['', 'Las reglas de unicidad consultan la version/estado visible en ArcGIS. No equivalen a la garantia atomica de una PK fisica SQL ante ediciones concurrentes ni garantizan unicidad entre versiones. La generacion de nuevos ID mediante secuencias y su control de concurrencia debe implementarse antes de habilitar altas en produccion.', '',
          '## Las 27 relaciones originales salientes', '',
          '| FK original | Referencia | Tratamiento |', '|---|---|---|']
for r in m['relations']:
    detail = treatments[r['treatment']]
    group = domain_fields.get((r['child'], r['child_key']))
    if group:
        detail += ': ' + group
    lines.append(f"| {r['name']} | {r['child']}.{r['child_key']} → {r['parent']}.{r['parent_key']} | {detail} |")
lines += ['', 'Las once referencias vigentes entre las ocho tablas incluyen dos autorreferencias. Se comprueba existencia del padre para insercion/actualizacion del hijo y se bloquea borrar o cambiar una clave de padre que todavia tiene hijos. Se permiten FK NULL, como en el DDL. Estas reglas se ejecutan en ArcGIS; un cambio SQL directo las evita. No se crean relationship classes recursivas ni se supone que una relacion SIMPLE equivale por si sola a NO ACTION.', '',
          'Ademas de los ocho campos con FK fisica hacia parametros, el EFT usa dominios para id_estado_componente e id_estado_regla_cfg. El paquete incluye esos dos consumidores y conserva los codigos historicos.', '',
          '## Dependencias futuras desde clases espaciales', '',
          '| Hijo pendiente | Padre actual | Campo |', '|---|---|---|']
for r in m.get('deferred_incoming_relations', []):
    lines.append(f"| {r['child']} | {r['parent']} | {r['child_key']} |")
lines += ['', 'La proteccion de esos padres frente a sus hijos espaciales debe completarse cuando dichas clases esten disponibles. El paquete no declara terminada la integridad del conjunto de 14 objetos.', '',
          '## Indices secundarios originales', '',
          '| Tabla | Indice original | Columnas |', '|---|---|---|']
for idx in m['original_indexes']:
    lines.append(f"| {idx['table']} | {idx['name']} | {', '.join(idx['columns'])} |")
lines += ['', 'Son 27 definiciones no unicas: las dos de proyectos suelen estar cubiertas por la carga anterior y faltan hasta 25 en las otras tablas. Se comprueba la definicion real antes de crear cada indice para no duplicar coberturas. Se conservan tambien los tres indices sobre referencias obsoletas, sin ocultar su existencia en el origen; esos tres campos estan vacios y pueden no aportar utilidad actual. No se modifican indices de ObjectID, GlobalID ni otros indices de sistema.', '',
          '## Fuentes', '',
          '- Respaldo original Mapline_20261030.sql; hash SHA-256 ' + m['source_sha256'] + '.',
          '- EFT, secciones 5.8.4, 5.8.5, 5.8.10 y 5.8.11.',
          '- [Restricciones de branch versioning](https://doc.esri.com/en/arcgis-pro/latest/help/data/geodatabases/overview/register-a-dataset-as-branch-versioned.html).',
          '- [Reglas de restriccion](https://doc.esri.com/en/arcgis-pro/latest/help/data/geodatabases/overview/constraint-attribute-rules.html).',
          '- [Requisitos de Add Attribute Rule](https://doc.esri.com/en/arcgis-pro/latest/tool-reference/data-management/add-attribute-rule.html).',
          '- [Indices de atributos](https://pro.arcgis.com/en/pro-app/3.4/tool-reference/data-management/add-attribute-index.htm).']
(ROOT / '04_correspondencia_restricciones.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
print('Correspondencia documentada: 8 PK, 27 FK y 27 indices de origen.')
