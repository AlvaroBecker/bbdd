"""Cierre 1.9: confirma el modelo y altera ocho columnas numericas vacias.

No convierte valores, crea campos ni recrea clases. La validacion admite una
migracion parcial; cada aplicacion vuelve a comprobar el lote antes del primer
DDL y conserva un estado inmutable antes y despues de cada operacion.
"""
from __future__ import annotations

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

import actualizar_campos_aprobados as migration
import datos_proyecto as runner
import validar_tipos_kmz as validation

HERE = Path(__file__).resolve().parent
require = runner.engine.require
NUMERIC = {
    ('sitios_arqueologicos_poligono_recorte', 'alt_mode'): 'LONG',
    ('sitios_arqueologicos_poligono_recorte', 'base'): 'DOUBLE',
    ('sitios_arqueologicos_poligono_recorte', 'clamped'): 'LONG',
    ('sitios_arqueologicos_poligono_recorte', 'extruded'): 'LONG',
    ('sitios_arqueologicos_punto_recorte', 'alt_mode'): 'LONG',
    ('sitios_arqueologicos_punto_recorte', 'base'): 'DOUBLE',
    ('sitios_arqueologicos_punto_recorte', 'has_label'): 'LONG',
    ('suelos_recorte', 'p_aui_suel'): 'LONG',
}
REFERENCE_FILES = ('esquema.json', 'esquema_anterior_1_8.json', 'cierre_tipos_1_9.json')
INGESTION_BLOCKS = [
    dict(clase='lineas_transmision_existentes_osinergmin_recorte', campo='longitud_subterranea',
         codigo='REGLA_NULL_PENDIENTE', detalle='Definir conversion del literal <Null>; el tipo DOUBLE ya esta confirmado.'),
    dict(clase='lineas_transmision_existentes_osinergmin_recorte', campo='maxima_tension_operativa',
         codigo='REGLA_NULL_PENDIENTE', detalle='Definir conversion del literal <Null>; el tipo DOUBLE ya esta confirmado.'),
    dict(clase='subestacion_poligono', campo='src_area_ha', codigo='REGLA_NULL_PENDIENTE',
         detalle='Definir conversion del literal <Null>; el tipo DOUBLE ya esta confirmado.'),
    dict(clase='predios_inscritos_sunarp_recorte', campo='oficina_registral',
         codigo='CONFLICTO_MAPEO_VALORES', detalle='TEXT conserva capacidad; falta resolver que valor corresponde cargar.'),
]


def load_reference(model_dir):
    from referencia_cierre_tipos import read_reference
    return read_reference(model_dir)


def input_hashes(model_dir):
    return {name: hashlib.sha256((model_dir / name).read_bytes()).hexdigest()
            for name in REFERENCE_FILES}


def require_inputs_unchanged(model_dir, expected):
    require(input_hashes(model_dir) == expected,
            'El modelo o la decision de cierre cambiaron durante la ejecucion; se detiene el lote.')


