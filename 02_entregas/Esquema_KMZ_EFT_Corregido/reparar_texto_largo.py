"""Sustitucion controlada de un campo TEXT vacio mediante herramientas ArcGIS.

La operacion es explicita y separada del lote de tipos. No ejecuta SQL DDL.
Conserva la columna original hasta verificar la sustituta y permite continuar
con el ultimo resultado.json si una herramienta modifica el esquema y falla.
"""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
from types import SimpleNamespace
import uuid

import actualizar_campos_aprobados as migration
import datos_proyecto as runner
import validacion_texto_sqlserver as sql_text
from ajustar_tipos_estructuras import properties, snapshot

HERE = Path(__file__).resolve().parent
CLASS = 'predios_inscritos_sunarp_recorte'
FIELD = 'cargas_y_gravamenes'
TEMP = 'tmp_cargas_y_gravamenes_151'
BACKUP = 'bak_cargas_y_gravamenes_151'
MARKER = 'reparacion_texto_largo_1.6'
STAGES = ('ORIGINAL_4000', 'TEMPORAL_VERIFICADO', 'ORIGINAL_RESPALDADO',
          'SUSTITUTO_VERIFICADO', 'FINAL_VERIFICADO')
OPERATIONS = ('CREAR_TEMPORAL', 'RESPALDAR_ORIGINAL', 'RENOMBRAR_SUSTITUTO',
              'ELIMINAR_RESPALDO_VACIO')


def require(condition, message):
    runner.engine.require(condition, message)


def connection_identity(a, args, path):
    """No registra contrasenas; distingue conexiones que reutilizan un .sde."""
    description = a.Describe(args.workspace)
    cp = getattr(description, 'connectionProperties', None)
    identity = dict(workspace=os.path.normcase(os.path.abspath(args.workspace)),
                    clase_path=os.path.normcase(os.path.abspath(path)),
                    database=args.database.casefold(), owner=args.owner.casefold())
    if cp is not None:
        identity['conexion'] = {key: str(getattr(cp, key, '')) for key in
            ('server', 'instance', 'db_connection_properties', 'database', 'user',
             'authentication_mode', 'version')}
    return identity


def dependency_guard(a, path):
    """Se rechazan dependencias en vez de intentar reconstruirlas."""
    d = a.Describe(path)
    require(not getattr(d, 'relationshipClassNames', []),
            'La clase tiene relaciones: revisar dependencias antes de sustituir el campo.')
    require(not getattr(d, 'attributeRules', []),
            'La clase tiene reglas de atributos: no se sustituye el campo automaticamente.')
    require(not getattr(d, 'isArchived', False),
            'La clase tiene archivado activo; requiere otro procedimiento.')
    require(not getattr(d, 'isReplicated', False),
            'La clase participa en una replica; requiere otro procedimiento.')
    require(not getattr(d, 'subtypeFieldName', ''),
            'La clase tiene subtipos; revisar dependencias antes de sustituir el campo.')
    require(hasattr(a.da, 'ListSubtypes'), 'ArcPy no permite comprobar los subtipos.')
    for item in (a.da.ListSubtypes(path) or {}).values():
        require(not item.get('SubtypeField', ''),
                'La clase tiene subtipos; revisar dependencias antes de sustituir el campo.')
        for name, pair in item.get('FieldValues', {}).items():
            if runner.engine.simple(name).casefold() in {FIELD, TEMP, BACKUP}:
                default, domain = pair
                require(default is None and domain is None,
                        'El campo tiene un dominio o valor predeterminado de subtipo.')


def original_guard(value):
    require(value['tipo'] == 'String' and not value['requerido'] and value['nullable']
            and not value['dominio'] and value['defecto'] == repr(None),
            'cargas_y_gravamenes debe ser TEXT, nullable, no requerido y sin dominio/default.')
    require(value['longitud'] == 4000 or value['longitud'] >= 10000,
            'Longitud de origen no reconocida; se admite4000 o el objetivo ya ampliado.')


