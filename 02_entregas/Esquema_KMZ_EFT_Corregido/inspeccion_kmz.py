"""Lectura completa y portable de atributos KMZ, sin ArcPy ni escrituras.

Los tipos declarados pertenecen a SchemaData/schemaUrl + SimpleField exactos.
Una etiqueta HTML o Data nunca hereda el tipo de otra etiqueta homonima.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import csv
from decimal import Decimal, InvalidOperation
import hashlib
from html.parser import HTMLParser
import io
import os
from pathlib import Path
import posixpath
import re
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET
import zipfile

from normalizacion_kmz import snake_case

GEOMETRIES = {'Point': 'Punto', 'LineString': 'Línea', 'Polygon': 'Polígono', 'LinearRing': 'Polígono',
              'Model': 'Modelo3D', 'Track': 'TrazaGX'}
MARKERS = {'<null>', 'null', '<nulo>', 'nulo', 'none', 'nan', 'n/a'}
NUMBER = re.compile(r'^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$')


def local(tag):
    return tag.rsplit('}', 1)[-1]


def basename(value):
    return str(value).replace('\\', '/').rsplit('/', 1)[-1]


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


class NamespaceStream:
    """Reparacion de namespace exclusivamente en la copia de lectura."""
    def __init__(self, source):
        self.source = source
        prefix = source.read(65536)
        root = re.search(rb'<(?:[A-Za-z_][\w.-]*:)?kml(?=[\s>])[^>]*>', prefix)
        self.repaired = bool(root and not re.search(rb'xmlns:xsi\s*=', root[0]))
        if self.repaired:
            start = re.match(rb'<(?:[A-Za-z_][\w.-]*:)?kml', root[0]).group()
            replacement = start + b' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"' + root[0][len(start):]
            prefix = prefix[:root.start()] + replacement + prefix[root.end():]
        self.prefix = io.BytesIO(prefix)

    def read(self, size=-1):
        if size < 0:
            return self.prefix.read() + self.source.read()
        first = self.prefix.read(size)
        return first + self.source.read(size - len(first)) if len(first) < size else first


class Pairs(HTMLParser):
    """Conserva valores de celdas, incluidos sus textos de tablas anidadas.

    La celda exterior no pierde sus descendientes al comenzar otra fila.
    Script/style son presentacion; texto literal que parezca codigo sigue
    siendo texto y no se elimina por heuristicas. Los pares interiores se
    conservan tambien: no se elige un titulo como sustituto de una celda.
    """
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.frames, self.pairs = [], []
        self.table_depth = 0
        self.ignored = []

    def close_cell(self):
        if self.frames and self.frames[-1]['cell'] is not None:
            frame = self.frames[-1]
            frame['cells'].append(''.join(frame['cell']).strip())
            frame['cell'] = None

    def close_row(self):
        self.close_cell()
        cells = self.frames.pop()['cells']
        if len(cells) == 2 and cells[0]:
            self.pairs.append((cells[0], cells[1]))

    def append_text(self, data):
        # Cada celda ascendente recibe el contenido de su propio subarbol.
        for frame in self.frames:
            if frame['cell'] is not None:
                frame['cell'].append(data)

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style'}:
            self.ignored.append(tag)
            return
        if self.ignored:
            return
        if tag == 'table':
            self.append_text('\n')
            self.table_depth += 1
        elif tag == 'tr':
            # HTML permite omitir </tr> antes de la fila siguiente.
            if self.frames and self.frames[-1]['depth'] == self.table_depth:
                self.close_row()
            self.append_text('\n')
            self.frames.append(dict(cells=[], cell=None, depth=self.table_depth))
        elif tag in {'td', 'th'} and self.frames:
            self.close_cell()
            self.append_text('\n')
            self.frames[-1]['cell'] = []
        elif tag == 'br':
            self.append_text('\n')

    def handle_endtag(self, tag):
        if self.ignored:
            if tag == self.ignored[-1]:
                self.ignored.pop()
            return
        if tag in {'td', 'th'}:
            if self.frames and self.frames[-1]['depth'] == self.table_depth:
                self.close_cell()
        elif tag == 'tr' and self.frames and self.frames[-1]['depth'] == self.table_depth:
            self.close_row()
        elif tag == 'table':
            while self.frames and self.frames[-1]['depth'] == self.table_depth:
                self.close_row()
            self.table_depth = max(0, self.table_depth - 1)
            self.append_text('\n')

    def handle_data(self, data):
        if not self.ignored:
            self.append_text(data)

    def close(self):
        super().close()
        while self.frames:
            self.close_row()


def geometry(elem):
    kinds = {GEOMETRIES[local(node.tag)] for node in elem.iter() if local(node.tag) in GEOMETRIES}
    return 'Mixta' if len(kinds) > 1 else next(iter(kinds)) if kinds else 'Sin geometría'


class VisibleText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)

    def handle_starttag(self, tag, attrs):
        if tag == 'br':
            self.parts.append('\n')


def folder_name(value):
    """El inventario usa el texto visible del nombre, no sus enlaces HTML.

    PLS-CADD exporta nombres como <a href="file:///...">Conexion ...</a>.
    Se lee solo el rotulo; no se sigue ni interpreta el destino del enlace.
    """
    value = (value or '').strip()
    parser = VisibleText()
    parser.feed(value)
    parser.close()
    return ''.join(parser.parts).strip()


def fresh():
    return dict(registros=0, valores_utiles=0, vacios=0, marcadores=Counter(),
        max_utf16=0, numericos=0, otros_textos=0, minimo=None, maximo=None,
        fraccionarios=0, leading_zeros=0, max_significant=0,
        tipos_declarados=Counter(), valores_sin_tipo=0, ejemplos=[],
        conflictos=0, copias_sin_tipo=0, contenedores_presentacion=0,
        tipos_declarados_fuentes=set(), miembros=set())


def observe(stats, value, declared=None, reference=None, observer=None):
    stats['max_utf16'] = max(stats['max_utf16'], len(value.encode('utf-16-le')) // 2)
    if len(stats['ejemplos']) < 5 and value[:250] not in stats['ejemplos']:
        stats['ejemplos'].append(value[:250])
    if declared:
        stats['tipos_declarados'][declared] += 1
        if reference:
            stats['tipos_declarados_fuentes'].add(reference)
    else:
        stats['valores_sin_tipo'] += 1
    text = value.strip()
    if not text:
        stats['vacios'] += 1
    elif text.casefold() in MARKERS:
        stats['marcadores'][text] += 1
    else:
        stats['valores_utiles'] += 1
        number = None
        if NUMBER.fullmatch(text):
            try:
                candidate = Decimal(text)
                if candidate.is_finite():
                    number = candidate
            except InvalidOperation:
                pass
        if number is None:
            stats['otros_textos'] += 1
        else:
            stats['numericos'] += 1
            stats['minimo'] = number if stats['minimo'] is None else min(stats['minimo'], number)
            stats['maximo'] = number if stats['maximo'] is None else max(stats['maximo'], number)
            stats['fraccionarios'] += int(number != number.to_integral_value())
            stats['leading_zeros'] += int(bool(re.fullmatch(r'[+-]?0\d+', text)))
            stats['max_significant'] = max(stats['max_significant'], len(number.as_tuple().digits))
    if observer:
        observer(stats, value, declared)


def finished(stats):
    result = dict(stats)
    for key in ('minimo', 'maximo'):
        if result[key] is not None:
            result[key] = str(result[key])
    for key in ('marcadores', 'tipos_declarados'):
        result[key] = dict(sorted(result[key].items()))
    for key in ('tipos_declarados_fuentes', 'miembros'):
        result[key] = sorted(result[key])
    return result


def _schemas_and_routes(archive, members, issue):
    schemas, routes, repairs = {}, {}, []
    for member in members:
        stack, containers, frames = [], [], {}
        next_id = 0
        with archive.open(member) as stream:
            reader = NamespaceStream(stream)
            for event, elem in ET.iterparse(reader, events=('start', 'end')):
                tag = local(elem.tag)
                if event == 'start':
                    stack.append(elem)
                    if tag in {'Document', 'Folder'}:
                        next_id += 1
                        frames[next_id] = dict(name='', parent=containers[-1] if containers else 0)
                        containers.append(next_id)
                    continue
                parent = stack[-2] if len(stack) > 1 else None
                if tag == 'name' and parent is not None and local(parent.tag) in {'Document', 'Folder'}:
                    frames[containers[-1]]['name'] = folder_name(elem.text)
                if tag == 'Schema':
                    sid = elem.get('id')
                    if sid:
                        key = member, sid
                        fields = {}
                        for node in elem:
                            if local(node.tag) not in {'SimpleField', 'SimpleArrayField'} or not node.get('name'):
                                continue
                            name, typ = node.get('name'), node.get('type')
                            if name in fields:
                                fields[name] = None
                                issue('SCHEMA_CAMPO_DUPLICADO', member, f'{sid}.{name}')
                            else:
                                fields[name] = typ
                        if key in schemas:
                            schemas[key] = None
                            issue('SCHEMA_ID_DUPLICADO', member, sid)
                        else:
                            schemas[key] = fields
                if tag in {'Placemark', 'Style', 'StyleMap', 'Schema', 'Document', 'Folder'}:
                    if tag in {'Document', 'Folder'}:
                        containers.pop()
                    if parent is not None:
                        parent.remove(elem)
                    elem.clear()
                stack.pop()
            if reader.repaired:
                repairs.append(member)
        def route(uid):
            if not uid:
                return ''
            f = frames[uid]
            if 'route' not in f:
                prefix = route(f['parent'])
                f['route'] = prefix + ' / ' + f['name'] if f['parent'] else f['name']
            return f['route']
        routes[member] = {uid: route(uid) for uid in frames}
    return schemas, routes, repairs


def _resolve_schema(member, url, schemas):
    parsed = urlsplit(url or '')
    if parsed.scheme or parsed.netloc or parsed.query or not parsed.fragment:
        return None, None
    target = posixpath.normpath(posixpath.join(posixpath.dirname(member), unquote(parsed.path))) if parsed.path else member
    if target.startswith('../') or target.startswith('/'):
        return None, None
    key = target, unquote(parsed.fragment)
    return schemas.get(key), target + '#' + key[1]


def attributes(elem, member, schemas, issue):
    """Devuelve todas las ocurrencias; las columnas HTML conservan su orden."""
    events, seen_nodes = [], set()
    for container in elem.iter():
        if local(container.tag) != 'SchemaData':
            continue
        definition, ref = _resolve_schema(member, container.get('schemaUrl'), schemas)
        if definition is None:
            issue('SCHEMA_NO_RESUELTO', member, container.get('schemaUrl') or '')
        for node in container:
            if local(node.tag) in {'SimpleData', 'SimpleArrayData'} and node.get('name'):
                seen_nodes.add(id(node))
                name = node.get('name')
                typ = definition.get(name) if definition is not None else None
                if not typ:
                    issue('SIMPLEDATA_SIN_TIPO', member, (ref or '') + '.' + name)
                if local(node.tag) == 'SimpleArrayData':
                    for child in node:
                        if local(child.tag) == 'value':
                            events.append((name, child.text or '', typ, ref, 'SimpleArrayData'))
                else:
                    events.append((name, node.text or '', typ, ref, 'SimpleData'))
    for node in elem.iter():
        tag = local(node.tag)
        if tag == 'SimpleData' and node.get('name') and id(node) not in seen_nodes:
            events.append((node.get('name'), node.text or '', None, None, 'SimpleData'))
            issue('SIMPLEDATA_SIN_SCHEMA', member, node.get('name'))
        elif tag == 'Data' and node.get('name'):
            value = next((child.text or '' for child in node if local(child.tag) == 'value'), '')
            events.append((node.get('name'), value, None, None, 'Data'))
        elif tag == 'description':
            events.append(('description', node.text or '', None, None, 'description'))
    output = []
    for name, value, declared, ref, kind in events:
        has_table = bool(re.search(r'<table\b', value, re.I))
        # Conservar la columna XML envolvente, aunque su contenido sea una tabla.
        output.append((name, value, declared, ref, kind))
        if has_table:
            parser = Pairs()
            parser.feed(value)
            parser.close()
            for label, text in parser.pairs:
                if snake_case(label) == 'field_name' and snake_case(text) == 'field_value':
                    continue
                output.append((label, text, None, None, 'HTML'))
    return output


def _read_csv(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream, delimiter=';'))


def collect(source_dir, model_dir, emit=print, value_observer=None):
    source_dir, model_dir = Path(source_dir).resolve(), Path(model_dir).resolve()
    if not source_dir.is_dir():
        raise ValueError('No existe la carpeta de fuentes KMZ: ' + str(source_dir))
    catalog = _read_csv(model_dir / 'mapeo_capas_revision.csv')
    mappings = _read_csv(model_dir / 'campos_por_ruta.csv')
    key = lambda row: (basename(row['archivo']), row['ruta'], row['geometria'])
    expected = {key(row): row for row in catalog}
    if len(expected) != len(catalog):
        raise ValueError('El inventario contiene rutas duplicadas; no se elige una arbitrariamente.')
    if not expected:
        raise ValueError('El inventario de rutas esta vacio.')
    wanted = {k[0] for k in expected}
    located = defaultdict(list)
    for path in source_dir.rglob('*'):
        if path.is_file() and path.suffix.casefold() == '.kmz' and path.name in wanted:
            located[path.name].append(path)
    ambiguous = {name: paths for name, paths in located.items() if len(paths) > 1}
    if ambiguous:
        raise ValueError('Fuentes KMZ ambiguas (nombres repetidos): ' + ', '.join(sorted(ambiguous)))
    missing = sorted(wanted - located.keys())
    maps = defaultdict(dict)
    names_from_kml = defaultdict(dict)
    required = defaultdict(set)
    required_links = defaultdict(set)
    seen_links = Counter()
    issues = Counter()
    def issue(code, member='', detail='', route_key=None):
        issues[(code, member, detail, route_key)] += 1
    for row in mappings:
        k = key(row)
        if k not in expected:
            raise ValueError('Mapeo de atributo fuera del inventario: ' + repr(k))
        source = snake_case(row['campo_original'])
        dest = (row['clase_destino'], row['campo_destino']) if row['clase_destino'] and row['campo_destino'] else None
        if source in maps[k] and maps[k][source] != dest:
            raise ValueError('Mapeo ambiguo tras normalizar el campo: ' + repr((k, source)))
        maps[k][source] = dest
        if row.get('regla') == 'NOMBRE_KML_100' and dest:
            names_from_kml[k][source] = row['campo_original']
        if dest:
            if dest[0] != expected[k]['clase_propuesta']:
                raise ValueError('Clase del atributo distinta de la ruta: ' + repr((k, dest)))
            required[dest].add(k)
            required_links[(dest, k, source)].add(row['campo_original'])
    found, sources, raw_stats, destination_stats = Counter(), [], {}, {k: fresh() for k in required}
    total_placemarks = 0
    extras = Counter()
    for filename in sorted(wanted - set(missing)):
        path = located[filename][0]
        emit(f"LEYENDO KMZ: {filename}.")
        before = digest(path)
        members_stats = []
        with zipfile.ZipFile(path) as archive:
            all_names = archive.namelist()
            members = sorted(name for name in all_names if name.lower().endswith('.kml'))
            if len(members) != len(set(members)):
                raise ValueError('Miembros KML duplicados en: ' + filename)
            if not members:
                issue('KMZ_SIN_KML', filename)
            local_issue = lambda code, member='', detail='': issue(code, filename + '::' + member, detail)
            schemas, frame_routes, repairs = _schemas_and_routes(archive, members, local_issue)
            for member in members:
                stack, frames, next_id, observed = [], [], 0, 0
                with archive.open(member) as stream:
                    reader = NamespaceStream(stream)
                    for event, elem in ET.iterparse(reader, events=('start', 'end')):
                        tag = local(elem.tag)
                        if event == 'start':
                            stack.append(elem)
                            if tag in {'Document', 'Folder'}:
                                next_id += 1
                                frames.append(next_id)
                            continue
                        parent = stack[-2] if len(stack) > 1 else None
                        if tag == 'Placemark':
                            observed += 1
                            total_placemarks += 1
                            if observed % 50000 == 0:
                                emit(f"PROGRESO KMZ: {filename} / {member}; {observed} elementos leidos.")
                            route = frame_routes[member][frames[-1]] if frames else ''
                            k = (filename, route, geometry(elem))
                            found[k] += 1
                            if k not in expected:
                                extras[k] += 1
                            attrs = attributes(elem, member, schemas, local_issue)
                            actual_names = {snake_case(event[0]) for event in attrs}
                            for canonical, original in names_from_kml[k].items():
                                if canonical not in actual_names:
                                    native = next((child for child in elem if local(child.tag) == 'name'), None)
                                    if native is not None:
                                        attrs.append((original, native.text or '', 'string', member + '#KML.name', 'KML.name'))
                                    else:
                                        issue('NOMBRE_KML_AUSENTE', filename + '::' + member, original, k)
                            occurrence = Counter()
                            targets = defaultdict(list)
                            for original, value, declared, ref, channel in attrs:
                                occurrence[original] += 1
                                raw_key = k + (original, occurrence[original], channel)
                                stats = raw_stats.setdefault(raw_key, fresh())
                                stats['registros'] += 1
                                stats['miembros'].add(member)
                                presentation = channel in {'Data', 'SimpleData', 'description'} and bool(re.search(r'<table\b', value, re.I))
                                stats['contenedores_presentacion'] += int(presentation)
                                observe(stats, value, declared, filename + '::' + ref if ref else None, value_observer)
                                source = snake_case(original)
                                dest = maps[k].get(source)
                                # Un <description> nativo con tabla presenta los
                                # atributos interiores. No es la columna homonima
                                # de esa tabla. Data/SimpleData con nombre explicito
                                # conservan, en cambio, su mapeo literal aprobado.
                                wrapper = channel == 'description' and presentation
                                if wrapper:
                                    dest = None
                                stats['registros_mapeados'] = stats.get('registros_mapeados', 0) + int(bool(dest))
                                stats['registros_solo_evidencia'] = stats.get('registros_solo_evidencia', 0) + int(not dest)
                                if dest:
                                    seen_links[(dest, k, source)] += 1
                                    targets[dest].append((value, declared, ref, source))
                                elif wrapper or source not in maps[k]:
                                    issue('CONTENEDOR_XML_SIN_DESTINO' if presentation else 'ATRIBUTO_SIN_MAPEO',
                                          filename + '::' + member, original, k)
                            for dest, values in targets.items():
                                stats = destination_stats[dest]
                                stats['registros'] += 1
                                stats['miembros'].add(filename + '::' + member)
                                distinct = list(dict.fromkeys(value for value, _, _, _ in values))
                                if len([value for value in distinct if value != '']) > 1:
                                    stats['conflictos'] += 1
                                    issue('VALORES_CONFLICTIVOS', filename + '::' + member, '.'.join(dest), k)
                                # Cada valor diferente se perfila una vez por entidad/destino.
                                # Las declaraciones se vinculan a ese valor y campo exactos.
                                # La copia HTML identica conserva la declaracion de SimpleData.
                                for value in distinct:
                                    instances = [(typ, ref, src) for v, typ, ref, src in values if v == value]
                                    types = {typ for typ, _, _ in instances}
                                    known = types - {None}
                                    typed_sources = {src for typ, _, src in instances if typ is not None}
                                    untyped_sources = {src for typ, _, src in instances if typ is None}
                                    # Una copia HTML identica del mismo campo/entidad no
                                    # borra el esquema de SimpleData. Una etiqueta distinta
                                    # fusionada por mapeo conserva su falta de declaracion.
                                    declared = next(iter(known)) if len(known) == 1 and untyped_sources <= typed_sources else None
                                    if declared:
                                        stats['copias_sin_tipo'] += sum(typ is None for typ, _, _ in instances)
                                    reference = next((ref for _, ref, _ in instances if ref), None)
                                    if len(types - {None}) > 1:
                                        issue('TIPOS_DECLARADOS_INCOMPATIBLES', filename + '::' + member, '.'.join(dest), k)
                                    observe(stats, value, declared, filename + '::' + reference if reference else None, value_observer)
                            if parent is not None:
                                parent.remove(elem)
                            elem.clear()
                        elif tag in {'Document', 'Folder'}:
                            frames.pop()
                            if parent is not None:
                                parent.remove(elem)
                            elem.clear()
                        elif tag in {'Style', 'StyleMap', 'Schema', 'GroundOverlay', 'ScreenOverlay', 'PhotoOverlay', 'NetworkLink'}:
                            if tag in {'GroundOverlay', 'ScreenOverlay', 'PhotoOverlay', 'NetworkLink'}:
                                issue('OBJETO_NO_PLACEMARK', filename + '::' + member, tag)
                            if parent is not None:
                                parent.remove(elem)
                            elem.clear()
                        stack.pop()
                members_stats.append(dict(miembro=member, placemarks=observed))
            schema_rows = [dict(miembro=m, schema_id=sid, campos=fields) for (m, sid), fields in sorted(schemas.items())]
        if digest(path) != before:
            raise ValueError('Cambio un KMZ durante la lectura: ' + filename)
        sources.append(dict(archivo=filename, ruta_lectura=str(path), sha256=before,
            miembros=members_stats, schemas=schema_rows, namespaces_reparados_en_lectura=repairs))
        emit(f"KMZ LEIDO: {filename}; {sum(row['placemarks'] for row in members_stats)} elementos.")
    coverage = []
    for k, row in sorted(expected.items()):
        expected_count = int(row['elementos'])
        status = 'FUENTE_AUSENTE' if k[0] in missing else 'COINCIDE' if found[k] == expected_count else 'DIFERENCIA'
        coverage.append(dict(archivo=k[0], ruta=k[1], geometria=k[2],
            clase=row['clase_propuesta'], esperados=expected_count, observados=found[k], estado=status))
    by_key = {(row['archivo'], row['ruta'], row['geometria']): row for row in coverage}
    missing_links = defaultdict(list)
    for (dest, k, source), originals in sorted(required_links.items()):
        if not seen_links[(dest, k, source)]:
            detail = dict(archivo=k[0], ruta=k[1], geometria=k[2],
                campo_normalizado=source, campos_originales=sorted(originals))
            missing_links[dest].append(detail)
            issue('ATRIBUTO_ESPERADO_NO_OBSERVADO', '',
                  '.'.join(dest) + ' <- ' + ' | '.join(sorted(originals)), k)
    destinations = []
    for dest, stats in sorted(destination_stats.items()):
        rr = sorted(required[dest])
        complete = bool(rr) and not missing_links[dest] and all(by_key[k]['estado'] == 'COINCIDE' for k in rr)
        destinations.append(dict(clase=dest[0], campo=dest[1], **finished(stats),
            cobertura='COMPLETA_RUTAS_DEL_CAMPO' if complete else 'INCOMPLETA',
            vinculos_sin_observar=missing_links[dest],
            rutas=[dict(archivo=k[0], ruta=k[1], geometria=k[2]) for k in rr]))
    raw_rows = []
    for k, stats in sorted(raw_stats.items()):
        route_key = k[:3]
        dest = maps[route_key].get(snake_case(k[3]))
        if not stats.get('registros_mapeados'):
            dest = None
        raw_rows.append(dict(archivo=k[0], ruta=k[1], geometria=k[2], campo_original=k[3],
            ocurrencia=k[4], canal=k[5], clase_destino=dest[0] if dest else '',
            campo_destino=dest[1] if dest else '', **finished(stats)))
    issue_rows = [dict(codigo=code, miembro=member, detalle=detail,
        ruta=dict(archivo=k[0], ruta=k[1], geometria=k[2]) if k else None, ocurrencias=count)
        for (code, member, detail, k), count in sorted(issues.items(), key=lambda item: repr(item[0]))]
    for k, count in sorted(extras.items()):
        issue_rows.append(dict(codigo='RUTA_NO_INVENTARIADA', miembro='', detalle='',
            ruta=dict(archivo=k[0], ruta=k[1], geometria=k[2]), ocurrencias=count))
    expected_total = sum(int(row['elementos']) for row in catalog)
    missing_count = sum(len(rows) for rows in missing_links.values())
    complete = not missing and not extras and not missing_count and all(row['estado'] == 'COINCIDE' for row in coverage)
    return dict(estado='LECTURA_COMPLETA' if complete else 'LECTURA_INCOMPLETA',
        fuentes=sources, fuentes_ausentes=missing, rutas=coverage,
        rutas_no_inventariadas=[dict(archivo=k[0], ruta=k[1], geometria=k[2], observados=count) for k, count in sorted(extras.items())],
        campos_fuente=raw_rows, campos_destino=destinations, incidencias=issue_rows,
        conteos=dict(kmz_esperados=len(wanted), kmz_leidos=len(sources),
            rutas_esperadas=len(expected), rutas_observadas=len(found),
            rutas_coincidentes=sum(row['estado'] == 'COINCIDE' for row in coverage),
            elementos_esperados=expected_total, elementos_observados=total_placemarks,
            campos_fuente=len(raw_rows), campos_destino=len(destinations),
            vinculos_campos_esperados=len(required_links), vinculos_campos_sin_observar=missing_count,
            rutas_sin_destino=sum(not row['clase_propuesta'] for row in catalog),
            elementos_sin_destino=sum(int(row['elementos']) for row in catalog if not row['clase_propuesta'])),
        cambios_en_fuentes=False, cambios_en_modelo=False, cambios_en_sde=False)
