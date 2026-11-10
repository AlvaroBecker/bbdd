"""Actualiza exclusivamente campos aprobados en clases vacias de Datos_Proyecto.

La validacion es de solo lectura. Aplicar usa AlterField, sin crear clases,
cargar registros, borrar columnas ni reconstruir objetos. Una ejecucion
posterior reconoce los cambios ya aplicados si una operacion se detuvo.
"""
from __future__ import annotations

import argparse
import copy
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
from ajustar_tipos_estructuras import properties, snapshot
import validacion_texto_sqlserver as sql_text

HERE = Path(__file__).resolve().parent
CONFIG = HERE / 'campos_aprobados_1_5.json'
AUDIT_FIELDS = (('creatorFieldName', 'created_user'),
                ('createdAtFieldName', 'created_date'),
                ('editorFieldName', 'last_edited_user'),
                ('editedAtFieldName', 'last_edited_date'))
VARIABLE_PROPERTIES = ('tipo', 'longitud', 'precision', 'escala')


def require_preserved(before, after, allowed=()):
    """Solo el campo alterado puede cambiar tipo/longitud/precision/escala."""
    runner.engine.require(before.keys() == after.keys(),
                          'Cambio inesperado en la lista de campos; detener para revision.')
    allowed = {name.casefold() for name in allowed}
    for name, original in before.items():
        old, current = dict(original), dict(after[name])
        if name in allowed:
            for prop in VARIABLE_PROPERTIES:
                old.pop(prop, None)
                current.pop(prop, None)
        runner.engine.require(old == current,
                              f'{name}: cambio inesperado de propiedades; detener para revision.')


def ensure_empty(a, path, name):
    count = int(a.management.GetCount(path).getOutput(0))
    runner.engine.require(count == 0,
        f'{name} contiene {count} registros. El cambio de campos requiere clase vacia.')


def selected_model(source, config, names=None):
    """Comprueba la aprobacion y limita la seleccion; no altera sus entradas."""
    runner.engine.require(config.get('version_paquete') == '1.5',
                          'La configuracion debe corresponder al paquete 1.5.')
    changes = copy.deepcopy(config.get('cambios'))
    runner.engine.require(isinstance(changes, list) and bool(changes),
                          'La configuracion no contiene cambios aprobados.')
    available = {c['nombre']: c for c in source['clases']
                 if c['dataset'] == runner.DATASET}
    seen = set()
    for change in changes:
        runner.engine.require(isinstance(change, dict), 'Cambio aprobado no valido.')
        cls, field = change.get('clase'), change.get('campo')
        runner.engine.require(all(isinstance(n, str) and re.fullmatch(
            r'[a-z][a-z0-9]*(?:_[a-z0-9]+)*', n) for n in (cls, field)),
            'La configuracion debe usar nombres exactos en snake_case.')
        key = (cls, field)
        runner.engine.require(key not in seen, f'Cambio duplicado: {cls}.{field}.')
        seen.add(key)
        runner.engine.require(cls in available,
                              f'{cls}: no pertenece al modelo de Datos_Proyecto.')
        runner.engine.require(change.get('tipo_anterior') == 'TEXT'
                              and change.get('longitud_anterior') == 4000,
                              f'{cls}.{field}: origen distinto de TEXT(4000) aprobado.')
        target = change.get('tipo_objetivo')
        runner.engine.require(target in {'DOUBLE', 'LONG', 'TEXT'},
                              f'{cls}.{field}: tipo objetivo no admitido.')
        length = change.get('longitud_objetivo')
        runner.engine.require((target == 'TEXT' and length == 10000)
                              or (target != 'TEXT' and length is None),
                              f'{cls}.{field}: longitud objetivo no aprobada.')
        fields = {f['nombre']: f for f in available[cls]['campos']}
        spec = fields.get(field)
        runner.engine.require(spec is not None,
                              f'{cls}.{field}: falta en el modelo objetivo.')
        runner.engine.require(spec['tipo'] == target and
                              (target != 'TEXT' or spec['longitud'] == length),
                              f'{cls}.{field}: el modelo no coincide con la aprobacion.')
        runner.engine.require(spec.get('origen', '').startswith('Atributo KMZ')
                              and bool(spec.get('campo_fuente')),
                              f'{cls}.{field}: no es un atributo propio del KMZ.')
        runner.engine.require(spec['nullable'] is True and not spec.get('dominio'),
                              f'{cls}.{field}: el modelo requiere revisar nulabilidad o dominio.')
    approved_classes = {change['clase'] for change in changes}
    runner.engine.require(names is None or not isinstance(names, str),
                          'Indique una lista de clases, no una cadena de texto.')
    chosen = approved_classes if names is None else set(names)
    runner.engine.require(bool(chosen) and chosen <= approved_classes,
                          'Seleccion vacia o clases sin cambios aprobados; no se crean clases.')
    model = runner.scoped_model(source, chosen)
    changes = [change for change in changes if change['clase'] in chosen]
    changes.sort(key=lambda change: (change['clase'], change['campo']))
    return model, changes