def same_field(value, original, name, long_text):
    expected = dict(original, nombre=name)
    left, right = dict(value), expected
    if long_text:
        require(left['tipo'] == 'String' and left['longitud'] >= 10000,
                f'{name}: no tiene la capacidad TEXT aprobada.')
        for prop in ('longitud', 'precision', 'escala'):
            left.pop(prop, None)
            right.pop(prop, None)
    require(left == right, f'{name}: propiedades distintas de la columna registrada; no se modifica.')


def observe_stage(a, args, path, baseline):
    """Acepta solamente cinco configuraciones exactas y verifica sus columnas."""
    current = snapshot(a, path)
    original = baseline[FIELD]
    original_guard(original)
    other = set(baseline) - {FIELD}
    present = set(current) & {FIELD, TEMP, BACKUP}
    require(set(current) - {FIELD, TEMP, BACKUP} == other,
            'Campos ajenos o ausentes respecto al informe de recuperacion; no se modifica.')
    for name in other:
        require(current[name] == baseline[name],
                f'{name}: cambio ajeno desde el inicio; no se modifica.')
    if present == {FIELD}:
        long_text = current[FIELD]['longitud'] >= 10000
        stage = 'FINAL_VERIFICADO' if long_text else 'ORIGINAL_4000'
    elif present == {FIELD, TEMP}:
        require(current[FIELD]['longitud'] == 4000, 'Estado temporal no reconocido.')
        stage = 'TEMPORAL_VERIFICADO'
    elif present == {TEMP, BACKUP}:
        stage = 'ORIGINAL_RESPALDADO'
    elif present == {FIELD, BACKUP}:
        stage = 'SUSTITUTO_VERIFICADO'
    else:
        raise ValueError('Combinacion de columnas de reparacion no reconocida; no se borra nada.')
    for name in present:
        long_text = name == TEMP or (name == FIELD and stage in
                                    {'SUSTITUTO_VERIFICADO', 'FINAL_VERIFICADO'})
        same_field(current[name], original, name, long_text)
        sql_text.verify(a, args.workspace, args.owner, require_max=long_text,
                        field_name=name)
    return stage, current


def compatible_preflight(a, args, model, changes, inventory, path, current):
    """Modelo fisico explicito: nunca oculta campos desconocidos a ArcPy."""
    compatible = copy.deepcopy(model)
    cls = compatible['clases'][0]
    original_spec = copy.deepcopy(next(f for f in cls['campos'] if f['nombre'] == FIELD))
    cls['campos'] = [f for f in cls['campos'] if f['nombre'] != FIELD]
    for name in (FIELD, TEMP, BACKUP):
        if name in current:
            spec = copy.deepcopy(original_spec)
            spec.update(nombre=name, alias=current[name]['alias'], longitud=current[name]['longitud'])
            cls['campos'].append(spec)
    numeric = [c for c in changes if c['campo'] != FIELD]
    migration.prepare_batch(a, args, compatible, numeric, inventory, {})
    dependency_guard(a, path)
    return migration.guard_class(a, path, CLASS, {c['campo'] for c in changes} | {TEMP, BACKUP})


def check_recovery(recovery, report, identity, stage, baseline):
    for key in ('procedimiento', 'modelo_sha256', 'aprobacion_sha256'):
        require(recovery.get(key) == report[key], f'Informe de recuperacion incompatible: {key}.')
    require(recovery.get('identidad') == identity, 'El informe pertenece a otro destino/conexion.')
    require(isinstance(recovery.get('campos_iniciales'), dict)
            and recovery['campos_iniciales'] == baseline, 'Informe sin snapshot inicial valido.')
    previous = recovery.get('etapa')
    require(previous in STAGES, 'Informe sin etapa de reparacion reconocida.')
    allowed = {previous}
    pending = recovery.get('operacion_pendiente')
    if pending:
        index = STAGES.index(previous)
        require(index < len(OPERATIONS) and pending == OPERATIONS[index],
                'Operacion pendiente incompatible con la etapa del informe.')
        allowed.add(STAGES[index + 1])
    require(stage in allowed,
            'El esquema avanzo fuera de la etapa registrada; use el ultimo resultado.json.')


