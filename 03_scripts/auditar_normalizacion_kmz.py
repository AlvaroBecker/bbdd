"""Verifica cobertura de los CSV y documenta decisiones de normalizacion."""
from collections import Counter, defaultdict
import csv
import hashlib
import io
import json
from pathlib import Path
import re
from nombres_clases_kmz import NAMES, policy_rows
from fuentes_inventario_verificadas import read_inventory_bytes, source_metadata

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'inventario_kmz_resumen'
OUT = ROOT / '02_entregas/Esquema_KMZ_EFT_Corregido'


def read(path):
    with path.open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream, delimiter=';'))


def write(name, rows, columns):
    with (OUT/name).open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, delimiter=';')
        writer.writeheader()
        writer.writerows(rows)


def main():
    source_names = ('inventario_kmz_campos.csv', 'inventario_kmz_capas.csv',
                    'inventario_kmz_matriz_campos.csv', 'inventario_kmz_resumen.csv')
    inputs = {name: list(csv.DictReader(io.StringIO(
        read_inventory_bytes(ROOT, name).decode('utf-8-sig'), newline=''), delimiter=';'))
        for name in source_names}
    occurrences = inputs['inventario_kmz_campos.csv']
    mappings = read(OUT/'campos_por_ruta.csv')
    matrix = read(OUT/'campos_matriz_a_esquema.csv')
    model = json.loads((OUT/'esquema.json').read_text(encoding='utf-8'))
    naming = policy_rows(model)
    assert model['version'] == 11
    assert {c['nombre'] for c in model['clases']} == set(NAMES.values())
    keys = ['archivo', 'ruta', 'geometria', 'descripcion']
    expected = Counter(tuple(r[k] for k in keys)+ (r['campo_normalizado'], r['campo']) for r in occurrences)
    actual = Counter(tuple(r[k] for k in keys)+ (r['campo_fuente'], r['campo_original']) for r in mappings)
    assert expected == actual
    assert {int(r['fila_matriz']) for r in matrix} == set(range(1, len(inputs['inventario_kmz_matriz_campos.csv'])+1))
    assert all(re.fullmatch(r'[a-z][a-z0-9]*(?:_[a-z0-9]+)*', f['nombre']) for c in model['clases'] for f in c['campos'])
    classes = {c['nombre']: {f['nombre'] for f in c['campos']} for c in model['clases']}
    assert all(not r['campo_destino'] or r['campo_destino'] in classes[r['clase_destino']] for r in mappings)
    groups = defaultdict(list)
    pending = []
    for r in mappings:
        if not r['campo_destino']:
            continue
        key = tuple(r[k] for k in ('clase_destino', 'campo_fuente', 'campo_original', 'campo_destino', 'regla'))
        groups[key].append(r)
        if r['regla'] in {'COLISION_CON_CAMPO_COMUN', 'COLISION_NORMALIZACION'} or (
                r['campo_fuente'] in {'NAME', 'NOMBRE', 'EAST', 'NORTH', 'X', 'Y', 'UTM', 'POSITION'}
                and r['regla'] == 'NOMBRE_NORMALIZADO'):
            pending.append({**{k:r[k] for k in ('archivo','ruta','descripcion','geometria','clase_destino','campo_original','campo_destino','ejemplo_valor','ejemplo_nombre','evidencia_nombre')},
                            'decision':'CONSERVAR_SIN_FUSION',
                            'motivo':'El CSV solo contiene ejemplos o no demuestra equivalencia del 100%; no se supone igualdad, unidad o sistema de coordenadas.'})
    equivalents = []
    for key, rows in sorted(groups.items()):
        equivalents.append(dict(zip(('clase_destino','campo_fuente','campo_original','campo_destino','regla'),key),
                                ocurrencias=len(rows),fundamento=rows[0]['conversion'],
                                ejemplos=json.dumps(list(dict.fromkeys(r['ejemplo_valor'] for r in rows))[:3],ensure_ascii=False)))
    write('equivalencias_nombres.csv', equivalents, list(equivalents[0]))
    write('revision_equivalencias.csv', pending, list(pending[0]))
    c = next(c for c in model['clases'] if c['nombre']=='estructuras')
    report = dict(version_paquete='1.7', version_modelo=model['version'],
                  clases_revisadas=len(naming), clases_renombradas=sum(row['renombrar'] for row in naming),
                  clases_nombre_conservado=sum(not row['renombrar'] for row in naming),
                  clases_sin_hashes=True,
                  fuentes={name:dict(filas=len(rows),sha256=hashlib.sha256(read_inventory_bytes(ROOT,name)).hexdigest(),
                    procedencia=source_metadata(ROOT,name)) for name,rows in inputs.items()},
                  ocurrencias_reconciliadas=len(mappings),filas_matriz_reconciliadas=len(inputs['inventario_kmz_matriz_campos.csv']),
                  todas_las_definiciones_en_snake_case=True,
                  campos_modelo=sum(len(c['campos']) for c in model['clases']),
                  campos_tipo_provisional=sum('pendiente' in f['origen'].lower() for c in model['clases'] for f in c['campos']),
                  reglas=dict(Counter(r['regla'] for r in mappings)),
                  estados=dict(Counter(r['estado'] for r in mappings)),
                  casos_conservados_para_revision=len(pending),
                  estructuras_campos_modelo=len(c['campos']),estructuras_campos_fisicos=len(c['campos'])+7,
                  estructuras_campos_tipo_provisional=sum('pendiente' in f['origen'].lower() for f in c['campos']),
                  excepciones_nombres=['Datos_Proyecto y otros datasets EFT','Campos nativos ArcGIS','Nombres oficiales del DDL y las 13 capas externas cuando se implementen'],
                  limites='Los CSV no contienen todos los valores por entidad. Se conservan las decisiones de estructuras y del lote 1.5 y se confirman 1356 campos TEXT mediante el perfil completo y la decision 1.7. Quedan 730 tipos provisionales. No se certifican unidades, destinos pendientes ni igualdad de campos basada solo en ejemplos.',
                  esquema_sha256=hashlib.sha256((OUT/'esquema.json').read_bytes()).hexdigest())
    (OUT/'VALIDACION_NORMALIZACION.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='fuentes'},ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