def indexes_snapshot(a, path, candidates):
    """Los indices sobre candidatos requieren una migracion independiente."""
    result = []
    for index in a.ListIndexes(path) or []:
        fields = [runner.engine.field_base_name(f).casefold() for f in index.fields]
        affected = set(fields) & set(candidates)
        runner.engine.require(not affected,
            f'Indice {index.name} usa {sorted(affected)}; requiere revision antes de alterar campos.')
        result.append(dict(nombre=index.name, campos=fields,
                           unico=getattr(index, 'isUnique', None),
                           ascendente=getattr(index, 'isAscending', None)))
    return sorted(result, key=lambda index: index['nombre'].casefold())


def guard_class(a, path, cls, candidates):
    description = a.Describe(path)
    runner.engine.require(not getattr(description, 'isVersioned', False),
                          f'{cls}: ya esta versionada.')
    runner.engine.require(description.hasGlobalID and description.editorTrackingEnabled
                          and getattr(description, 'isTimeInUTC', False),
                          f'{cls}: requiere GlobalID y Editor Tracking UTC.')
    for prop, field in AUDIT_FIELDS:
        runner.engine.require(getattr(description, prop, '').casefold() == field,
                              f'{cls}: campo activo de auditoria incorrecto ({prop}).')
    ensure_empty(a, path, cls)
    return indexes_snapshot(a, path, candidates)


def field_action(field, change):
    name = f'{change["clase"]}.{change["campo"]}'
    runner.engine.require(not getattr(field, 'required', False), f'{name}: es un campo requerido.')
    runner.engine.require(not field.domain and field.isNullable,
                          f'{name}: dominio o nulabilidad incompatibles.')
    runner.engine.require(getattr(field, 'defaultValue', None) is None,
                          f'{name}: tiene un valor predeterminado; requiere revision previa.')
    target = change['tipo_objetivo']
    if target == 'TEXT':
        runner.engine.require(field.type == 'String',
                              f'{name}: tipo {field.type}; se requiere TEXT.')
        if field.length >= change['longitud_objetivo']:
            return 'YA_OBJETIVO'
        runner.engine.require(field.length == change['longitud_anterior'],
            f'{name}: longitud intermedia {field.length}; solo se admite TEXT(4000) anterior '
            'o longitud mayor o igual al objetivo aprobado.')
        return 'AMPLIAR_LONGITUD'
    if field.type == runner.engine.TYPE[target]:
        return 'YA_OBJETIVO'
    runner.engine.require(field.type == 'String' and field.length == change['longitud_anterior'],
        f'{name}: tipo/longitud {field.type}({field.length}); solo se admite TEXT(4000) anterior '
        f'o {runner.engine.TYPE[target]} objetivo.')
    return 'ALTERAR_TIPO'


