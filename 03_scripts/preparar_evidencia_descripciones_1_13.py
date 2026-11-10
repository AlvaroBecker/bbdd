"""Empaqueta evidencia acotada de descripciones; no toca el modelo operativo."""
import csv
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '02_entregas/Esquema_KMZ_EFT_Corregido'
SOURCE = ROOT / 'outputs/revision_preingesta_20261109_165626/revision_description_sin_mapeo.json'


def main():
    evidence = json.loads(SOURCE.read_text(encoding='utf-8-sig'))
    model = json.loads((OUT / 'esquema.json').read_text(encoding='utf-8-sig'))
    profile = json.loads((OUT / 'PERFIL_COMPLETO_KMZ_1_9.json').read_text(encoding='utf-8-sig'))['perfil']
    hashes = {s['archivo']: s['sha256'] for s in profile['fuentes']}
    assert evidence['rutas'] == len(evidence['detalle']) == 59
    assert sum(r['registros_con_description'] for r in evidence['detalle']) == 1403
    assert all(hashes[s['archivo']] == s['sha256'] for s in evidence['fuentes_releidas'])
    fields = {(c['nombre'], f['nombre']): f for c in model['clases'] for f in c['campos']}
    rows = []
    for item in evidence['detalle']:
        row = {k: v for k, v in item.items() if k != 'ejemplos'}
        row['ejemplos'] = [{k: v for k, v in e.items() if k in {
            'nombre_kml', 'description', 'description_truncada', 'description_sha256'}}
            for e in item.get('ejemplos', [])[:2]]
        row['fuente_sha256'] = hashes[row['archivo']]
        row['estado_regla'] = ('CONTENIDO_EN_ATRIBUTOS_MAS_REGLAS_SISTEMA'
            if item['clasificacion'] == 'HTML_DUPLICADO_EN_ATRIBUTOS_CON_MAPEO_O_REGLA_SISTEMA'
            else 'CORRESPONDENCIA_PENDIENTE')
        row['mapeo_texto_propuesto'] = []
        for candidate in item.get('campos_existentes_candidatos', []):
            spec = fields[item['clase_destino'], candidate['nombre']]
            if (set(item['formatos']) == {'TEXTO_PLANO'} and spec['tipo'] == 'TEXT'
                    and spec['longitud'] >= item['max_utf16']
                    and not candidate['atributo_fuente_presente_mismo_registro']
                    and not candidate['mapeos_en_ruta']):
                row['mapeo_texto_propuesto'].append(candidate['nombre'])
        row['aplicada'] = False
        rows.append(row)
    data = dict(version='1.13', metodo=evidence['metodo'],
        evidencia_auditoria_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        referencias_sha256={n: hashlib.sha256((OUT / n).read_bytes()).hexdigest()
            for n in ('esquema.json', 'campos_por_ruta.csv', 'PERFIL_COMPLETO_KMZ_1_9.json')},
        rutas=rows, resumen=dict(rutas=59, registros=1403, formatos=evidence['formatos'],
            clasificacion_rutas=evidence['clasificacion_rutas']),
        limite='Identidad exacta de los KMZ requerida. Propuestas no aplicadas. No se descarta description en bloque.')
    (OUT / 'descripciones_1_13.json').write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    source_csv = ROOT / 'outputs/revision_preingesta_20261109_163345/confirmar_proyectos_13_confirmados.csv'
    with source_csv.open(encoding='utf-8-sig', newline='') as stream:
        mapping = list(csv.DictReader(stream, delimiter=';'))
    assert len(mapping) == 13 and all(r['confirmado'] == 'si' for r in mapping)
    shutil.copyfile(source_csv, OUT / 'confirmar_proyectos_13_confirmados.csv')
    assert (OUT / 'confirmar_proyectos_13_confirmados.csv').read_bytes() == source_csv.read_bytes()
    print('Evidencia de 59 rutas y CSV confirmado de 13 proyectos preparados.')


if __name__ == '__main__':
    main()
