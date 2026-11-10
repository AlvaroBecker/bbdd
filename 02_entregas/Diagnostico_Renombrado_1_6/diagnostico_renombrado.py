"""Diagnostico de solo lectura contra la evidencia original de nombres 1.6.

Nunca ejecuta el renombrador ni adopta el estado actual como referencia. Las
diferencias se conservan literalmente, incluidas las de alias y mayusculas.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
from types import SimpleNamespace
import uuid

import renombrar_clases as renamer
from ajustar_tipos_estructuras import properties

HERE = Path(__file__).resolve().parent
VERSION = '1.6-diagnostico-1'
INPUTS = (('esquema.json', 'modelo_sha256'),
          ('nombres_clases_1_6.json', 'mapeo_sha256'),
          ('campos_aprobados_1_5.json', 'aprobacion_tipos_sha256'))
CSV_COLUMNS = ('clase', 'ruta', 'seccion', 'elemento', 'propiedad',
               'tipo_cambio', 'antes_presente', 'despues_presente', 'antes', 'despues')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def normalized_path(path):
    return os.path.normcase(os.path.normpath(os.path.abspath(path)))


def read_reference(workspace, previous_report_path, database, owner, names=None):
    """Valida identidad, aprobaciones y referencia ANTES de acceder al destino."""
    require(all(isinstance(value, str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', value)
                for value in (database, owner)), 'Base de datos o propietario invalido.')
    path = Path(previous_report_path).resolve()
    raw = path.read_bytes()
    previous = json.loads(raw.decode('utf-8-sig'))
    require(isinstance(previous, dict), 'El informe original no es un objeto JSON.')
    require(previous.get('version_paquete') == '1.6'
            and previous.get('modo') == 'APLICAR_NOMBRES',
            'Seleccione el resultado.json original de Aplicar nombres aprobados 1.6.')
    require(isinstance(previous.get('workspace'), str)
            and normalized_path(previous['workspace']) == normalized_path(workspace),
            'El workspace no coincide con la conexion del informe original.')
    require(str(previous.get('database', '')).casefold() == database.casefold()
            and str(previous.get('owner', '')).casefold() == owner.casefold(),
            'La base de datos o el propietario no coinciden con el informe original.')
    loaded, hashes = {}, {}
    for filename, key in INPUTS:
        payload = (HERE / filename).read_bytes()
        hashes[key] = sha256(payload)
        require(previous.get(key) == hashes[key],
                f'{filename}: no coincide con la aprobacion del informe original ({key}).')
        loaded[filename] = json.loads(payload.decode('utf-8-sig'))
    model, mapping, config = (loaded[name] for name, _ in INPUTS)
    if mapping.get('modelo_objetivo_sha256'):
        require(mapping['modelo_objetivo_sha256'] == hashes['modelo_sha256'],
                'El modelo no corresponde al mapeo de nombres aprobado.')
    all_rows, _ = renamer.selected_mapping(model, mapping, config)
    rows_by_name = {row['nombre_nuevo']: row for row in all_rows}
    baseline = previous.get('campos_y_metadatos_antes')
    require(isinstance(baseline, dict) and bool(baseline),
            'El informe no contiene campos_y_metadatos_antes; no se reconstruye su referencia.')
    require(set(baseline) <= set(rows_by_name),
            'El informe contiene clases ajenas al mapeo aprobado.')
    require(names is None or not isinstance(names, str), 'Indique clases como lista.')
    selected = set(baseline) if names is None else set(names)
    require(bool(selected) and selected <= set(baseline),
            'La seleccion debe contener clases con referencia en el informe original.')
    for name in selected:
        before = baseline[name]
        require(isinstance(before, dict)
                and isinstance(before.get('campos'), dict) and bool(before['campos'])
                and all(isinstance(field, dict) for field in before['campos'].values())
                and isinstance(before.get('indices'), list)
                and isinstance(before.get('geometria'), dict),
                f'{name}: referencia original incompleta o mal formada.')
    rows = [rows_by_name[name] for name in sorted(selected)]
    return previous, raw, path, model, rows, hashes


def diff_properties(before, after, *, cls, path, section, element=''):
    """Diferencias por propiedad; claves ausentes no equivalen a valores nulos."""
    differences = []
    for key in sorted(set(before) | set(after)):
        had, has = key in before, key in after
        old, new = before.get(key), after.get(key)
        if had and has and type(old) is type(new) and old == new:
            continue
        differences.append(dict(clase=cls, ruta=path, seccion=section, elemento=element,
            propiedad=key, tipo_cambio='MODIFICADO' if had and has else 'AGREGADO' if has else 'ELIMINADO',
            antes_presente=had, despues_presente=has, antes=old, despues=new))
    return differences


def compare_fields(before, after, cls, path):
    result = []
    for field in sorted(set(before) | set(after)):
        if field not in before or field not in after:
            result += diff_properties({field: before[field]} if field in before else {},
                                      {field: after[field]} if field in after else {},
                                      cls=cls, path=path, section='campos', element=field)
        else:
            result += diff_properties(before[field], after[field], cls=cls, path=path,
                                      section='campos', element=field)
    return result


def index_snapshot(a, path):
    result = []
    for index in a.ListIndexes(path) or []:
        result.append(dict(nombre=index.name,
            campos=[renamer.runner.engine.field_base_name(field).casefold() for field in index.fields],
            unico=getattr(index, 'isUnique', None), ascendente=getattr(index, 'isAscending', None)))
    return sorted(result, key=lambda index: index['nombre'].casefold())


def compare_indexes(before, after, cls, path):
    # El orden de campos de un indice tambien forma parte de la comparacion.
    previous = {item['nombre']: item for item in before}
    current = {item['nombre']: item for item in after}
    if len(previous) != len(before) or len(current) != len(after):
        return diff_properties({'lista': before}, {'lista': after},
                               cls=cls, path=path, section='indices')
    result = []
    for name in sorted(set(previous) | set(current)):
        result += diff_properties(previous.get(name, {}), current.get(name, {}),
                                  cls=cls, path=path, section='indices', element=name)
    result += diff_properties({'orden_indices': [item['nombre'] for item in before]},
        {'orden_indices': [item['nombre'] for item in after]}, cls=cls, path=path, section='indices')
    return result


def raw_fields(fields):
    result = []
    for field in fields:
        default = getattr(field, 'defaultValue', None)
        result.append(dict(name=field.name, baseName=getattr(field, 'baseName', None),
            defaultValue_repr=repr(default), defaultValue_tipo_python=type(default).__name__))
    return result


def write_reports(folder, report):
    """Solo crea archivos nuevos en una carpeta unica; nunca reemplaza evidencia."""
    folder.mkdir(parents=False, exist_ok=False)
    report['archivo_resultado'] = str(folder / 'resultado.json')
    report['archivo_diferencias'] = str(folder / 'diferencias.csv')
    report['archivo_informe'] = str(folder / 'informe.md')
    with (folder / 'diferencias.csv').open('x', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, CSV_COLUMNS, delimiter=';')
        writer.writeheader()
        for row in report['diferencias']:
            values = dict(row)
            for key in ('antes', 'despues'):
                values[key] = json.dumps(values[key], ensure_ascii=False, sort_keys=True)
            writer.writerow(values)
    lines = ['# Diagnostico del renombrado 1.6', '',
        f"Estado: **{report['estado']}**", '',
        f"Referencia original: `{report['informe_original']}`",
        f"SHA-256: `{report['informe_original_sha256']}`", '',
        f"Clase detenida: `{report['clase_detenida_original']}`",
        f"Operacion original: `{report['operacion_detenida_original']}`", '',
        f"Clases seleccionadas: {len(report['clases'])}. Diferencias: {len(report['diferencias'])}. "
        f"Incidencias de lectura: {len(report['incidencias'])}.", '',
        'La herramienta solo lee metadatos y recuentos; no renombra ni modifica la geodatabase.',
        'Compara con el informe original, sin aceptar el estado actual como nueva referencia.',
        'Las diferencias de alias de campos se registran sin considerarlas inocuas.',
        'El alias de la clase y el avance del nombre se muestran por separado porque su cambio estaba previsto.',
        'El recuento de referencia es 0: la prevalidacion 1.6 exigia clases vacias; el informe no guardaba ese numero.',
        'SIN_DIFERENCIAS_ACTUALES no explica una diferencia transitoria anterior ni autoriza reanudar automaticamente.',
        'Este diagnostico no certifica integridad de filas, EFT completo, relaciones externas ni ausencia de cambios concurrentes.', '',
        'Ver todas las propiedades en diferencias.csv y la evidencia completa en resultado.json.', '']
    for incidence in report['incidencias']:
        lines.append(f"- {incidence['clase']} / {incidence['seccion']}: {incidence['error']}")
    with (folder / 'informe.md').open('x', encoding='utf-8') as stream:
        stream.write('\n'.join(lines) + '\n')
    with (folder / 'resultado.json').open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def run(workspace, previous_report_path, database='ArcGisAWS', owner='gis', reports=None,
        arcpy_module=None, emit=print, names=None):
    previous, raw, previous_path, model, rows, hashes = read_reference(
        workspace, previous_report_path, database, owner, names)
    output_parent = Path(reports or HERE).resolve()
    require(output_parent.is_dir(), 'La carpeta existente para informes no existe.')
    folder = output_parent / ('Diagnostico_Nombres_' + dt.datetime.now().strftime('%Y%m%d_%H%M%S')
                              + '_' + uuid.uuid4().hex[:12])
    args = SimpleNamespace(workspace=os.path.abspath(workspace), database=database,
                           owner=owner, aplicar=False)
    report = dict(version_diagnostico=VERSION, estado='DIAGNOSTICO_INCOMPLETO',
        modo='SOLO_LECTURA_CONTRA_INFORME_ORIGINAL', workspace=args.workspace,
        database=database, owner=owner, informe_original=str(previous_path),
        informe_original_sha256=sha256(raw), estado_original=previous.get('estado'),
        clase_detenida_original=previous.get('clase_en_curso'),
        operacion_detenida_original=previous.get('operacion_en_curso'),
        inicio_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
        cambios_en_geodatabase=0, reanudacion_automatica_autorizada=False,
        referencia_recuento='0, inferido del control obligatorio de clases vacias de la prevalidacion 1.6',
        clases={}, diferencias=[], incidencias=[], **hashes)
    before_all = previous['campos_y_metadatos_antes']
    plan_by_name = {item['nombre_nuevo']: item for item in previous.get('plan', [])}

    def incidence(cls, section, error):
        report['incidencias'].append(dict(clase=cls, seccion=section, error=str(error)))

    try:
        if arcpy_module is None:
            import arcpy as arcpy_module
        a = arcpy_module
        report['arcgis'] = a.GetInstallInfo().get('Version')
        require(a.Exists(args.workspace), 'El workspace del informe no existe o no es accesible.')
        with a.EnvManager(overwriteOutput=False, extent=None):
            inventory, _ = renamer.runner.engine.inspect(a, args, model, [])
            # Se atiende primero la clase donde se detuvo el proceso original.
            rows.sort(key=lambda row: (row['nombre_nuevo'] != report['clase_detenida_original'],
                                       row['nombre_nuevo']))
            for row in rows:
                cls, old = row['nombre_nuevo'], row['nombre_anterior']
                old_path, new_path = inventory.get(old.casefold()), inventory.get(cls.casefold())
                evidence = report['clases'][cls] = dict(antes=before_all[cls], despues={},
                    nombre_anterior=old, nombre_objetivo=cls, ruta_nombre_anterior=old_path,
                    ruta_nombre_objetivo=new_path, alias_objetivo=row['alias'],
                    plan_original=plan_by_name.get(cls), recuento_referencia=0)
                if old != cls and old_path and new_path:
                    incidence(cls, 'resolucion', 'Existen ambos nombres; no se elige ni modifica ninguno.')
                    continue
                path = new_path or old_path
                if path is None:
                    incidence(cls, 'resolucion', 'No se encuentra el nombre anterior ni el objetivo.')
                    continue
                evidence['ruta_actual'] = path
                actual = renamer.runner.engine.simple(os.path.basename(path))
                evidence['nombre_actual'] = actual
                evidence['nombre_objetivo_presente'] = bool(new_path)
                try:
                    description = a.Describe(path)
                    evidence['alias_actual'] = getattr(description, 'aliasName', None)
                    evidence['alias_objetivo_coincide'] = (row['alias'] is None
                        or evidence['alias_actual'] == row['alias'])
                    require(description.dataType == 'FeatureClass', 'El objeto actual no es una FeatureClass.')
                    require(renamer.runner.engine.simple(os.path.basename(description.path)).casefold()
                            == renamer.runner.DATASET.casefold(), 'La clase esta fuera de Datos_Proyecto.')
                    require(actual in (old, cls), 'La escritura del nombre actual no coincide exactamente con el mapeo.')
                except Exception as exc:
                    incidence(cls, 'identidad', exc)
                try:
                    fields = a.ListFields(path)
                    evidence['campos_crudos_actuales'] = raw_fields(fields)
                    evidence['despues']['campos'] = {key: properties(field)
                        for key, field in renamer.runner.engine.field_index(fields).items()}
                    report['diferencias'] += compare_fields(before_all[cls]['campos'],
                        evidence['despues']['campos'], cls, path)
                except Exception as exc:
                    incidence(cls, 'campos', exc)
                try:
                    indices = evidence['despues']['indices'] = index_snapshot(a, path)
                    report['diferencias'] += compare_indexes(before_all[cls]['indices'], indices, cls, path)
                except Exception as exc:
                    incidence(cls, 'indices', exc)
                try:
                    geometry = evidence['despues']['geometria'] = renamer.geometry_snapshot(a, path)
                    report['diferencias'] += diff_properties(before_all[cls]['geometria'], geometry,
                        cls=cls, path=path, section='geometria')
                except Exception as exc:
                    incidence(cls, 'geometria', exc)
                try:
                    count = evidence['recuento_actual'] = int(a.management.GetCount(path).getOutput(0))
                    report['diferencias'] += diff_properties({'registros': 0}, {'registros': count},
                        cls=cls, path=path, section='recuento')
                except Exception as exc:
                    incidence(cls, 'recuento', exc)
                evidence['diferencias'] = sum(item['clase'] == cls for item in report['diferencias'])
                evidence['incidencias'] = sum(item['clase'] == cls for item in report['incidencias'])
                emit(f"LEIDA: {cls}; diferencias: {evidence['diferencias']}; incidencias: {evidence['incidencias']}.")
    except Exception as exc:
        incidence('*', 'lectura_global', exc)
    # La evidencia de origen no se escribe; detectar incluso una alteracion externa durante la lectura.
    try:
        require(sha256(previous_path.read_bytes()) == sha256(raw),
                'El informe original cambio durante el diagnostico; esta ejecucion no es concluyente.')
    except Exception as exc:
        incidence('*', 'informe_original', exc)
    report['estado'] = ('DIAGNOSTICO_INCOMPLETO' if report['incidencias'] else
                       'DIFERENCIAS_DETECTADAS' if report['diferencias'] else 'SIN_DIFERENCIAS_ACTUALES')
    report['clases_solicitadas'] = [row['nombre_nuevo'] for row in rows]
    report['fin_utc'] = dt.datetime.now(dt.timezone.utc).isoformat()
    write_reports(folder, report)
    emit(f"Clase detenida original: {report['clase_detenida_original']}; operacion: {report['operacion_detenida_original']}")
    for difference in report['diferencias'][:20]:
        emit(f"DIFERENCIA: {difference['clase']}.{difference['elemento']} / {difference['seccion']}."
             f"{difference['propiedad']}: {difference['antes']!r} -> {difference['despues']!r}")
    emit(f"Estado: {report['estado']}. Diferencias: {len(report['diferencias'])}; incidencias: {len(report['incidencias'])}.")
    emit(f"Resultado JSON: {report['archivo_resultado']}")
    emit(f"Diferencias CSV: {report['archivo_diferencias']}")
    emit('Solo lectura; este resultado no autoriza reanudar automaticamente el renombrado.')
    return folder, report
