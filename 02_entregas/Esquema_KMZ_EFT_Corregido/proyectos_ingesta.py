"""Consulta de proyectos y propuestas de correspondencia KMZ, sin escrituras GIS.

Los candidatos por nombre no confirman una relacion. Solo un CSV explicito puede
confirmar la correspondencia con una clave exacta presente en el catalogo leido.
Los codigos nuevos y el id_analisis quedan fuera de esta consulta.
"""
from __future__ import annotations

from collections import Counter
import csv
import hashlib
import io
from pathlib import Path
import re
import unicodedata


CSV_COLUMNS = ('archivo_kmz', 'co_proyecto', 'confirmado')


def _issue(code, message, **context):
    return {'codigo': code, 'mensaje': message, **context}


def _base(field):
    return (getattr(field, 'baseName', None) or field.name.rsplit('.', 1)[-1]).casefold()


def _units(text):
    return len(text.encode('utf-16-le')) // 2


def read_projects(arcpy, parent_path, model=None):
    """Leer co_proyecto y descripciones de la tabla padre ya localizada.

    Devuelve catalogo con ``filas``, ``incidencias`` y ``verificado``. Las filas
    conservan la clave original; solo se quita relleno ASCII derecho de nchar.
    Ningun metodo de management ni cursor de escritura se utiliza aqui.
    """
    key = (model or {}).get('clave_proyecto', 'co_proyecto')
    result = {'tabla': str(parent_path or ''), 'clave': key, 'filas': [],
              'incidencias': [], 'advertencias': [], 'verificado': False,
              'cambios_en_sde': False, 'campos_consultados': []}
    issues = result['incidencias']
    if not parent_path or not arcpy.Exists(str(parent_path)):
        issues.append(_issue('PADRE_AUSENTE', 'No existe la tabla real de proyectos.'))
        return result
    description = arcpy.Describe(str(parent_path))
    if not getattr(description, 'hasOID', False):
        issues.append(_issue('PADRE_NO_REGISTRADO', 'La tabla padre debe tener ObjectID de geodatabase.'))
    fields = {}
    for field in arcpy.ListFields(str(parent_path)):
        name = _base(field)
        if name in fields:
            issues.append(_issue('CAMPO_AMBIGUO', 'Nombre base repetido en la tabla padre.', campo=name))
        fields[name] = field
    pk = fields.get(key.casefold())
    if pk is None or pk.type != 'String' or pk.length != 12:
        issues.append(_issue('CLAVE_INCOMPATIBLE', 'co_proyecto debe ser texto de longitud 12.', campo=key))
    name_field = fields.get('no_proyecto')
    if name_field is None or name_field.type != 'String':
        issues.append(_issue('NOMBRE_PROYECTO_AUSENTE', 'Falta no_proyecto de tipo texto para verificar las propuestas.'))
    for optional in ('de_proyecto', 'es_registro'):
        if optional in fields and fields[optional].type != 'String':
            issues.append(_issue('CAMPO_INCOMPATIBLE', 'Campo descriptivo de proyecto con tipo inesperado.', campo=optional))
    if issues:
        return result
    selected = [key.casefold(), 'no_proyecto']
    selected.extend(n for n in ('de_proyecto', 'es_registro', 'fe_eliminacion') if n in fields)
    cursor_fields = [fields[n].name for n in selected]
    result['campos_consultados'] = cursor_fields
    with arcpy.da.SearchCursor(str(parent_path), cursor_fields) as cursor:
        for number, values in enumerate(cursor, 1):
            raw = dict(zip(selected, values))
            code = raw[key.casefold()]
            normalized = code.rstrip(' ') if isinstance(code, str) else None
            if not normalized:
                issues.append(_issue('CLAVE_VACIA', 'Codigo de proyecto nulo o vacio.', fila=number))
            elif _units(normalized) > 12:
                issues.append(_issue('CLAVE_LARGA', 'Codigo de proyecto mayor que 12 unidades UTF-16.', fila=number))
            elif normalized != normalized.strip() or any(ord(c) < 32 for c in normalized):
                issues.append(_issue('CLAVE_ESPACIOS_INVALIDOS', 'Codigo con espacios iniciales o controles.', fila=number))
            row = {'co_proyecto': normalized, 'co_proyecto_original': code,
                   'no_proyecto': raw['no_proyecto'], 'de_proyecto': raw.get('de_proyecto'),
                   'es_registro': raw.get('es_registro'),
                   'tiene_fecha_eliminacion': raw.get('fe_eliminacion') is not None}
            result['filas'].append(row)
    counts = Counter(r['co_proyecto'].casefold() for r in result['filas'] if r['co_proyecto'])
    for code, count in sorted(counts.items()):
        if count > 1:
            issues.append(_issue('CLAVE_DUPLICADA', 'Codigo repetido sin distinguir mayusculas.',
                                 co_proyecto=code, repeticiones=count))
    if not result['filas']:
        issues.append(_issue('PADRE_VACIO', 'La tabla padre no contiene proyectos.'))
    for row in result['filas']:
        if row['tiene_fecha_eliminacion']:
            result['advertencias'].append(_issue('PROYECTO_CON_FECHA_ELIMINACION',
                'El proyecto conserva una fecha de eliminacion; revisar su estado antes de cargar.',
                co_proyecto=row['co_proyecto']))
    result['verificado'] = not issues
    return result


