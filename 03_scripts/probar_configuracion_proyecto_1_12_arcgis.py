"""Ensayo local de configuracion 1.12, sin conexiones SDE ni datos reales.

Prepara cuarenta filas sinteticas con auditoria heredada y prueba que los dos
dominios completos y la auditoria nativa propuesta no cambian ninguno de sus
valores. El consentimiento usado aqui solo corresponde al fixture local.
"""
from __future__ import annotations

import argparse
from collections import Counter
import datetime as dt
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import uuid

from probar_alta_proyectos_1_11_arcgis import LEGACY_FIELDS

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '02_entregas' / 'Esquema_KMZ_EFT_Corregido'
VALIDATION = OUT / '_validacion'
TABLE = 'mline_tc_proyecto'
NATIVE_FIELDS = ('created_user', 'created_date', 'last_edited_user', 'last_edited_date')


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def write_json(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, default=str)
        stream.write('\n')


def gdb_files(gdb):
    require(gdb.is_dir() and gdb.suffix.lower() == '.gdb', 'Solo se admite la GDB local nueva.')
    return {str(p.relative_to(gdb)): sha(p) for p in sorted(gdb.rglob('*'))
            if p.is_file() and not p.name.lower().endswith('.lock')}


def snapshot(a, table, names=None):
    fields = list(a.ListFields(str(table)))
    selected = names or [f.name for f in fields]
    oid = a.Describe(str(table)).OIDFieldName
    with a.da.SearchCursor(str(table), selected) as cursor:
        rows = [dict(zip(selected, values)) for values in cursor]
    rows.sort(key=lambda row: row[oid])
    return dict(filas=rows, oid=oid, nombres=selected,
        campos=[dict(nombre=f.name, tipo=f.type, longitud=f.length, precision=f.precision,
                     nullable=f.isNullable, requerido=f.required, dominio=f.domain)
                for f in fields])


def legacy_value(name, kind, number):
    fixed = dict(id_proyecto=number, id_tipo_proyecto=7 + number % 2,
                 id_estado_proyecto=3 + number % 4, co_proyecto=f'PRY-{number:08d}',
                 no_proyecto=f'Historico de ensayo {number:02d}',
                 de_proyecto='Registro sintetico ajeno a los dos proyectos nuevos',
                 es_registro='0' if number % 3 == 0 else '1',
                 co_alternativa_reciente=0 if number % 2 == 0 else None)
    if name in fixed:
        return fixed[name]
    if number % 5 == 0:
        return None
    if kind == 'DATE':
        return dt.datetime(2020 + number % 3, 4, number % 28 + 1, 9, 31, 27)
    if name.startswith('us_'):
        return f'usuario_heredado_{number:02d}'
    if name.startswith('ip_'):
        return f'192.0.2.{number}'
    if name.startswith('es_'):
        return str(number % 3)
    if kind == 'TEXT':
        return f'valor_{name}_{number}'
    return None


def prepare(a):
    VALIDATION.mkdir(exist_ok=True)
    folder = VALIDATION / ('configuracion112_' + dt.datetime.now().strftime('%Y%m%d_%H%M%S_')
                           + uuid.uuid4().hex[:12])
    require(folder.resolve().parent == VALIDATION.resolve() and not folder.exists(),
            'Solo se crea una carpeta nueva de ensayo.')
    folder.mkdir()
    gdb = folder / 'ensayo.gdb'
    a.management.CreateFileGDB(str(folder), gdb.name)
    a.management.CreateTable(str(gdb), TABLE)
    table = gdb / TABLE
    require(len(LEGACY_FIELDS) == 34, 'El fixture debe tener los 34 campos heredados.')
    for name, kind, length, nullable in LEGACY_FIELDS:
        kwargs = dict(field_is_nullable='NULLABLE' if nullable else 'NON_NULLABLE')
        if length:
            kwargs['field_length'] = length
        a.management.AddField(str(table), name, kind, **kwargs)
    with a.da.InsertCursor(str(table), [n for n, _, _, _ in LEGACY_FIELDS], explicit=True) as cursor:
        for number in range(1, 41):
            cursor.insertRow([legacy_value(n, kind, number) for n, kind, _, _ in LEGACY_FIELDS])
    initial = snapshot(a, table)
    require(len(initial['filas']) == 40 and len(initial['campos']) == 35, 'Fixture no coincide con contrato.')
    require(not a.Describe(str(table)).editorTrackingEnabled, 'El fixture debe empezar sin tracking.')
    require(not a.da.ListDomains(str(gdb)), 'El fixture debe empezar sin dominios.')
    write_json(folder / 'fixture.json', dict(estado='FIXTURE_NUEVO_PREPARADO', geodatabase=str(gdb),
        tabla=str(table), registros_sinteticos=40, campos_heredados=34,
        no_global_id_inicial=True, editor_tracking_inicial=False, snapshot=initial,
        datos_reales=False, conexion_sde=False))
    return folder, gdb, table, initial


