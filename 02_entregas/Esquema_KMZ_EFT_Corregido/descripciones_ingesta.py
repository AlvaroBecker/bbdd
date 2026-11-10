"""Reglas de conservación de description apoyadas en lectura completa del origen.

No descarta HTML, no interpreta una fotografía como texto cargado y no modifica
los campos. La evidencia solo es aplicable con los mismos bytes de los KMZ.
"""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load_plan(base=None, *, current_sources_verified=False):
    base = Path(base or HERE)
    plan = json.loads((base / 'descripciones_1_13.json').read_text(encoding='utf-8-sig'))
    for name, expected in plan['referencias_sha256'].items():
        if Path(name).name != name:
            raise ValueError('Referencia de descripcion fuera del paquete.')
        if hashlib.sha256((base / name).read_bytes()).hexdigest() != expected:
            raise ValueError('Referencia de descripciones modificada: ' + name)
    keys = [(r['archivo'], r['ruta'], r['geometria']) for r in plan['rutas']]
    if len(keys) != len(set(keys)):
        raise ValueError('Rutas de description duplicadas.')
    if sum(r['registros_con_description'] for r in plan['rutas']) != plan['resumen']['registros']:
        raise ValueError('Conteos de description inconsistentes.')
    for row in plan['rutas']:
        row['evidencia_actual_verificada'] = bool(current_sources_verified)
        row['estado_efectivo'] = row['estado_regla'] if current_sources_verified else 'FUENTES_NO_VERIFICADAS'
        row['aplicada'] = False
    plan['ingesta_autorizada'] = False
    plan['cambios_en_sde'] = False
    return plan


def preserve_plain_text(value, spec, existing=None):
    """Conversión sin pérdida para un mapeo específico ya elegido por el llamador.

Esta función no elige campo por semejanza. No trunca ni sustituye valores,
no elimina tildes del contenido y no se usa para descomponer HTML.
"""
    if not isinstance(value, str) or spec.get('tipo') != 'TEXT':
        raise ValueError('La conservación de description requiere texto y campo TEXT.')
    length = spec.get('longitud')
    if not isinstance(length, int) or len(value.encode('utf-16-le')) // 2 > length:
        raise ValueError('description excede la capacidad del campo; no se trunca.')
    if existing is not None and existing != value:
        raise ValueError('Colisión de description con un valor existente; no se sobrescribe.')
    return value