def _norm(value):
    value = unicodedata.normalize('NFKD', str(value or '')).casefold()
    value = ''.join(c for c in value if not unicodedata.combining(c))
    return ' '.join(re.findall(r'[a-z0-9]+', value))


def _source_label(filename):
    label = filename[:-4] if filename.casefold().endswith('.kmz') else filename
    label = re.sub(r'\s*\(\d+\)$', '', label)
    return re.sub(r'^proyecto\s+', '', label, flags=re.IGNORECASE)


def candidates(filename, rows):
    """Sugerencias explicables por nombres; no calcula probabilidades ni confirma."""
    source = _norm(_source_label(filename))
    compact = source.replace(' ', '')
    words = {w for w in source.split() if not w.isdigit()
             and w not in {'g1', 'g2', 'g3', 'g4', 'lt', 'kv', 'se', 'y', 'de', 'enlace', 'enlaces'}}
    found = []
    for row in rows:
        reasons = []
        exact = False
        for field in ('no_proyecto', 'de_proyecto'):
            target = _norm(row.get(field))
            if not compact or not target:
                continue
            if compact == target.replace(' ', ''):
                reasons.append('COINCIDENCIA_NOMBRE_NORMALIZADO:' + field)
                exact = True
            elif len(compact) >= 4 and compact in target.replace(' ', ''):
                reasons.append('NOMBRE_INCLUIDO:' + field)
            elif words and words <= set(target.split()):
                reasons.append('TERMINOS_COMPARTIDOS:' + field)
        if reasons:
            found.append({'co_proyecto': row.get('co_proyecto'),
                          'no_proyecto': row.get('no_proyecto'),
                          'de_proyecto': row.get('de_proyecto'),
                          'es_registro': row.get('es_registro'),
                          'tiene_fecha_eliminacion': row.get('tiene_fecha_eliminacion', False),
                          'motivos': reasons, 'coincidencia_exacta_normalizada': exact,
                          'confirmado': False})
    return sorted(found, key=lambda r: (not r['coincidencia_exacta_normalizada'], str(r['co_proyecto'])))


def _read_mapping(path, known):
    data = Path(path).read_bytes()
    text = data.decode('utf-8-sig')
    if not text.strip():
        raise ValueError('El CSV de proyectos esta vacio.')
    delimiter = ';' if ';' in text.splitlines()[0] else ','
    reader = csv.DictReader(io.StringIO(text, newline=''), delimiter=delimiter, strict=True)
    headers = reader.fieldnames or []
    if len(headers) != len(set(headers)) or not set(CSV_COLUMNS) <= set(headers):
        raise ValueError('El CSV debe tener encabezados unicos archivo_kmz, co_proyecto y confirmado.')
    rows, issues = {}, []
    for number, row in enumerate(reader, 2):
        if None in row or any(row[k] is None for k in CSV_COLUMNS):
            issues.append(_issue('CSV_FILA_INVALIDA', 'Fila CSV con numero de valores incompatible.', fila=number))
            continue
        filename = row['archivo_kmz']
        if filename not in known:
            issues.append(_issue('CSV_ARCHIVO_DESCONOCIDO', 'El archivo no es un nombre canonico del perfil.',
                                 archivo_kmz=filename, fila=number))
            continue
        if filename in rows:
            issues.append(_issue('CSV_ARCHIVO_DUPLICADO', 'Mas de una fila para el mismo KMZ.',
                                 archivo_kmz=filename, fila=number))
            continue
        flag = _norm(row['confirmado'])
        if flag not in {'', 'si', 'true', '1', 'no', 'false', '0'}:
            issues.append(_issue('CSV_CONFIRMACION_INVALIDA', 'confirmado debe ser si o no.',
                                 archivo_kmz=filename, fila=number))
            continue
        rows[filename] = {'co_proyecto': row['co_proyecto'], 'confirmado': flag in {'si', 'true', '1'}}
    return rows, issues, hashlib.sha256(data).hexdigest()