class ArcPyGuard:
    """Admite solo llamadas de configuracion sobre el fixture de este proceso."""
    WRITES = {'CreateDomain', 'AddCodedValueToDomain', 'AssignDomainToField',
              'AddField', 'EnableEditorTracking'}

    def __init__(self, a, gdb, table, readonly=False):
        self.a, self.gdb, self.table, self.readonly = a, gdb.resolve(), table.resolve(), readonly
        self.calls = []
        self.da = SimpleNamespace(ListDomains=self.list_domains, ListSubtypes=self.list_subtypes,
                                  SearchCursor=self.search_cursor)
        self.management = SimpleNamespace(GetCount=self.get_count)
        for name in self.WRITES:
            setattr(self.management, name, self.write_call(name))

    def guard_path(self, path, kind=None):
        normalized = Path(str(path)).resolve()
        allowed = {self.gdb, self.table}
        require(normalized in allowed, f'Ruta fuera del fixture: {path}')
        if kind == 'gdb':
            require(normalized == self.gdb, 'La llamada exige la GDB del fixture.')
        if kind == 'table':
            require(normalized == self.table, 'La llamada exige la tabla del fixture.')

    def write_call(self, name):
        def call(path, *args, **kwargs):
            require(not self.readonly, 'La validacion intento modificar la geodatabase: ' + name)
            kind = 'gdb' if name in ('CreateDomain', 'AddCodedValueToDomain') else 'table'
            self.guard_path(path, kind)
            if name == 'AddField':
                field_name = args[0] if args else kwargs.get('field_name')
                require(field_name in NATIVE_FIELDS, 'Se intento agregar un campo ajeno a auditoria.')
            self.calls.append(name)
            return getattr(self.a.management, name)(path, *args, **kwargs)
        return call

    def list_domains(self, workspace):
        self.guard_path(workspace, 'gdb')
        return self.a.da.ListDomains(workspace)

    def list_subtypes(self, table):
        self.guard_path(table, 'table')
        return self.a.da.ListSubtypes(table)

    def search_cursor(self, table, *args, **kwargs):
        self.guard_path(table, 'table')
        self.calls.append('SearchCursor')
        return self.a.da.SearchCursor(table, *args, **kwargs)

    def get_count(self, table):
        self.guard_path(table, 'table')
        return self.a.management.GetCount(table)

    def __getattr__(self, name):
        require(name in ('Exists', 'Describe', 'ListFields', 'ListTables', 'EnvManager',
                         'TestSchemaLock', 'GetInstallInfo', 'ValidateFieldName', 'ListIndexes'),
                'ArcPy no permitido en el ensayo: ' + name)
        return getattr(self.a, name)


def run_tool(runtime, guard, gdb, folder, apply=False, approved=False):
    folder.mkdir(exist_ok=False)
    return runtime.run(str(gdb), apply=apply, approve_native_audit=approved,
                       database='ArcGisAWS', owner='gis', reports=str(folder),
                       arcpy_module=guard, emit=lambda message: print(message, flush=True))