def approved_scope(base, target, config):
    """Defensa adicional: ni el caller ni una seleccion parcial amplian el DDL."""
    require(base.get('version') == 11 and target.get('version') == 12,
            'El cierre requiere modelo anterior 11 y objetivo 12.')
    source = runner.scoped_model(base)
    model = runner.scoped_model(target)
    old = {(c['nombre'], f['nombre']): f for c in source['clases'] for f in c['campos']}
    fields = {(c['nombre'], f['nombre']): f for c in model['clases'] for f in c['campos']}
    require(len(model['clases']) == 76 and len(fields) == 3340 and old.keys() == fields.keys(),
            'El cierre conserva las 76 clases y 3340 definiciones existentes.')
    pending = {key for key, field in old.items() if runner.provisional(field)}
    rows = config.get('campos', [])
    require(len(pending) == len(rows) == 730 and
            {(row.get('clase'), row.get('campo')) for row in rows} == pending,
            'La decision debe enumerar exactamente los 730 tipos provisionales del modelo 11.')
    require(not any(runner.provisional(field) for field in fields.values()),
            'El modelo objetivo todavia contiene tipos provisionales.')
    changes = copy.deepcopy(config.get('cambios_fisicos', []))
    require(len(changes) == 8 and
            {(row.get('clase'), row.get('campo')): row.get('tipo_objetivo') for row in changes} == NUMERIC,
            'Solo se admiten los seis LONG y dos DOUBLE del cierre aprobado.')
    for change in changes:
        key = change['clase'], change['campo']
        require(key in pending and change.get('tipo_anterior') == 'TEXT' and
                change.get('longitud_anterior') == 4000 and change.get('longitud_objetivo') is None,
                f'{key}: la transicion debe partir de TEXT(4000).')
        require(old[key]['tipo'] == 'TEXT' and old[key]['longitud'] == 4000 and
                fields[key]['tipo'] == NUMERIC[key] and fields[key].get('longitud') is None,
                f'{key}: la definicion del modelo no coincide con la transicion aprobada.')
    for key in pending - NUMERIC.keys():
        require(fields[key]['tipo'] == old[key]['tipo'] == 'TEXT' and
                fields[key]['longitud'] == old[key]['longitud'] == 4000,
                f'{key}: la confirmacion TEXT no puede cambiar su almacenamiento.')
    return model, sorted(changes, key=lambda row: (row['clase'], row['campo']))


def dependencies(a, path, name):
    """Una clase con dependencias administradas necesita una migracion propia."""
    desc = a.Describe(path)
    for property_name, label in (
            ('hasAttachments', 'adjuntos'), ('isArchived', 'archivado'),
            ('relationshipClassNames', 'relaciones'), ('controllerMemberships', 'topologia o red'),
            ('attributeRules', 'reglas de atributos')):
        require(not getattr(desc, property_name, False),
                f'{name}: tiene {label}; requiere revisar dependencias antes de alterar tipos.')


def compatible_model(model, rows):
    compatible = copy.deepcopy(model)
    pending = {(row['clase'], row['campo']) for row in rows if row['accion'] != 'YA_OBJETIVO'}
    for cls in compatible['clases']:
        for field in cls['campos']:
            if (cls['nombre'], field['nombre']) in pending:
                field.update(tipo='TEXT', longitud=4000)
    return compatible


def pending_changes(rows):
    return sum(row['accion'] not in {'YA_OBJETIVO', 'ALTERADA_VERIFICADA'} for row in rows)


def write_csv(path, rows):
    rows = list(rows)
    columns = list(dict.fromkeys(key for row in rows for key in row)) or ['estado']
    with path.open('x', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, columns, delimiter=';')
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value, ensure_ascii=False)
                             if isinstance(value, (dict, list, tuple)) else value
                             for key, value in row.items()})


