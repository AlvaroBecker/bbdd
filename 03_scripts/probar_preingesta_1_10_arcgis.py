"""Ensayo nativo de la herramienta 10 en una copia local; ninguna conexión SDE.

La preparación del único registro sintético se documenta por separado. Durante
el ensayo, una fachada limita ArcPy a lectura y las huellas prueban que ni la
GDB, ni los KMZ, ni el modelo se modifican.
"""
from __future__ import annotations

import argparse
from collections import Counter
import datetime as dt
import hashlib
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import uuid


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '02_entregas/Esquema_KMZ_EFT_Corregido'
VALIDATION = OUT / '_validacion'
SOURCE = VALIDATION / 'cierre19_20261109_145013_d81c6c9291' / 'ensayo.gdb'
SOURCES = ROOT / '01_fuentes'


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def sha(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def write_json(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def gdb_files(path):
    require(path.is_dir() and path.suffix.lower() == '.gdb', 'Se requiere una GDB local.')
    rows = {str(p.relative_to(path)): sha(p) for p in sorted(path.rglob('*'))
            if p.is_file() and not p.name.lower().endswith('.lock')}
    require(rows, 'Geodatabase vacía o ilegible.')
    return rows


def fixture_paths(requested_folder):
    folder = Path(requested_folder).resolve()
    require(folder.parent == VALIDATION.resolve() and folder.name.startswith('preingesta110_'),
            'Solo se admite la copia nueva preingesta110_ en _validacion.')
    fixture = json.loads((folder / 'fixture.json').read_text(encoding='utf-8'))
    gdb = (folder / 'ensayo.gdb').resolve()
    require(gdb.parent == folder and fixture['estado'] == 'FIXTURE_PREPARADO',
            'Fixture incompatible.')
    require(gdb_files(SOURCE) == fixture['fuente_archivos_sha256'], 'El fixture original 1.9 cambió.')
    return folder, fixture, gdb


def prepare():
    require(SOURCE.is_dir() and SOURCE.resolve().parent.parent == VALIDATION.resolve(),
            'Falta el fixture cerrado 1.9 esperado.')
    require(not list(SOURCE.glob('*.lock')), 'El fixture original tiene locks; no copiar en uso.')
    proof = json.loads((OUT / 'VALIDACION_CIERRE_1_9_ARCGIS.json').read_text(encoding='utf-8'))
    require(proof['cierre_verificado'] and proof['campos_ensayados'] == 3340
            and proof['clases_ensayadas_total'] == 76
            and Path(proof['geodatabase']).resolve() == SOURCE.resolve(),
            'El origen no es el fixture del cierre 1.9 aprobado.')
    original = gdb_files(SOURCE)
    folder = VALIDATION / ('preingesta110_' + dt.datetime.now().strftime('%Y%m%d_%H%M%S_')
                           + uuid.uuid4().hex[:10])
    folder.mkdir()
    target = folder / 'ensayo.gdb'
    require(folder.resolve().parent == VALIDATION.resolve() and not target.exists(),
            'Solo se admite una copia nueva dentro del área de ensayos.')
    shutil.copytree(SOURCE, target, ignore=shutil.ignore_patterns('*.lock'))
    require(gdb_files(SOURCE) == original == gdb_files(target),
            'La copia debe ser idéntica y el fixture original debe permanecer intacto.')
    require(not list(SOURCE.glob('*.lock')), 'Se abrió el fixture original durante la copia.')
    evidence = dict(estado='FIXTURE_PREPARADO', version_paquete='1.10', version_modelo=12,
        carpeta=str(folder), geodatabase=str(target), fuente=str(SOURCE),
        fuente_archivos_sha256=original, copia_archivos_sha256=gdb_files(target),
        clases=76, campos=3340, fuente_1_9_inalterada=True,
        metodo_copia='ARCHIVOS_SIN_LOCKS_Y_VERIFICACION_SHA256',
        script_preparacion_sha256=sha(__file__))
    write_json(folder / 'fixture.json', evidence)
    print(json.dumps(dict(estado=evidence['estado'], carpeta=str(folder),
                         archivos_copiados=len(original)), ensure_ascii=False), flush=True)


def prepare_parent(a, requested_folder):
    folder, fixture, gdb = fixture_paths(requested_folder)
    require(gdb_files(gdb) == fixture['copia_archivos_sha256'],
            'La copia debe permanecer en su estado inicial antes de preparar el padre.')
    parent = gdb / 'mline_tc_proyecto'
    require(a.Exists(str(parent)), 'Se esperaba la tabla padre sintética del fixture 1.9.')
    fields = {f.name: f for f in a.ListFields(str(parent))}
    require('no_proyecto' not in fields and fields['co_proyecto'].type == 'String'
            and fields['co_proyecto'].length == 12, 'Estructura sintética inesperada.')
    with a.da.SearchCursor(str(parent), ['co_proyecto']) as cursor:
        require(list(cursor) == [('ENSAYO_19',)], 'Solo se permite el registro sintético ENSAYO_19.')
    before = gdb_files(gdb)
    a.management.AddField(str(parent), 'no_proyecto', 'TEXT', field_length=250)
    with a.da.UpdateCursor(str(parent), ['co_proyecto', 'no_proyecto']) as cursor:
        for row in cursor:
            require(row[0] == 'ENSAYO_19', 'Código sintético inesperado.')
            row[1] = 'Proyecto sintetico de ensayo local'
            cursor.updateRow(row)
    with a.da.SearchCursor(str(parent), ['co_proyecto', 'no_proyecto']) as cursor:
        require(list(cursor) == [('ENSAYO_19', 'Proyecto sintetico de ensayo local')],
                'No se verificó la preparación del padre.')
    require(gdb_files(SOURCE) == fixture['fuente_archivos_sha256'], 'Se alteró el fixture original.')
    evidence = dict(estado='PADRE_SINTETICO_PREPARADO', tabla=str(parent),
        operaciones=['AddField(no_proyecto TEXT250)', 'UpdateCursor(1 fila sintética ENSAYO_19)'],
        archivos_antes=before, archivos_despues=gdb_files(gdb),
        fuente_1_9_inalterada=True, validacion_sde=False,
        aclaracion='Preparación aislada anterior al ensayo; no es modificación de datos reales.')
    write_json(folder / 'preparacion_padre.json', evidence)
    print(json.dumps(dict(estado=evidence['estado'], tabla=str(parent)), ensure_ascii=False), flush=True)


class ReadNamespace:
    def __init__(self, wrapped, allowed, calls, prefix):
        self._wrapped, self._allowed, self._calls, self._prefix = wrapped, allowed, calls, prefix

    def __getattr__(self, name):
        require(name in self._allowed, 'API no admitida en el ensayo: ' + self._prefix + '.' + name)
        def call(*args, **kwargs):
            self._calls.append(dict(api=self._prefix + '.' + name))
            return getattr(self._wrapped, name)(*args, **kwargs)
        return call


class Guarded:
    def __init__(self, a, calls):
        self._a, self._calls = a, calls
        self.management = ReadNamespace(a.management, {'GetCount'}, calls, 'arcpy.management')
        self.da = ReadNamespace(a.da, {'ListDomains', 'SearchCursor'}, calls, 'arcpy.da')

    def __getattr__(self, name):
        return ReadNamespace(self._a, {'GetInstallInfo', 'Exists', 'Describe', 'EnvManager',
            'ValidateTableName', 'ValidateFieldName', 'ListDatasets', 'ListFeatureClasses',
            'ListTables', 'ListFields', 'ListIndexes', 'TestSchemaLock',
            'AddMessage', 'AddWarning', 'AddError'}, self._calls, 'arcpy').__getattr__(name)


def verify(a, requested_folder):
    folder, fixture, gdb = fixture_paths(requested_folder)
    prep_path = folder / 'preparacion_padre.json'
    preparation = json.loads(prep_path.read_text(encoding='utf-8'))
    require(preparation['archivos_antes'] == fixture['copia_archivos_sha256']
            and preparation['estado'] == 'PADRE_SINTETICO_PREPARADO'
            and gdb_files(gdb) == preparation['archivos_despues'],
            'El fixture no conserva la preparación aislada esperada.')
    sys.path.insert(0, str(OUT))
    import referencia_cierre_tipos
    import fuentes_ingesta
    _, model, _ = referencia_cierre_tipos.read_reference(OUT)
    require(model['version'] == 12 and len(model['clases']) == 76, 'Modelo cerrado incompatible.')
    profile = json.loads((OUT / 'PERFIL_COMPLETO_KMZ_1_9.json').read_text(encoding='utf-8'))['perfil']
    sources_before = fuentes_ingesta.discover_sources(SOURCES, profile['fuentes'], emit=None)
    require(sources_before['verificado'] and sources_before['conteos']['referencias_cubiertas'] == 13,
            'No se verificaron los trece KMZ originales antes del ensayo.')
    before = gdb_files(gdb)
    names = [p.name for p in OUT.glob('*.py') if not p.name.startswith(('test_', 'probar_'))]
    names += ['Datos_Proyecto.pyt', 'esquema.json', 'esquema_anterior_1_8.json',
        'cierre_tipos_1_9.json', 'campos_por_ruta.csv', 'mapeo_capas_revision.csv',
        'PERFIL_COMPLETO_KMZ_1_9.json', 'PERFIL_COMPLETO_KMZ_1_9.sha256']
    hashes = {name: sha(OUT / name) for name in sorted(set(names))}
    audit = folder / ('verificacion_' + uuid.uuid4().hex[:10])
    audit.mkdir()
    write_json(audit / 'archivos_antes.json', before)
    loader = importlib.machinery.SourceFileLoader('toolbox_preingesta110_native', str(OUT / 'Datos_Proyecto.pyt'))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    toolbox = importlib.util.module_from_spec(spec)
    loader.exec_module(toolbox)
    tools = toolbox.Toolbox().tools
    require(len(tools) == 10 and tools[-1] is toolbox.PrevalidarIngesta,
            'La herramienta décima debe ser PrevalidarIngesta.')
    tool = toolbox.PrevalidarIngesta()
    params = tool.getParameterInfo()
    require([p.name for p in params] == ['workspace', 'kmz_dir', 'project_csv', 'database', 'owner', 'reports', 'report'],
            'La interfaz no coincide con el contrato del ensayo.')
    require(params[2].parameterType == 'Optional', 'El CSV debe ser opcional en la primera ejecución.')
    for parameter, value in zip(params, [str(gdb), str(SOURCES), None, 'ArcGisAWS', 'gis', str(audit)]):
        parameter.value = value
    calls = []
    toolbox.arcpy = Guarded(a, calls)
    print('EJECUTANDO HERRAMIENTA10: prevalidación de solo lectura.', flush=True)
    tool.execute(params, None)
    result_path = Path(params[-1].valueAsText)
    report = json.loads(result_path.read_text(encoding='utf-8'))
    require(report['estado'] == 'PLAN_INGESTA_CON_PENDIENTES'
            and report['comprobaciones_lectura_completas'], 'La lectura nativa quedó incompleta.')
    require(report['destino']['verificado'] and report['destino']['campos_verificados'] == 3340
            and report['destino']['clases_esperadas'] == 76 and not report['destino']['incidencias']
            and not report['destino']['incidencias_preingesta']
            and report['destino']['registros_existentes'] == 0
            and len(report['destino']['recuentos']) == 76, 'La comprobación de destino no coincide.')
    require(report['fuentes']['verificado'] and report['fuentes']['conteos']['referencias_cubiertas'] == 13,
            'La herramienta no verificó los trece KMZ.')
    catalog, projects, plan = report['catalogo_proyectos'], report['proyectos'], report['plan']
    require(catalog['verificado'] and len(catalog['filas']) == 1
            and catalog['filas'][0]['co_proyecto'] == 'ENSAYO_19', 'El padre sintético no se leyó correctamente.')
    require(len(projects['asociaciones']) == 13 and not projects['verificado']
            and not any(row['confirmado'] for row in projects['asociaciones']),
            'Se confirmaron asociaciones sin decisión explícita.')
    routes = plan['rutas']
    require(len(routes) == 3638 and not any(row['cargable'] for row in routes),
            'Las rutas no conservan el inventario o se declararon cargables.')
    require(plan['resumen']['elementos'] == 279623
            and plan['resumen']['elementos_con_destino'] == 139304
            and plan['resumen']['elementos_sin_destino'] == 140319,
            'Los recuentos del plan no conservan todos los Placemarks.')
    require(report['registros_insertados'] == 0 and not report['cambios_en_sde']
            and not report['cambios_en_modelo'] and not report['ingesta_autorizada'],
            'La herramienta debe ser únicamente de lectura.')
    after = gdb_files(gdb)
    require(before == after, 'La prevalidación modificó bytes de la geodatabase (excluidos locks).')
    require(gdb_files(SOURCE) == fixture['fuente_archivos_sha256'], 'El fixture original 1.9 cambió.')
    require(all(sha(OUT / name) == value for name, value in hashes.items()),
            'El paquete cambió durante el ensayo.')
    require(fuentes_ingesta.discover_sources(SOURCES, profile['fuentes'], emit=None) == sources_before,
            'Las fuentes KMZ cambiaron durante el ensayo.')
    require(any(call['api'] == 'arcpy.da.SearchCursor' for call in calls),
            'No se ejercitó el cursor de consulta del catálogo.')
    write_json(audit / 'archivos_despues.json', after)
    evidence = dict(version_paquete='1.10', version_modelo=12, estado=report['estado'],
        arcgis=a.GetInstallInfo()['Version'], validacion_sde=False, geodatabase=str(gdb),
        toolbox_ejecutada=True, herramienta='PrevalidarIngesta',
        herramientas_declaradas=[t.__name__ for t in tools],
        clases_ensayadas=76, campos_ensayados=3340, fuentes_verificadas=13,
        rutas=3638, placemarks=279623, mapeados=139304, sin_destino=140319,
        resumen_plan=plan['resumen'],
        filas_padre_leidas=1, asociaciones_confirmadas=0, registros_insertados=0,
        mutaciones_durante_ensayo=0, gdb_inalterada=True, fuente_1_9_inalterada=True,
        modelo_inalterado=True, fuentes_kmz_inalteradas=True, ingesta_autorizada=False,
        preparacion_padre=str(prep_path), preparacion_padre_sha256=sha(prep_path),
        llamadas=dict(sorted(Counter(call['api'] for call in calls).items())),
        informe_herramienta=str(result_path), informe_herramienta_sha256=sha(result_path),
        carpeta_evidencia=str(audit), archivos_gdb_modificados=[],
        archivos_sha256={**hashes, '03_scripts/probar_preingesta_1_10_arcgis.py': sha(__file__)},
        alcance='Herramienta10 real en una copia local de las 76 clases cerradas en1.9. '
            'Fachada ArcPy restringida a consultas. Se leen13KMZ auténticos por identidad SHA256 '
            'y un único proyecto sintético, sin confirmar las13asociaciones. Se conservan todos '
            'los bytes GDB salvo locks, las fuentes y el modelo. La preparación del padre está '
            'separada del ensayo. No acredita SDE ni una carga de registros.')
    write_json(audit / 'VALIDACION_PREINGESTA_1_10_ARCGIS.json', evidence)
    write_json(OUT / 'VALIDACION_PREINGESTA_1_10_ARCGIS.json', evidence)
    print(json.dumps(dict(estado=evidence['estado'], clases=76, campos=3340, fuentes=13,
                         informe=str(OUT / 'VALIDACION_PREINGESTA_1_10_ARCGIS.json')),
                     ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('etapa', choices=['preparar', 'preparar_padre', 'verificar'])
    parser.add_argument('--carpeta')
    args = parser.parse_args()
    require(bool(args.carpeta) == (args.etapa != 'preparar'),
            '--carpeta se requiere para preparar padre o verificar.')
    if args.etapa == 'preparar':
        prepare()
    else:
        import arcpy
        with arcpy.EnvManager(overwriteOutput=False, extent=None):
            if args.etapa == 'preparar_padre':
                prepare_parent(arcpy, args.carpeta)
            else:
                verify(arcpy, args.carpeta)


if __name__ == '__main__':
    main()
