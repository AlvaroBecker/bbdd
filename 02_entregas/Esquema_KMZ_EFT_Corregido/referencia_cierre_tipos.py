"""Referencia cerrada del lote 1.9: modelo 11 -> 12; sin ArcPy ni escrituras."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE_NAME = 'esquema_anterior_1_8.json'
CONFIG_NAME = 'cierre_tipos_1_9.json'
MODEL11_SHA = '7e4640548a87ef8775884c5ab510196ae5e88d382fe8ca068fb7bffe6eaea626'
PROFILE18_SHA = '28088388a8dbe1973568c0e5ba9eabc42c2abdfd912f66e3965142fffd8b25c4'
NUMERIC = {
    ('sitios_arqueologicos_poligono_recorte', 'alt_mode'): 'LONG',
    ('sitios_arqueologicos_poligono_recorte', 'clamped'): 'LONG',
    ('sitios_arqueologicos_poligono_recorte', 'extruded'): 'LONG',
    ('sitios_arqueologicos_poligono_recorte', 'base'): 'DOUBLE',
    ('sitios_arqueologicos_punto_recorte', 'alt_mode'): 'LONG',
    ('sitios_arqueologicos_punto_recorte', 'has_label'): 'LONG',
    ('sitios_arqueologicos_punto_recorte', 'base'): 'DOUBLE',
    ('suelos_recorte', 'p_aui_suel'): 'LONG',
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def definitions(model):
    classes = model.get('clases', [])
    fields = {(c['nombre'], f['nombre']): f for c in classes for f in c['campos']}
    require(len(classes) == len({c['nombre'] for c in classes}) == 76,
            'El cierre conserva exactamente 76 clases.')
    require(len(fields) == sum(len(c['campos']) for c in classes) == 3340,
            'El cierre conserva exactamente 3340 definiciones de campos.')
    return fields


def target_model(base):
    """Transformacion determinista: 730 confirmaciones y solo ocho tipos fisicos."""
    require(base.get('version') == 11, 'El origen del cierre debe ser el modelo 11.')
    target = copy.deepcopy(base)
    fields = definitions(target)
    pending = {key for key, f in fields.items() if 'pendiente' in f.get('origen', '').lower()}
    require(len(pending) == 730 and set(NUMERIC) <= pending,
            'El cierre requiere los 730 pendientes originales y los ocho candidatos numericos.')
    for key in pending:
        field = fields[key]
        require(field['tipo'] == 'TEXT' and field['longitud'] == 4000
                and field['nullable'] is True and not field.get('dominio') and field.get('campo_fuente'),
                'Campo de origen fuera del alcance del cierre: ' + '.'.join(key))
        typ = NUMERIC.get(key, 'TEXT')
        field.update(tipo=typ, longitud=4000 if typ == 'TEXT' else None, tipo_confirmado=True,
            origen=('Atributo KMZ; almacenamiento TEXT confirmado por decision conservadora 1.9'
                if typ == 'TEXT' else 'Atributo KMZ; tipo ' + typ + ' confirmado por declaracion KML y cierre 1.9'))
    target['version'] = 12
    return target


def changes():
    return [dict(clase=cls, campo=field, tipo_anterior='TEXT', longitud_anterior=4000,
                 tipo_objetivo=typ, longitud_objetivo=None)
            for (cls, field), typ in sorted(NUMERIC.items())]


def read_reference(model_dir=None):
    folder = Path(model_dir or HERE)
    base_raw = (folder / BASE_NAME).read_bytes()
    target_raw = (folder / 'esquema.json').read_bytes()
    config = json.loads((folder / CONFIG_NAME).read_text(encoding='utf-8-sig'))
    require(sha(base_raw) == MODEL11_SHA, 'El modelo 11 de referencia fue modificado.')
    base, target = json.loads(base_raw), json.loads(target_raw)
    require(config.get('version_paquete') == '1.9' and config.get('version_modelo') == 12
            and config.get('version_modelo_origen') == 11 and config.get('aprobado') is True,
            'Falta la decision autorizada de cierre 1.9 / modelo 12.')
    require(config.get('modelo_origen_sha256') == MODEL11_SHA
            and config.get('modelo_objetivo_sha256') == sha(target_raw),
            'Los hashes del modelo no coinciden con el cierre autorizado.')
    require(target == target_model(base),
            'El modelo 12 contiene diferencias ajenas a las 730 confirmaciones y ocho tipos.')
    require(config.get('cambios_fisicos') == changes(), 'El lote fisico no coincide con los ocho cambios autorizados.')
    require(config.get('campos_confirmados') == 730 and config.get('textos_confirmados') == 722
            and config.get('campos_pendientes_antes') == 730 and config.get('campos_pendientes_despues') == 0,
            'Los contadores del cierre no corresponden al lote autorizado.')
    profile_raw = (folder / 'PERFIL_COMPLETO_KMZ_1_8.json').read_bytes()
    require(config.get('perfil_origen_sha256') == PROFILE18_SHA == sha(profile_raw),
            'El perfil original 1.8 no coincide con la evidencia revisada.')
    profile = json.loads(profile_raw)['perfil']
    require(profile['estado'] == 'LECTURA_COMPLETA'
            and profile['conteos']['kmz_leidos'] == 13
            and profile['conteos']['rutas_coincidentes'] == 3638
            and profile['conteos']['elementos_observados'] == 279623
            and profile['conteos']['vinculos_campos_sin_observar'] == 0,
            'El cierre requiere evidencia completa de los 13 KMZ.')
    original = definitions(base)
    proposed = definitions(target)
    pending = {key for key, f in original.items() if 'pendiente' in f.get('origen', '').lower()}
    rows = config.get('campos', [])
    by_key = {(r['clase'], r['campo']): r for r in rows}
    require(len(rows) == len(by_key) == 730 and set(by_key) == pending,
            'La lista de decisiones debe cubrir exactamente los 730 pendientes originales.')
    evidence = {(r['clase'], r['campo']): r for r in profile['campos_destino']}
    for key, row in by_key.items():
        typ = NUMERIC.get(key, 'TEXT')
        require(row.get('tipo_objetivo') == proposed[key]['tipo'] == typ
                and row.get('longitud_objetivo') == proposed[key]['longitud']
                and row.get('aprobado') is True
                and row.get('cambio_fisico') is (key in NUMERIC),
                'Decision incompatible con el alcance: ' + '.'.join(key))
        stats = evidence.get(key)
        require(stats and stats['cobertura'] == 'COMPLETA_RUTAS_DEL_CAMPO'
                and stats['max_utf16'] <= 4000,
                'Evidencia o capacidad insuficiente: ' + '.'.join(key))
        if typ != 'TEXT':
            declared = 'int' if typ == 'LONG' else 'double'
            flags = stats['validacion_valores']
            require(set(stats['tipos_declarados']) == {declared}
                    and not stats['valores_sin_tipo'] and not stats['conflictos']
                    and stats['valores_utiles'] > 0 and not stats['marcadores']
                    and not flags.get('no_numericos') and not flags.get('ceros_iniciales'),
                    'El candidato numerico no conserva su evidencia completa: ' + '.'.join(key))
            if typ == 'LONG':
                require(not flags.get('fuera_long') and not flags.get('fraccionarios'),
                        'Entero fuera de rango o con fracciones: ' + '.'.join(key))
            else:
                require(not flags.get('double_no_finito') and not flags.get('no_finitos')
                        and not flags.get('double_roundtrip_diferente') and stats['max_significant'] <= 15,
                        'Decimal no representable sin la revision requerida: ' + '.'.join(key))
    required_blocks = {'NULOS_LITERAL', 'OFICINA_REGISTRAL', 'RUTAS_SIN_DESTINO',
                       'G1_SIN_COMPROBAR_EN_CT6788', 'DATASETS_RESTANTES'}
    require({b.get('codigo') for b in config.get('bloqueos_ingesta', [])} == required_blocks
            and all(b.get('resuelto') is False for b in config['bloqueos_ingesta'])
            and config.get('ingesta_autorizada') is False,
            'El cierre no puede ocultar ni resolver automaticamente los bloqueos de ingesta.')
    require(not any('pendiente' in f.get('origen', '').lower() for f in proposed.values()),
            'Persisten campos con tipo provisional en el modelo objetivo.')
    return base, target, config
