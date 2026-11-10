"""Recupera definiciones del respaldo, sin acceder ni modificar el servidor."""
from pathlib import Path
import hashlib
import json
import re

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'ArcGisAWS_Restricciones'
OUT.mkdir(exist_ok=True)
BASE = ROOT / 'ArcGisAWS_Carga_Mapline'
model = json.loads((BASE / 'modelo_eft.json').read_text(encoding='utf-8'))
control = json.loads((BASE / 'control_origen.json').read_text(encoding='utf-8'))
tables = [t for t in model['tables'] if t['geometry_type'] is None]
names = {t['name'] for t in tables}

def values(text):
    """Leer exclusivamente literales de VALUES de mysqldump, nunca ejecutar SQL."""
    p = 0
    while p < len(text):
        while p < len(text) and text[p].isspace(): p += 1
        if p >= len(text) or text[p] == ';': break
        assert text[p] == '('
        p += 1
        row = []
        while True:
            while text[p].isspace(): p += 1
            if text[p] == "'":
                p += 1
                chars = []
                while True:
                    ch = text[p]; p += 1
                    if ch == '\\':
                        esc = text[p]; p += 1
                        chars.append({'0':'\0','b':'\b','n':'\n','r':'\r','t':'\t','Z':'\x1a'}.get(esc, esc))
                    elif ch == "'":
                        if text[p:p+1] == "'": chars.append("'"); p += 1
                        else: break
                    else: chars.append(ch)
                value = ''.join(chars)
            else:
                start = p
                while text[p] not in ',)': p += 1
                token = text[start:p].strip()
                assert token == 'NULL' or re.fullmatch(r'[-+]?\d+(?:\.\d+)?', token)
                value = None if token == 'NULL' else token
            row.append(value)
            while text[p].isspace(): p += 1
            if text[p] == ',': p += 1; continue
            assert text[p] == ')'; p += 1; break
        yield row
        while p < len(text) and text[p].isspace(): p += 1
        if text[p:p+1] == ',': p += 1
        else: assert text[p:p+1] == ';'

indexes = []
params, param_types = [], []
current = None
source = ROOT / 'Mapline_20261030.sql'
with source.open(encoding='utf-8-sig') as stream:
    for line in stream:
        found = re.match(r'^CREATE TABLE `([^`]+)`', line)
        if found: current = found[1]
        if current in names:
            key = re.match(r'^\s*KEY `([^`]+)` \(([^)]+)\)', line)
            if key:
                indexes.append({'table': current, 'name': key[1],
                                'columns': re.findall(r'`([^`]+)`', key[2]), 'unique': False})
        if line.startswith(') ENGINE='): current = None
        insert = re.match(r'^INSERT INTO `(mline_tp_parametro|mline_tp_tipoparametro)` (\(.*?\)) VALUES (.*);\s*$', line)
        if insert:
            cols = re.findall(r'`([^`]+)`', insert[2])
            target = params if insert[1] == 'mline_tp_parametro' else param_types
            target.extend(dict(zip(cols, row)) for row in values(insert[3] + ';'))
assert len(indexes) == 27 and len(tables) == 8
types = {p['id_tipo_parametro']: p['co_tipo_parametro'] for p in param_types}
groups = {d['parameter_type'] for d in model['domain_fields']}
codes = {group: {} for group in groups}
numeric_values = {group: {} for group in groups}
for p in params:
    group = types.get(p['id_tipo_parametro'])
    if group in groups:
        codes[group][str(p['id_parametro'])] = p['no_valor_parametro'] or str(p['id_parametro'])
        numeric_values[group][str(p['id_parametro'])] = p['nu_valor_numerico']
assert all(codes.values())
relations = []
for r in control['all_relations']:
    if r['child'] not in names: continue
    r = dict(r)
    if r.get('obsolete'):
        r['treatment'] = 'obsolete_null'
    elif r['parent'] in names:
        r['treatment'] = 'arcgis_constraint'
    elif r['parent'] == 'mline_tp_parametro':
        r['treatment'] = 'coded_domain'
    elif r['parent'] in ('mline_tm_capa', 'mline_tm_capa_propiedad'):
        r['treatment'] = 'pending_portal_field_mapping'
    else:
        r['treatment'] = 'pending_spatial_parent'
    r['on_delete'] = 'NO_ACTION'
    r['on_update'] = 'NO_ACTION'
    relations.append(r)
assert len(relations) == 27
manifest = {
    'database': 'ArcGisAWS', 'owner': 'gis', 'versioning_target': 'BRANCH',
    'rules_prefix': 'mline', 'tables': tables, 'original_indexes': indexes,
    'domain_fields': model['domain_fields'], 'domain_codes': codes,
    'domain_numeric_values': numeric_values, 'relations': relations,
    'deferred_incoming_relations': [r for r in model['relations']
        if r['parent'] in names and r['child'] not in names and not r.get('obsolete')],
    'obsolete_fields': model['obsolete_fields'], 'enforce_obsolete_null': True,
    'source_sha256': control['sourceSHA256'],
    'scope': 'Ocho tablas existentes. No carga ni reemplaza datos. No agrega PK/FK SQL incompatibles con branch.',
    'limitations': [
        'Las reglas de atributos no son una PK/FK fisica SQL ni garantizan unicidad atomica entre ediciones concurrentes/versiones.',
        'Faltan relaciones con padres espaciales y equivalencias Portal/campos.',
        'Los codigos de parametros se preservan; el valor de ponderacion es distinto del ID.',
        'La generacion de nuevos ID se prepara por separado; no se crean identidades ni secuencias en este paquete.']}
(OUT / 'modelo_restricciones.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'tables': len(tables), 'original_indexes': len(indexes), 'relations': len(relations),
                  'domain_groups': len(codes), 'coded_values': sum(len(v) for v in codes.values()),
                  'treatments': {t: sum(r['treatment'] == t for r in relations) for t in sorted({r['treatment'] for r in relations})}}))