def prepare_batch(a, args, model, changes, inventory, report):
    """Prevalida el lote completo antes de cualquier AlterField."""
    compatible = copy.deepcopy(model)
    by_class = {c['nombre']: [] for c in model['clases']}
    for change in changes:
        by_class[change['clase']].append(change)
    rows, before = [], {}
    for cls in compatible['clases']:
        name = cls['nombre']
        report['clase_en_curso'] = name
        path = inventory.get(name.casefold())
        runner.engine.require(path is not None,
                              f'No existe {name}; esta herramienta no crea clases.')
        actual = runner.engine.field_index(a.ListFields(path))
        before[name] = {key: properties(field) for key, field in actual.items()}
        expected = {f['nombre']: f for f in cls['campos']}
        for change in by_class[name]:
            field = actual.get(change['campo'].casefold())
            runner.engine.require(field is not None,
                f'{name}: falta {change["campo"]}. No se agregan columnas automaticamente.')
            action = field_action(field, change)
            if change['tipo_objetivo'] == 'TEXT':
                report['texto_sqlserver_antes'] = sql_text.verify(a, args.workspace, args.owner,
                    require_max=field.length >= change['longitud_objetivo'], table_name=name)
            if action != 'YA_OBJETIVO':
                expected[change['campo']].update(tipo=change['tipo_anterior'],
                                               longitud=change['longitud_anterior'])
            rows.append(dict(clase=name, campo=change['campo'], tipo_actual=field.type,
                             longitud_actual=field.length, tipo_objetivo=change['tipo_objetivo'],
                             longitud_objetivo=change['longitud_objetivo'], accion=action))
    report['plan'] = rows
    runner.preflight(a, args, compatible)
    indices, locks = {}, {}
    for cls in model['clases']:
        name = cls['nombre']
        report['clase_en_curso'] = name
        path = inventory[name.casefold()]
        candidates = {change['campo'].casefold() for change in by_class[name]}
        indices[name] = guard_class(a, path, name, candidates)
        require_preserved(before[name], snapshot(a, path))
        locks[name] = bool(a.TestSchemaLock(path))
        pending = any(row['clase'] == name and row['accion'] != 'YA_OBJETIVO' for row in rows)
        if args.aplicar and pending:
            runner.engine.require(locks[name],
                                  f'No hay bloqueo de esquema disponible sobre {name}; cierre su uso y reintente.')
    report['clase_en_curso'] = None
    return rows, before, indices, locks


def write_plan(folder, rows):
    path = folder / 'plan.csv'
    with path.open('x', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=('clase', 'campo', 'tipo_actual',
            'longitud_actual', 'tipo_objetivo', 'longitud_objetivo', 'accion'), delimiter=';')
        writer.writeheader()
        writer.writerows(rows)
    return str(path)


def target_confirmed(after, change):
    actual = after[change['campo'].casefold()]
    return actual['tipo'] == runner.engine.TYPE[change['tipo_objetivo']] and (
        change['tipo_objetivo'] != 'TEXT' or actual['longitud'] >= change['longitud_objetivo'])


