"""Ensayo nativo completo del lote TEXT 1.7 en una GDB nueva y aislada.

Ejecutar con el Python de ArcGIS Pro, en dos procesos independientes:
  python probar_textos_confirmados_1_7_arcgis.py preparar
  python probar_textos_confirmados_1_7_arcgis.py verificar --carpeta <salida>

La preparacion crea unicamente objetos sinteticos bajo _validacion. La segunda
etapa ejecuta la septima herramienta real mediante una fachada de solo lectura.
No abre SDE ni utiliza geodatabases existentes como destino de escritura.
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
import sys
import uuid


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '02_entregas' / 'Esquema_KMZ_EFT_Corregido'
VALIDATION = OUT / '_validacion'
MODEL = OUT / 'esquema.json'
CONFIG = OUT / 'textos_confirmados_1_7.json'


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def json_sha(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


def write_json(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def reference():
    sys.path.insert(0, str(OUT))
    import verificar_textos_confirmados as verifier
    model, config, _, hashes = verifier.read_reference(MODEL, CONFIG)
    names = {row['clase'] for row in config['campos']}
    classes = sorted((c for c in model['clases'] if c['nombre'] in names), key=lambda c: c['nombre'])
    require(len(classes) == len(names) == 70, 'El lote debe afectar exactamente 70 clases.')
    require(len(config['campos']) == 1356, 'El ensayo debe usar la aprobacion completa de 1356 campos.')
    return model, config, hashes, classes


def prepare(a):
    model, config, hashes, classes = reference()
    VALIDATION.mkdir(exist_ok=True)
    folder = VALIDATION / ('textos17_' + dt.datetime.now().strftime('%Y%m%d_%H%M%S')
                           + '_' + uuid.uuid4().hex[:10])
    folder.mkdir()
    gdb = folder / 'ensayo.gdb'
    require(folder.resolve().is_relative_to(VALIDATION.resolve()), 'Destino fuera del area de ensayos.')
    require(not gdb.exists(), 'El ensayo no reutiliza una GDB existente para escribir.')
    print('Carpeta de ensayo: ' + str(folder), flush=True)
    a.management.CreateFileGDB(str(folder), gdb.name)
    ds = str(gdb / 'Datos_Proyecto')
    a.management.CreateFeatureDataset(str(gdb), 'Datos_Proyecto', a.SpatialReference(4326))
    needed_domains = {f['dominio'] for c in classes for f in c['campos'] if f.get('dominio')}
    for name in sorted(needed_domains):
        spec = model['dominios'][name]
        a.management.CreateDomain(str(gdb), name, spec['descripcion'], 'TEXT', 'CODED')
        for value in spec['valores']:
            a.management.AddCodedValueToDomain(str(gdb), name, value, value)
    count_fields = 0
    for number, cls in enumerate(classes, 1):
        path = str(Path(ds) / cls['nombre'])
        a.management.CreateFeatureclass(ds, cls['nombre'], cls['geometria'],
            has_m='DISABLED', has_z='ENABLED', spatial_reference=a.SpatialReference(4326))
        nullable = [f for f in cls['campos'] if f['nullable']]
        if nullable:
            a.management.AddFields(path, [[f['nombre'], f['tipo'], f['alias'],
                f['longitud'], None, f.get('dominio') or None] for f in nullable])
        for field in cls['campos']:
            if not field['nullable']:
                a.management.AddField(path, field['nombre'], field['tipo'],
                    field_length=field['longitud'], field_alias=field['alias'],
                    field_is_nullable='NON_NULLABLE', field_domain=field.get('dominio') or '')
        count_fields += len(cls['campos'])
        print(f"PREPARADA {number}/{len(classes)}: {cls['nombre']}; {len(cls['campos'])} campos.", flush=True)
    # Estas operaciones afectan solo al dataset sintetico recien creado.
    a.management.AddGlobalIDs(ds)
    a.management.EnableEditorTracking(ds, 'created_user', 'created_date',
        'last_edited_user', 'last_edited_date', 'ADD_FIELDS', 'UTC')
    manifest = dict(estado='FIXTURE_PREPARADO', version_paquete='1.7', version_modelo=11,
        carpeta=str(folder), geodatabase=str(gdb), clases=[c['nombre'] for c in classes],
        campos_modelo_creados=count_fields, campos_lote=1356,
        campos_pendientes_modelo=config['campos_pendientes_despues'],
        arcgis=a.GetInstallInfo()['Version'], script_sha256=sha(__file__), **hashes)
    write_json(folder / 'fixture.json', manifest)
    print(json.dumps(dict(estado=manifest['estado'], carpeta=str(folder),
        siguiente='verificar --carpeta "' + str(folder) + '"'), ensure_ascii=False), flush=True)


class ReadOnly:
    """Registra consultas y rechaza cualquier API no enumerada para el ensayo."""

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


def snapshot(a, gdb, names, phase):
    """Esquema, indices, dominios y conteos, sin modificar tablas ni registros."""
    result = {'clases': {}}
    with a.EnvManager(workspace=str(gdb)):
        result['datasets'] = sorted(a.ListDatasets(feature_type='Feature') or [])
        result['tablas'] = sorted(a.ListTables() or [])
        result['clases_fuera_dataset'] = sorted(a.ListFeatureClasses() or [])
        result['clases_dataset'] = sorted(a.ListFeatureClasses(feature_dataset='Datos_Proyecto') or [])
    require(result['clases_dataset'] == sorted(names), 'El inventario del fixture no coincide con el lote.')
    result['dominios'] = sorted([dict(nombre=d.name, tipo=d.type, clase=d.domainType,
        valores=sorted(d.codedValues.items(), key=lambda item: str(item[0])))
        for d in a.da.ListDomains(str(gdb))], key=lambda d: d['nombre'])
    for number, name in enumerate(sorted(names), 1):
        path = str(gdb / 'Datos_Proyecto' / name)
        desc = a.Describe(path)
        properties = ('dataType', 'shapeType', 'hasZ', 'hasM', 'hasGlobalID',
            'editorTrackingEnabled', 'isTimeInUTC', 'isVersioned', 'creatorFieldName',
            'createdAtFieldName', 'editorFieldName', 'editedAtFieldName')
        item = {key: getattr(desc, key, None) for key in properties}
        item['epsg'] = desc.spatialReference.factoryCode
        item['campos'] = [{key: getattr(field, key, None) for key in
            ('name', 'baseName', 'aliasName', 'type', 'length', 'precision', 'scale',
             'isNullable', 'required', 'domain', 'defaultValue')}
            for field in a.ListFields(path)]
        item['indices'] = sorted([dict(nombre=index.name, unico=index.isUnique,
            ascendente=index.isAscending, campos=[f.name for f in index.fields])
            for index in a.ListIndexes(path)], key=lambda index: index['nombre'])
        # Un cursor de OID cuenta exactamente sin el coste de iniciar 70 tools GP.
        with a.da.SearchCursor(path, ['OID@']) as rows:
            item['filas'] = sum(1 for _ in rows)
        require(item['filas'] == 0, 'El fixture sintetico debe permanecer vacio: ' + name)
        result['clases'][name] = item
        if number % 10 == 0 or number == len(names):
            print(f'FOTOGRAFIA {phase}: {number}/{len(names)} clases.', flush=True)
    return result


def verify(a, requested_folder):
    _, config, hashes, classes = reference()
    folder = Path(requested_folder).resolve()
    require(folder.parent == VALIDATION.resolve() and folder.name.startswith('textos17_'),
            'Solo se verifican fixtures propios bajo _validacion/textos17_*.')
    manifest = json.loads((folder / 'fixture.json').read_text(encoding='utf-8'))
    require(manifest['estado'] == 'FIXTURE_PREPARADO', 'Fixture sin preparacion completa.')
    for key, value in hashes.items():
        require(manifest[key] == value, 'El modelo/configuracion cambio desde la preparacion: ' + key)
    gdb = (folder / 'ensayo.gdb').resolve()
    require(gdb.is_dir() and gdb.suffix == '.gdb' and gdb.parent == folder,
            'El fixture debe ser una GDB local propia existente.')
    names = [c['nombre'] for c in classes]
    require(manifest['clases'] == names, 'Las clases preparadas difieren del lote actual.')
    audit_folder = folder / ('verificacion_' + uuid.uuid4().hex[:10])
    audit_folder.mkdir()
    before = snapshot(a, gdb, names, 'ANTES')
    write_json(audit_folder / 'esquema_antes.json', before)
    input_hashes = {name: sha(OUT / name) for name in ('Datos_Proyecto.pyt',
        'esquema.json', 'textos_confirmados_1_7.json', 'verificar_textos_confirmados.py',
        'crear_esquema.py', 'datos_proyecto.py', 'nombres_clases_1_6.json', 'campos_aprobados_1_5.json')}
    loader = importlib.machinery.SourceFileLoader('toolbox_textos17_native', str(OUT / 'Datos_Proyecto.pyt'))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    toolbox = importlib.util.module_from_spec(spec)
    loader.exec_module(toolbox)
    declared = toolbox.Toolbox().tools
    require(len(declared) == 7 and declared[-1] is toolbox.ValidarTextosConfirmados,
            'La septima herramienta debe ser ValidarTextosConfirmados.')
    tool = toolbox.ValidarTextosConfirmados()
    params = tool.getParameterInfo()
    require([p.name for p in params] == ['workspace', 'database', 'owner', 'reports', 'report'],
            'La interfaz de la herramienta cambio.')
    for parameter, value in zip(params, (str(gdb), 'ArcGisAWS', 'gis', str(audit_folder))):
        parameter.value = value
    require(all(p.name != 'mode' for p in params), 'No debe existir una accion de escritura.')
    calls = []
    allowed = dict.fromkeys(('GetInstallInfo', 'Exists', 'Describe', 'EnvManager',
        'ValidateTableName', 'ValidateFieldName', 'ListDatasets', 'ListFeatureClasses',
        'ListTables', 'ListFields', 'AddMessage', 'AddWarning', 'AddError'), True)
    allowed['da'] = {'ListDomains': True}
    toolbox.arcpy = ReadOnly(a, allowed, calls)
    tool.execute(params, None)
    result_path = Path(params[-1].valueAsText)
    result = json.loads(result_path.read_text(encoding='utf-8'))
    require(result['estado'] == 'TEXTOS_CONFIRMADOS_VERIFICADOS', 'La herramienta no verifico el lote.')
    require(result['campos_verificados'] == len(result['campos']) == 1356, 'Cobertura incompleta de campos.')
    require(result['campos_pendientes_modelo'] == 730, 'Conteo de pendientes incorrecto.')
    require(set(result['clases_verificadas']) == set(names), 'Cobertura incompleta de clases.')
    require(not result['discrepancias'], 'Se detectaron discrepancias en el fixture.')
    require(not any('api_bloqueada' in call for call in calls), 'Se intento una API ajena a lectura.')
    require(all(sha(OUT / name) == digest for name, digest in input_hashes.items()),
            'La verificacion modifico o encontro cambios en sus entradas.')
    after = snapshot(a, gdb, names, 'DESPUES')
    write_json(audit_folder / 'esquema_despues.json', after)
    require(after == before, 'Cambio el esquema, los indices, los dominios o los conteos durante la lectura.')
    evidence = dict(version_paquete='1.7', version_modelo=11,
        estado=result['estado'], arcgis=a.GetInstallInfo()['Version'], validacion_sde=False,
        geodatabase=str(gdb), clases_ensayadas=names, clases_ensayadas_total=len(names),
        clases_modelo=76, campos_ensayados=1356, campos_pendientes_modelo=730,
        campos_modelo_creados=manifest['campos_modelo_creados'],
        toolbox_cargada=True, toolbox_ejecutada=True, herramienta='ValidarTextosConfirmados',
        herramientas_declaradas=[declared_tool.__name__ for declared_tool in declared],
        parametros=[p.name for p in params], informe_herramienta=str(result_path),
        esquema_antes=str(audit_folder / 'esquema_antes.json'),
        esquema_despues=str(audit_folder / 'esquema_despues.json'),
        esquema_antes_sha256=json_sha(before), esquema_despues_sha256=json_sha(after),
        esquemas_iguales=True, clases_permanecen_vacias=True,
        conteos_fixture='Lectura exacta de OID con arcpy.da.SearchCursor antes y despues',
        mutaciones_geodatabase_durante_verificacion=0,
        llamadas=dict(sorted(Counter(call['api'] for call in calls).items())),
        archivos_sha256={**input_hashes, '03_scripts/probar_textos_confirmados_1_7_arcgis.py': sha(__file__)},
        alcance='Lote completo de 1356 campos en sus 70 clases dentro de una GDB nueva sintetica. '
            'El fixture contiene las definiciones fisicas completas de esas clases; '
            'la herramienta solo certifica los 1356 campos del lote y las propiedades de sus clases. '
            'No ensaya SQL Server/SDE, relaciones, codigos de proyecto ni carga de datos.',
        documentacion_esri=[
            'https://pro.arcgis.com/en/pro-app/latest/tool-reference/data-management/add-fields.htm',
            'https://pro.arcgis.com/en/pro-app/latest/tool-reference/data-management/add-global-ids.htm',
            'https://pro.arcgis.com/en/pro-app/latest/tool-reference/data-management/enable-editor-tracking.htm'],
        **hashes)
    write_json(audit_folder / 'VALIDACION_TEXTOS_1_7_ARCGIS.json', evidence)
    # Publica evidencia reproducible de esta ejecucion, no modifica fuentes ni GDB.
    (OUT / 'VALIDACION_TEXTOS_1_7_ARCGIS.json').write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(estado=result['estado'], clases=len(names), campos=1356,
        mutaciones_durante_verificacion=0, informe=str(OUT / 'VALIDACION_TEXTOS_1_7_ARCGIS.json')),
        ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('etapa', choices=['preparar', 'verificar'])
    parser.add_argument('--carpeta', help='Carpeta de un fixture creado por la etapa preparar.')
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
