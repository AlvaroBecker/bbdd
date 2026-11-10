"""Preparacion acotada del padre: dominios completos y auditoria UTC separada.

Las operaciones de esquema no forman una transaccion unica. Cada paso queda
registrado y comprobado; un fallo no se describe como rollback automatico.
Agregar la auditoria separada requiere aprobacion explicita del operador.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import uuid

import alta_proyectos as alta

HERE = Path(__file__).resolve().parent
require = alta.require
NATIVE = {'created_user': ('TEXT', 255), 'created_date': ('DATE', None),
          'last_edited_user': ('TEXT', 255), 'last_edited_date': ('DATE', None)}
TRACKING = dict(creatorFieldName='created_user', createdAtFieldName='created_date',
                editorFieldName='last_edited_user', editedAtFieldName='last_edited_date')
EXPECTED_DOMAINS = {'id_tipo_proyecto': {7: 'Central de Generación', 8: 'Línea de Transmisión'},
                    'id_estado_proyecto': {3: 'Registrado', 4: 'Con malla', 5: 'Finalizado', 6: 'Cancelado'}}


def read_config():
    path = HERE / 'configuracion_proyecto_1_12.json'
    raw = path.read_bytes()
    config = json.loads(raw.decode('utf-8-sig'))
    require(config['version'] == '1.12' and config['tabla'] == alta.TABLE, 'Configuracion no compatible.')
    require(len(config['dominios']) == 2, 'La configuracion debe contener exactamente dos dominios.')
    actual = {d['campo']: {c['codigo']: c['descripcion'] for c in d['codigos']} for d in config['dominios']}
    require(actual == EXPECTED_DOMAINS, 'Catalogo de parametros distinto del original aprobado.')
    expected_names = {'id_tipo_proyecto': 'mline_proyecto_tipo', 'id_estado_proyecto': 'mline_proyecto_estado'}
    require(all(d['nombre'] == expected_names[d['campo']] and d['tipo_arcgis'] == 'LONG'
                and d['tipo_dominio'] == 'CODED' for d in config['dominios']), 'Definicion de dominios alterada.')
    return config, hashlib.sha256(raw).hexdigest()


def field_signature(fields):
    return {name: dict(tipo=f.type, longitud=f.length, nullable=f.isNullable,
                      precision=f.precision, escala=f.scale, alias=f.aliasName,
                      required=f.required, default=getattr(f, 'defaultValue', None))
            for name, f in fields.items()}


def inspect(a, workspace, database, owner, config):
    path, fields, metadata = alta.inspect_parent(a, workspace, database, owner)
    # Estas son precisamente las tres condiciones que esta herramienta resuelve.
    repairable = {
        'Falta Editor Tracking, requerido por el EFT para tablas editables. Configurarlo antes de aplicar.',
        'id_tipo_proyecto: falta un dominio codificado que acepte el valor 8.',
        'id_estado_proyecto: falta un dominio codificado que acepte el valor 3.'}
    blockers = [s for s in metadata['incidencias'] if s not in repairable]
    require(not blockers, 'Condiciones fuera del alcance: ' + ' | '.join(blockers))
    rows = alta.read_rows(a, path, fields)
    # No se asignan claves aqui; permite acreditar preservacion y catalogo coherente.
    alta.logic.plan_projects(rows)
    operations, resolved = [], []
    domains = {d.name: d for d in a.da.ListDomains(workspace)}
    for spec in config['dominios']:
        field = fields[spec['campo']]
        require(field.type == 'Integer', f"{spec['campo']}: se requiere LONG para el dominio original.")
        codes = EXPECTED_DOMAINS[spec['campo']]
        for row in rows:
            require(row[spec['campo']] is None or row[spec['campo']] in codes,
                    f"{spec['campo']}: valor historico fuera del catalogo completo: {row[spec['campo']]!r}.")
        name = field.domain or spec['nombre']
        domain = domains.get(name)
        if domain is None:
            require(not field.domain, f'{name}: dominio asignado no encontrado.')
            operations.append(dict(accion='CREAR_DOMINIO', nombre=name, descripcion=spec['descripcion']))
            current = {}
        else:
            require(domain.domainType == 'CodedValue' and domain.type in ('Integer', 'Long'),
                    f'{name}: dominio existente de otro tipo; no se sustituye.')
            current = domain.codedValues
            require(all(k in codes and codes[k] == v for k, v in current.items()),
                    f'{name}: dominio con codigos o descripciones incompatibles; no se modifica.')
            if name != spec['nombre']:
                require(current == codes, f'{name}: solo se reutiliza un dominio alternativo completo y equivalente.')
            if current != codes and metadata['geodatabase_remota']:
                require(str(getattr(domain, 'owner', '')).casefold() == owner.casefold(),
                        f'{name}: no se amplian dominios de otro propietario.')
        for code, label in codes.items():
            if code not in current:
                operations.append(dict(accion='AGREGAR_CODIGO', nombre=name, codigo=code, descripcion=label))
        if field.domain != name:
            operations.append(dict(accion='ASIGNAR_DOMINIO', campo=spec['campo'], nombre=name))
        resolved.append(dict(campo=spec['campo'], nombre=name, codigos=codes))
    description = a.Describe(path)
    enabled = bool(description.editorTrackingEnabled)
    if enabled:
        require(all(alta.engine.simple(getattr(description, k, '')).casefold() == v for k, v in TRACKING.items()),
                'Ya existe otra configuracion de auditoria. No se desactiva ni se reasigna automaticamente.')
        require(description.isTimeInUTC, 'La auditoria existente no usa UTC; no se cambia automaticamente.')
    for name, (kind, length) in NATIVE.items():
        f = fields.get(name)
        if f is None:
            require(not enabled, 'Editor Tracking hace referencia a un campo inexistente.')
            operations.append(dict(accion='AGREGAR_CAMPO', campo=name, tipo=kind, longitud=length))
        else:
            expected = 'String' if kind == 'TEXT' else 'Date'
            require(f.type == expected and (length is None or f.length >= length),
                    f'{name}: campo preexistente incompatible; no se altera ni se borra.')
            require(f.isNullable and not f.required, f'{name}: la auditoria separada requiere un campo nullable no obligatorio.')
            require(kind != 'DATE' or f.precision == 0, f'{name}: se requiere fecha de precision baja.')
            require(getattr(f, 'defaultValue', None) is None and not f.domain,
                    f'{name}: campo con default/dominio ajeno a la auditoria propuesta.')
            if not enabled:
                require(all(row[name] is None for row in rows),
                        f'{name}: contiene valores de origen no acreditado; no se reinterpretan como auditoria UTC.')
    if not enabled:
        operations.append(dict(accion='ACTIVAR_TRACKING', campos=TRACKING, zona='UTC'))
    plan = dict(tabla=path, registros=len(rows), operaciones=operations,
        dominios=resolved, tracking_previamente_activo=enabled,
        campos_auditoria_propuestos=[dict(nombre=n, tipo=t, longitud=l) for n, (t, l) in NATIVE.items()],
        requiere_aprobacion_auditoria=any(op['accion'] in ('AGREGAR_CAMPO', 'ACTIVAR_TRACKING') for op in operations),
        zona_historica_acreditada=False, conversion_fechas_historicas=False,
        metadata_destino=metadata)
    return path, fields, rows, plan


def verify_preserved(a, path, before_fields, before_rows, native_was_enabled):
    fields = alta.engine.field_index(a.ListFields(path))
    before_sig, now_sig = field_signature(before_fields), field_signature(fields)
    require(all(now_sig.get(name) == sig for name, sig in before_sig.items()),
            'Cambio inesperado en un campo preexistente. Revisar el informe; no se ejecuta borrado automatico.')
    require(all(fields[name].domain == field.domain for name, field in before_fields.items()
                if name not in EXPECTED_DOMAINS), 'Cambio de dominio fuera de los dos campos autorizados.')
    require(set(fields) - set(before_fields) <= set(NATIVE), 'Aparecio una columna fuera del alcance.')
    rows = alta.read_rows(a, path, fields)
    projected = [{name: row[name] for name in before_fields} for row in rows]
    require(projected == before_rows, 'Cambio inesperado en filas historicas. Se detienen los siguientes pasos.')
    if not native_was_enabled:
        require(all(row.get(name) is None for row in rows for name in NATIVE),
                'Se poblo auditoria retrospectiva inesperadamente. No continuar sin revisar.')


def execute_step(a, workspace, path, step):
    action = step['accion']
    if action == 'CREAR_DOMINIO':
        a.management.CreateDomain(workspace, step['nombre'], step['descripcion'], 'LONG', 'CODED', 'DEFAULT', 'DEFAULT')
    elif action == 'AGREGAR_CODIGO':
        a.management.AddCodedValueToDomain(workspace, step['nombre'], step['codigo'], step['descripcion'])
    elif action == 'ASIGNAR_DOMINIO':
        fields = alta.engine.field_index(a.ListFields(path))
        a.management.AssignDomainToField(path, fields[step['campo']].name, step['nombre'])
    elif action == 'AGREGAR_CAMPO':
        kwargs = dict(field_is_nullable='NULLABLE', field_is_required='NON_REQUIRED')
        if step['longitud'] is not None:
            kwargs['field_length'] = step['longitud']
        a.management.AddField(path, step['campo'], step['tipo'], **kwargs)
    elif action == 'ACTIVAR_TRACKING':
        fields = alta.engine.field_index(a.ListFields(path))
        a.management.EnableEditorTracking(path, fields['created_user'].name, fields['created_date'].name,
            fields['last_edited_user'].name, fields['last_edited_date'].name, 'NO_ADD_FIELDS', 'UTC')
    else:
        raise ValueError('Operacion no autorizada: ' + action)


def verify_step(a, workspace, path, step):
    action = step['accion']
    if action in ('CREAR_DOMINIO', 'AGREGAR_CODIGO'):
        found = {d.name: d for d in a.da.ListDomains(workspace)}.get(step['nombre'])
        require(found is not None and found.domainType == 'CodedValue' and found.type in ('Integer', 'Long'),
                'No se verifico el dominio creado.')
        if action == 'AGREGAR_CODIGO':
            require(found.codedValues.get(step['codigo']) == step['descripcion'], 'Codigo no verificado.')
    elif action == 'ASIGNAR_DOMINIO':
        require(alta.engine.field_index(a.ListFields(path))[step['campo']].domain == step['nombre'],
                'Dominio no asignado al campo esperado.')
    elif action == 'AGREGAR_CAMPO':
        f = alta.engine.field_index(a.ListFields(path)).get(step['campo'])
        require(f is not None and f.type == ('String' if step['tipo'] == 'TEXT' else 'Date'),
                'Campo nativo no creado con el tipo esperado.')
    elif action == 'ACTIVAR_TRACKING':
        d = a.Describe(path)
        require(d.editorTrackingEnabled and d.isTimeInUTC
                and all(alta.engine.simple(getattr(d, k, '')).casefold() == v for k, v in TRACKING.items()),
                'Editor Tracking no quedo configurado en los cuatro campos UTC previstos.')


def save_report(folder, report):
    report['archivo_resultado'] = str(folder / 'resultado.json')
    alta.write_json(folder / 'resultado.json', report)
    lines = ['# Configuracion del catalogo de proyectos 1.12', '', f"Estado: **{report['estado']}**.", '',
        'Se preservan las filas, IDs, codigos y fechas de auditoria heredadas. No se registra ningun proyecto.',
        'La auditoria UTC propuesta usa created_user, created_date, last_edited_user y last_edited_date. '
        'Son campos administrados por ArcGIS, no nombres expresamente ordenados por el EFT. '
        'Se requiere aprobacion para esta decision de implementacion.', '',
        'Dominios completos: tipo 7/8 y estado 3/4/5/6. No se sustituye un dominio incompatible.', '',
        'Las operaciones de esquema son pasos independientes, no una transaccion con rollback automatico. '
        'El diario documenta el ultimo paso intentado/verificado; una repeticion revisa el estado real.', '',
        'Despues de CONFIGURACION_PROYECTO_VERIFICADA, repetir Registrar proyectos faltantes: '
        'Validar altas y luego Crear proyectos faltantes durante la ventana sin otros escritores.', '',
        'Error: ' + report.get('error', ''), '', '```json',
        json.dumps(report.get('plan', {}), ensure_ascii=False, indent=2, default=alta.serial), '```', '']
    (folder / 'informe.md').write_text('\n'.join(lines), encoding='utf-8')


def run(workspace, *, apply=False, approve_native_audit=False, database='ArcGisAWS', owner='gis',
        reports=None, arcpy_module=None, emit=print):
    if arcpy_module is None:
        import arcpy as arcpy_module
    a = arcpy_module
    workspace = os.path.abspath(workspace)
    root = Path(reports or HERE)
    require(root.is_dir(), 'La carpeta de informes debe existir.')
    folder = root / ('Configuracion_Proyectos_' + dt.datetime.now().strftime('%Y%m%d_%H%M%S_') + uuid.uuid4().hex[:10])
    folder.mkdir(exist_ok=False)
    report = dict(version='1.12', estado='INICIADO', pasos_ejecutados=[], cambios_intentados=0,
        aprobacion_auditoria_separada=approve_native_audit is True, aplicacion_solicitada=bool(apply),
        proyectos_insertados=0, registros_kmz_insertados=0, rollback_automatico=False)
    emit(f'Informe: {folder}')
    try:
        config, digest = read_config()
        report['configuracion_sha256'] = digest
        path, fields, rows, plan = inspect(a, workspace, database, owner, config)
        report['plan'] = plan
        alta.write_json(folder / 'plan_previo.json', report)
        emit(f"PREVALIDACION: {len(rows)} proyectos conservados; {len(plan['operaciones'])} pasos previstos.")
        for operation in plan['operaciones']:
            emit('PROPUESTA: ' + json.dumps(operation, ensure_ascii=False))
        if not apply:
            report['estado'] = ('CONFIGURACION_PENDIENTE_APROBACION_AUDITORIA'
                if plan['requiere_aprobacion_auditoria'] and not approve_native_audit
                else 'CONFIGURACION_VALIDADA_SIN_CAMBIOS')
        else:
            require(not plan['requiere_aprobacion_auditoria'] or approve_native_audit is True,
                    'Falta aprobar la auditoria separada en cuatro campos ArcGIS; no se aplico ningun cambio.')
            if plan['operaciones']:
                require(a.TestSchemaLock(path), 'No hay disponibilidad de bloqueo de esquema; cierre tablas y sesiones de edicion.')
            # Evidencia duradera de los datos antes de cualquier cambio. Nunca se
            # inventa una restauracion SQL si falla posteriormente una operacion.
            alta.write_json(folder / 'respaldo_historico.json', dict(campos=field_signature(fields), filas=rows))
            for number, step in enumerate(plan['operaciones'], 1):
                verify_preserved(a, path, fields, rows, plan['tracking_previamente_activo'])
                report['ultimo_paso_intentado'] = step
                alta.write_json(folder / f'{number:02d}_intento.json', step)
                report['cambios_intentados'] += 1
                execute_step(a, workspace, path, step)
                verify_step(a, workspace, path, step)
                verify_preserved(a, path, fields, rows, plan['tracking_previamente_activo'])
                report['pasos_ejecutados'].append(step)
                alta.write_json(folder / f'{number:02d}_verificado.json', step)
                emit('CONFIGURACION verificada: ' + step['accion'] + ' ' + step.get('campo', step.get('nombre', '')))
            _, _, _, final = inspect(a, workspace, database, owner, config)
            require(not final['operaciones'], 'La configuracion final aun tiene pasos pendientes.')
            _, _, metadata = alta.inspect_parent(a, workspace, database, owner)
            require(not metadata['incidencias'], 'La tabla sigue bloqueada para el alta: ' + ' | '.join(metadata['incidencias']))
            report.update(estado='CONFIGURACION_PROYECTO_VERIFICADA', plan_final=final, historico_inalterado=True,
                          campos_nativos_creados=sum(s['accion'] == 'AGREGAR_CAMPO' for s in report['pasos_ejecutados']))
    except BaseException as exc:
        report['estado'] = 'CONFIGURACION_DETENIDA_CON_PASOS_A_REVISAR' if report['cambios_intentados'] else 'ERROR_SIN_CAMBIOS'
        report['error'] = str(exc)
        try:
            save_report(folder, report)
            emit(f"Estado: {report['estado']}. Resultado JSON: {report['archivo_resultado']}")
        except Exception as report_error:
            emit(f"Fallo de informe: {report_error}. Pasos intentados: {report['cambios_intentados']}; carpeta: {folder}")
        raise
    try:
        save_report(folder, report)
    except Exception as exc:
        emit(f"Fallo de informe; estado alcanzado {report['estado']}; carpeta {folder}. No se afirma rollback.")
        raise RuntimeError(f"{report['estado']}: fallo el informe, revisar diario de {folder}; sin rollback automatico.") from exc
    emit(f"Estado: {report['estado']}. Resultado JSON: {report['archivo_resultado']}")
    return folder, report