def report_files(folder, report):
    folder.mkdir(parents=True, exist_ok=True)
    revision = folder / 'estados' / (
        dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ_') + uuid.uuid4().hex[:8])
    revision.mkdir(parents=True, exist_ok=False)
    report.update(archivo_resultado=str(revision / 'resultado.json'),
                  archivo_informe=str(revision / 'informe.md'), archivo_plan=str(revision / 'plan.csv'))
    write_csv(revision / 'plan.csv', report.get('plan', []))
    with (revision / 'resultado.json').open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    lines = ['# Cierre de tipos KMZ 1.9', '', f"Estado: **{report['estado']}**", '',
        f"Modo: {report['modo']}", f"Modelo objetivo: {report.get('version_modelo', 'NO_VERIFICADO')}",
        f"Tipos provisionales en el modelo: {report.get('campos_pendientes_modelo', 'NO_VERIFICADOS')}",
        f"Cambios fisicos pendientes en el destino: {report.get('cambios_pendientes_destino', 'NO_VERIFICADOS')}",
        f"Cierre fisico verificado: {report['cierre_verificado']}", '',
        'La decision confirma 722 columnas TEXT existentes y autoriza ocho cambios numericos. '
        'Cero tipos provisionales en el modelo no acredita por si solo la migracion del destino.', '',
        '| Clase | Campo | Tipo objetivo | Accion |', '|---|---|---|---|']
    lines.extend(f"| {row['clase']} | {row['campo']} | {row['tipo_objetivo']} | {row['accion']} |"
                 for row in report.get('plan', []))
    lines += ['', '## Limites y trabajo de ingesta', ''] + ['- ' + item for item in report['advertencias']]
    if report.get('error'):
        lines += ['', '## Error', '', report['error'], '',
                  'Revise clase_en_curso, campo_en_curso, completadas y campos_observados_al_detener. '
                  'La siguiente ejecucion vuelve a leer el destino y reconoce los tipos ya aplicados.']
    with (revision / 'informe.md').open('x', encoding='utf-8') as stream:
        stream.write('\n'.join(lines) + '\n')


def inspect_global(a, args, model, folder, report, phase):
    result = validation.inspect_destination(a, args.workspace, args.database, args.owner, model)
    report['destino_' + phase] = result
    path = folder / ('destino_' + phase + '.csv')
    write_csv(path, result['campos'])
    report['archivo_destino_' + phase] = str(path)
    require(result['verificado'] and result['campos_verificados'] == 3340 and
            result['clases_esperadas'] == 76 and not result['incidencias'],
            f'Validacion global {phase}: el destino no coincide con las 76 clases y 3340 campos esperados. '
            'Revise el detalle del informe; no se corrigen diferencias ajenas al lote.')
    return result


def run(workspace, apply=False, database='ArcGisAWS', owner='gis', reports=None,
        arcpy_module=None, emit=print, model_dir=None):
    model_dir = Path(model_dir or HERE).resolve()
    parent = Path(reports or model_dir).resolve()
    require(parent.is_dir(), 'La carpeta de informes debe existir.')
    require(isinstance(apply, bool), 'La accion de aplicar debe ser booleana.')
    require(all(isinstance(value, str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', value)
                for value in (database, owner)), 'Base o propietario invalido.')
    args = SimpleNamespace(workspace=os.path.abspath(workspace), database=database, owner=owner, aplicar=apply)
    folder = parent / ('Cierre_Tipos_' + dt.datetime.now().strftime('%Y%m%d_%H%M%S_') + uuid.uuid4().hex[:10])
    folder.mkdir(exist_ok=False)
    report = dict(version_paquete='1.9', version_modelo=12, estado='INICIADO',
        modo='APLICAR_CIERRE' if apply else 'VALIDAR_CIERRE', workspace=args.workspace,
        database=database, owner=owner, inicio_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
        campos_pendientes_modelo=None, confirmaciones_texto=722, cambios_fisicos_aprobados=8,
        cambios_pendientes_destino=None, cierre_verificado=False, ingesta_autorizada=False,
        cambios_en_modelo=False, cambios_en_sde=False, operaciones_intentadas=[],
        completadas=[], plan=[], clase_en_curso=None, campo_en_curso=None,
        incidencias_campos_ingesta=copy.deepcopy(INGESTION_BLOCKS), bloqueos_ingesta=[],
        rutas_sin_destino=2601, elementos_sin_destino=140319,
        datasets_pendientes=['Datos_Externos', 'Datos_Internos'],
        advertencias=[
            'La aprobacion de tipos esta en el modelo distribuido; aplicar no modifica archivos del modelo.',
            'Solo se permiten ocho AlterField sobre clases existentes y vacias; no se crean ni borran objetos.',
            'Las tres reglas para <Null> y el mapeo de oficina_registral siguen abiertos; no se convierten valores.',
            'Las 2601 rutas sin destino, las llaves/relaciones de proyecto y los otros dos datasets conservan su fase propia.',
            'DDL no es una transaccion atomica. Un error detiene el lote y conserva los cambios ya realizados para reanudar.',
            'Este resultado no acredita ingesta, relaciones/FK, branch ni cumplimiento integral de los otros datasets.'])
    inventory, changes, model = {}, [], None
    failure = None
    try:
        references = input_hashes(model_dir)
        base, target, config = load_reference(model_dir)
        model, changes = approved_scope(base, target, config)
        report['bloqueos_ingesta'] = copy.deepcopy(config.get('bloqueos_ingesta', []))
        require(bool(report['bloqueos_ingesta']) and
                all(item.get('resuelto') is False for item in report['bloqueos_ingesta']),
                'El cierre debe conservar separados y abiertos los bloqueos de ingesta.')
        report.update(referencias_sha256=references, modelo_sha256=references['esquema.json'],
            campos_pendientes_modelo=0, campos_modelo=3340, clases_modelo=76)
        report_files(folder, report)
        emit('Informe: ' + str(folder))
        if arcpy_module is None:
            import arcpy as arcpy_module
        a = arcpy_module
        report['arcgis'] = a.GetInstallInfo().get('Version')
        selected = runner.scoped_model(model, sorted({row['clase'] for row in changes}))
        with a.EnvManager(overwriteOutput=False, extent=None):
            require(a.Exists(args.workspace), 'La conexion/geodatabase existente no se encuentra.')
            inventory, _ = runner.engine.inspect(a, args, model, [])
            report['rutas_clases'] = {cls['nombre']: inventory.get(cls['nombre'].casefold())
                                       for cls in selected['clases']}
            rows, before, indices, locks = migration.prepare_batch(
                a, args, selected, changes, inventory, report)
            for cls in selected['clases']:
                report['clase_en_curso'] = cls['nombre']
                dependencies(a, inventory[cls['nombre'].casefold()], cls['nombre'])
            report.update(campos_antes=before, indices_antes=indices, bloqueos_disponibles=locks,
                          cambios_pendientes_destino=pending_changes(rows), clase_en_curso=None)
            for name, available in locks.items():
                if not available:
                    report['advertencias'].append(
                        f'{name}: TestSchemaLock no disponible. Cierre su uso antes de aplicar cambios pendientes.')
            inspect_global(a, args, compatible_model(model, rows), folder, report, 'antes')
            require_inputs_unchanged(model_dir, references)
            for name, fields in before.items():
                migration.require_preserved(fields, migration.snapshot(a, inventory[name.casefold()]))
            report['estado'] = 'PREVALIDADO'
            report_files(folder, report)
            emit(f"Prevalidacion completa: 76 clases; 3340 campos; "
                 f"{report['cambios_pendientes_destino']} cambios fisicos pendientes; 722 TEXT confirmados en el modelo.")
            expected = copy.deepcopy(before)
            if apply and pending_changes(rows):
                for cls in selected['clases']:
                    name = cls['nombre']
                    path = inventory[name.casefold()]
                    one = runner.scoped_model(model, [name])
                    class_changes = [change for change in changes if change['clase'] == name]
                    candidates = {change['campo'] for change in class_changes}
                    report['clase_en_curso'] = name
                    migration.prepare_batch(a, args, one, class_changes, inventory, {})
                    dependencies(a, path, name)
                    migration.require_preserved(expected[name], migration.snapshot(a, path))
                    for change in class_changes:
                        row = next(row for row in rows if (row['clase'], row['campo']) ==
                                   (name, change['campo']))
                        if row['accion'] == 'YA_OBJETIVO':
                            continue
                        current = migration.snapshot(a, path)
                        migration.require_preserved(expected[name], current)
                        require(migration.guard_class(a, path, name, candidates) == indices[name],
                                f'{name}: cambio inesperado de indices.')
                        require(bool(a.TestSchemaLock(path)),
                                f'{name}: bloqueo de esquema no disponible; cierre su uso antes de reintentar.')
                        require_inputs_unchanged(model_dir, references)
                        report.update(clase_en_curso=name, campo_en_curso=change['campo'])
                        report['operaciones_intentadas'].append(dict(clase=name, campo=change['campo'],
                                                                    tipo_objetivo=change['tipo_objetivo']))
                        report['estado'] = 'ALTERACION_INICIADA'
                        report_files(folder, report)
                        a.management.AlterField(path, change['campo'], field_type=change['tipo_objetivo'])
                        after = migration.snapshot(a, path)
                        migration.require_preserved(current, after, [change['campo']])
                        require(migration.target_confirmed(after, change),
                                f'{name}.{change["campo"]}: ArcGIS no confirma el tipo objetivo.')
                        require(migration.guard_class(a, path, name, candidates) == indices[name],
                                f'{name}: cambio inesperado de indices despues de AlterField.')
                        expected[name] = after
                        row['accion'] = 'ALTERADA_VERIFICADA'
                        report['completadas'].append(name + '.' + change['campo'])
                        report.update(cambios_en_sde=True, cambios_pendientes_destino=pending_changes(rows),
                                      campo_en_curso=None, estado='CAMPO_VERIFICADO')
                        report_files(folder, report)
                        emit(f'CAMPO actualizado y verificado: {name}.{change["campo"]}')
                    runner.preflight(a, args, one)
                    migration.require_preserved(expected[name], migration.snapshot(a, path))
                report['clase_en_curso'] = None
                inspect_global(a, args, model, folder, report, 'despues')
                for name, fields in expected.items():
                    migration.require_preserved(fields, migration.snapshot(a, inventory[name.casefold()]))
                    candidates = {change['campo'] for change in changes if change['clase'] == name}
                    require(migration.guard_class(a, inventory[name.casefold()], name, candidates) == indices[name],
                            f'{name}: indices distintos al finalizar el lote.')
                report['campos_despues'] = expected
                report['verificacion_final_reutiliza_lectura_previa'] = False
            elif not pending_changes(rows):
                # La lectura previa ya contrasto el modelo objetivo completo.
                report['destino_despues'] = report['destino_antes']
                report['archivo_destino_despues'] = report['archivo_destino_antes']
                report['verificacion_final_reutiliza_lectura_previa'] = True
            require_inputs_unchanged(model_dir, references)
            report['cambios_pendientes_destino'] = pending_changes(rows)
            report['cierre_verificado'] = not pending_changes(rows) and bool(
                report.get('destino_despues', {}).get('verificado'))
            report['estado'] = ('TIPOS_CERRADOS_CON_PENDIENTES_DE_INGESTA' if report['cierre_verificado']
                                else 'CIERRE_VALIDADO_SIN_CAMBIOS')
    except Exception as exc:
        failure = exc
        report.update(estado='ERROR_DETENIDO', error=str(exc), cierre_verificado=False)
        if 'a' in locals() and inventory:
            observed = {}
            for name in sorted({change['clase'] for change in changes}):
                path = inventory.get(name.casefold())
                if path:
                    try:
                        observed[name] = migration.snapshot(a, path)
                    except Exception as observation_error:
                        observed[name] = dict(error_al_leer_estado=str(observation_error))
            report['campos_observados_al_detener'] = observed
            try:
                report['cambios_pendientes_destino'] = sum(not migration.target_confirmed(
                    observed[change['clase']], change) for change in changes)
            except (KeyError, TypeError):
                report['cambios_pendientes_destino'] = None
            if report.get('campos_antes'):
                report['cambios_en_sde'] = any(observed.get(name) != fields
                    for name, fields in report['campos_antes'].items())
    finally:
        report['fin_utc'] = dt.datetime.now(dt.timezone.utc).isoformat()
        try:
            report_files(folder, report)
        except OSError as write_error:
            if failure is None:
                raise
            emit(f'No se pudo guardar el estado final: {write_error}. Error original: {failure}')
        else:
            emit('Estado: ' + report['estado'])
            emit('Resultado JSON: ' + report['archivo_resultado'])
    if failure is not None:
        raise failure
    return folder, report
