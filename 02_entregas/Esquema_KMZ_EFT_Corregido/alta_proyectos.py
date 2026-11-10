"""Alta acotada de JAENNORTE/POROMA por ArcGIS, sin SQL ni cambios de esquema.

MAX+1 exige una ventana sin otras altas: Editor aporta transaccion, NO un
bloqueo global del catalogo. La condicion operativa se declara expresamente.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json
import os
from pathlib import Path
import uuid

import crear_esquema as engine
import alta_proyectos_logica as logic

HERE = Path(__file__).resolve().parent
TABLE = 'mline_tc_proyecto'
require = engine.require
BUSINESS = ('id_proyecto', 'co_proyecto', 'no_proyecto', 'de_proyecto',
            'id_tipo_proyecto', 'id_estado_proyecto', 'es_registro')
TRACKING = ('creatorFieldName', 'createdAtFieldName', 'editorFieldName', 'editedAtFieldName')


def serial(value):
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    raise TypeError(f'Valor no serializable: {type(value).__name__}')


def write_json(path, value):
    # Archivos nuevos, nunca replace sobre un informe abierto por ArcGIS.
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, default=serial)
        stream.write('\n')


def inspect_parent(a, workspace, database, owner):
    require(a.Exists(workspace), 'La geodatabase debe existir.')
    remote = workspace.lower().endswith('.sde')
    wd = a.Describe(workspace)
    require(wd.workspaceType == ('RemoteDatabase' if remote else 'LocalDatabase'),
            'Se requiere una conexion .sde o una geodatabase de archivo.')
    if remote:
        cp = wd.connectionProperties
        require(str(cp.database).casefold() == database.casefold(), 'La conexion apunta a otra base de datos.')
        require(str(getattr(cp, 'user', '')).casefold() == owner.casefold(),
                'Utilice la conexion del propietario esperado.')
    with a.EnvManager(workspace=workspace):
        tables = a.ListTables() or []
    matches = [name for name in tables if engine.simple(name).casefold() == TABLE
               and (not remote or (len(name.split('.')) >= 2
                    and name.split('.')[-2].casefold() == owner.casefold()))]
    require(len(matches) == 1, 'Debe existir una unica tabla fisica del propietario: mline_tc_proyecto.')
    path = os.path.join(workspace, matches[0])
    d = a.Describe(path)
    require(d.dataType == 'Table' and getattr(d, 'hasOID', False),
            'La tabla padre debe estar registrada y tener ObjectID nativo.')
    fields = engine.field_index(a.ListFields(path))
    for name in BUSINESS:
        require(name in fields, f'Falta el campo obligatorio {TABLE}.{name}.')
        field = fields[name]
        expected = ('Integer', 'SmallInteger') if name.startswith('id_') else ('String',)
        require(field.type in expected, f'{name}: tipo no compatible ({field.type}).')
        require(getattr(field, 'editable', True), f'{name}: campo no editable.')
    require(fields['id_proyecto'].type == 'Integer', 'id_proyecto debe ser LONG, no SHORT.')
    require(fields['co_proyecto'].length == 12, 'co_proyecto debe ser TEXT de longitud 12.')
    blockers = []
    if getattr(d, 'isVersioned', False) or getattr(d, 'isArchived', False):
        blockers.append('Tabla versionada o archivada: esta herramienta requiere la ruta no versionada; no cambia esa configuracion.')
    rules = list(getattr(d, 'attributeRules', []) or [])
    if rules:
        blockers.append('Hay reglas de atributos existentes: revisar su asignacion de identificadores antes de usar MAX+1.')
    subtypes = a.da.ListSubtypes(path)
    if any(v.get('SubtypeField') for v in subtypes.values()):
        blockers.append('La tabla tiene subtipos; se requiere resolver su configuracion antes del alta.')
    if getattr(d, 'hasAttachments', False):
        blockers.append('La tabla tiene adjuntos; esta alta acotada no certifica sus comportamientos.')
    tracking = {key: str(getattr(d, key, '') or '') for key in TRACKING}
    if not getattr(d, 'editorTrackingEnabled', False):
        blockers.append('Falta Editor Tracking, requerido por el EFT para tablas editables. Configurarlo antes de aplicar.')
    elif not all(tracking.values()) or any(engine.simple(n).casefold() not in fields for n in tracking.values()):
        blockers.append('La configuracion de los cuatro campos de Editor Tracking esta incompleta.')
    elif any(engine.simple(n).casefold() in BUSINESS for n in tracking.values()):
        blockers.append('Editor Tracking apunta a un campo de negocio y no puede conservarse de forma segura.')
    domains = {domain.name: domain for domain in a.da.ListDomains(workspace)}
    evidence = []
    for name, value, meaning in (('id_tipo_proyecto', 8, 'linea de transmision'),
                                  ('id_estado_proyecto', 3, 'registrado')):
        domain_name = fields[name].domain
        domain = domains.get(domain_name)
        codes = getattr(domain, 'codedValues', {}) if domain else {}
        label = codes.get(value)
        evidence.append(dict(campo=name, dominio=domain_name, codigo=value, etiqueta=label))
        if not domain or getattr(domain, 'domainType', '') != 'CodedValue' or label is None:
            blockers.append(f'{name}: falta un dominio codificado que acepte el valor {value}.')
        elif logic.normalize_name(str(label)) != logic.normalize_name(meaning):
            blockers.append(f'{name}: el dominio no identifica {value} como {meaning}.')
    tracking_names = {engine.simple(v).casefold() for v in tracking.values() if v}
    for name, field in fields.items():
        if name in BUSINESS or name in tracking_names or field.type in ('OID', 'GlobalID'):
            continue
        if field.type in ('Blob', 'Raster', 'Geometry'):
            blockers.append(f'{name}: tipo no compatible con la comprobacion completa de la tabla padre.')
        if not field.isNullable:
            blockers.append(f'{name}: campo adicional obligatorio sin valor de negocio autorizado.')
        if getattr(field, 'defaultValue', None) is not None:
            blockers.append(f'{name}: tiene un valor predeterminado no previsto; revisarlo antes de insertar.')
    return path, fields, dict(tabla=path, geodatabase_remota=remote,
        versionada=bool(getattr(d, 'isVersioned', False)),
        editor_tracking=bool(getattr(d, 'editorTrackingEnabled', False)),
        campos_auditoria=tracking, dominios=evidence,
        relaciones_observadas=list(getattr(d, 'relationshipClassNames', []) or []),
        incidencias=blockers)


def read_rows(a, path, fields):
    names = sorted(fields)
    with a.da.SearchCursor(path, [fields[name].name for name in names]) as cursor:
        rows = [dict(zip(names, values)) for values in cursor]
    return sorted(rows, key=lambda row: row[oid_key(fields)])


def oid_key(fields):
    keys = [n for n, f in fields.items() if f.type == 'OID']
    require(len(keys) == 1, 'Se requiere un ObjectID unico.')
    return keys[0]


def validate_values(plan, fields, a, workspace):
    domains = {d.name: d for d in a.da.ListDomains(workspace)}
    for entry in plan['altas']:
        for name, value in entry['valores'].items():
            f = fields[name]
            if isinstance(value, str):
                require(len(value.encode('utf-16-le')) // 2 <= f.length,
                        f'{name}: longitud insuficiente para {value!r}.')
            if f.domain:
                domain = domains.get(f.domain)
                require(domain is not None, f'{name}: dominio no encontrado.')
                if domain.domainType == 'CodedValue':
                    require(value in domain.codedValues, f'{name}: {value!r} fuera del dominio.')
                elif domain.domainType == 'Range':
                    require(domain.range[0] <= value <= domain.range[1], f'{name}: valor fuera del rango.')
                else:
                    raise ValueError(f'{name}: dominio no reconocido.')


def verify_rows(before, after, plan, fields, metadata):
    """Comparacion exacta de todas las filas previas y todos sus atributos."""
    key = oid_key(fields)
    previous = {row[key]: row for row in before}
    current = {row[key]: row for row in after}
    require(len(current) == len(after) and len(previous) == len(before), 'ObjectID duplicado.')
    require(all(current.get(oid) == row for oid, row in previous.items()),
            'Se modifico o desaparecio una fila preexistente. Se detiene el alta.')
    added = [row for oid, row in current.items() if oid not in previous]
    require(len(added) == len(plan['altas']), 'El numero de altas no coincide; posible escritura simultanea.')
    actual = {row['id_proyecto']: row for row in added}
    require(len(actual) == len(added), 'Identificadores duplicados entre las altas.')
    for entry in plan['altas']:
        expected = entry['valores']
        row = actual.get(expected['id_proyecto'])
        require(row is not None, 'No se encuentra una de las altas.')
        for name, value in expected.items():
            observed = row[name]
            if isinstance(observed, str):
                observed = observed.rstrip(' ')
            require(observed == value, f'{name}: valor guardado distinto del aprobado.')
        for name in ('fe_eliminacion', 'us_eliminacion', 'ip_eliminacion', 'co_alternativa_reciente'):
            require(row.get(name) is None, f'{name}: el alta no debe copiar eliminaciones ni alternativas.')
        for name in metadata['campos_auditoria'].values():
            require(row.get(engine.simple(name).casefold()) not in (None, ''),
                    'ArcGIS no completo los campos de auditoria nativa.')
        for name, field in fields.items():
            if field.type == 'GlobalID':
                require(row.get(name) not in (None, '', '{00000000-0000-0000-0000-000000000000}'),
                        'GlobalID no generado por ArcGIS.')
    final = logic.plan_projects(after)
    require(not final['altas'], 'La comprobacion final aun propone altas.')
    return final


def read_mapping(path):
    if not path:
        return [], None
    raw = Path(path).read_bytes()
    text = raw.decode('utf-8-sig')
    require(text.strip(), 'El CSV de correspondencias esta vacio.')
    delimiter = ';' if text.splitlines()[0].count(';') >= text.splitlines()[0].count(',') else ','
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    require(reader.fieldnames and len(set(reader.fieldnames)) == len(reader.fieldnames), 'Cabeceras CSV duplicadas.')
    require(set(('archivo_kmz', 'co_proyecto', 'confirmado')) <= set(reader.fieldnames), 'CSV sin cabeceras requeridas.')
    rows = list(reader)
    require(all(None not in row and all(v is not None for v in row.values()) for row in rows), 'Filas CSV mal formadas.')
    require(len({row['archivo_kmz'] for row in rows}) == len(rows), 'KMZ repetido en el CSV.')
    require(all(row['confirmado'].strip().casefold() in ('si', 'sí', 'no', '') for row in rows), 'Confirmado debe ser si/no.')
    return rows, dict(archivo=str(Path(path).resolve()), sha256=hashlib.sha256(raw).hexdigest())


def merge_mapping(rows, final_plan, catalog):
    result = [dict(row) for row in rows]
    by_file = {row['archivo_kmz']: row for row in result}
    codes = {row['co_proyecto'].rstrip(' '): row for row in catalog}
    for row in result:
        if row['confirmado'].strip().casefold() in ('si', 'sí'):
            require(row['co_proyecto'] in codes, f"Codigo confirmado inexistente: {row['co_proyecto']}.")
            proposed_name = row.get('nombre_proyecto_propuesto', '')
            if proposed_name:
                require(logic.normalize_name(proposed_name) == logic.normalize_name(codes[row['co_proyecto']]['no_proyecto']),
                        f"Cambio de nombre del proyecto confirmado para {row['archivo_kmz']}.")
    for project in final_plan['existentes']:
        filename, code = project['archivo_kmz'], project['co_proyecto']
        row = by_file.get(filename)
        if row is None:
            row = dict(archivo_kmz=filename, co_proyecto='', confirmado='no')
            result.append(row)
        require(not row.get('co_proyecto') or row['co_proyecto'] == code,
                f'{filename}: el CSV propone otro codigo; no se sobreescribe.')
        row.update(co_proyecto=code, confirmado='si')
        for name, value in (('codigos_candidatos', code), ('nombre_proyecto_propuesto', project['no_proyecto']),
                            ('estado_correspondencia', 'VERIFICADO_EN_CATALOGO'),
                            ('es_registro_propuesto', codes[code].get('es_registro', '')),
                            ('fecha_eliminacion_informada', 'si' if project['inactivo'] else 'no'),
                            ('observacion', 'Existencia verificada; no se reactiva si esta inactivo.')):
            if name in row:
                row[name] = value
    return result


def write_mapping(path, rows):
    columns = list(dict.fromkeys(['archivo_kmz', 'co_proyecto', 'confirmado'] + [k for row in rows for k in row]))
    with Path(path).open('x', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, delimiter=';')
        writer.writeheader()
        writer.writerows(rows)


def write_report(folder, report):
    report['archivo_resultado'] = str(folder / 'resultado.json')
    write_json(folder / 'resultado.json', report)
    text = [f"# Alta de proyectos 1.11\n\nEstado: **{report['estado']}**.",
        f"Transaccion: {report['transaccion']}. Altas confirmadas: {report['nuevas_filas_confirmadas']}.",
        'Esta herramienta solo registra JAENNORTE y POROMA si faltan. No carga KMZ, no crea analisis, '
        'no modifica el esquema ni reactiva proyectos. Los codigos de validacion no estan reservados.',
        'La asignacion MAX+1 requiere ausencia de otras altas durante toda la ejecucion. '
        'La sesion Editor permite guardar o revertir el lote; no es un bloqueo global contra otros escritores.',
        'Los usuarios, fechas y GlobalID los genera ArcGIS. No se inventan IP. '
        'La validacion de esta alta no certifica la publicacion, branch ni todo el modelo EFT.',
        'Tras aplicar, use confirmar_proyectos.csv en Prevalidar ingesta. Si no suministro un CSV previo, '
        'el archivo contiene solo los dos proyectos de esta operacion; debe integrar las demas correspondencias.',
        'Incidencias: ' + json.dumps(report.get('incidencias', []), ensure_ascii=False),
        'Error: ' + report.get('error', '')]
    (folder / 'informe.md').write_text('\n\n'.join(text) + '\n', encoding='utf-8')


def run(workspace, *, apply=False, exclusive=False, database='ArcGisAWS', owner='gis',
        reports=None, arcpy_module=None, emit=print, project_csv=None):
    if arcpy_module is None:
        import arcpy as arcpy_module
    a = arcpy_module
    workspace = os.path.abspath(workspace)
    root = Path(reports or HERE)
    require(root.is_dir(), 'La carpeta de informes debe existir.')
    folder = root / ('Alta_Proyectos_' + dt.datetime.now().strftime('%Y%m%d_%H%M%S_') + uuid.uuid4().hex[:12])
    folder.mkdir(exist_ok=False)
    report = dict(version='1.11', estado='INICIADO', transaccion='NO_INICIADA',
        nuevas_filas_confirmadas=0, workspace=workspace, aplicacion_solicitada=bool(apply),
        exclusividad_operativa_declarada=bool(exclusive), bloqueo_global=False,
        cambios_esquema=0, registros_kmz_insertados=0, incidencias=[])
    emit(f'Informe: {folder}')
    editor = None
    editing = False
    operation = False
    committing = False
    before = None
    try:
        mapping, evidence = read_mapping(project_csv)
        report['csv_entrada'] = evidence
        path, fields, metadata = inspect_parent(a, workspace, database, owner)
        report['destino'] = metadata
        before = read_rows(a, path, fields)
        plan = logic.plan_projects(before)
        report['plan'] = plan
        validate_values(plan, fields, a, workspace)
        # Validar correspondencias previas antes de abrir una sesion de escritura.
        merge_mapping(mapping, dict(existentes=plan['existentes']), before)
        proposed = {entry['archivo_kmz']: entry['valores']['co_proyecto'] for entry in plan['altas']}
        for row in mapping:
            if row['archivo_kmz'] in proposed:
                require(not row['co_proyecto'] or row['co_proyecto'] == proposed[row['archivo_kmz']],
                        f"{row['archivo_kmz']}: el CSV propone otro codigo; no se sobreescribe.")
        report['incidencias'] = metadata['incidencias']
        write_json(folder / 'plan_previo.json', report)
        emit(f"CATALOGO: {len(before)} proyectos; altas previstas: {len(plan['altas'])}; existentes: {len(plan['existentes'])}.")
        for row in plan['altas']:
            emit(f"PROPUESTA sin reservar: {row['archivo_kmz']} -> {row['valores']['co_proyecto']}.")
        if not apply:
            report['estado'] = 'ALTAS_BLOQUEADAS_SIN_CAMBIOS' if report['incidencias'] else 'ALTAS_VALIDADAS_SIN_CAMBIOS'
        else:
            require(not report['incidencias'], 'No se puede aplicar: ' + ' | '.join(report['incidencias']))
            if plan['altas']:
                require(exclusive is True, 'Aplicar requiere una ventana sin otras altas de proyectos, confirmada en el parametro de exclusividad.')
                editor = a.da.Editor(workspace)
                editor.startEditing(False, False)
                editing = True
                report['transaccion'] = 'ABIERTA'
                editor.startOperation()
                operation = True
                require(read_rows(a, path, fields) == before, 'El catalogo cambio tras validar; vuelva a ejecutar sin otras altas.')
                with a.da.InsertCursor(path, [fields[name].name for name in BUSINESS], explicit=True) as cursor:
                    for entry in plan['altas']:
                        cursor.insertRow([entry['valores'][name] for name in BUSINESS])
                after = read_rows(a, path, fields)
                final_plan = verify_rows(before, after, plan, fields, metadata)
                output_mapping = merge_mapping(mapping, final_plan, after)
                # Informe duradero antes del commit, sin afirmar que este ya ocurrio.
                write_json(folder / 'verificacion_antes_commit.json', dict(plan=final_plan, transaccion='ABIERTA',
                    altas=len(plan['altas']), codigos_reservados=False))
                editor.stopOperation()
                operation = False
                committing = True
                editor.stopEditing(True)
                report['transaccion'] = 'CONFIRMADA'
                report['nuevas_filas_confirmadas'] = len(plan['altas'])
                editor = None
                committing = False
                persisted = read_rows(a, path, fields)
                final_plan = verify_rows(before, persisted, plan, fields, metadata)
            else:
                persisted = before
                final_plan = plan
                output_mapping = merge_mapping(mapping, final_plan, persisted)
            report['plan_final'] = final_plan
            write_mapping(folder / 'confirmar_proyectos.csv', output_mapping)
            report['archivo_csv_proyectos'] = str(folder / 'confirmar_proyectos.csv')
            report['estado'] = 'ALTAS_PROYECTOS_VERIFICADAS'
            for row in final_plan['existentes']:
                emit(f"PROYECTO verificado: {row['archivo_kmz']} -> {row['co_proyecto']}.")
    except BaseException as exc:
        report['error'] = str(exc)
        if hasattr(exc, 'incidencias'):
            report['incidencias'].extend(exc.incidencias)
        if committing:
            report['transaccion'] = 'ESTADO_INCIERTO'
            report['error'] += ' Fallo durante commit: comprobar el catalogo antes de reintentar; no se afirma rollback.'
        elif editor is not None and editing:
            try:
                if operation:
                    editor.abortOperation()
                editor.stopEditing(False)
                require(read_rows(a, path, fields) == before, 'El catalogo no coincide despues del rollback.')
                report['transaccion'] = 'REVERTIDA'
            except BaseException as rollback_error:
                report['transaccion'] = 'ESTADO_INCIERTO'
                report['error_rollback'] = str(rollback_error)
        report['estado'] = ('ALTA_CONFIRMADA_REVISION_POSTERIOR_PENDIENTE'
            if report['transaccion'] == 'CONFIRMADA' else 'ERROR_DETENIDO')
        try:
            write_report(folder, report)
            emit(f"Estado: {report['estado']}. Resultado JSON: {report['archivo_resultado']}")
        except Exception as report_error:
            emit(f"No se pudo completar el informe: {report_error}. Transaccion: {report['transaccion']}; carpeta: {folder}")
        raise
    try:
        write_report(folder, report)
    except Exception as exc:
        emit(f"Fallo al guardar informe. Transaccion: {report['transaccion']}; "
             f"altas confirmadas: {report['nuevas_filas_confirmadas']}; carpeta: {folder}")
        if report['transaccion'] == 'CONFIRMADA':
            raise RuntimeError('ALTA_CONFIRMADA_REVISION_POSTERIOR_PENDIENTE: los proyectos se guardaron; '
                               f'fallo el informe, no se afirma rollback. Carpeta: {folder}') from exc
        raise
    emit(f"Estado: {report['estado']}. Resultado JSON: {report['archivo_resultado']}")
    return folder, report