def verify(a):
    sys.path.insert(0, str(OUT))
    import configurar_proyecto
    import alta_proyectos
    runtime_paths = [OUT / name for name in ('configurar_proyecto.py', 'configuracion_proyecto_1_12.json',
        'alta_proyectos.py', 'alta_proyectos_logica.py', 'crear_esquema.py', 'esquema.json')]
    hashes = {p.name: sha(p) for p in runtime_paths}
    folder, gdb, table, initial = prepare(a)
    print('FIXTURE NUEVO: ' + str(folder), flush=True)
    before_bytes = gdb_files(gdb)
    readonly = ArcPyGuard(a, gdb, table, readonly=True)
    _, validation = run_tool(configurar_proyecto, readonly, gdb, folder / 'validar')
    require(snapshot(a, table) == initial, 'Validar modifico los campos o valores.')
    require(gdb_files(gdb) == before_bytes, 'Validar modifico bytes de la GDB, excluidos locks.')
    require(not any(c in readonly.WRITES for c in readonly.calls), 'Validar llamo una herramienta de escritura.')

    denied_guard = ArcPyGuard(a, gdb, table, readonly=True)
    refusal = None
    try:
        _, refused = run_tool(configurar_proyecto, denied_guard, gdb, folder / 'sin_aprobacion', apply=True)
        require(refused['estado'] != 'CONFIGURACION_PROYECTO_VERIFICADA',
                'Aplicar sin aprobacion no puede quedar verificado con campos ausentes.')
        refusal = json.dumps(refused, ensure_ascii=False).casefold()
    except Exception as exc:
        refusal = str(exc).casefold()
    require(refusal and ('aprob' in refusal or 'autoriza' in refusal),
            'No se identifico un rechazo por falta de aprobacion de los campos nativos.')
    require(not any(c in denied_guard.WRITES for c in denied_guard.calls)
            and snapshot(a, table) == initial, 'La falta de aprobacion no preservo el destino.')

    apply_guard = ArcPyGuard(a, gdb, table)
    _, applied = run_tool(configurar_proyecto, apply_guard, gdb, folder / 'aplicar', apply=True, approved=True)
    require(applied['estado'] == 'CONFIGURACION_PROYECTO_VERIFICADA', 'La configuracion nativa no quedo verificada.')
    after = snapshot(a, table)
    require(len(after['filas']) == 40, 'Configurar altero el numero de filas.')
    require(snapshot(a, table, initial['nombres'])['filas'] == initial['filas'],
            'Se cambio al menos un valor de las cuarenta filas originales.')
    previous_fields = {f['nombre']: f for f in initial['campos']}
    actual_fields = {f['nombre']: f for f in after['campos']}
    require(set(actual_fields) - set(previous_fields) == set(NATIVE_FIELDS), 'Campos agregados distintos de los cuatro propuestos.')
    for name, field in previous_fields.items():
        expected = dict(field)
        if name == 'id_tipo_proyecto':
            expected['dominio'] = 'mline_proyecto_tipo'
        elif name == 'id_estado_proyecto':
            expected['dominio'] = 'mline_proyecto_estado'
        require(actual_fields[name] == expected, 'Se altero el esquema heredado: ' + name)
    for name in ('created_user', 'last_edited_user'):
        require(actual_fields[name]['tipo'] == 'String' and actual_fields[name]['longitud'] == 255,
                'Campo nativo de usuario con tipo/longitud incorrecto.')
    for name in ('created_date', 'last_edited_date'):
        require(actual_fields[name]['tipo'] == 'Date' and actual_fields[name]['precision'] == 0,
                'Campo nativo fecha no es DATE de baja precision.')
    description = a.Describe(str(table))
    require(description.editorTrackingEnabled and description.isTimeInUTC,
            'Editor Tracking no se habilito en UTC.')
    require([description.creatorFieldName, description.createdAtFieldName,
             description.editorFieldName, description.editedAtFieldName] == list(NATIVE_FIELDS),
            'Editor Tracking no usa exclusivamente los cuatro campos nuevos.')
    domains = {domain.name: domain for domain in a.da.ListDomains(str(gdb))}
    proposal = json.loads((OUT / 'configuracion_proyecto_1_12.json').read_text(encoding='utf-8'))
    for expected in proposal['dominios']:
        domain = domains[expected['nombre']]
        require(domain.domainType == 'CodedValue' and domain.type in ('Integer', 'Long'), 'Dominio no LONG/CODED.')
        require(dict(domain.codedValues) == {c['codigo']: c['descripcion'] for c in expected['codigos']},
                'El dominio no conserva el catalogo completo original.')
    require(set(domains) == {'mline_proyecto_tipo', 'mline_proyecto_estado'}, 'Se crearon dominios ajenos al alcance.')

    repeat_guard = ArcPyGuard(a, gdb, table, readonly=True)
    _, repeated = run_tool(configurar_proyecto, repeat_guard, gdb, folder / 'repetir', apply=True, approved=True)
    require(repeated['estado'] == 'CONFIGURACION_PROYECTO_VERIFICADA', 'Repetir no verifico configuracion existente.')
    require(not repeated['plan']['operaciones'], 'La repeticion propuso operaciones adicionales.')
    require(snapshot(a, table) == after, 'La repeticion modifico datos o campos.')
    path, fields, metadata = alta_proyectos.inspect_parent(readonly, str(gdb), 'ArcGisAWS', 'gis')
    require(not metadata['incidencias'], 'El padre preparado sigue bloqueando las altas: ' + str(metadata['incidencias']))
    altas_folder = folder / 'validar_altas'
    altas_folder.mkdir()
    _, next_plan = alta_proyectos.run(str(gdb), reports=str(altas_folder), arcpy_module=readonly,
                                    emit=lambda message: print(message, flush=True))
    require(next_plan['estado'] == 'ALTAS_VALIDADAS_SIN_CAMBIOS' and len(next_plan['plan']['altas']) == 2,
            'La nueva configuracion no permite validar las dos altas.')
    require(snapshot(a, table) == after, 'Validar las altas modifico datos.')
    require(all(sha(OUT / name) == digest for name, digest in hashes.items()), 'El runtime cambio durante el ensayo.')
    proof = dict(estado='ENSAYO_LOCAL_CONFIGURACION_VERIFICADO', version_paquete='1.12',
        arcgis=a.GetInstallInfo()['Version'], geodatabase=str(gdb), campos_heredados=34,
        registros_iniciales=40, registros_finales=40, campos_nativos_creados=4,
        nombres_campos_nativos=list(NATIVE_FIELDS),
        validacion_sin_cambios=True, validacion_sin_cambios_fisicos=True,
        rechazo_sin_aprobacion_verificado=True,
        dominios_completos_verificados=True, editor_tracking_nativo_verificado=True,
        dominios_verificados=True, tracking_utc_verificado=True,
        auditoria_nativa_utc_verificada=True, valores_heredados_inalterados=True,
        historico_inalterado=True, modelo_inalterado=True,
        fechas_heredadas_inalteradas=True, zonas_historicas_reinterpretadas=False,
        reejecucion_sin_operaciones=True, reejecucion_sin_cambios=True,
        nuevas_altas_validadas=2, proyectos_insertados=0,
        validacion_sde=False, concurrencia_sql_server_validada=False,
        toolbox_ejecutada=False, runtime_ejecutado=True, ingesta_kmz_realizada=False,
        aprobacion_campos='Solo para cuatro campos tecnicos del fixture local; no acredita consentimiento en SDE.',
        llamadas=dict(Counter(c for guard in (readonly, denied_guard, apply_guard, repeat_guard) for c in guard.calls)),
        informes=[validation['archivo_resultado'], applied['archivo_resultado'],
                  repeated['archivo_resultado'], next_plan['archivo_resultado']],
        archivos_sha256={**hashes,
            '03_scripts/probar_configuracion_proyecto_1_12_arcgis.py': sha(__file__),
            '03_scripts/probar_alta_proyectos_1_11_arcgis.py': sha(ROOT / '03_scripts/probar_alta_proyectos_1_11_arcgis.py')},
        alcance='Runtime ArcPy real sobre File GDB nueva, preservacion de cuarenta filas sinteticas y '
            'auditoria heredada, dos dominios, cuatro campos nativos e idempotencia. No SDE ni branch.')
    proof_path = folder / 'VALIDACION_CONFIGURACION_1_12_ARCGIS.json'
    write_json(proof_path, proof)
    print(json.dumps(dict(estado=proof['estado'], informe=str(proof_path))), flush=True)


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    import arcpy
    with arcpy.EnvManager(overwriteOutput=False, extent=None):
        verify(arcpy)


if __name__ == '__main__':
    main()
