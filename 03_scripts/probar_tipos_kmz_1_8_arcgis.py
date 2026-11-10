"""Ensayo 1.8 de solo lectura sobre 76 clases sinteticas, sin conexion SDE.

La preparacion copia el fixture local de 1.7 a una carpeta nueva y agrega las
seis clases restantes. La verificacion ejecuta la octava herramienta real con
el perfil incluido y compara SHA256 de todos los archivos de la geodatabase
antes y despues, excluyendo solamente cerraduras transitorias *.lock.
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
import uuid


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '02_entregas' / 'Esquema_KMZ_EFT_Corregido'
VALIDATION = OUT / '_validacion'
MODEL = OUT / 'esquema.json'
PROFILE = OUT / 'PERFIL_COMPLETO_KMZ_1_8.json'
SOURCE = VALIDATION / 'textos17_20261106_185344_47ec3385ab' / 'ensayo.gdb'
MODEL_SHA = '7e4640548a87ef8775884c5ab510196ae5e88d382fe8ca068fb7bffe6eaea626'


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def json_sha(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':')).encode('utf-8')).hexdigest()


def write_json(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def gdb_files(gdb):
    """La comparacion incluye contenido y presencia de todo archivo salvo locks."""
    require(gdb.is_dir() and gdb.suffix.lower() == '.gdb', 'Se requiere una GDB local existente.')
    result = {str(path.relative_to(gdb)): sha(path) for path in sorted(gdb.rglob('*'))
            if path.is_file() and not path.name.lower().endswith('.lock')}
    require(result, 'La geodatabase no contiene archivos verificables.')
    return result


def source_files():
    return gdb_files(SOURCE)


def reference():
    require(sha(MODEL) == MODEL_SHA, 'El modelo 11 cambio; el ensayo debe revisarse.')
    model = json.loads(MODEL.read_text(encoding='utf-8'))
    classes = sorted(model['clases'], key=lambda cls: cls['nombre'])
    require(model['version'] == 11 and len(classes) == 76, 'Se requieren las 76 clases del modelo 11.')
    require(sum(len(cls['campos']) for cls in classes) == 3340, 'Se requieren 3340 campos del modelo.')
    require(all(cls['dataset'] == 'Datos_Proyecto' for cls in classes), 'Dataset inesperado.')
    return model, classes


def prepare(a):
    model, classes = reference()
    require(SOURCE.is_dir() and SOURCE.resolve().parent.parent == VALIDATION.resolve(),
            'Falta el fixture local 1.7 o su ruta no es la esperada.')
    original_manifest = json.loads((SOURCE.parent / 'fixture.json').read_text(encoding='utf-8'))
    require(original_manifest['estado'] == 'FIXTURE_PREPARADO'
            and original_manifest['modelo_sha256'] == MODEL_SHA
            and len(original_manifest['clases']) == 70, 'El fixture original no es la referencia 1.7.')
    source_before = source_files()
    folder = VALIDATION / ('tipos18_' + dt.datetime.now().strftime('%Y%m%d_%H%M%S')
                           + '_' + uuid.uuid4().hex[:10])
    folder.mkdir()
    gdb = folder / 'ensayo.gdb'
    require(folder.resolve().parent == VALIDATION.resolve() and not gdb.exists(),
            'Se requiere un destino nuevo dentro del area de ensayos.')
    print('Carpeta de ensayo: ' + str(folder), flush=True)
    a.management.Copy(str(SOURCE), str(gdb))
    require(source_files() == source_before, 'Cambio el contenido del fixture original al copiarlo.')
    with a.EnvManager(workspace=str(gdb)):
        existing = set(a.ListFeatureClasses(feature_dataset='Datos_Proyecto') or [])
    require(existing == set(original_manifest['clases']), 'La copia no conserva las 70 clases originales.')
    missing = [cls for cls in classes if cls['nombre'] not in existing]
    require(len(missing) == 6 and sum(len(cls['campos']) for cls in missing) == 95,
            'Las seis clases pendientes deben sumar 95 campos del modelo.')
    domains = {domain.name for domain in a.da.ListDomains(str(gdb))}
    required_domains = {field['dominio'] for cls in missing for field in cls['campos'] if field.get('dominio')}
    require(required_domains <= domains, 'La copia no contiene todos los dominios necesarios.')
    ds = str(gdb / 'Datos_Proyecto')
    for number, cls in enumerate(missing, 1):
        path = str(Path(ds) / cls['nombre'])
        a.management.CreateFeatureclass(ds, cls['nombre'], cls['geometria'],
            has_m='DISABLED', has_z='ENABLED', spatial_reference=a.SpatialReference(4326))
        nullable = [field for field in cls['campos'] if field['nullable']]
        if nullable:
            a.management.AddFields(path, [[field['nombre'], field['tipo'], field['alias'],
                field['longitud'], None, field.get('dominio') or None] for field in nullable])
        for field in cls['campos']:
            if not field['nullable']:
                a.management.AddField(path, field['nombre'], field['tipo'],
                    field_length=field['longitud'], field_alias=field['alias'],
                    field_is_nullable='NON_NULLABLE', field_domain=field.get('dominio') or '')
        a.management.AddGlobalIDs(path)
        a.management.EnableEditorTracking(path, 'created_user', 'created_date',
            'last_edited_user', 'last_edited_date', 'ADD_FIELDS', 'UTC')
        print(f"AGREGADA {number}/6: {cls['nombre']}; {len(cls['campos'])} campos.", flush=True)
    require(source_files() == source_before, 'Se modifico el fixture original durante la preparacion.')
    manifest = dict(estado='FIXTURE_PREPARADO', version_paquete='1.8', version_modelo=11,
        carpeta=str(folder), geodatabase=str(gdb), clases=[cls['nombre'] for cls in classes],
        clases_copiadas=70, clases_agregadas=[cls['nombre'] for cls in missing], campos_modelo=3340,
        fuente=str(SOURCE), fuente_archivos_sha256=source_before,
        fuente_inalterada=True, modelo_sha256=MODEL_SHA, arcgis=a.GetInstallInfo()['Version'],
        script_preparacion_sha256=sha(__file__))
    write_json(folder / 'fixture.json', manifest)
    print(json.dumps(dict(estado='FIXTURE_PREPARADO', carpeta=str(folder), clases=76, campos=3340),
        ensure_ascii=False), flush=True)


class ReadOnly:
    def __init__(self, wrapped, allowed, calls, prefix='arcpy'):
        self.wrapped, self.allowed, self.calls, self.prefix = wrapped, allowed, calls, prefix

    def __getattr__(self, key):
        name = self.prefix + '.' + key
        if key not in self.allowed:
            self.calls.append({'api_bloqueada': name})
            raise AssertionError('API ajena a la verificacion de lectura: ' + name)
        item = getattr(self.wrapped, key)
        if isinstance(self.allowed[key], dict):
            return ReadOnly(item, self.allowed[key], self.calls, name)
        if callable(item):
            def call(*args, **kwargs):
                self.calls.append({'api': name})
                return item(*args, **kwargs)
            return call
        return item


def verify(a, requested_folder):
    _, classes = reference()
    folder = Path(requested_folder).resolve()
    require(folder.parent == VALIDATION.resolve() and folder.name.startswith('tipos18_'),
            'Solo se verifican fixtures propios bajo _validacion/tipos18_*.')
    fixture = json.loads((folder / 'fixture.json').read_text(encoding='utf-8'))
    names = [cls['nombre'] for cls in classes]
    require(fixture['estado'] == 'FIXTURE_PREPARADO' and fixture['modelo_sha256'] == MODEL_SHA
            and fixture['clases'] == names, 'Fixture incompatible con el modelo vigente.')
    gdb = (folder / 'ensayo.gdb').resolve()
    require(gdb.is_dir() and gdb.parent == folder and gdb.suffix == '.gdb', 'Destino de ensayo no valido.')
    require(PROFILE.is_file(), 'Falta el perfil completo incluido 1.8.')
    audit_folder = folder / ('verificacion_' + uuid.uuid4().hex[:10])
    audit_folder.mkdir()
    before = gdb_files(gdb)
    write_json(audit_folder / 'archivos_gdb_antes.json', before)
    print(f'HUELLA ANTES: {len(before)} archivos de la GDB; solo se excluyen *.lock.', flush=True)
    input_names = ('Datos_Proyecto.pyt', 'esquema.json', 'PERFIL_COMPLETO_KMZ_1_8.json',
        'validar_tipos_kmz.py', 'inspeccion_kmz.py', 'crear_esquema.py', 'datos_proyecto.py',
        'mapeo_capas_revision.csv', 'campos_por_ruta.csv', 'nombres_clases_1_6.json',
        'campos_aprobados_1_5.json')
    input_hashes = {name: sha(OUT / name) for name in input_names}
    loader = importlib.machinery.SourceFileLoader('toolbox_tipos18_native', str(OUT / 'Datos_Proyecto.pyt'))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    toolbox = importlib.util.module_from_spec(spec)
    loader.exec_module(toolbox)
    declared = toolbox.Toolbox().tools
    require(len(declared) == 8 and declared[-1] is toolbox.ValidarTodosTiposKMZ,
            'La octava herramienta debe ser ValidarTodosTiposKMZ.')
    tool = toolbox.ValidarTodosTiposKMZ()
    params = tool.getParameterInfo()
    require([parameter.name for parameter in params] == ['workspace', 'kmz_dir', 'database', 'owner', 'reports', 'report'],
            'La interfaz de la herramienta cambio.')
    values = [str(gdb), None, 'ArcGisAWS', 'gis', str(audit_folder)]
    for parameter, value in zip(params, values):
        if value is not None:
            parameter.value = value
    require(params[1].valueAsText in (None, ''), 'Se debe usar el perfil incluido, sin releer KMZ.')
    calls = []
    allowed = dict.fromkeys(('GetInstallInfo', 'Exists', 'Describe', 'EnvManager',
        'ValidateTableName', 'ValidateFieldName', 'ListDatasets', 'ListFeatureClasses',
        'ListTables', 'ListFields', 'AddMessage', 'AddWarning', 'AddError'), True)
    allowed['da'] = {'ListDomains': True}
    toolbox.arcpy = ReadOnly(a, allowed, calls)
    print('EJECUTANDO: ValidarTodosTiposKMZ con perfil incluido y fachada de solo lectura.', flush=True)
    tool.execute(params, None)
    result_path = Path(params[-1].valueAsText)
    result = json.loads(result_path.read_text(encoding='utf-8'))
    require(result['estado'] in {'VALIDACION_TIPOS_COMPLETA_CON_PENDIENTES', 'TIPOS_VERIFICADOS'},
            'La herramienta no completo la validacion: ' + result['estado'])
    require(result['origen_evidencia'] == 'PERFIL_INCLUIDO_VERIFICADO'
            and result['perfil_incluido_sha256'] == input_hashes['PERFIL_COMPLETO_KMZ_1_8.json'],
            'No se verifico el perfil incluido esperado.')
    require(result['campos_revisados'] == result['campos_modelo'] == 3340
            and result['clases_modelo'] == 76 and result['campos_tipo_pendiente'] == 730,
            'La cobertura del modelo o sus pendientes no coincide.')
    target = result['destino']
    require(target['verificado'] is True and target['campos_verificados'] == 3340
            and target['clases_esperadas'] == 76 and not target['incidencias'],
            'La validacion fisica no cubrio las 76 clases y 3340 campos sin incidencias.')
    require(not any('api_bloqueada' in call for call in calls), 'Se intento una API ajena a lectura.')
    require(all(sha(OUT / name) == digest for name, digest in input_hashes.items()),
            'Cambio una entrada durante la validacion.')
    after = gdb_files(gdb)
    write_json(audit_folder / 'archivos_gdb_despues.json', after)
    require(before == after, 'Cambio la presencia o contenido de archivos de la geodatabase.')
    print(f'HUELLA DESPUES: {len(after)} archivos; contenido y presencia identicos.', flush=True)
    require(source_files() == fixture['fuente_archivos_sha256'], 'Cambio el fixture original 1.7.')
    evidence = dict(version_paquete='1.8', version_modelo=11, estado=result['estado'],
        arcgis=a.GetInstallInfo()['Version'], validacion_sde=False, geodatabase=str(gdb),
        clases_ensayadas=names, clases_ensayadas_total=76, campos_ensayados=3340,
        campos_pendientes_modelo=730, diferencias_destino=0, perfil_incluido_verificado=True,
        perfil_incluido_sha256=result['perfil_incluido_sha256'], modelo_sha256=MODEL_SHA,
        toolbox_cargada=True, toolbox_ejecutada=True, herramienta='ValidarTodosTiposKMZ',
        herramientas_declaradas=[entry.__name__ for entry in declared],
        parametros=[parameter.name for parameter in params], informe_herramienta=str(result_path),
        metodo_preservacion='SHA256_TODOS_ARCHIVOS_GDB_EXCEPTO_LOCKS',
        archivos_gdb_total=len(before), archivos_gdb_antes=str(audit_folder / 'archivos_gdb_antes.json'),
        archivos_gdb_despues=str(audit_folder / 'archivos_gdb_despues.json'),
        huella_gdb_antes_sha256=json_sha(before), huella_gdb_despues_sha256=json_sha(after),
        archivos_gdb_identicos=True, conteos_filas_verificados=False, fuente_1_7_inalterada=True,
        mutaciones_geodatabase_durante_verificacion=0,
        llamadas=dict(sorted(Counter(call['api'] for call in calls).items())),
        archivos_sha256={**input_hashes, '03_scripts/probar_tipos_kmz_1_8_arcgis.py': sha(__file__)},
        alcance='Validacion fisica de 3340 campos en las 76 clases de Datos_Proyecto, en una GDB '
            'sintetica local nueva. La evidencia KMZ procede del perfil incluido verificado. '
            'La preservacion se comprueba con hashes del contenido y presencia de todos los '
            'archivos GDB, excepto locks transitorios. No se ejecutan recuentos de filas ni '
            'fotografias ArcPy separadas antes/despues. No valida SQL Server/SDE, carga de datos '
            'ni los datasets Datos_Externos y Datos_Internos.')
    write_json(audit_folder / 'VALIDACION_TIPOS_1_8_ARCGIS.json', evidence)
    (OUT / 'VALIDACION_TIPOS_1_8_ARCGIS.json').write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(estado=result['estado'], clases=76, campos=3340,
        mutaciones_durante_verificacion=0, informe=str(OUT / 'VALIDACION_TIPOS_1_8_ARCGIS.json')),
        ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('etapa', choices=['preparar', 'verificar'])
    parser.add_argument('--carpeta')
    args = parser.parse_args()
    require(bool(args.carpeta) == (args.etapa == 'verificar'),
            '--carpeta se requiere exclusivamente para verificar un fixture propio.')
    import arcpy
    with arcpy.EnvManager(overwriteOutput=False, extent=None):
        if args.etapa == 'preparar':
            prepare(arcpy)
        else:
            verify(arcpy, args.carpeta)


if __name__ == '__main__':
    main()
