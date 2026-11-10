"""Confirma una seleccion cerrada de tipos TEXT, sin conectar a ArcGIS ni a SDE.

La revision historica sigue siendo un borrador. La autorizacion posterior del
usuario se registra en una configuracion separada. Unicamente cambia el estado
de confirmacion de 1356 campos del modelo; su definicion fisica se conserva.
"""

import copy
import csv
import hashlib
import io
import json
from collections import Counter
from pathlib import Path, PureWindowsPath
import zipfile


ROOT = Path(__file__).resolve().parents[1]
REVIEW_RELATIVE = Path('02_entregas/Revision_Pendientes_2086/revision_pendientes_2086.json')
PROFILE_RELATIVE = Path('02_entregas/Revision_Tipos_Datos_Proyecto/revision_2185_campos.csv')
BASELINE_RELATIVE = Path('02_entregas/Datos_Proyecto_Controlado_v1_6_2.zip')
REVIEW_SHA256 = 'e8bb0d0c7dd6594820a8fc96c9f6a9ed7df70cf8349e66a24f4addaafceac95f'
REVIEW_CANONICAL_SHA256 = '4b054e357bfbd5c4c36334ee62394d1f8a317f2a51f08a90a2ee48113eef140d'
SOURCE_HASHES = {
    'revision_2185_campos.csv': 'd2b9afd9b541f8fc51597dedc200a66a9e38c5e15236786468cf5076fa3752e5',
    'esquema.json': '2f2a1348d6d5d45379a75f5fd857f215fce3873829261119b8185916b7a4217c',
    'nombres_clases_1_6.json': '2d10e23f2c418c01aa6b99cc80af093101ff50f6b00763a261229aa90ddb498a',
    'campos_aprobados_1_5.json': '1ee95c66de434366da24eac78eb37c94fa0c5d502a2c22dae20376732dbb4163',
    'PERFIL_GENERAL_ORIGEN.json': '649763fe759f514524bb30ad5af1407a045d23639fd58b24fd795e5ad4437a83',
}
MODEL10_SHA256 = SOURCE_HASHES['esquema.json']
PENDING_ORIGIN = 'Atributo KMZ; texto conservador pendiente de revision de tipo'
CONFIRMED_ORIGIN = 'Atributo KMZ; tipo TEXT confirmado por perfil y decision 1.7'
TEXT_GROUP = 'CANDIDATO_A_CONFIRMAR_TEXT'
TEXT_PROPOSALS = frozenset(('MANTENER_TEXT_CONTENIDO', 'MANTENER_TEXT_IDENTIFICADOR_O_ETIQUETA'))
GROUP_COUNTS = {
    TEXT_GROUP: 1356,
    'SIN_VALORES_UTILES': 187,
    'REVISAR_SIGNIFICADO_NUMERICO': 474,
    'REVISAR_FECHA_CON_VALORES': 47,
    'PRESERVAR_CEROS_Y_REVISAR_CODIGO': 21,
    'CONFLICTO_DE_MAPEO': 1,
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha_bytes(raw):
    return hashlib.sha256(raw).hexdigest()


def model_bytes(model):
    """Misma serializacion estable que el generador del esquema."""
    return json.dumps(model, ensure_ascii=False, indent=2).encode('utf-8')


def model_sha256(model):
    return sha_bytes(model_bytes(model))


def sha_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _review_rows(review):
    canonical = json.dumps(review, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    require(sha_bytes(canonical) == REVIEW_CANONICAL_SHA256,
            'La revision no coincide con el borrador historico autorizado; no se confirma ningun campo.')
    require(review['version_modelo'] == 10 and review['campos_pendientes'] == 2086,
            'Version o alcance de revision inesperados.')
    require(review['estado'] == 'BORRADOR_DE_REVISION_SIN_APROBACIONES'
            and review['cambios_en_modelo'] is False and review['cambios_en_sde'] is False,
            'La revision historica debe conservarse sin aprobaciones ni cambios.')
    rows = {(row['clase'], row['campo']): row for row in review['campos']}
    require(len(rows) == len(review['campos']) == 2086, 'Campos duplicados o alcance de revision incompleto.')
    require(dict(Counter(row['grupo_revision'] for row in rows.values())) == GROUP_COUNTS
            and review['grupos'] == GROUP_COUNTS, 'Los grupos de revision no coinciden con el alcance autorizado.')
    for row in rows.values():
        require(row['aprobado'] is False and row['cambio_fisico_propuesto'] is False,
                'El borrador historico no puede incorporar aprobaciones nuevas.')
        if row['grupo_revision'] == TEXT_GROUP:
            require(row['tipo_actual'] == 'TEXT' and row['longitud_actual'] == 4000
                    and row['valores_utiles'] > 0 and not row['bloqueos']
                    and row['propuesta_historica'] in TEXT_PROPOSALS
                    and row['cobertura'] == 'COMPLETA_RUTAS_DEL_CAMPO'
                    and 0 < row['longitud_maxima_utf16'] <= 4000,
                    f'Candidato TEXT no admisible: {row["clase"]}.{row["campo"]}.')
    require(rows[('predios_inscritos_sunarp_recorte', 'oficina_registral')]['grupo_revision']
            == 'CONFLICTO_DE_MAPEO', 'El conflicto de oficinas debe permanecer pendiente.')
    return rows


def _definitions(model):
    classes = model['clases']
    require(len(classes) == len({cls['nombre'] for cls in classes}) == 76,
            'El modelo debe conservar las 76 clases.')
    fields = {(cls['nombre'], field['nombre']): field for cls in classes for field in cls['campos']}
    require(len(fields) == sum(len(cls['campos']) for cls in classes) == 3340,
            'El modelo debe conservar los 3340 campos definidos, sin duplicados.')
    return fields


def _read_baseline(root):
    archive_path = root / BASELINE_RELATIVE
    if not archive_path.is_file():
        archive_path = root / '02_entregas/Datos_Proyecto_Controlado.zip'
    require(archive_path.is_file(), 'Falta el paquete historico 1.6.2 para verificar la referencia.')
    with zipfile.ZipFile(archive_path) as archive:
        require(len(archive.namelist()) == len(set(archive.namelist())), 'El ZIP historico contiene nombres duplicados.')
        manifest = json.loads(archive.read('MANIFIESTO_DATOS_PROYECTO.json'))
        require(manifest['version'] == '1.6.2' and manifest['version_modelo'] == 10,
                'La referencia debe ser el paquete 1.6.2, modelo 10.')
        payloads = {}
        for name, expected in SOURCE_HASHES.items():
            if name.endswith('.csv'):
                continue
            raw = archive.read(name)
            require(sha_bytes(raw) == expected and manifest['archivos'].get(name) == expected,
                    f'Integridad incorrecta en la referencia 1.6.2: {name}.')
            payloads[name] = json.loads(raw)
    return payloads


def _verify_profile(review, payloads, profile_raw):
    require(sha_bytes(profile_raw) == SOURCE_HASHES['revision_2185_campos.csv'],
            'El perfil historico de 2185 campos ha cambiado.')
    model = payloads['esquema.json']
    fields = _definitions(model)
    pending = {key: field for key, field in fields.items() if 'pendiente' in field.get('origen', '').lower()}
    review_rows = _review_rows(review)
    mapping = payloads['nombres_clases_1_6.json']['clases']
    translations = {row['nombre_anterior']: row['nombre_nuevo'] for row in mapping}
    require(len(mapping) == len(translations) == len(set(translations.values())) == 76,
            'El mapa historico de nombres debe conservar las 76 clases.')
    reader = csv.DictReader(io.StringIO(profile_raw.decode('utf-8-sig'), newline=''), delimiter=';')
    source_rows = list(reader)
    require(all(row['clase'] in translations for row in source_rows), 'El perfil incluye clases sin mapeo historico.')
    profile = {(translations[row['clase']], row['campo']): row for row in source_rows}
    approved_rows = payloads['campos_aprobados_1_5.json']['cambios']
    approved = {(row['clase'], row['campo']) for row in approved_rows}
    require(len(source_rows) == len(profile) == 2185 and len(approved_rows) == len(approved) == 99,
            'El cruce debe contener 2185 perfiles unicos y 99 cambios aprobados previos.')
    require(set(pending) == set(review_rows) and len(pending) == 2086
            and set(pending) <= set(profile) and set(profile) - set(pending) == approved
            and not set(pending) & approved, 'El cruce entre modelo, perfil y aprobaciones no coincide.')
    for key, row in review_rows.items():
        original = profile[key]
        values = {
            'clase_en_perfil': original['clase'],
            'tipo_actual': pending[key]['tipo'],
            'longitud_actual': pending[key]['longitud'],
            'propuesta_historica': original['propuesta'],
            'valores_utiles': int(original['numericos']) + int(original['otros_textos']),
            'registros_con_campo': int(original['registros_con_campo']),
            'vacios': int(original['vacios']),
            'marcadores_literales': int(original['marcadores_literales']),
            'longitud_maxima_utf16': int(original['longitud_maxima_utf16']),
            'ceros_iniciales': int(original['ceros_iniciales']),
            'digitos_significativos_max': int(original['digitos_significativos_max']),
            'cobertura': original['cobertura'],
            'bloqueos': original['bloqueos'],
            'fundamento': original['fundamento'],
        }
        require(all(row[name] == value for name, value in values.items())
                and not original['fuentes_ausentes'], f'Evidencia de perfil no coincidente: {key[0]}.{key[1]}.')


def load_verified_review(root=ROOT):
    """Lee evidencia original y verifica 13 KMZ; no lee ni escribe la conexion SDE.

    Las referencias del modelo se toman del ZIP historico, porque los archivos
    generados vigentes pueden haber avanzado ya al modelo 11. Se conserva la ruta
    relativa de cada KMZ dentro de 01_fuentes para permitir mover el proyecto.
    """
    root = Path(root).resolve()
    review_raw = (root / REVIEW_RELATIVE).read_bytes()
    require(sha_bytes(review_raw) == REVIEW_SHA256, 'La revision historica ha cambiado; SHA-256 incorrecto.')
    review = json.loads(review_raw)
    _review_rows(review)
    historical_sources = {PureWindowsPath(path).name: digest for path, digest in review['fuentes_sha256'].items()}
    require(len(historical_sources) == len(review['fuentes_sha256']) == len(SOURCE_HASHES)
            and historical_sources == SOURCE_HASHES, 'Las referencias SHA-256 de la revision no coinciden.')
    payloads = _read_baseline(root)
    _verify_profile(review, payloads, (root / PROFILE_RELATIVE).read_bytes())
    sources = payloads['PERFIL_GENERAL_ORIGEN.json']['fuentes']
    expected = [{'archivo': source['archivo'], 'sha256': source['sha256']} for source in sources]
    require(len(sources) == len({source['archivo'] for source in sources}) == 13
            and expected == review['kmz_verificados'], 'La lista de 13 fuentes KMZ no coincide.')
    source_root = (root / '01_fuentes').resolve()
    for source in sources:
        name = source['archivo']
        require(PureWindowsPath(name).name == name and Path(name).name == name, 'Nombre de fuente KMZ no valido.')
        parts = PureWindowsPath(source['ruta_lectura']).parts
        require(parts.count('01_fuentes') == 1 and parts[-1] == name, 'Ruta historica de fuente KMZ no valida.')
        relative = parts[parts.index('01_fuentes') + 1:]
        source_path = source_root.joinpath(*relative).resolve()
        require(source_path.is_relative_to(source_root) and source_path.is_file(), f'Falta la fuente KMZ original: {name}.')
        require(sha_file(source_path) == source['sha256'], f'SHA-256 no coincidente en KMZ: {name}.')
    return review


def apply_text_confirmation(model, review):
    """Devuelve modelo 11 y configuracion deterministas; no modifica las entradas.

    Admite el modelo 10 exacto y el modelo 11 producido por esta funcion. Cualquier
    otra modificacion se rechaza, incluidos cambios fisicos o aprobaciones extra.
    """
    review_rows = _review_rows(review)
    candidates = {key: row for key, row in review_rows.items() if row['grupo_revision'] == TEXT_GROUP}
    require(len(candidates) == 1356, 'La seleccion autorizada debe contener exactamente 1356 campos.')
    require(model.get('version') in (10, 11), 'Solo se admite el modelo 10 o el modelo 11 ya confirmado.')
    base = copy.deepcopy(model)
    definitions = _definitions(base)
    require(set(candidates) <= set(definitions), 'La revision incluye un campo o una clase ajenos al modelo.')
    if base['version'] == 11:
        for key in candidates:
            field = definitions[key]
            require(field.get('origen') == CONFIRMED_ORIGIN and field.get('tipo_confirmado') is True,
                    f'Confirmacion incompleta en modelo 11: {key[0]}.{key[1]}.')
            field['origen'] = PENDING_ORIGIN
            del field['tipo_confirmado']
        base['version'] = 10
    require(model_sha256(base) == MODEL10_SHA256, 'El modelo de origen no coincide con la referencia 1.6.2, modelo 10.')
    pending = {key for key, field in definitions.items() if 'pendiente' in field.get('origen', '').lower()}
    require(pending == set(review_rows), 'El conjunto pendiente debe coincidir con los 2086 campos revisados.')
    target = copy.deepcopy(base)
    target_fields = _definitions(target)
    for key in sorted(candidates):
        field = target_fields[key]
        require(field['tipo'] == 'TEXT' and field['longitud'] == 4000
                and field['origen'] == PENDING_ORIGIN and 'tipo_confirmado' not in field,
                f'El campo no conserva su definicion pendiente original: {key[0]}.{key[1]}.')
        field['origen'] = CONFIRMED_ORIGIN
        field['tipo_confirmado'] = True
    target['version'] = 11
    remaining = {key for key, field in target_fields.items() if 'pendiente' in field.get('origen', '').lower()}
    require(remaining == pending - set(candidates) and len(remaining) == 730,
            'Deben conservarse exactamente 730 campos pendientes fuera de esta aprobacion.')
    config = {
        'version_paquete': '1.7',
        'version_modelo': 11,
        'modelo_origen_sha256': MODEL10_SHA256,
        'modelo_objetivo_sha256': model_sha256(target),
        'revision_sha256': REVIEW_SHA256,
        'campos_confirmados': 1356,
        'campos_pendientes_antes': 2086,
        'campos_pendientes_despues': 730,
        'clases_modelo': 76,
        'campos_modelo': 3340,
        'confirmacion_solo_metadatos': True,
        'cambios_fisicos': False,
        'carga_de_datos': False,
        'aprobacion_usuario': {
            'texto': 'ok vamos con el siguiente paso',
            'alcance': 'Confirmacion de 1356 candidatos como TEXT; sin cambios fisicos ni carga de datos',
            'contexto': 'Continuacion de la revision de 2086 pendientes, despues de la validacion del modelo 10.',
        },
        'fuentes_sha256': copy.deepcopy(review['fuentes_sha256']),
        'kmz_verificados': copy.deepcopy(review['kmz_verificados']),
        'alcance_perfil': copy.deepcopy(review['alcance']),
        'grupos_excluidos': {name: count for name, count in GROUP_COUNTS.items() if name != TEXT_GROUP},
        'campos': [
            {
                'clase': key[0], 'campo': key[1], 'tipo': 'TEXT', 'longitud': 4000,
                'longitud_maxima_utf16': row['longitud_maxima_utf16'],
                'valores_utiles': row['valores_utiles'],
                'cobertura': row['cobertura'], 'propuesta_historica': row['propuesta_historica'],
            }
            for key, row in sorted(candidates.items())
        ],
    }
    return target, config
