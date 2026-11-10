"""Aplica la politica 1.6 a modelos y mapeos generados, sin editar fuentes.

El esquema 1.5.1 distribuido es la referencia inmutable para la migracion.
Solo se cambian nombres de clases, sus aliases y referencias explicitas a
clases; atributos, descripciones originales y decisiones de tipos se conservan.
"""
from __future__ import annotations

import copy
import csv
import hashlib
import json
from pathlib import Path
import zipfile

from nombres_clases_kmz import NAMES, VERSION, final_name, policy_rows


BASELINE_SHA256 = '3a819d55272930e3bc812ca278a58acfa18adecce61791350d9354af2a5e793d'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def load_baseline(root, output):
    """Extrae una copia exacta del ZIP distribuido; nunca reemplaza una distinta."""
    archive_path = Path(root) / '02_entregas/Datos_Proyecto_Controlado_v1_5_1.zip'
    with zipfile.ZipFile(archive_path) as archive:
        raw = archive.read('esquema.json')
    if sha(raw) != BASELINE_SHA256:
        raise ValueError('El esquema del ZIP 1.5.1 no coincide con la referencia distribuida.')
    target = Path(output) / 'esquema_anterior_1_5_1.json'
    if target.exists():
        if target.read_bytes() != raw:
            raise ValueError('El esquema anterior guardado fue modificado; no se reemplaza.')
    else:
        with target.open('xb') as stream:
            stream.write(raw)
    return json.loads(raw.decode('utf-8-sig')), raw


def apply_model_policy(model):
    rows = policy_rows(model)
    aliases = {row['nombre_nuevo']: row['alias'] for row in rows}
    result = copy.deepcopy(model)
    result['version'] = 10
    result['politica_nombres'] = (
        'snake_case; clases descriptivas sin hashes ni palabras prescindibles; '
        'nombres nativos de ArcGIS, datasets EFT y DDL conservados')
    for cls in result['clases']:
        cls['nombre'] = final_name(cls['nombre'])
        alias = aliases[cls['nombre']]
        if alias is not None:
            cls['alias'] = alias
    for relation in result['relaciones']:
        relation['destino'] = final_name(relation['destino'])
        if relation['origen'] in NAMES or relation['origen'] in NAMES.values():
            relation['origen'] = final_name(relation['origen'])
        relation['nombre'] = 'rel_proy_' + relation['destino']
        if len(relation['nombre']) > 64:
            raise ValueError('Nombre de relacion excede el limite de la politica: ' + relation['nombre'])
    for relation in result['relaciones_negocio']:
        for key in ('origen', 'destino'):
            if relation[key] in NAMES or relation[key] in NAMES.values():
                relation[key] = final_name(relation[key])
    return result, rows


def retarget_rows(rows, columns, list_columns=()):
    """Retarget de columnas enumeradas: no reemplaza texto libre ni origen."""
    result = copy.deepcopy(rows)
    for row in result:
        for column in columns:
            if row.get(column):
                row[column] = final_name(row[column])
        for column in list_columns:
            if row.get(column):
                row[column] = ' | '.join(sorted(final_name(value.strip())
                    for value in row[column].split('|') if value.strip()))
    return result


def retarget_approval(config, model_version=10):
    """Mantiene aprobacion/evidencias de tipos 1.5 con referencias fisicas 1.6."""
    result = copy.deepcopy(config)
    result['version_modelo'] = model_version
    result['normalizacion_nombres_version'] = VERSION
    reverse = {new: old for old, new in NAMES.items()}
    seen = set()
    for change in result['cambios']:
        current = change['clase']
        original = current if current in NAMES else reverse.get(current)
        if original is None:
            raise ValueError('Cambio aprobado refiere una clase desconocida: ' + current)
        if 'clase_anterior' in change and change['clase_anterior'] != original:
            raise ValueError('La clase anterior de la aprobacion no coincide con el mapeo.')
        change['clase_anterior'] = original
        change['clase'] = final_name(current)
        key = (change['clase'], change['campo'])
        if key in seen:
            raise ValueError('Cambio de tipo duplicado tras normalizar nombres: ' + repr(key))
        seen.add(key)
    return result


def save_mapping(output, rows, before_raw, after_raw, model_version=10):
    result = dict(version_paquete=VERSION, version_modelo=model_version,
        autorizacion='Usuario: ok acepto las propuestas, asegurate de aplicar el formato a todas las tablas',
        modelo_anterior_sha256=sha(before_raw), modelo_objetivo_sha256=sha(after_raw),
        clases=rows)
    Path(output, 'nombres_clases_1_6.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    write_rows(Path(output, 'nombres_clases_1_6.csv'), rows)
    return result


def write_rows(path, rows):
    if not rows:
        raise ValueError('No se escribe un mapeo vacio.')
    with Path(path).open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), delimiter=';')
        writer.writeheader()
        writer.writerows(rows)


def retarget_existing_csv(path, columns):
    path = Path(path)
    with path.open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.DictReader(stream, delimiter=';'))
    write_rows(path, retarget_rows(rows, columns))
