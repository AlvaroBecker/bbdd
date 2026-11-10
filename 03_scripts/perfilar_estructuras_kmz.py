"""Perfil de valores de estructuras segun rutas existentes; no importa ArcPy.

Lee KMZ originales sin modificarlos. Produce evidencia de tipos, nunca ALTER ni
carga datos. Incluye todas las copias por ruta y no deduplica entidades.
"""
from collections import Counter, defaultdict
import csv
from decimal import Decimal, InvalidOperation
import hashlib
from html.parser import HTMLParser
import importlib.util
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile

from normalizacion_kmz import snake_case

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / '02_entregas/Esquema_KMZ_EFT_Corregido'
OUT = ROOT / '02_entregas/Revision_Tipos_Estructuras'
NUMERIC_CANDIDATES = {'este', 'norte', 'east', 'north', 'x', 'y', 'vano'}
MARKERS = {'<null>', 'null', '<nulo>', 'nulo', 'none', 'nan', 'n/a'}
NUMBER = re.compile(r'^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$')


def read(path):
    with path.open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f, delimiter=';'))


def local(tag):
    return tag.rsplit('}', 1)[-1]


class Pairs(HTMLParser):
    """Conserva pares de tablas HTML, incluidos valores vacios y nulos literales."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.frames = []
        self.pairs = []

    def close_cell(self):
        if self.frames and self.frames[-1][1] is not None:
            self.frames[-1][0].append(''.join(self.frames[-1][1]).strip())
            self.frames[-1][1] = None

    def handle_starttag(self, tag, attrs):
        if tag == 'tr':
            self.frames.append([[], None])
        elif tag in {'td', 'th'} and self.frames:
            self.close_cell()
            self.frames[-1][1] = []
        elif tag == 'br' and self.frames and self.frames[-1][1] is not None:
            self.frames[-1][1].append('\n')

    def handle_endtag(self, tag):
        if tag in {'td', 'th'}:
            self.close_cell()
        elif tag == 'tr' and self.frames:
            self.close_cell()
            cells = self.frames.pop()[0]
            if len(cells) == 2 and cells[0]:
                self.pairs.append((cells[0], cells[1]))

    def handle_data(self, data):
        if self.frames and self.frames[-1][1] is not None:
            self.frames[-1][1].append(data)


def attributes(elem):
    pairs = []
    for node in elem.iter():
        kind = local(node.tag)
        if kind == 'description':
            text = node.text or ''
        elif kind == 'SimpleData' and node.get('name'):
            text = node.text or ''
            if not re.search(r'<table\b', text, re.I):
                pairs.append((node.get('name'), text))
                continue
        elif kind == 'Data' and node.get('name'):
            text = next((v.text or '' for v in node if local(v.tag) == 'value'), '')
            if not re.search(r'<table\b', text, re.I):
                pairs.append((node.get('name'), text))
                continue
        else:
            continue
        parser = Pairs()
        parser.feed(text)
        parser.close()
        pairs.extend(parser.pairs)
    return pairs


def value_kind(value):
    text = value.strip()
    if not text:
        return 'VACIO', None
    if text.casefold() in MARKERS:
        return 'MARCADOR_LITERAL', None
    if NUMBER.fullmatch(text):
        try:
            number = Decimal(text)
            if number.is_finite():
                return 'NUMERICO_DECIMAL', number
        except InvalidOperation:
            pass
    return 'TEXTO', None


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def recommendation(name, kinds):
    useful = kinds['TEXTO'] + kinds['NUMERICO_DECIMAL']
    if not useful:
        return 'SIN_VALORES_UTILES_CONSERVAR_TEXT'
    if name in NUMERIC_CANDIDATES and kinds['TEXTO'] == 0:
        return 'DOUBLE_CANDIDATO'
    return 'TEXT_CONSERVAR'


def write(name, rows, columns=None):
    with (OUT / name).open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=columns or list(rows[0]), delimiter=';')
        writer.writeheader()
        writer.writerows(rows)


def main():
    OUT.mkdir(exist_ok=True)
    model = json.loads((MODEL / 'esquema.json').read_text(encoding='utf-8'))
    cls = next(c for c in model['clases'] if c['nombre'] == 'estructuras')
    own = {f['nombre'] for f in cls['campos'] if f.get('campo_fuente')}
    routes = [r for r in read(MODEL / 'mapeo_capas_revision.csv') if r['clase_propuesta'] == 'estructuras']
    mappings = [r for r in read(MODEL / 'campos_por_ruta.csv') if r['clase_destino'] == 'estructuras']
    by_route = defaultdict(dict)
    for r in mappings:
        key = (Path(r['archivo'].replace('\\', '/')).name, r['ruta'])
        canonical = snake_case(r['campo_original'])
        old = by_route[key].get(canonical)
        assert old is None or old == r['campo_destino']
        by_route[key][canonical] = r['campo_destino']
    expected = {}
    for r in routes:
        key = (Path(r['archivo'].replace('\\', '/')).name, r['ruta'])
        assert key not in expected and r['geometria'] == 'Punto'
        expected[key] = int(r['elementos'])
    stats = {n: dict(kinds=Counter(), records=0, values=Counter(), max_length=0, nums=[]) for n in own}
    found = Counter()
    issues = []
    sources = []
    common_max = Counter()
    spec = importlib.util.spec_from_file_location('kmz_inventory', ROOT / '02_entregas/KMZ_EFT/01_inventariar_kmz.py')
    inventory = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(inventory)
    for filename in sorted({k[0] for k in expected}):
        path = ROOT / '01_fuentes/kmz' / filename
        before = sha(path)
        repairs = []
        with zipfile.ZipFile(path) as archive:
            for member in archive.namelist():
                if not member.lower().endswith('.kml'):
                    continue
                stack = []
                frames = []
                with archive.open(member) as stream:
                    reader = inventory.NamespaceStream(stream)
                    for event, elem in ET.iterparse(reader, events=('start', 'end')):
                        tag = local(elem.tag)
                        if event == 'start':
                            stack.append(elem)
                            if tag in {'Document', 'Folder'}:
                                frames.append({'name': ''})
                            continue
                        parent = stack[-2] if len(stack) > 1 else None
                        if tag == 'name' and parent is not None and local(parent.tag) in {'Document', 'Folder'}:
                            frames[-1]['name'] = (elem.text or '').strip()
                        if tag == 'Placemark':
                            route = ' / '.join(f['name'] for f in frames)
                            key = (filename, route)
                            if key in expected:
                                geometries = {local(e.tag) for e in elem.iter()} & {'Point','LineString','Polygon','Track','Model'}
                                if geometries != {'Point'}:
                                    issues.append(dict(archivo=filename,ruta=route,motivo='GEOMETRIA_INESPERADA',detalle=str(sorted(geometries))))
                                else:
                                    found[key] += 1
                                    values = defaultdict(list)
                                    for original, value in attributes(elem):
                                        source = snake_case(original)
                                        target = by_route[key].get(source)
                                        if source not in by_route[key]:
                                            issues.append(dict(archivo=filename,ruta=route,motivo='ATRIBUTO_NO_MAPEADO',detalle=original))
                                        elif target in own:
                                            if value not in values[target]:
                                                values[target].append(value)
                                    for target, raw in values.items():
                                        s = stats[target]
                                        s['records'] += 1
                                        if len(raw) > 1:
                                            issues.append(dict(archivo=filename,ruta=route,motivo='VALORES_CONFLICTIVOS',detalle=target+': '+json.dumps(raw,ensure_ascii=False)))
                                        for value in raw:
                                            kind, number = value_kind(value)
                                            s['kinds'][kind] += 1
                                            s['values'][value] += 1
                                            s['max_length'] = max(s['max_length'], len(value))
                                            if number is not None:
                                                s['nums'].append(number)
                                    name = next((e.text or '' for e in elem if local(e.tag)=='name'),'')
                                    common_max['nombre'] = max(common_max['nombre'],len(name))
                                    common_max['ruta_kml'] = max(common_max['ruta_kml'],len(route))
                            if parent is not None:
                                parent.remove(elem)
                            elem.clear()
                        elif tag in {'Document','Folder'}:
                            frames.pop()
                            if parent is not None:
                                parent.remove(elem)
                            elem.clear()
                        elif tag in {'Style','StyleMap','Schema'}:
                            if parent is not None:
                                parent.remove(elem)
                            elem.clear()
                        stack.pop()
                    if reader.repaired:
                        repairs.append(member)
        assert before == sha(path), 'El original cambio durante el perfil.'
        sources.append(dict(archivo=filename,sha256=before,xsi_declarado_en_lectura=repairs))
        print(filename, 'registros de estructuras:',sum(n for k,n in found.items() if k[0]==filename),flush=True)
    coverage = [dict(archivo=k[0],ruta=k[1],esperados=n,observados=found[k],coincide=n==found[k]) for k,n in expected.items()]
    total = sum(found.values())
    rows = []
    for name in sorted(own):
        s = stats[name]
        kinds = s['kinds']
        useful = kinds['TEXTO'] + kinds['NUMERICO_DECIMAL']
        decision = recommendation(name, kinds)
        rows.append(dict(campo=name,registros_con_campo=s['records'],ausente_en_registros=total-s['records'],
                         valores_no_vacios_utiles=useful,vacios=kinds['VACIO'],marcadores_literales=kinds['MARCADOR_LITERAL'],
                         numeros_decimales=kinds['NUMERICO_DECIMAL'],otros_textos=kinds['TEXTO'],
                         longitud_maxima_observada=s['max_length'],valores_distintos=len(s['values']),
                         minimo_numerico=str(min(s['nums'])) if s['nums'] else '',maximo_numerico=str(max(s['nums'])) if s['nums'] else '',
                         propuesta=decision,aprobado='NO',unidad_y_crs_confirmados='NO' if name in NUMERIC_CANDIDATES else 'NO_APLICA',
                         ejemplos=json.dumps(list(s['values'])[:5],ensure_ascii=False)))
    write('revision_21_campos.csv',rows)
    write('cobertura_76_rutas.csv',coverage)
    write('incidencias.csv',issues,['archivo','ruta','motivo','detalle'])
    full_values = {name:dict(s['values']) for name,s in stats.items()}
    (OUT/'frecuencias_valores.json').write_text(json.dumps(full_values,ensure_ascii=False,indent=2),encoding='utf-8')
    report = dict(clase='estructuras',fuentes=sources,esquema_sha256=sha(MODEL/'esquema.json'),
                  mapeo_sha256=sha(MODEL/'mapeo_capas_revision.csv'),campos_por_ruta_sha256=sha(MODEL/'campos_por_ruta.csv'),
                  rutas=len(expected),registros_esperados=sum(expected.values()),registros_observados=total,
                  rutas_con_diferencias=sum(not r['coincide'] for r in coverage),incidencias=len(issues),
                  campos_revisados=len(rows),propuestas=dict(Counter(r['propuesta'] for r in rows)),
                  maximos_campos_comunes=dict(common_max),validacion_sde=False,cambios_en_sde=False,
                  alcance='Solo las 76 rutas asignadas actualmente a estructuras; no aprueba el mapeo ni elimina copias. Marcadores literales se cuentan pero no se convierten a NULL. No se alteran tipos ni longitudes.')
    (OUT/'resultado.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='fuentes'},ensure_ascii=True,indent=2))


if __name__ == '__main__':
    main()
