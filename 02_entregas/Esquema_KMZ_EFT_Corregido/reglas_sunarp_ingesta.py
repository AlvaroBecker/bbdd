"""Equivalencias SUNARP 1.13: lectura y asignacion en memoria, sin ArcPy.

API del lector futuro::

    rules = load_rules()
    validate_references(rules)  # una vez, antes de leer/cargar registros
    source = dict(archivo=..., miembro='doc.kml', ruta=..., geometria=...,
                  sha256=...)  # SHA calculado sobre el KMZ, una vez por archivo
    result = resolve_record(rules, source, attributes)

``attributes`` conserva el orden original de las tuplas de cinco elementos de
``inspeccion_kmz.attributes``: etiqueta, valor, tipo, schema, canal. Tambien admite
diccionarios con etiqueta/valor/canal. No pasar un dict etiqueta->valor, pues ya
habria perdido las ocurrencias repetidas. ``indices_consumidos`` identifica los
atributos que el mapeador general debe omitir; ``asignaciones`` contiene SOLO las
oficinas resueltas. No se alteran argumentos, valores, archivos ni base de datos.

``existing`` es un mapa de destinos YA asignados, no una plantilla con columnas
nulas. Cualquier destino ocupado causa error incluso si coincide el valor: el
llamante debe resolver la procedencia, nunca sobrescribirla silenciosamente.

La comprobacion de referencias es independiente para evitar recalcular hashes
por registro. ``resolve_record`` exige el hash del KMZ calculado por el lector;
comparar solo un hash suministrado no sustituye leer/verificar el archivo fuente.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from typing import Mapping


CONFIG = 'reglas_sunarp_1_13.json'
CLASS = 'predios_inscritos_sunarp_recorte'
FIELDS = {'oficina', 'oficina_registral', 'oficina_re', 'oficina_1'}
LABELS = {'OFICINA', 'OFICINA REGISTRAL', 'OFICINA_RE', 'OFICINA__1'}


class SunarpRuleError(ValueError):
    """Error bloqueante con codigo estable para el informe del llamante."""
    def __init__(self, code, message):
        self.code = code
        super().__init__(f'{code}: {message}')


def require(condition, code, message):
    if not condition:
        raise SunarpRuleError(code, message)


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _valid_sha(value):
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None


def _text(value):
    return isinstance(value, str) and bool(value)


def _validate_rules(rules):
    require(isinstance(rules, dict), 'CONFIG_INVALIDA', 'Se esperaba una configuracion JSON.')
    require(rules.get('version') == '1.13' and rules.get('clase') == CLASS,
            'CONFIG_INVALIDA', 'Version o clase no reconocida.')
    fields = rules.get('campos_existentes')
    require(isinstance(fields, dict) and set(fields) == FIELDS
            and all(isinstance(field, dict) for field in fields.values()),
            'CONFIG_INVALIDA', 'Deben conservarse los cuatro destinos existentes.')
    sources = rules.get('fuentes', [])
    require(isinstance(sources, list) and len(sources) == 8
            and all(isinstance(source, dict) for source in sources),
            'CONFIG_INVALIDA', 'Se requieren las ocho fuentes verificadas.')
    names = [source.get('archivo') for source in sources]
    require(all(_text(name) for name in names) and len(set(names)) == len(names)
            and all(_valid_sha(source.get('sha256')) for source in sources),
            'CONFIG_INVALIDA', 'Fuentes duplicadas o hashes invalidos.')
    rows = rules.get('equivalencias', [])
    require(isinstance(rows, list) and len(rows) == 16,
            'CONFIG_INVALIDA', 'Se requieren las 16 equivalencias verificadas.')
    seen = set()
    changes = []
    routes = set()
    for row in rows:
        require(isinstance(row, dict), 'CONFIG_INVALIDA', 'Equivalencia invalida.')
        label, occurrence = row.get('etiqueta_original'), row.get('ocurrencia')
        require(label in LABELS and type(occurrence) is int and occurrence > 0,
                'CONFIG_INVALIDA', 'Etiqueta u ocurrencia no reconocida.')
        target = (('oficina_registral' if occurrence == 1 else 'oficina_1')
                  if label == 'OFICINA REGISTRAL' else
                  {'OFICINA': 'oficina', 'OFICINA_RE': 'oficina_re',
                   'OFICINA__1': 'oficina_1'}[label])
        require(occurrence in ({1, 2} if label == 'OFICINA REGISTRAL' else {1})
                and row.get('campo_destino_existente') == target,
                'CONFIG_INVALIDA', 'La equivalencia alteraria un destino verificado.')
        require(row.get('archivo') in names and _text(row.get('ruta'))
                and _text(row.get('geometria')) and row.get('canal') == 'HTML'
                and row.get('miembros') == ['doc.kml'],
                'CONFIG_INVALIDA', 'Identidad o canal de equivalencia invalido.')
        role = 'oficina_persona_juridica' if target == 'oficina_1' else 'oficina_inmueble'
        require(row.get('rol_semantico') == role, 'CONFIG_INVALIDA', 'Rol inconsistente.')
        for key in ('contexto_anterior', 'contexto_posterior'):
            context = row.get(key)
            require(isinstance(context, list) and 1 <= len(context) <= 3
                    and all(_text(item) for item in context),
                    'CONFIG_INVALIDA', 'Contexto incompleto.')
        key = (row['archivo'], row['ruta'], row['geometria'], label, occurrence)
        require(key not in seen, 'CONFIG_INVALIDA', 'Equivalencia duplicada.')
        seen.add(key)
        routes.add(key[:3])
        if row.get('cambio_de_mapeo'):
            require(label == 'OFICINA REGISTRAL' and occurrence == 2,
                    'CONFIG_INVALIDA', 'Solo puede cambiarse la segunda oficina duplicada.')
            changes.append(row)
    require(len(routes) == 12 and len(changes) == 2,
            'CONFIG_INVALIDA', 'Debe haber 12 rutas y solo dos equivalencias corregidas.')
    return rules


def load_rules(path=None):
    """Lee la configuracion portable junto al modulo y valida su estructura."""
    path = Path(path) if path is not None else Path(__file__).with_name(CONFIG)
    try:
        rules = json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError) as exc:
        raise SunarpRuleError('CONFIG_ILEGIBLE', str(path)) from exc
    return _validate_rules(rules)


def validate_schema(rules, model):
    """Exige los cuatro destinos TEXT existentes; no propone ni ejecuta DDL."""
    _validate_rules(rules)
    require(isinstance(model, dict), 'ESQUEMA_INVALIDO', 'Modelo no reconocido.')
    declared_classes = model.get('clases')
    require(isinstance(declared_classes, list) and all(isinstance(item, dict) for item in declared_classes),
            'ESQUEMA_INVALIDO', 'La lista de clases es invalida.')
    classes = [item for item in declared_classes if item.get('nombre') == CLASS]
    require(len(classes) == 1, 'ESQUEMA_INVALIDO', 'Clase SUNARP ausente o duplicada.')
    declared = classes[0].get('campos', [])
    require(isinstance(declared, list) and all(isinstance(field, dict) for field in declared),
            'ESQUEMA_INVALIDO', 'La lista de campos es invalida.')
    for name, expected in rules['campos_existentes'].items():
        matches = [field for field in declared if field.get('nombre') == name]
        require(len(matches) == 1, 'ESQUEMA_INVALIDO', f'Destino ausente o duplicado: {name}.')
        field = matches[0]
        require(all(field.get(key) == expected.get(key)
                    for key in ('tipo', 'longitud', 'nullable', 'dominio', 'tipo_confirmado')),
                'ESQUEMA_INVALIDO', f'Definicion incompatible: {name}.')
        require(field.get('tipo') == 'TEXT' and field.get('longitud') == 4000
                and field.get('tipo_confirmado') is True,
                'ESQUEMA_INVALIDO', f'Destino TEXT confirmado requerido: {name}.')
    return {'estado': 'ESQUEMA_SUNARP_VERIFICADO', 'clase': CLASS,
            'campos': sorted(FIELDS), 'ddl': False}


def validate_references(rules, base_dir=None):
    """Verifica SHA de modelo, perfil y dos CSV locales una vez por ejecucion.

    Las rutas del equipo original no se usan. Los cuatro archivos deben estar
    en ``base_dir`` (por defecto, junto a este modulo), como en la entrega.
    """
    _validate_rules(rules)
    base = Path(base_dir) if base_dir is not None else Path(__file__).parent
    refs = rules.get('referencias', [])
    required = {'esquema.json', 'PERFIL_COMPLETO_KMZ_1_9.json',
                'campos_por_ruta.csv', 'mapeo_capas_revision.csv'}
    require(isinstance(refs, list) and len(refs) == len(required)
            and all(isinstance(ref, dict) for ref in refs)
            and {ref.get('archivo') for ref in refs} == required,
            'CONFIG_INVALIDA', 'Referencias incompletas o duplicadas.')
    verified = []
    for ref in refs:
        require(_valid_sha(ref.get('sha256')), 'CONFIG_INVALIDA', 'Hash de referencia invalido.')
        path = base / ref['archivo']
        try:
            actual = _sha256(path)
        except OSError as exc:
            raise SunarpRuleError('REFERENCIA_ILEGIBLE', ref['archivo']) from exc
        require(actual == ref['sha256'], 'REFERENCIA_CAMBIO', ref['archivo'])
        verified.append({'archivo': ref['archivo'], 'sha256': actual})
    try:
        model = json.loads((base / 'esquema.json').read_text(encoding='utf-8-sig'))
    except (OSError, ValueError) as exc:
        raise SunarpRuleError('ESQUEMA_INVALIDO', 'No se pudo leer el esquema.') from exc
    schema = validate_schema(rules, model)
    return {'estado': 'REFERENCIAS_SUNARP_VERIFICADAS', 'referencias': verified,
            'esquema': schema, 'carga_ejecutada': False}


def _route_rules(rules, source):
    require(isinstance(source, Mapping), 'IDENTIDAD_INVALIDA', 'Se requiere identidad de la fuente.')
    keys = ('archivo', 'miembro', 'ruta', 'geometria', 'sha256')
    require(all(_text(source.get(key)) for key in keys),
            'IDENTIDAD_INVALIDA', 'Falta archivo, miembro, ruta, geometria o SHA256.')
    references = [item for item in rules['fuentes'] if item['archivo'] == source['archivo']]
    require(len(references) == 1, 'IDENTIDAD_NO_VERIFICADA', 'Archivo fuera de las reglas SUNARP.')
    require(source['sha256'] == references[0]['sha256'],
            'FUENTE_CAMBIO', f'El SHA256 no coincide: {source["archivo"]}.')
    matches = [row for row in rules['equivalencias']
               if all(row[key] == source[key] for key in ('archivo', 'ruta', 'geometria'))
               and source['miembro'] in row['miembros']]
    require(bool(matches), 'IDENTIDAD_NO_VERIFICADA', 'Ruta, geometria o miembro no verificados.')
    return matches


def _attribute(item, index):
    if isinstance(item, Mapping):
        require(all(key in item for key in ('etiqueta', 'valor', 'canal')),
                'ATRIBUTOS_INVALIDOS', f'Atributo incompleto en indice {index}.')
        label, value, channel = item['etiqueta'], item['valor'], item['canal']
    else:
        require(isinstance(item, (tuple, list)) and len(item) == 5,
                'ATRIBUTOS_INVALIDOS', f'Tupla de atributo invalida en indice {index}.')
        label, value, _, _, channel = item
    require(isinstance(label, str) and isinstance(channel, str),
            'ATRIBUTOS_INVALIDOS', f'Etiqueta/canal invalidos en indice {index}.')
    return {'etiqueta': label, 'valor': value, 'canal': channel, 'indice': index}


def resolve_record(rules, source, attributes, existing=None):
    """Resuelve oficinas de UN registro con identidad y contexto exactos.

    Requiere las doce rutas verificadas; una ruta desconocida NO se considera
    vacia ni se resuelve por semejanza. Rechaza ocurrencias adicionales, canales
    distintos, contexto cambiado y destinos ocupados. Incluso valores iguales
    se devuelven por separado para conservar inmueble/persona juridica.
    """
    _validate_rules(rules)
    rows = _route_rules(rules, source)
    require(isinstance(attributes, (list, tuple)), 'ATRIBUTOS_INVALIDOS',
            'Los atributos deben conservar orden y duplicados en una lista.')
    require(existing is None or isinstance(existing, Mapping), 'ATRIBUTOS_INVALIDOS',
            'Las asignaciones previas deben ser un mapa de destinos ocupados.')
    previous = {} if existing is None else existing
    parsed = [_attribute(item, index) for index, item in enumerate(attributes)]
    offices = [item for item in parsed if 'oficina' in item['etiqueta'].casefold()]
    require(all(item['etiqueta'] in LABELS and item['canal'] == 'HTML' for item in offices),
            'OFICINA_NO_VERIFICADA', 'Etiqueta de oficina o canal inesperados.')
    actual_counts = Counter(item['etiqueta'] for item in offices)
    expected_counts = Counter(row['etiqueta_original'] for row in rows)
    require(actual_counts == expected_counts, 'OCURRENCIAS_INVALIDAS',
            'Las oficinas presentes no coinciden exactamente con la ruta verificada.')
    html = [item for item in parsed if item['canal'] == 'HTML']
    html_indices = {item['indice']: position for position, item in enumerate(html)}
    counts, assignments, trace = Counter(), {}, []
    consumed = []
    for office in offices:
        label = office['etiqueta']
        counts[label] += 1
        candidates = [row for row in rows if row['etiqueta_original'] == label
                      and row['ocurrencia'] == counts[label]]
        require(len(candidates) == 1, 'OCURRENCIAS_INVALIDAS', 'Ocurrencia sin equivalencia unica.')
        row = candidates[0]
        position = html_indices[office['indice']]
        before = [item['etiqueta'] for item in html[max(0, position - 3):position]]
        after = [item['etiqueta'] for item in html[position + 1:position + 4]]
        require(before == row['contexto_anterior'] and after == row['contexto_posterior'],
                'CONTEXTO_CAMBIO', f'Contexto no verificado: {label}, ocurrencia {counts[label]}.')
        target, value = row['campo_destino_existente'], office['valor']
        require(target not in previous and target not in assignments,
                'DESTINO_OCUPADO', f'No se sobrescribe {target}.')
        require(value is None or isinstance(value, str), 'VALOR_INVALIDO',
                f'La oficina debe conservarse como texto original: {target}.')
        try:
            length = 0 if value is None else len(value.encode('utf-16-le')) // 2
        except UnicodeEncodeError as exc:
            raise SunarpRuleError('VALOR_INVALIDO', f'Unicode invalido: {target}.') from exc
        require(length <= rules['campos_existentes'][target]['longitud'],
                'LONGITUD_EXCEDIDA', f'No se trunca el texto de {target}.')
        assignments[target] = value
        consumed.append(office['indice'])
        trace.append({'indice': office['indice'], 'etiqueta_original': label,
                      'ocurrencia': counts[label], 'canal': 'HTML',
                      'campo_destino': target, 'rol_semantico': row['rol_semantico'],
                      'cambio_de_mapeo': row['cambio_de_mapeo']})
    return {'estado': 'OFICINAS_SUNARP_RESUELTAS', 'clase': CLASS,
            'asignaciones': assignments, 'indices_consumidos': consumed,
            'trazabilidad': trace,
            'roles': {item['rol_semantico']: item['campo_destino'] for item in trace},
            'ddl': False, 'carga_ejecutada': False}
