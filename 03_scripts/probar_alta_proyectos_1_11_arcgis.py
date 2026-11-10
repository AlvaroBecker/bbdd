"""Ensayo ArcPy de altas 1.11 en una geodatabase nueva y exclusivamente local.

Crea 40 proyectos sintéticos; prueba lectura sin cambios, rollback real,
alta de dos proyectos e idempotencia. No abre conexiones SDE ni reutiliza una
GDB anterior. La exclusividad se limita al fixture creado por este proceso:
no acredita exclusividad, concurrencia ni versionado de SQL Server.
"""
from __future__ import annotations

import argparse
from collections import Counter
import datetime as dt
import hashlib
import json
from pathlib import Path
import sys
import uuid


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '02_entregas' / 'Esquema_KMZ_EFT_Corregido'
VALIDATION = OUT / '_validacion'
PARENT = 'mline_tc_proyecto'
INSERT_FIELDS = ('id_proyecto', 'id_tipo_proyecto', 'id_estado_proyecto',
                 'co_proyecto', 'no_proyecto', 'de_proyecto', 'es_registro')
# Los 34 campos originales, sin copiar registros ni datos personales del SQL.
LEGACY_FIELDS = (
    ('id_proyecto', 'LONG', None, False),
    ('id_tipo_proyecto', 'LONG', None, True),
    ('id_estado_proyecto', 'LONG', None, True),
    ('co_proyecto', 'TEXT', 12, True),
    ('no_proyecto', 'TEXT', 128, True),
    ('de_proyecto', 'TEXT', 128, True),
    ('co_alternativa_reciente', 'LONG', None, True),
    ('es_registro', 'TEXT', 1, True),
    ('us_creacion', 'TEXT', 38, True),
    ('ip_creacion', 'TEXT', 38, True),
    ('fe_creacion', 'DATE', None, True),
    ('us_actualizacion', 'TEXT', 38, True),
    ('ip_actualizacion', 'TEXT', 38, True),
    ('fe_actualizacion', 'DATE', None, True),
    ('us_eliminacion', 'TEXT', 38, True),
    ('ip_eliminacion', 'TEXT', 38, True),
    ('fe_eliminacion', 'DATE', None, True),
    ('es_proceso', 'TEXT', 1, True),
    ('fe_inicio_proc', 'DATE', None, True),
    ('fe_avance_proc', 'DATE', None, True),
    ('fe_fin_proc', 'DATE', None, True),
    ('de_mensaje_usuario', 'TEXT', 1000, True),
    ('no_archivo_reporte_celda', 'TEXT', 1000, True),
    ('no_archivo_reporte_alternativa', 'TEXT', 1000, True),
    ('es_proceso_reporte_celda', 'TEXT', 1, True),
    ('fe_inicio_proc_reporte_celda', 'DATE', None, True),
    ('fe_avance_proc_reporte_celda', 'DATE', None, True),
    ('fe_fin_proc_reporte_celda', 'DATE', None, True),
    ('de_mensaje_usuario_reporte_celda', 'TEXT', 1000, True),
    ('es_proceso_reporte_alternativa', 'TEXT', 1, True),
    ('fe_inicio_proc_reporte_alternativa', 'DATE', None, True),
    ('fe_avance_proc_reporte_alternativa', 'DATE', None, True),
    ('fe_fin_proc_reporte_alternativa', 'DATE', None, True),
    ('de_mensaje_usuario_reporte_alternativa', 'TEXT', 1000, True),
)


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def sha(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def write_json(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, default=str)
        stream.write('\n')


def gdb_files(gdb):
    require(gdb.is_dir() and gdb.suffix.lower() == '.gdb', 'Se requiere la GDB local del ensayo.')
    result = {str(p.relative_to(gdb)): sha(p) for p in sorted(gdb.rglob('*'))
              if p.is_file() and not p.name.lower().endswith('.lock')}
    require(result, 'La GDB no contiene archivos legibles.')
    return result


def table_snapshot(a, parent):
    fields = list(a.ListFields(str(parent)))
    names = [f.name for f in fields]
    oid = a.Describe(str(parent)).OIDFieldName
    with a.da.SearchCursor(str(parent), names) as cursor:
        rows = [dict(zip(names, row)) for row in cursor]
    rows.sort(key=lambda row: row[oid])
    return dict(campos=[dict(nombre=f.name, tipo=f.type, longitud=f.length,
        nullable=f.isNullable, requerido=f.required, dominio=f.domain,
        default=f.defaultValue) for f in fields], filas=rows, oid=oid)


def prepare(a):
    VALIDATION.mkdir(exist_ok=True)
    folder = VALIDATION / ('altas111_' + dt.datetime.now().strftime('%Y%m%d_%H%M%S_')
                           + uuid.uuid4().hex[:12])
    require(folder.resolve().parent == VALIDATION.resolve() and not folder.exists(),
            'El ensayo solo crea una carpeta nueva dentro de _validacion.')
    folder.mkdir()
    gdb = folder / 'ensayo.gdb'
    require(not gdb.exists(), 'Nunca se sobrescribe una GDB existente.')
    a.management.CreateFileGDB(str(folder), gdb.name)
    a.management.CreateTable(str(gdb), PARENT)
    parent = gdb / PARENT
    require(len(LEGACY_FIELDS) == 34, 'Contrato de columnas legado inesperado.')
    for name, kind, length, nullable in LEGACY_FIELDS:
        options = dict(field_is_nullable='NULLABLE' if nullable else 'NON_NULLABLE')
        if length is not None:
            options['field_length'] = length
        a.management.AddField(str(parent), name, kind, **options)
    for field, domain, code, label in (
        ('id_tipo_proyecto', 'ensayo_tipo_proyecto', 8, 'Línea de Transmisión'),
        ('id_estado_proyecto', 'ensayo_estado_proyecto', 3, 'Registrado'),
    ):
        a.management.CreateDomain(str(gdb), domain, label, 'LONG', 'CODED')
        a.management.AddCodedValueToDomain(str(gdb), domain, code, label)
        a.management.AssignDomainToField(str(parent), field, domain)
    a.management.AddGlobalIDs(str(parent))
    a.management.EnableEditorTracking(str(parent), 'creador', 'fe_creacion',
        'editor', 'fe_actualizacion', 'ADD_FIELDS', 'UTC')
    with a.da.InsertCursor(str(parent), INSERT_FIELDS, explicit=True) as cursor:
        for number in range(1, 41):
            cursor.insertRow((number, 8, 3, 'PRY-' + format(number, '08d'),
                'Ensayo histórico ' + format(number, '02d'),
                'Registro sintético para verificar conservación', '1'))
    before = table_snapshot(a, parent)
    require(len(before['filas']) == 40, 'No se verificaron las cuarenta filas sintéticas.')
    require(a.Describe(str(parent)).editorTrackingEnabled,
            'Editor Tracking no quedó habilitado en el fixture.')
    write_json(folder / 'fixture.json', dict(estado='FIXTURE_NUEVO_PREPARADO',
        geodatabase=str(gdb), tabla=str(parent), registros_sinteticos=40,
        campos_legado=34, global_id_nativo=True, editor_tracking_nativo=True,
        campos_editor_tracking=['creador', 'fe_creacion', 'editor', 'fe_actualizacion'],
        snapshot=before, script_sha256=sha(__file__), validacion_sde=False,
        exclusividad='GDB nueva creada únicamente por este proceso de ensayo.'))
    return folder, gdb, parent, before


class InjectedInsertFailure(RuntimeError):
    pass


class InsertCursorProxy:
    def __init__(self, cursor, owner):
        self.cursor, self.owner = cursor, owner

    def __enter__(self):
        self.cursor.__enter__()
        return self

    def __exit__(self, *args):
        return self.cursor.__exit__(*args)

    def insertRow(self, row):
        self.owner.insert_attempts += 1
        if self.owner.fail_second and self.owner.insert_attempts == 2:
            raise InjectedInsertFailure('FALLO_INYECTADO_SEGUNDA_INSERCION_EN_FIXTURE_LOCAL')
        oid = self.cursor.insertRow(row)
        self.owner.native_insertions += 1
        return oid

    def __getattr__(self, name):
        return getattr(self.cursor, name)


class NamespaceGuard:
    def __init__(self, wrapped, owner, namespace):
        self.wrapped, self.owner, self.namespace = wrapped, owner, namespace

    def __getattr__(self, name):
        read_da = {'SearchCursor', 'ListDomains', 'ListSubtypes'}
        allowed = read_da | {'InsertCursor', 'Editor'} if self.namespace == 'da' else {'GetCount'}
        require(name in allowed, 'API no autorizada en ensayo: ' + self.namespace + '.' + name)
        target = getattr(self.wrapped, name)

        def call(*args, **kwargs):
            self.owner.calls.append(self.namespace + '.' + name)
            if name in {'InsertCursor', 'Editor'}:
                require(not self.owner.readonly, 'La validación intentó abrir una sesión de escritura.')
                actual = Path(str(args[0])).resolve()
                expected = self.owner.gdb if name == 'Editor' else self.owner.parent
                require(actual == expected, 'La escritura salió del fixture local autorizado.')
            if name == 'InsertCursor':
                return InsertCursorProxy(target(*args, **kwargs), self.owner)
            return target(*args, **kwargs)
        return call


class ArcPyGuard:
    def __init__(self, a, gdb, parent, *, readonly=False, fail_second=False):
        self.a, self.gdb, self.parent = a, gdb.resolve(), parent.resolve()
        self.readonly, self.fail_second = readonly, fail_second
        self.calls, self.insert_attempts, self.native_insertions = [], 0, 0
        self.da = NamespaceGuard(a.da, self, 'da')
        self.management = NamespaceGuard(a.management, self, 'management')

    def __getattr__(self, name):
        allowed = {'GetInstallInfo', 'Exists', 'Describe', 'EnvManager', 'env',
            'ListTables', 'ListFields', 'ListIndexes', 'TestSchemaLock',
            'AddMessage', 'AddWarning', 'AddError', 'GetMessages',
            'ValidateFieldName', 'ValidateTableName'}
        require(name in allowed, 'ArcPy no autorizado en ensayo: ' + name)
        return getattr(self.a, name)


def run_tool(module, guard, gdb, reports, *, apply):
    reports.mkdir()
    return module.run(str(gdb), apply=apply, exclusive=apply, reports=str(reports),
        arcpy_module=guard, emit=lambda value: print(value, flush=True))


def verify(a):
    sys.path.insert(0, str(OUT))
    import alta_proyectos
    require(Path(alta_proyectos.__file__).resolve() == (OUT / 'alta_proyectos.py').resolve(),
            'Se cargó un módulo ajeno al paquete esperado.')
    inputs = [OUT / name for name in ('alta_proyectos.py', 'alta_proyectos_logica.py',
                                      'crear_esquema.py', 'esquema.json')]
    package = {p.name: sha(p) for p in inputs}
    folder, gdb, parent, original = prepare(a)
    print('FIXTURE NUEVO: ' + str(folder), flush=True)
    before_bytes = gdb_files(gdb)
    read_guard = ArcPyGuard(a, gdb, parent, readonly=True)
    _, validation = run_tool(alta_proyectos, read_guard, gdb, folder / 'solo_validar', apply=False)
    require(validation['nuevas_filas_confirmadas'] == 0
            and validation['transaccion'] == 'NO_INICIADA', 'La validación modificó registros.')
    require(len(validation['plan']['altas']) == 2, 'La validación no propuso las dos altas autorizadas.')
    require(table_snapshot(a, parent) == original, 'La validación alteró filas o campos.')
    require(gdb_files(gdb) == before_bytes, 'La validación alteró bytes de GDB, excluidos locks.')

    failure_guard = ArcPyGuard(a, gdb, parent, fail_second=True)
    failure_text = None
    try:
        run_tool(alta_proyectos, failure_guard, gdb, folder / 'rollback', apply=True)
    except Exception as exc:
        failure_text = str(exc)
    require(failure_text is not None and failure_guard.insert_attempts == 2
            and failure_guard.native_insertions == 1,
            'No se ejercitó el fallo tras una inserción nativa real.')
    rollback_paths = list((folder / 'rollback').rglob('resultado.json'))
    require(len(rollback_paths) == 1, 'Se esperaba un informe único del rollback.')
    rollback = json.loads(rollback_paths[0].read_text(encoding='utf-8-sig'))
    require(rollback['estado'] == 'ERROR_DETENIDO' and rollback['transaccion'] == 'REVERTIDA',
            'La herramienta no certificó rollback de la transacción.')
    require(table_snapshot(a, parent) == original, 'El rollback dejó filas o campos diferentes.')

    apply_guard = ArcPyGuard(a, gdb, parent)
    _, applied = run_tool(alta_proyectos, apply_guard, gdb, folder / 'aplicar', apply=True)
    require(applied['transaccion'] == 'CONFIRMADA' and applied['nuevas_filas_confirmadas'] == 2,
            'No se confirmó el alta nativa de los dos proyectos.')
    after = table_snapshot(a, parent)
    require(original['campos'] == after['campos'] and len(after['filas']) == 42,
            'Se alteró el esquema o el recuento no es 42.')
    require([row for row in after['filas'] if row['id_proyecto'] <= 40] == original['filas'],
            'Se modificó alguno de los cuarenta registros históricos sintéticos.')
    new_rows = [row for row in after['filas'] if row['id_proyecto'] > 40]
    require({(r['id_proyecto'], r['co_proyecto']) for r in new_rows}
            == {(41, 'PRY-00000041'), (42, 'PRY-00000042')}, 'Secuencia inesperada.')
    desc = a.Describe(str(parent))
    global_id = desc.globalIDFieldName
    for row in new_rows:
        require(row[global_id] and row['creador'] and row['editor']
                and row['fe_creacion'] and row['fe_actualizacion'],
                'GlobalID o auditoría nativa no se poblaron automáticamente.')
        require(row['id_tipo_proyecto'] == 8 and row['id_estado_proyecto'] == 3
                and row['es_registro'] == '1', 'Valores de negocio inesperados.')
        require(all(row[n] is None for n in ('us_creacion', 'ip_creacion',
                'us_actualizacion', 'ip_actualizacion', 'us_eliminacion',
                'ip_eliminacion', 'fe_eliminacion', 'co_alternativa_reciente')),
                'Se inventaron datos de auditoría legado o alternativas.')

    repeat_guard = ArcPyGuard(a, gdb, parent)
    _, repeated = run_tool(alta_proyectos, repeat_guard, gdb, folder / 'repetir', apply=True)
    require(repeated['nuevas_filas_confirmadas'] == 0 and repeat_guard.native_insertions == 0
            and len(repeated['plan']['existentes']) == 2,
            'La repetición no reutilizó los proyectos existentes.')
    require(table_snapshot(a, parent) == after, 'La repetición modificó datos o auditoría.')
    require(all(sha(OUT / name) == digest for name, digest in package.items()),
            'El paquete cambió durante el ensayo.')
    evidence = dict(estado='ENSAYO_LOCAL_ALTAS_VERIFICADO', version_paquete='1.11',
        arcgis=a.GetInstallInfo()['Version'], geodatabase=str(gdb),
        registros_iniciales=40, registros_finales=42, nuevas_filas=2,
        validacion_sin_cambios_fisicos=True, validacion_sin_cambios=True,
        rollback_nativo_verificado=True, rollback_verificado=True,
        idempotencia_verificada=True, registros_anteriores_inalterados=True,
        altas_creadas=2, reejecucion_sin_altas=True, esquema_inalterado=True,
        modelo_inalterado=True, toolbox_ejecutada=False, runtime_ejecutado=True,
        editor_tracking_nativo_verificado=True, global_id_nativo_verificado=True,
        campos_legado=34, validacion_sde=False, concurrencia_sql_server_validada=False,
        branch_versioning_validado=False, ingesta_kmz_realizada=False,
        exclusividad='Exclusiva sobre GDB nueva local; no acredita exclusividad en SDE.',
        informes=[validation['archivo_resultado'], str(rollback_paths[0]),
                  applied['archivo_resultado'], repeated['archivo_resultado']],
        llamadas=dict(Counter(call for guard in
            (read_guard, failure_guard, apply_guard, repeat_guard) for call in guard.calls)),
        archivos_paquete_sha256=package,
        archivos_sha256={**package, '03_scripts/probar_alta_proyectos_1_11_arcgis.py': sha(__file__)},
        script_sha256=sha(__file__),
        alcance='Prueba del runtime y de ArcPy Editor/InsertCursor reales en File GDB '
            'sintética creada desde cero. No acredita el destino SQL Server, '
            'concurrencia entre escritores, servicios, versionado, relaciones ni carga KMZ.')
    proof_path = folder / 'VALIDACION_ALTAS_1_11_ARCGIS.json'
    write_json(proof_path, evidence)
    print(json.dumps(dict(estado=evidence['estado'], informe=str(proof_path)),
                     ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    import arcpy
    with arcpy.EnvManager(overwriteOutput=False, extent=None):
        verify(arcpy)


if __name__ == '__main__':
    main()
