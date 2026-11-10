"""Verifica el lote aprobado de texto 1.7 mediante consultas, sin ejecutar DDL.

La confirmacion es metadata del modelo distribuido. Esta herramienta contrasta
sus 1356 columnas existentes; no crea columnas ni convierte o carga valores.
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

import datos_proyecto as runner

HERE = Path(__file__).resolve().parent
EXPECTED_FIELDS = 1356
EXPECTED_PENDING = 730
EXPECTED_CLASSES = 76
CONFIRMED_ORIGIN = 'Atributo KMZ; tipo TEXT confirmado por perfil y decision 1.7'
PROPOSALS = {'MANTENER_TEXT_CONTENIDO', 'MANTENER_TEXT_IDENTIFICADOR_O_ETIQUETA'}
require = runner.engine.require


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def read_reference(model_path, config_path):
    """Resolver el lote completo antes de acceder al destino ArcGIS."""
    model_raw, config_raw = model_path.read_bytes(), config_path.read_bytes()
    model, config = json.loads(model_raw), json.loads(config_raw)
    require(config.get('version_paquete') == '1.7' and config.get('version_modelo') == 11,
            'Se requiere la confirmacion de textos del paquete 1.7 / modelo 11.')
    require(model.get('version') in (11, 12), 'Se requiere el modelo 11 o su cierre verificado como modelo 12.')
    historical_raw = model_raw
    closure_hashes = {}
    if model['version'] == 12:
        from referencia_cierre_tipos import read_reference as read_closure
        base, target, _ = read_closure(model_path.parent)
        require(target == model, 'El modelo no coincide con el objetivo del cierre 1.9.')
        historical_raw = (model_path.parent / 'esquema_anterior_1_8.json').read_bytes()
        require(json.loads(historical_raw) == base and base.get('version') == 11,
                'El modelo historico del cierre no coincide con la referencia 1.8.')
        require(sum(runner.provisional(field) for cls in base['clases'] for field in cls['campos'])
                == EXPECTED_PENDING, 'La referencia historica debe conservar 730 campos pendientes.')
        closure_hashes = {name:sha256((model_path.parent / name).read_bytes()) for name in
            ('esquema_anterior_1_8.json', 'cierre_tipos_1_9.json', 'referencia_cierre_tipos.py')}
    for key in ('modelo_origen_sha256', 'modelo_objetivo_sha256', 'revision_sha256'):
        require(isinstance(config.get(key), str) and re.fullmatch(r'[0-9a-f]{64}', config[key]),
                f'Hash ausente o invalido: {key}.')
    require(config['modelo_objetivo_sha256'] == sha256(historical_raw),
            'El SHA256 del modelo no coincide con la confirmacion aprobada.')
    for key, expected in (('campos_confirmados', EXPECTED_FIELDS),
                          ('campos_pendientes_antes', EXPECTED_FIELDS + EXPECTED_PENDING),
                          ('campos_pendientes_despues', EXPECTED_PENDING),
                          ('clases_modelo', EXPECTED_CLASSES)):
        require(type(config.get(key)) is int and config[key] == expected,
                f'El lote aprobado requiere {key}={expected}.')
    scoped = runner.scoped_model(model)
    require(len(scoped['clases']) == EXPECTED_CLASSES
            and len(model['clases']) == EXPECTED_CLASSES,
            f'El modelo debe contener exactamente {EXPECTED_CLASSES} clases en Datos_Proyecto.')
    fields = {(cls['nombre'], field['nombre']): field
              for cls in scoped['clases'] for field in cls['campos']}
    pending = sum(runner.provisional(field) for field in fields.values())
    expected_pending = EXPECTED_PENDING if model['version'] == 11 else 0
    require(pending == expected_pending,
            f'El modelo debe conservar {expected_pending} campos pendientes; contiene {pending}.')
    approved = {key for key, field in fields.items()
                if field.get('origen') == CONFIRMED_ORIGIN}
    require(len(approved) == EXPECTED_FIELDS,
            f'El modelo no contiene los {EXPECTED_FIELDS} textos confirmados de la version 1.7.')
    rows = config.get('campos')
    require(isinstance(rows, list) and len(rows) == EXPECTED_FIELDS,
            f'La confirmacion debe enumerar exactamente {EXPECTED_FIELDS} campos.')
    seen = set()
    for row in rows:
        require(isinstance(row, dict), 'Entrada de confirmacion invalida.')
        cls, name = row.get('clase'), row.get('campo')
        require(isinstance(cls, str) and isinstance(name, str), 'Falta clase/campo en la confirmacion.')
        key = cls, name
        require(key not in seen, f'Campo duplicado en la confirmacion: {cls}.{name}.')
        seen.add(key)
        require(key in approved, f'{cls}.{name}: no pertenece al lote confirmado del modelo 11.')
        field = fields[key]
        require(field.get('tipo_confirmado') is True and field.get('campo_fuente')
                and not runner.provisional(field),
                f'{cls}.{name}: falta confirmacion explicita y atributo KMZ de origen.')
        require(row.get('tipo') == field['tipo'] == 'TEXT'
                and type(row.get('longitud')) is int
                and row['longitud'] == field['longitud'] == 4000,
                f'{cls}.{name}: solo se admite conservar TEXT(4000).')
        maximum, useful = row.get('longitud_maxima_utf16'), row.get('valores_utiles')
        require(type(maximum) is int and 0 < maximum <= 4000
                and type(useful) is int and useful > 0,
                f'{cls}.{name}: evidencia de longitud/valores utiles invalida.')
        require(row.get('cobertura') == 'COMPLETA_RUTAS_DEL_CAMPO'
                and row.get('propuesta_historica') in PROPOSALS,
                f'{cls}.{name}: cobertura o propuesta historica fuera del lote aprobado.')
    require(seen == approved, 'La lista aprobada difiere de los campos confirmados del modelo.')
    return scoped, config, fields, {
        'modelo_sha256': sha256(model_raw), 'confirmacion_sha256': sha256(config_raw),
        'modelo_origen_sha256': config['modelo_origen_sha256'],
        'modelo_historico_sha256': sha256(historical_raw),
        'referencias_cierre_sha256': closure_hashes,
        'revision_sha256': config['revision_sha256']}


class ReadOnlyArcPy:
    """Solo expone las consultas que necesita este flujo y el inspector comun."""
    _allowed = frozenset(('GetInstallInfo', 'Exists', 'Describe', 'EnvManager',
        'ValidateTableName', 'ValidateFieldName', 'ListDatasets',
        'ListFeatureClasses', 'ListTables', 'ListFields'))

    def __init__(self, arcpy_module):
        self._arcpy = arcpy_module
        self.da = SimpleNamespace(ListDomains=arcpy_module.da.ListDomains)

    def __getattr__(self, name):
        if name not in self._allowed:
            raise AttributeError(f'Operacion no admitida por el verificador de solo lectura: {name}')
        return getattr(self._arcpy, name)


def write_reports(folder, report):
    folder.mkdir(parents=True, exist_ok=False)
    report['archivo_resultado'] = str(folder / 'resultado.json')
    report['archivo_campos'] = str(folder / 'campos_verificados.csv')
    report['archivo_diferencias'] = str(folder / 'diferencias.csv')
    report['archivo_informe'] = str(folder / 'informe.md')
    columns = ['clase', 'campo', 'ruta', 'estado', 'tipo_esperado', 'longitud_minima',
               'nullable_esperado', 'dominio_esperado', 'nombre_actual', 'tipo_actual',
               'longitud_actual', 'nullable_actual', 'dominio_actual',
               'longitud_maxima_utf16', 'valores_utiles', 'cobertura', 'propuesta_historica']
    with (folder / 'campos_verificados.csv').open('x', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, columns, delimiter=';', extrasaction='ignore')
        writer.writeheader()
        writer.writerows(report['campos'])
    with (folder / 'diferencias.csv').open('x', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, ['clase', 'campo', 'propiedad', 'esperado', 'actual', 'detalle'],
                                delimiter=';')
        writer.writeheader()
        writer.writerows(report['discrepancias'])
    lines = ['# Validacion de textos confirmados 1.7', '', f"Estado: **{report['estado']}**", '',
             f"- Campos del lote: {report['campos_esperados']}.",
             f"- Campos verificados: {report['campos_verificados']}.",
             f"- Campos pendientes en el modelo: {report['campos_pendientes_modelo']}.",
             f"- Diferencias/incidencias: {len(report['discrepancias'])}.", '',
             'Esta ejecucion consulta el esquema de los campos aprobados y sus clases. '
             'No ejecuta DDL, no modifica datos ni archivos del modelo. '
             'No certifica la carga de datos, los otros campos, las relaciones ni la integridad '
             'de los codigos de proyecto. La evidencia de longitudes corresponde a las rutas '
             'perfiladas de cada campo, no a todos los elementos de los KMZ.', '']
    if report.get('error'):
        lines.extend(['## Motivo de detencion', '', report['error'], ''])
    for diff in report['discrepancias']:
        lines.append(f"- {diff['clase']}.{diff['campo']} / {diff['propiedad']}: {diff['detalle']}")
    with (folder / 'informe.md').open('x', encoding='utf-8') as stream:
        stream.write('\n'.join(lines) + '\n')
    with (folder / 'resultado.json').open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def run(workspace, database='ArcGisAWS', owner='gis', reports=None,
        arcpy_module=None, emit=print, model_path=None, config_path=None):
    output_parent = Path(reports or HERE).resolve()
    require(output_parent.is_dir(), 'La carpeta existente para informes no existe.')
    folder = output_parent / ('Textos_Confirmados_' + dt.datetime.now().strftime('%Y%m%d_%H%M%S')
                              + '_' + uuid.uuid4().hex[:12])
    model_path = Path(model_path or HERE / 'esquema.json').resolve()
    config_path = Path(config_path or HERE / 'textos_confirmados_1_7.json').resolve()
    args = SimpleNamespace(workspace=os.path.abspath(workspace), database=database, owner=owner, aplicar=False)
    report = dict(version_paquete='1.9', version_modelo=None, lote_verificado='1.7', estado='ERROR_DETENIDO',
        modo='SOLO_LECTURA', workspace=args.workspace, database=database, owner=owner,
        modelo=str(model_path), confirmacion=str(config_path),
        inicio_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
        campos_esperados=EXPECTED_FIELDS, campos_verificados=0,
        campos_pendientes_modelo=None, clases_modelo=EXPECTED_CLASSES,
        clases_solicitadas=[], clases_verificadas=[], campos=[], discrepancias=[],
        cambios_en_geodatabase=0, cambios_en_modelo=False, carga_datos_verificada=False,
        alcance='Los 1356 campos TEXT confirmados y las clases que los contienen; '
                'no valida los otros campos ni los codigos de tc_proyecto.')
    failure = None

    def difference(cls, field, prop, expected, actual, detail):
        report['discrepancias'].append(dict(clase=cls, campo=field, propiedad=prop,
            esperado=expected, actual=actual, detalle=str(detail)))

    try:
        source_version = json.loads(model_path.read_bytes()).get('version')
        report.update(version_modelo=source_version,
                      version_paquete='1.9' if source_version == 12 else '1.7')
        model, config, definitions, hashes = read_reference(model_path, config_path)
        report.update(hashes)
        report['campos_pendientes_modelo'] = sum(runner.provisional(field) for field in definitions.values())
        grouped = {}
        for row in sorted(config['campos'], key=lambda row: (row['clase'], row['campo'])):
            grouped.setdefault(row['clase'], []).append(row)
        report['clases_solicitadas'] = list(grouped)
        if arcpy_module is None:
            import arcpy as arcpy_module
        a = ReadOnlyArcPy(arcpy_module)
        report['arcgis'] = a.GetInstallInfo().get('Version')
        require(a.Exists(args.workspace), 'La conexion/geodatabase debe existir.')
        context = dict(model, dominios={})
        with a.EnvManager(overwriteOutput=False, extent=None):
            inventory, domains = runner.engine.inspect(a, args, context, [])
            dataset = inventory.get(runner.DATASET.casefold())
            require(dataset is not None, 'No existe Datos_Proyecto para el propietario indicado.')
            ds = a.Describe(dataset)
            require(ds.dataType == 'FeatureDataset' and ds.spatialReference.factoryCode == 4326,
                    'Datos_Proyecto debe ser un feature dataset EPSG:4326.')
            classes = {cls['nombre']: cls for cls in model['clases']}
            for name, rows in grouped.items():
                path = inventory.get(name.casefold())
                observed = {}
                class_ok = True
                try:
                    require(path is not None, f'Falta la clase existente {name}; no se crea.')
                    require(runner.engine.simple(os.path.basename(path)) == name,
                            f'{name}: el nombre de la clase no coincide exactamente.')
                    desc, spec = a.Describe(path), classes[name]
                    require(desc.dataType == 'FeatureClass'
                            and runner.engine.simple(os.path.basename(desc.path)).casefold() == runner.DATASET.casefold(),
                            f'{name}: debe ser una feature class de Datos_Proyecto.')
                    require(desc.shapeType.casefold() == spec['geometria'].casefold()
                            and desc.spatialReference.factoryCode == 4326 and desc.hasZ and not desc.hasM,
                            f'{name}: geometria, referencia espacial, Z o M incompatibles.')
                    require(desc.hasGlobalID and desc.editorTrackingEnabled and getattr(desc, 'isTimeInUTC', False),
                            f'{name}: requiere GlobalID y Editor Tracking UTC.')
                    observed = runner.engine.field_index(a.ListFields(path))
                except Exception as exc:
                    class_ok = False
                    difference(name, '*', 'clase', 'Clase existente compatible con el modelo', path, exc)
                for row in rows:
                    field = definitions[name, row['campo']]
                    actual = observed.get(row['campo'].casefold())
                    evidence = dict(row, ruta=path, estado='NO_VERIFICADO',
                        tipo_esperado='String', longitud_minima=4000,
                        nullable_esperado=field['nullable'], dominio_esperado=field.get('dominio') or '',
                        nombre_actual=None, tipo_actual=None, longitud_actual=None,
                        nullable_actual=None, dominio_actual=None)
                    report['campos'].append(evidence)
                    if not class_ok:
                        continue
                    if actual is None:
                        difference(name, row['campo'], 'campo', 'Existente', None, 'Falta el campo aprobado.')
                        continue
                    evidence.update(nombre_actual=runner.engine.field_base_name(actual), tipo_actual=actual.type,
                        longitud_actual=actual.length, nullable_actual=actual.isNullable, dominio_actual=actual.domain or '')
                    checks = [('nombre_actual', row['campo'], evidence['nombre_actual'], evidence['nombre_actual'] == row['campo']),
                        ('tipo_actual', 'String', actual.type, actual.type == 'String'),
                        ('longitud_actual', max(4000, row['longitud_maxima_utf16']), actual.length,
                         type(actual.length) is int and actual.length >= max(4000, row['longitud_maxima_utf16'])),
                        ('nullable_actual', field['nullable'], actual.isNullable, actual.isNullable == field['nullable']),
                        ('dominio_actual', field.get('dominio') or '', actual.domain or '',
                         (actual.domain or '') == (field.get('dominio') or ''))]
                    for prop, expected, value, ok in checks:
                        if not ok:
                            difference(name, row['campo'], prop, expected, value,
                                       f'Esperado {expected!r}; observado {value!r}.')
                    if field.get('dominio') and field['dominio'] not in domains:
                        difference(name, row['campo'], 'dominio_existente', field['dominio'], None,
                                   'El dominio esperado no existe en el destino.')
                        checks.append(('dominio_existente', None, None, False))
                    if all(check[3] for check in checks):
                        evidence['estado'] = 'VERIFICADO'
                        report['campos_verificados'] += 1
                if class_ok and all(item['estado'] == 'VERIFICADO'
                                    for item in report['campos'] if item['clase'] == name):
                    report['clases_verificadas'].append(name)
                emit(f"LEIDA: {name}; textos verificados: "
                     f"{sum(item['estado'] == 'VERIFICADO' for item in report['campos'] if item['clase'] == name)}/{len(rows)}.")
        require(not report['discrepancias'] and report['campos_verificados'] == EXPECTED_FIELDS,
                f"Validacion incompleta: {report['campos_verificados']}/{EXPECTED_FIELDS} campos verificados; "
                f"{len(report['discrepancias'])} diferencias/incidencias. Consulte diferencias.csv.")
        require(sha256(model_path.read_bytes()) == hashes['modelo_sha256']
                and sha256(config_path.read_bytes()) == hashes['confirmacion_sha256'],
                'El modelo o la confirmacion cambio durante la lectura; resultado no concluyente.')
        require(all(sha256((model_path.parent / name).read_bytes()) == digest
                    for name, digest in hashes['referencias_cierre_sha256'].items()),
                'La referencia de cierre cambio durante la lectura; resultado no concluyente.')
        report['estado'] = 'TEXTOS_CONFIRMADOS_VERIFICADOS'
    except Exception as exc:
        failure = exc
        report['error'] = str(exc)
        if not report['discrepancias']:
            difference('*', '*', 'validacion', 'Lote completo valido', None, exc)
    report['fin_utc'] = dt.datetime.now(dt.timezone.utc).isoformat()
    write_reports(folder, report)
    emit(f"Textos verificados: {report['campos_verificados']}/{EXPECTED_FIELDS}. "
         f"Campos con tipo pendiente en el modelo: {report['campos_pendientes_modelo']}.")
    emit(f"Estado: {report['estado']}")
    emit(f"Resultado JSON: {report['archivo_resultado']}")
    if failure is not None:
        raise failure
    return folder, report