def run(workspace, apply=False, database='ArcGisAWS', owner='gis', reports=None,
        arcpy_module=None, emit=print, model_path=None, config_path=None, recovery_path=None):
    require(all(isinstance(v, str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', v)
                for v in (database, owner)), 'Base o propietario invalido.')
    raw = Path(model_path or HERE / 'esquema.json').read_bytes()
    config_raw = Path(config_path or HERE / 'campos_aprobados_1_5.json').read_bytes()
    model, changes = migration.selected_model(json.loads(raw.decode('utf-8-sig')),
        json.loads(config_raw.decode('utf-8-sig')), [CLASS])
    require(sum(c['campo'] == FIELD and c['tipo_objetivo'] == 'TEXT'
                and c['longitud_objetivo'] == 10000 for c in changes) == 1,
            'Falta la unica ampliacion de texto aprobada.')
    args = SimpleNamespace(workspace=os.path.abspath(workspace), database=database,
                           owner=owner, aplicar=False)
    folder = Path(reports or HERE) / ('Reparacion_Texto_' +
        dt.datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:8])
    report = dict(estado='INICIADO', modo='REPARAR_TEXTO' if apply else 'VALIDAR_REPARACION_TEXTO',
        procedimiento=MARKER, version_paquete='1.6', workspace=args.workspace,
        database=database, owner=owner, modelo_sha256=hashlib.sha256(raw).hexdigest(),
        aprobacion_sha256=hashlib.sha256(config_raw).hexdigest(),
        inicio_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
        etapa=None, operacion_pendiente=None, completadas=[],
        recuperacion_origen=str(recovery_path) if recovery_path else None,
        clases=[dict(nombre=CLASS, geometria=model['clases'][0]['geometria'],
                     campos=len(model['clases'][0]['campos']),
                     tipos_pendientes=sum(runner.provisional(f) for f in model['clases'][0]['campos']),
                     accion='POR_VALIDAR')],
        advertencias=[
            'Solo sustituye cargas_y_gravamenes en predios SUNARP vacia. No carga datos ni cambia tipos numericos.',
            'Crea una columna temporal, conserva el original hasta verificar el sustituto y elimina el respaldo vacio.',
            'El orden fisico de las columnas puede cambiar. No modifica SQL directamente.',
            'Cerrar uso de la clase e impedir cargas concurrentes durante toda la reparacion.',
            'Si falla, use el ultimo resultado.json como informe de recuperacion; no borre columnas manualmente.'])
    runner.report_files(folder, report, model)
    emit(f'Informe: {folder}')
    path = None
    try:
        if arcpy_module is None:
            import arcpy as arcpy_module
        a = arcpy_module
        report['arcgis'] = a.GetInstallInfo().get('Version')
        with a.EnvManager(overwriteOutput=False):
            inventory, _ = runner.engine.inspect(a, args, model, [])
            path = inventory.get(CLASS)
            require(path, f'No existe {CLASS}; no se crean clases.')
            identity = connection_identity(a, args, path)
            report['identidad'] = identity
            actual = snapshot(a, path)
            recovery = None
            if recovery_path:
                recovery = json.loads(Path(recovery_path).read_text(encoding='utf-8-sig'))
                baseline = copy.deepcopy(recovery.get('campos_iniciales'))
                require(isinstance(baseline, dict) and FIELD in baseline
                        and not {TEMP, BACKUP} & set(baseline),
                        'Informe sin estado inicial reconocido.')
            else:
                require(not {TEMP, BACKUP} & set(actual),
                        'Hay columnas temporales; indique el ultimo resultado.json de esta reparacion.')
                require(FIELD in actual, 'Falta cargas_y_gravamenes; se requiere informe de recuperacion.')
                baseline = actual
            report['campos_iniciales'] = baseline
            stage, actual = observe_stage(a, args, path, baseline)
            if recovery is not None:
                check_recovery(recovery, report, identity, stage, baseline)
            indices = compatible_preflight(a, args, model, changes, inventory, path, actual)
            if recovery is not None:
                require(recovery.get('indices_iniciales') == indices,
                        'Indices distintos de los registrados; no se modifica.')
            report.update(etapa=stage, campos_observados=actual, indices_iniciales=indices,
                          estado='PREVALIDADO')
            runner.report_files(folder, report, model)
            if apply:
                while stage != 'FINAL_VERIFICADO':
                    index = STAGES.index(stage)
                    operation = OPERATIONS[index]
                    # Revalidar estado, dependencias, filas e indices antes de cada escritura.
                    checked_stage, actual = observe_stage(a, args, path, baseline)
                    require(checked_stage == stage, 'El esquema cambio durante la reparacion.')
                    observed_indices = compatible_preflight(a, args, model, changes, inventory, path, actual)
                    require(observed_indices == indices, 'Cambio inesperado de indices.')
                    require(bool(a.TestSchemaLock(path)), 'No hay bloqueo de esquema disponible; cierre su uso.')
                    migration.ensure_empty(a, path, CLASS)
                    require(snapshot(a, path) == actual, 'El esquema cambio antes de la escritura.')
                    report.update(etapa=stage, operacion_pendiente=operation, campos_observados=actual)
                    runner.report_files(folder, report, model)
                    # Este ultimo conteo precede tambien a DeleteField: nunca borrar con filas.
                    migration.ensure_empty(a, path, CLASS)
                    alias = baseline[FIELD]['alias']
                    if operation == 'CREAR_TEMPORAL':
                        a.management.AddField(path, TEMP, 'TEXT', field_length=10000,
                            field_alias=alias, field_is_nullable='NULLABLE', field_is_required='NON_REQUIRED')
                    elif operation == 'RESPALDAR_ORIGINAL':
                        a.management.AlterField(path, FIELD, new_field_name=BACKUP, new_field_alias=alias)
                    elif operation == 'RENOMBRAR_SUSTITUTO':
                        a.management.AlterField(path, TEMP, new_field_name=FIELD, new_field_alias=alias)
                    else:
                        # observe_stage ya verifico NVARCHAR(MAX) del nombre definitivo.
                        a.management.DeleteField(path, [BACKUP])
                    stage, after = observe_stage(a, args, path, baseline)
                    require(stage == STAGES[index + 1], 'ArcGIS no confirma el paso de reparacion previsto.')
                    require(compatible_preflight(a, args, model, changes, inventory, path, after) == indices,
                            'Cambio inesperado de indices despues de la escritura.')
                    report.update(etapa=stage, operacion_pendiente=None, campos_observados=after)
                    report['completadas'].append(operation)
                    runner.report_files(folder, report, model)
                    emit(f'Paso verificado: {operation}')
                stage, final = observe_stage(a, args, path, baseline)
                require(compatible_preflight(a, args, model, changes, inventory, path, final) == indices,
                        'Indices finales incompatibles.')
                migration.require_preserved(baseline, final, [FIELD])
                report.update(campos_finales=final, etapa=stage)
            report['estado'] = 'TEXTO_LARGO_VERIFICADO' if apply else 'VALIDACION_OK_SIN_CAMBIOS'
            report['clases'][0]['accion'] = report['estado']
    except Exception as exc:
        report.update(estado='ERROR_DETENIDO', error=str(exc))
        if path and 'a' in locals():
            try:
                report['campos_observados_al_detener'] = snapshot(a, path)
            except Exception as diagnostic_error:
                report['error_al_leer_estado'] = str(diagnostic_error)
        raise
    finally:
        report['fin_utc'] = dt.datetime.now(dt.timezone.utc).isoformat()
        try:
            runner.report_files(folder, report, model)
        except OSError as error:
            if not report.get('error'):
                raise
            emit(f'No se pudo guardar el informe final: {error}. Error original: {report["error"]}')
        else:
            emit(f'Estado: {report["estado"]}')
            emit(f'Resultado JSON: {report["archivo_resultado"]}')
    return folder, report