def run(workspace, apply=False, database='ArcGisAWS', owner='gis', reports=None,
        arcpy_module=None, emit=print, model_path=None, config_path=None, names=None):
    runner.engine.require(all(isinstance(v, str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', v)
                              for v in (database, owner)), 'Base o propietario invalido.')
    raw = Path(model_path or HERE / 'esquema.json').read_bytes()
    config_raw = Path(config_path or CONFIG).read_bytes()
    config = json.loads(config_raw.decode('utf-8-sig'))
    model, changes = selected_model(json.loads(raw.decode('utf-8-sig')), config, names)
    args = SimpleNamespace(workspace=os.path.abspath(workspace), database=database,
                           owner=owner, aplicar=apply)
    folder = Path(reports or HERE) / ('Campos_Aprobados_' +
        dt.datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:8])
    report = dict(estado='INICIADO', modo='APLICAR_CAMPOS' if apply else 'VALIDAR_CAMPOS',
        workspace=args.workspace, database=database, owner=owner,
        modelo_sha256=hashlib.sha256(raw).hexdigest(),
        aprobacion_sha256=hashlib.sha256(config_raw).hexdigest(), version_paquete='1.6',
        inicio_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
        completadas=[], clase_en_curso=None, campo_en_curso=None,
        clases=[dict(nombre=c['nombre'], geometria=c['geometria'], campos=len(c['campos']),
                     tipos_pendientes=sum(runner.provisional(f) for f in c['campos']),
                     accion='POR_VALIDAR') for c in model['clases']],
        advertencias=['Solo se alteran campos aprobados en clases existentes y vacias de Datos_Proyecto.',
          'No carga datos, convierte valores o unidades, crea relaciones ni activa versionado.',
          'DDL no es una transaccion atomica. Un error detiene el lote sin borrar ni recrear objetos; '
          'la siguiente ejecucion reconoce tipos y longitudes objetivo ya aplicados.'])
    runner.report_files(folder, report, model)
    emit(f'Informe: {folder}')
    inventory = {}
    try:
        if arcpy_module is None:
            import arcpy as arcpy_module
        a = arcpy_module
        report['arcgis'] = a.GetInstallInfo().get('Version')
        with a.EnvManager(overwriteOutput=False):
            # Primero valida la conexion y resuelve rutas sin exigir aun tipos nuevos.
            inventory, _ = runner.engine.inspect(a, args, model, [])
            report['rutas_clases'] = {c['nombre']: inventory.get(c['nombre'].casefold())
                                     for c in model['clases']}
            rows, before, indices, locks = prepare_batch(a, args, model, changes, inventory, report)
            report.update(campos_antes=before, bloqueos_disponibles=locks,
                          archivo_plan=write_plan(folder, rows), estado='PREVALIDADO')
            for row in report['clases']:
                row['accion'] = 'VALIDADA_PARA_CAMPOS'
            for name, available in locks.items():
                if not available:
                    report['advertencias'].append(f'{name}: TestSchemaLock no disponible. '
                        'Cierre capas, tablas o procesos que usen la clase antes de aplicar cambios pendientes.')
            runner.report_files(folder, report, model)
            emit(f'Prevalidacion completa: {len(model["clases"])} clases; '
                 f'{sum(row["accion"] != "YA_OBJETIVO" for row in rows)} cambios pendientes; '
                 f'{sum(row["accion"] == "YA_OBJETIVO" for row in rows)} ya aplicados.')
            text_pending = args.workspace.lower().endswith('.sde') and any(
                row['tipo_objetivo'] == 'TEXT' and row['accion'] != 'YA_OBJETIVO' for row in rows)
            if text_pending:
                message = ('Ejecute primero Reparar texto largo de predios: cargas_y_gravamenes '
                           'necesita NVARCHAR(MAX). AlterField no se usara para cruzar este limite '
                           'en SQL Server. No se aplicaron cambios en esta ejecucion.')
                report['advertencias'].append(message)
                if apply:
                    raise ValueError(message)
                emit(message)
            if apply:
                expected = copy.deepcopy(before)
                for cls, class_report in zip(model['clases'], report['clases']):
                    name = cls['nombre']
                    report['clase_en_curso'] = name
                    path = inventory[name.casefold()]
                    class_changes = [change for change in changes if change['clase'] == name]
                    one = runner.scoped_model(model, [name])
                    # La revalidacion completa se hace una vez por clase, no por campo.
                    prepare_batch(a, args, one, class_changes, inventory, {})
                    report['clase_en_curso'] = name
                    require_preserved(expected[name], snapshot(a, path))
                    for change in class_changes:
                        row = next(row for row in rows if row['clase'] == name
                                   and row['campo'] == change['campo'])
                        if row['accion'] == 'YA_OBJETIVO':
                            continue
                        current = snapshot(a, path)
                        require_preserved(expected[name], current)
                        actual_indices = guard_class(a, path, name,
                            {candidate['campo'] for candidate in class_changes})
                        runner.engine.require(actual_indices == indices[name],
                                              f'{name}: cambio inesperado de indices.')
                        runner.engine.require(bool(a.TestSchemaLock(path)),
                            f'No hay bloqueo de esquema disponible sobre {name}; cierre su uso y reintente.')
                        require_preserved(expected[name], snapshot(a, path))
                        report.update(clase_en_curso=name, campo_en_curso=change['campo'])
                        runner.report_files(folder, report, model)
                        kwargs = dict(field_type=change['tipo_objetivo'])
                        if change['tipo_objetivo'] == 'TEXT':
                            sql_text.verify(a, args.workspace, args.owner, require_max=False, table_name=name)
                            kwargs['field_length'] = change['longitud_objetivo']
                        a.management.AlterField(path, change['campo'], **kwargs)
                        after = snapshot(a, path)
                        require_preserved(current, after, [change['campo']])
                        runner.engine.require(target_confirmed(after, change),
                            f'{name}.{change["campo"]}: ArcGIS no confirma el tipo/longitud objetivo despues de AlterField.')
                        if change['tipo_objetivo'] == 'TEXT':
                            report['texto_sqlserver_despues'] = sql_text.verify(
                                a, args.workspace, args.owner, require_max=True, table_name=name)
                        actual_indices = guard_class(a, path, name,
                            {candidate['campo'] for candidate in class_changes})
                        runner.engine.require(actual_indices == indices[name],
                                              f'{name}: cambio inesperado de indices.')
                        expected[name] = after
                        report['completadas'].append(f'{name}.{change["campo"]}')
                        row['accion'] = 'ALTERADA_VERIFICADA'
                        report['campo_en_curso'] = None
                        runner.report_files(folder, report, model)
                        emit(f'CAMPO actualizado y verificado: {name}.{change["campo"]}')
                    runner.preflight(a, args, one)
                    require_preserved(expected[name], snapshot(a, path))
                    runner.engine.require(all(target_confirmed(expected[name], change)
                                              for change in class_changes),
                                          f'{name}: persisten campos sin el tipo/longitud objetivo.')
                    class_report['accion'] = 'CAMPOS_VERIFICADOS'
                    report['clase_en_curso'] = None
                # Una ultima lectura tambien detecta efectos ajenos entre clases del lote.
                runner.preflight(a, args, model)
                for cls in model['clases']:
                    name = cls['nombre']
                    report['clase_en_curso'] = name
                    path = inventory[name.casefold()]
                    require_preserved(expected[name], snapshot(a, path))
                    final_indices = guard_class(a, path, name,
                        {change['campo'] for change in changes if change['clase'] == name})
                    runner.engine.require(final_indices == indices[name],
                                          f'{name}: cambio inesperado de indices.')
                    if any(change['clase'] == name and change['tipo_objetivo'] == 'TEXT'
                           for change in changes):
                        report['texto_sqlserver_despues'] = sql_text.verify(
                            a, args.workspace, args.owner, require_max=True)
                report.update(campos_despues=expected, clase_en_curso=None)
            report['estado'] = 'CAMPOS_VERIFICADOS' if apply else 'VALIDACION_OK_SIN_CAMBIOS'
    except Exception as exc:
        report.update(estado='ERROR_DETENIDO', error=str(exc))
        if 'a' in locals():
            observed = {}
            for cls in model['clases']:
                path = inventory.get(cls['nombre'].casefold())
                if path:
                    try:
                        observed[cls['nombre']] = snapshot(a, path)
                    except Exception as diagnostic_error:
                        observed[cls['nombre']] = {'error_al_leer_estado': str(diagnostic_error)}
            report['campos_observados_al_detener'] = observed
        raise
    finally:
        report['fin_utc'] = dt.datetime.now(dt.timezone.utc).isoformat()
        try:
            runner.report_files(folder, report, model)
        except OSError as error:
            if not report.get('error'):
                raise
            emit(f'No se pudo guardar el estado final: {error}. Error original: {report["error"]}')
        else:
            emit(f'Estado: {report["estado"]}')
            emit(f'Resultado JSON: {report["archivo_resultado"]}')
    return folder, report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', required=True)
    parser.add_argument('--aplicar', action='store_true')
    parser.add_argument('--database', default='ArcGisAWS')
    parser.add_argument('--owner', default='gis')
    parser.add_argument('--informes')
    parser.add_argument('--modelo')
    parser.add_argument('--aprobacion')
    parser.add_argument('--clase', action='append')
    args = parser.parse_args(argv)
    run(args.workspace, apply=args.aplicar, database=args.database, owner=args.owner,
        reports=args.informes, model_path=args.modelo, config_path=args.aprobacion, names=args.clase)


if __name__ == '__main__':
    main()