def plan_projects(expected_sources, catalog, mapping_csv=None):
    """Construir plan consultivo de 13 (o N) archivos canonicos del perfil.

    ``expected_sources`` admite nombres o diccionarios con ``archivo``. Resultado:
    ``asociaciones``, ``plantilla_csv``, ``incidencias``, ``confirmados``,
    ``pendientes`` y ``verificado``. Una coincidencia de nombre siempre queda
    PROPUESTA_SIN_CONFIRMAR; solo el CSV puede producir CONFIRMADO_CSV.
    """
    names = [s if isinstance(s, str) else s['archivo'] for s in expected_sources]
    if len(names) != len(set(names)) or not names:
        raise ValueError('Lista de fuentes canonicas vacia o duplicada.')
    issues = list(catalog.get('incidencias', []))
    result = {'tabla': catalog.get('tabla'), 'asociaciones': [], 'plantilla_csv': [],
              'incidencias': issues, 'advertencias': list(catalog.get('advertencias', [])),
              'verificado': False, 'confirmados': 0, 'pendientes': len(names),
              'mapping_csv': str(mapping_csv) if mapping_csv else None,
              'mapping_sha256': None, 'cambios_en_sde': False}
    mappings = {}
    if mapping_csv:
        try:
            mappings, csv_issues, result['mapping_sha256'] = _read_mapping(mapping_csv, set(names))
            issues.extend(csv_issues)
        except (OSError, ValueError, UnicodeError, csv.Error) as exc:
            issues.append(_issue('CSV_NO_VALIDO', str(exc)))
    codes = {r['co_proyecto']: r for r in catalog.get('filas', []) if r.get('co_proyecto')}
    for filename in names:
        options = candidates(filename, catalog.get('filas', []))
        mapped = mappings.get(filename, {})
        entry = {'archivo_kmz': filename, 'co_proyecto': None, 'confirmado': False,
                 'estado': 'PROPUESTA_SIN_CONFIRMAR' if options else 'SIN_CANDIDATO',
                 'candidatos': options, 'evidencia': None}
        code = mapped.get('co_proyecto', '')
        if mapped.get('confirmado'):
            if not catalog.get('verificado'):
                entry['estado'] = 'CATALOGO_NO_VALIDADO'
            elif not code or code not in codes:
                entry['estado'] = 'CODIGO_NO_EXISTE'
                issues.append(_issue('CSV_CODIGO_NO_EXISTE', 'Codigo confirmado no presente exactamente en la tabla padre.',
                                     archivo_kmz=filename, co_proyecto=code))
            else:
                entry.update({'co_proyecto': code, 'confirmado': True, 'estado': 'CONFIRMADO_CSV',
                              'evidencia': {'archivo_csv': str(mapping_csv), 'sha256': result['mapping_sha256'],
                                            'nombre_padre': codes[code].get('no_proyecto')}})
                result['confirmados'] += 1
        if not entry['confirmado']:
            issues.append(_issue('ASOCIACION_PROYECTO_PENDIENTE',
                'Se necesita correspondencia explicita con un co_proyecto existente; no se genera un codigo.',
                archivo_kmz=filename))
        result['asociaciones'].append(entry)
        result['plantilla_csv'].append({'archivo_kmz': filename, 'co_proyecto': code,
            'confirmado': 'si' if entry['confirmado'] else 'no',
            'codigos_candidatos': '|'.join(str(c['co_proyecto']) for c in options),
            'nombres_candidatos': ' | '.join(str(c['no_proyecto'] or '') for c in options)})
    result['pendientes'] = len(names) - result['confirmados']
    result['verificado'] = bool(catalog.get('verificado')) and not issues and result['pendientes'] == 0
    return result
