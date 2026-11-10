"""Renombra clases existentes mediante ArcGIS y aplica aliases descriptivos.

No cambia campos, tipos, datos ni relaciones. Prevalida toda la seleccion y
reanuda por el nombre fisico observado si un Rename/AlterAliasName se interrumpe.
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

import datos_proyecto as runner
import actualizar_campos_aprobados as migration
import validacion_texto_sqlserver as sql_text
from ajustar_tipos_estructuras import snapshot

HERE = Path(__file__).resolve().parent
IDENTIFIER = re.compile(r'[a-z][a-z0-9]*(?:_[a-z0-9]+)*')


def require(condition, message):
    runner.engine.require(condition, message)


def selected_mapping(model, mapping, config, names=None):
    require(mapping.get('version_paquete') == '1.6', 'Mapeo de nombres distinto de 1.6.')
    rows = copy.deepcopy(mapping.get('clases'))
    require(isinstance(rows, list) and bool(rows), 'Mapeo de nombres vacio.')
    available = {c['nombre']: c for c in model['clases'] if c['dataset'] == runner.DATASET}
    previous, target = set(), set()
    for row in rows:
        old, new = row.get('nombre_anterior'), row.get('nombre_nuevo')
        require(all(isinstance(n, str) and IDENTIFIER.fullmatch(n) for n in (old, new)),
                'Los nombres del mapeo deben ser identificadores snake_case.')
        require(old not in previous and new not in target, 'Nombres duplicados en el mapeo.')
        previous.add(old); target.add(new)
        require(new in available, f'{new}: clase ajena al modelo objetivo.')
        cls = available[new]
        require(row.get('geometria') == cls['geometria'] and row.get('rol') == cls.get('rol'),
                f'{new}: geometria o rol distintos del modelo.')
        require(type(row.get('renombrar')) is bool and row['renombrar'] == (old != new),
                f'{new}: indicador renombrar incompatible.')
        alias = row.get('alias')
        require(alias is None or isinstance(alias, str) and bool(alias.strip()),
                f'{new}: alias no valido.')
        if cls.get('rol') == 'migrada':
            require(old == new and alias is None, 'Los nombres y aliases migrados se conservan.')
        else:
            require(alias == cls.get('alias') and alias is not None,
                    f'{new}: alias distinto del modelo aprobado.')
    require(target == set(available), 'El mapeo debe representar todas las clases del modelo.')
    for row in rows:
        require(row['nombre_nuevo'] not in previous or row['nombre_anterior'] == row['nombre_nuevo'],
                'El mapeo contiene cadenas o ciclos de renombrado; requiere otro procedimiento.')
    # Valida los cambios de tipos reconocidos, pero nunca los aplica.
    _, changes = migration.selected_model(model, config)
    require(names is None or not isinstance(names, str), 'Indique nombres como lista.')
    selected = target if names is None else set(names)
    require(bool(selected) and selected <= target, 'Seleccion vacia o nombres objetivo desconocidos.')
    rows = sorted((r for r in rows if r['nombre_nuevo'] in selected), key=lambda r: r['nombre_nuevo'])
    return rows, [c for c in changes if c['clase'] in selected]


def dependency_guard(a, path):
    d = a.Describe(path)
    for prop, label in (('relationshipClassNames','relaciones'), ('attributeRules','reglas de atributos'),
                        ('isArchived','archivado'), ('isReplicated','replicacion'),
                        ('subtypeFieldName','subtipos')):
        require(not getattr(d, prop, None), f'{path}: tiene {label}; revisar dependencias antes de renombrar.')
    require(hasattr(a.da, 'ListSubtypes'), 'ArcPy no permite comprobar subtipos.')
    require(not any(x.get('SubtypeField') for x in (a.da.ListSubtypes(path) or {}).values()),
            f'{path}: tiene subtipos; no se renombra automaticamente.')


def geometry_snapshot(a, path):
    d = a.Describe(path)
    result = {key: getattr(d, key, None) for key in ('shapeType','hasZ','hasM','hasOID',
        'OIDFieldName','shapeFieldName','globalIDFieldName','lengthFieldName','areaFieldName',
        'hasGlobalID','editorTrackingEnabled','isTimeInUTC','creatorFieldName',
        'createdAtFieldName','editorFieldName','editedAtFieldName','isVersioned')}
    result['wkid'] = d.spatialReference.factoryCode
    # Algunos nombres de campo SDE incluyen el nombre de tabla; comparar su base.
    for key in ('OIDFieldName','shapeFieldName','globalIDFieldName','lengthFieldName','areaFieldName'):
        if isinstance(result[key], str):
            result[key] = runner.engine.simple(result[key])
    return result


def desired_path(path, old, new):
    """Conserva calificacion real database/owner que expone ArcGIS."""
    prefix, separator, basename = os.path.basename(path).rpartition('.')
    require((basename if separator else os.path.basename(path)).casefold() == old.casefold(),
            'La ruta observada no corresponde al nombre del mapeo.')
    return os.path.join(os.path.dirname(path), prefix + '.' + new if separator else new)


def resolve_inventory(a, args, model, rows):
    inventory, _ = runner.engine.inspect(a, args, model, [])
    resolved = {}
    for row in rows:
        old, new = row['nombre_anterior'], row['nombre_nuevo']
        old_path, new_path = inventory.get(old.casefold()), inventory.get(new.casefold())
        require(old == new or not (old_path and new_path),
                f'Existen ambos nombres {old} y {new}; no se fusionan ni eliminan clases.')
        path = new_path or old_path
        require(path is not None, f'No existe {old} ni {new}; esta herramienta no crea clases.')
        actual = new if new_path else old
        physical = runner.engine.simple(os.path.basename(path))
        require(physical == actual,
                f'{physical}: escritura del nombre incompatible; se esperaba exactamente {actual}. '
                'No se confirma un nombre por coincidencia sin distinguir mayusculas.')
        resolved[new] = (actual, path)
        require(a.ValidateTableName(new, args.workspace) == new,
                f'Nombre objetivo no valido en el destino: {new}.')
        expected = desired_path(path, new if new_path else old, new)
        if path != expected:
            require(not a.Exists(expected), f'El destino ya existe: {expected}.')
    return resolved


def prepare(a, args, source, rows, changes, report):
    model = runner.scoped_model(source, [r['nombre_nuevo'] for r in rows])
    resolved = resolve_inventory(a, args, model, rows)
    aliases = {r['nombre_nuevo']: r['alias'] for r in rows}
    before, plan = {}, []
    actual_names = {}
    for cls in model['clases']:
        target = cls['nombre']
        actual, path = resolved[target]
        report['clase_en_curso'] = target
        actual_names[target] = actual
        listed = runner.engine.field_index(a.ListFields(path))
        specs = {f['nombre']: f for f in cls['campos']}
        for change in (c for c in changes if c['clase'] == target):
            field = listed.get(change['campo'])
            require(field is not None, f'{actual}: falta {change["campo"]}; no se crean campos.')
            action = migration.field_action(field, change)
            if action != 'YA_OBJETIVO':
                specs[change['campo']].update(tipo=change['tipo_anterior'], longitud=change['longitud_anterior'])
            if change['tipo_objetivo'] == 'TEXT' and args.workspace.lower().endswith('.sde'):
                sql_text.verify(a, args.workspace, args.owner,
                    require_max=field.length >= change['longitud_objetivo'], table_name=actual)
        cls['nombre'] = actual
        indices = migration.guard_class(a, path, actual, set())
        dependency_guard(a, path)
        before[target] = dict(campos=snapshot(a, path), indices=indices,
                              geometria=geometry_snapshot(a, path))
        alias = getattr(a.Describe(path), 'aliasName', None)
        require(isinstance(alias, str), f'{actual}: no se pudo leer el alias.')
        rename = actual != target
        update_alias = aliases[target] is not None and alias != aliases[target]
        lock = bool(a.TestSchemaLock(path))
        if args.aplicar and (rename or update_alias):
            require(lock, f'No hay bloqueo de esquema disponible sobre {actual}; cierre su uso.')
        plan.append(dict(nombre_actual=actual, nombre_nuevo=target, ruta_actual=path,
            alias_actual=alias, alias_objetivo=aliases[target], renombrar=rename,
            actualizar_alias=update_alias, bloqueo_disponible=lock,
            accion='PENDIENTE' if rename or update_alias else 'YA_OBJETIVO'))
    for relationship in model.get('relaciones', []) + model.get('relaciones_negocio', []):
        for key in ('origen','destino'):
            relationship[key] = actual_names.get(relationship[key], relationship[key])
    runner.preflight(a, args, model)
    report['clase_en_curso'] = None
    return sorted(plan, key=lambda r: r['nombre_nuevo']), before


def normalized_path(path):
    return os.path.normcase(os.path.normpath(os.path.abspath(path)))


def reference_context(row, path):
    return dict(nombre_anterior=row['nombre_anterior'], nombre_objetivo=row['nombre_nuevo'],
                ruta_referencia=path)


def qualified_alias_only(before, after, context, path):
    """Reconoce solamente <mismo esquema>.<clase aprobada>.<mismo campo>."""
    if not context or context['nombre_anterior'] == context['nombre_objetivo']:
        return False
    original = context['ruta_referencia']
    if normalized_path(os.path.dirname(original)) != normalized_path(os.path.dirname(path)):
        return False
    old_prefix, old_dot, old_name = os.path.basename(original).rpartition('.')
    new_prefix, new_dot, new_name = os.path.basename(path).rpartition('.')
    if not (old_dot and new_dot and old_prefix and old_prefix == new_prefix
            and old_name == context['nombre_anterior'] and new_name == context['nombre_objetivo']):
        return False
    field = before.get('nombre')
    if not isinstance(field, str) or not field or after.get('nombre') != field:
        return False
    if before.get('alias') != os.path.basename(original) + '.' + field:
        return False
    if after.get('alias') != os.path.basename(path) + '.' + field:
        return False
    old_properties = {key: value for key, value in before.items() if key != 'alias'}
    new_properties = {key: value for key, value in after.items() if key != 'alias'}
    return old_properties == new_properties


def compare_fields(before, after, context=None, path=''):
    differences, recognized = [], []
    for field in sorted(set(before) | set(after)):
        if field not in before or field not in after:
            differences.append(dict(campo=field, propiedad='campo', antes=before.get(field),
                despues=after.get(field), antes_presente=field in before, despues_presente=field in after))
            continue
        original, current = before[field], after[field]
        if original == current:
            continue
        if qualified_alias_only(original, current, context, path):
            recognized.append(dict(campo=field, propiedad='alias', antes=original['alias'],
                despues=current['alias'], regla='MISMO_ESQUEMA_CLASE_APROBADA_MISMO_CAMPO'))
            continue
        for property_name in sorted(set(original) | set(current)):
            has_before, has_after = property_name in original, property_name in current
            if has_before and has_after and original[property_name] == current[property_name]:
                continue
            differences.append(dict(campo=field, propiedad=property_name,
                antes=original.get(property_name), despues=current.get(property_name),
                antes_presente=has_before, despues_presente=has_after))
    return differences, recognized


def append_unique(report, key, item):
    if report is not None:
        collection = report.setdefault(key, [])
        if item not in collection:
            collection.append(item)


def validate_reference_path(path, args, row):
    require(isinstance(path, str) and os.path.isabs(path),
            f'{row["nombre_nuevo"]}: ruta original ausente o no absoluta.')
    dataset = os.path.dirname(path)
    require(normalized_path(os.path.dirname(dataset)) == normalized_path(args.workspace)
            and runner.engine.simple(os.path.basename(dataset)).casefold() == runner.DATASET.casefold(),
            f'{row["nombre_nuevo"]}: ruta original fuera del workspace o de Datos_Proyecto.')
    parts = os.path.basename(path).split('.')
    require(parts[-1] in (row['nombre_anterior'], row['nombre_nuevo']),
            f'{row["nombre_nuevo"]}: ruta original incompatible con el mapeo.')
    if args.workspace.lower().endswith('.sde'):
        require(len(parts) in (2, 3) and parts[-2].casefold() == args.owner.casefold(),
                f'{row["nombre_nuevo"]}: propietario de la ruta original incompatible.')
        require(len(parts) != 3 or parts[0].casefold() == args.database.casefold(),
                f'{row["nombre_nuevo"]}: base de la ruta original incompatible.')


def load_reference(path, args, rows, hashes):
    """Carga evidencia previa sin adoptar el estado actual como referencia."""
    path = Path(path).resolve()
    raw = path.read_bytes()
    previous = json.loads(raw.decode('utf-8-sig'))
    require(isinstance(previous, dict) and previous.get('version_paquete') in ('1.6', '1.6.2')
            and previous.get('modo') == 'APLICAR_NOMBRES',
            'Use el resultado JSON original de Aplicar nombres aprobados 1.6 o 1.6.2.')
    require(isinstance(previous.get('workspace'), str)
            and normalized_path(previous['workspace']) == normalized_path(args.workspace),
            'El workspace no coincide con el informe original.')
    require(str(previous.get('database', '')).casefold() == args.database.casefold()
            and str(previous.get('owner', '')).casefold() == args.owner.casefold(),
            'Base o propietario distintos del informe original.')
    for key, digest in hashes.items():
        require(previous.get(key) == digest, f'{key}: no coincide con el informe original.')
    baseline = previous.get('campos_y_metadatos_antes')
    require(isinstance(baseline, dict), 'El informe original no contiene la referencia de campos.')
    paths = previous.get('rutas_referencia')
    if paths is None:
        require(previous['version_paquete'] == '1.6',
                'El informe 1.6.2 no contiene las rutas originales de referencia.')
        plan = previous.get('plan')
        require(isinstance(plan, list), 'El informe original no contiene su plan de rutas.')
        plan_names = [item.get('nombre_nuevo') for item in plan if isinstance(item, dict)]
        require(len(plan_names) == len(plan) == len(set(plan_names)), 'Plan original ambiguo o mal formado.')
        paths = {item['nombre_nuevo']: item.get('ruta_actual') for item in plan}
    require(isinstance(paths, dict), 'Rutas originales de referencia mal formadas.')
    selected, contexts = {}, {}
    for row in rows:
        target = row['nombre_nuevo']
        before = baseline.get(target)
        require(isinstance(before, dict) and isinstance(before.get('campos'), dict)
                and bool(before['campos']) and all(isinstance(field, dict) for field in before['campos'].values())
                and isinstance(before.get('indices'), list) and isinstance(before.get('geometria'), dict),
                f'{target}: no hay una referencia original completa; no se reconstruye con el estado actual.')
        original_path = paths.get(target)
        validate_reference_path(original_path, args, row)
        selected[target] = copy.deepcopy(before)
        contexts[target] = reference_context(row, original_path)
    return selected, contexts, dict(ruta=str(path), sha256=hashlib.sha256(raw).hexdigest())


def preserved(a, path, before, context=None, report=None):
    cls = context['nombre_objetivo'] if context else runner.engine.simple(os.path.basename(path))
    if report is not None:
        report['clase_en_curso'] = cls
    actual = snapshot(a, path)
    differences, recognized = compare_fields(before['campos'], actual, context, path)
    for item in recognized:
        append_unique(report, 'aliases_calificados_reconocidos', dict(clase=cls, ruta=path, **item))
    if differences:
        if report is not None:
            report['clase_en_curso'] = cls
            report.setdefault('campos_observados_al_detener', {})[cls] = actual
        for item in differences:
            append_unique(report, 'diferencias_campos_no_admitidas', dict(clase=cls, ruta=path, **item))
        detail = '; '.join(f'{cls}.{item["campo"]}.{item["propiedad"]}: '
                           f'{item["antes"]!r} -> {item["despues"]!r}' for item in differences[:10])
        require(False, 'Se modificaron campos durante el renombrado. ' + detail)
    require(migration.guard_class(a, path, runner.engine.simple(os.path.basename(path)), set()) == before['indices'],
            'Se modificaron indices durante el renombrado.')
    require(geometry_snapshot(a, path) == before['geometria'],
            'Se modificaron geometria, GlobalID o auditoria durante el renombrado.')
    dependency_guard(a, path)


def check_reference_file(reference):
    if reference:
        require(hashlib.sha256(Path(reference['ruta']).read_bytes()).hexdigest() == reference['sha256'],
                'El informe original cambio durante la ejecucion; detener sin adoptar otra referencia.')


def run(workspace, apply=False, database='ArcGisAWS', owner='gis', reports=None,
        arcpy_module=None, emit=print, model_path=None, mapping_path=None,
        config_path=None, names=None, previous_report_path=None):
    require(all(isinstance(v, str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', v)
                for v in (database, owner)), 'Base o propietario invalido.')
    raw = Path(model_path or HERE/'esquema.json').read_bytes()
    map_raw = Path(mapping_path or HERE/'nombres_clases_1_6.json').read_bytes()
    config_raw = Path(config_path or HERE/'campos_aprobados_1_5.json').read_bytes()
    source = json.loads(raw.decode('utf-8-sig'))
    mapping = json.loads(map_raw.decode('utf-8-sig'))
    if mapping.get('modelo_objetivo_sha256'):
        require(mapping['modelo_objetivo_sha256'] == hashlib.sha256(raw).hexdigest(),
                'El modelo objetivo no coincide con el hash aprobado del mapeo.')
    rows, changes = selected_mapping(source, mapping,
                                    json.loads(config_raw.decode('utf-8-sig')), names)
    model = runner.scoped_model(source, [r['nombre_nuevo'] for r in rows])
    args = SimpleNamespace(workspace=os.path.abspath(workspace), database=database,
                           owner=owner, aplicar=apply)
    hashes = dict(modelo_sha256=hashlib.sha256(raw).hexdigest(),
                  mapeo_sha256=hashlib.sha256(map_raw).hexdigest(),
                  aprobacion_tipos_sha256=hashlib.sha256(config_raw).hexdigest())
    reference = None
    if previous_report_path:
        reference_before, reference_contexts, reference = load_reference(
            previous_report_path, args, rows, hashes)
    folder = Path(reports or HERE)/('Nombres_Clases_'+dt.datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8])
    report = dict(estado='INICIADO', modo='APLICAR_NOMBRES' if apply else 'VALIDAR_NOMBRES',
        version_paquete='1.6.2', workspace=args.workspace, database=database, owner=owner, **hashes,
        inicio_utc=dt.datetime.now(dt.timezone.utc).isoformat(), completadas=[],
        clase_en_curso=None, operacion_en_curso=None, aliases_calificados_reconocidos=[],
        diferencias_campos_no_admitidas=[], informe_referencia=reference,
        clases=[dict(nombre=c['nombre'],geometria=c['geometria'],campos=len(c['campos']),
                     tipos_pendientes=sum(runner.provisional(f) for f in c['campos']),accion='POR_VALIDAR')
                for c in model['clases']],
        advertencias=['Solo renombra clases existentes y ajusta aliases aprobados; no cambia columnas ni carga datos.',
            'Cerrar el uso de las clases e impedir cargas concurrentes durante el procedimiento.',
            'Un error detiene el lote sin deshacer nombres ya aplicados; reejecutar reconoce el estado actual.',
            'Solo se admite el cambio exacto de alias cualificado al nombre de clase aprobado, conservando esquema y campo.',
            'El renombrado no actualiza automaticamente referencias de mapas, servicios o consultas externas.'])
    if reference:
        report.update(campos_y_metadatos_antes=reference_before,
                      rutas_referencia={name: ctx['ruta_referencia'] for name, ctx in reference_contexts.items()})
    runner.report_files(folder, report, model)
    emit(f'Informe: {folder}')
    try:
        if arcpy_module is None:
            import arcpy as arcpy_module
        a = arcpy_module
        report['arcgis'] = a.GetInstallInfo().get('Version')
        with a.EnvManager(overwriteOutput=False, extent=None):
            # Comparar todas las referencias antes de permitir cualquier escritura.
            if reference:
                resolved = resolve_inventory(a, args, model, rows)
                for row in rows:
                    target = row['nombre_nuevo']
                    report.update(clase_en_curso=target, operacion_en_curso='VERIFICAR_REFERENCIA_ORIGINAL')
                    preserved(a, resolved[target][1], reference_before[target], reference_contexts[target], report)
                check_reference_file(reference)
            plan, current_before = prepare(a,args,source,rows,changes,report)
            if reference:
                before, contexts = reference_before, reference_contexts
            else:
                before = current_before
                row_by_name = {row['nombre_nuevo']: row for row in rows}
                contexts = {entry['nombre_nuevo']: reference_context(row_by_name[entry['nombre_nuevo']], entry['ruta_actual'])
                            for entry in plan}
            with (folder/'plan_nombres.csv').open('x',encoding='utf-8-sig',newline='') as stream:
                writer=csv.DictWriter(stream,fieldnames=list(plan[0]),delimiter=';')
                writer.writeheader();writer.writerows(plan)
            report.update(plan=plan,campos_y_metadatos_antes=before,estado='PREVALIDADO',
                          rutas_referencia={name: ctx['ruta_referencia'] for name, ctx in contexts.items()},
                          operacion_en_curso=None, archivo_plan=str(folder/'plan_nombres.csv'))
            runner.report_files(folder,report,model)
            emit(f'Prevalidacion completa: {len(rows)} clases; '
                 f'{sum(p["renombrar"] for p in plan)} nombres y '
                 f'{sum(p["actualizar_alias"] or p["renombrar"] for p in plan)} aliases por verificar.')
            for item in report['aliases_calificados_reconocidos']:
                emit(f'ALIAS CALIFICADO reconocido: {item["clase"]}.{item["campo"]}: '
                     f'{item["antes"]!r} -> {item["despues"]!r}')
            if apply:
                by_target={r['nombre_nuevo']:r for r in rows}
                for entry in plan:
                    target=entry['nombre_nuevo']
                    report['clase_en_curso']=target
                    current,_=prepare(a,args,source,[by_target[target]],changes,report)
                    current=current[0];path=current['ruta_actual']
                    check_reference_file(reference)
                    preserved(a,path,before[target],contexts[target],report)
                    if current['renombrar']:
                        require(bool(a.TestSchemaLock(path)),f'No hay bloqueo de esquema sobre {target}.')
                        migration.ensure_empty(a,path,target)
                        destination=desired_path(path,current['nombre_actual'],target)
                        require(not a.Exists(destination),f'El destino ya existe: {destination}.')
                        report.update(clase_en_curso=target,operacion_en_curso='RENOMBRAR_CLASE')
                        runner.report_files(folder,report,model)
                        check_reference_file(reference)
                        a.management.Rename(path,destination,'FeatureClass')
                        resolved=resolve_inventory(a,args,model,[by_target[target]])
                        actual,path=resolved[target]
                        require(actual==target,f'ArcGIS no confirma el nombre {target}.')
                        preserved(a,path,before[target],contexts[target],report)
                        report['completadas'].append(dict(clase=target,operacion='RENOMBRAR_CLASE'))
                    desired_alias=by_target[target]['alias']
                    actual_alias=getattr(a.Describe(path),'aliasName',None)
                    if desired_alias is not None and actual_alias!=desired_alias:
                        require(bool(a.TestSchemaLock(path)),f'No hay bloqueo de esquema sobre {target}.')
                        migration.ensure_empty(a,path,target)
                        preserved(a,path,before[target],contexts[target],report)
                        report.update(clase_en_curso=target,operacion_en_curso='ACTUALIZAR_ALIAS')
                        runner.report_files(folder,report,model)
                        check_reference_file(reference)
                        a.AlterAliasName(path,desired_alias)
                        require(getattr(a.Describe(path),'aliasName',None)==desired_alias,
                                f'ArcGIS no confirma el alias de {target}.')
                        report['completadas'].append(dict(clase=target,operacion='ACTUALIZAR_ALIAS'))
                    preserved(a,path,before[target],contexts[target],report)
                    require(desired_alias is None or getattr(a.Describe(path),'aliasName',None)==desired_alias,
                            f'{target}: alias objetivo no verificado.')
                    entry.update(accion='VERIFICADA',nombre_actual=target,ruta_actual=path,
                                 alias_actual=getattr(a.Describe(path),'aliasName',None))
                    report['operacion_en_curso']=None
                    runner.report_files(folder,report,model)
                    emit(f'NOMBRE y alias verificados: {target}')
                final,_=prepare(a,args,source,rows,changes,report)
                require(all(p['accion']=='YA_OBJETIVO' for p in final),'Quedan nombres o aliases pendientes.')
                for item in final:
                    preserved(a,item['ruta_actual'],before[item['nombre_nuevo']],contexts[item['nombre_nuevo']],report)
                report['plan_final']=final
            check_reference_file(reference)
            report['estado']='NOMBRES_VERIFICADOS' if apply else 'VALIDACION_OK_SIN_CAMBIOS'
            report['clase_en_curso']=None
            for item in report['clases']:
                item['accion']=report['estado']
    except Exception as exc:
        report.update(estado='ERROR_DETENIDO',error=str(exc))
        if 'a' in locals():
            try:
                inventory=runner.engine.find_objects(a,args)
                report['nombres_observados_al_detener']={r['nombre_nuevo']:
                    {n:inventory.get(n.casefold()) for n in {r['nombre_anterior'],r['nombre_nuevo']}}
                    for r in rows}
            except Exception as diagnostic:
                report['error_al_leer_estado']=str(diagnostic)
        raise
    finally:
        report['fin_utc']=dt.datetime.now(dt.timezone.utc).isoformat()
        try:
            runner.report_files(folder,report,model)
        except OSError as logging_error:
            if not report.get('error'):
                raise
            emit(f'No se pudo guardar el informe final: {logging_error}. Error original: {report["error"]}')
        else:
            emit(f'Estado: {report["estado"]}')
            emit(f'Resultado JSON: {report["archivo_resultado"]}')
    return folder,report
