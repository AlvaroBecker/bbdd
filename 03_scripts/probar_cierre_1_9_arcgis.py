"""Ensayo nativo del cierre 1.9 en una copia local aislada, nunca sobre SDE.

La preparacion copia un fixture inactivo con verificacion byte por byte. El
ensayo aplica exclusivamente ocho AlterField mediante una fachada restringida,
comprueba el esquema de las 76 clases y preserva los 73 esquemas no afectados.
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
SOURCE = VALIDATION / 'tipos18_20261109_091851_fe2c56f6a9' / 'ensayo.gdb'
BASE_SHA = '7e4640548a87ef8775884c5ab510196ae5e88d382fe8ca068fb7bffe6eaea626'
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
TARGET_TYPES = {'LONG': 'Integer', 'DOUBLE': 'Double'}


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def json_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(',', ':')).encode('utf-8')).hexdigest()


def write_json(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def gdb_files(path):
    require(path.is_dir() and path.suffix.lower() == '.gdb', 'Se requiere una GDB local.')
    rows = {str(p.relative_to(path)): sha(p) for p in sorted(path.rglob('*'))
            if p.is_file() and not p.name.lower().endswith('.lock')}
    require(rows, 'Geodatabase vacia o ilegible.')
    return rows


def prepare():
    require(SOURCE.is_dir() and SOURCE.resolve().parent.parent == VALIDATION.resolve(),
            'Falta el fixture 1.8 original esperado.')
    require(not any(p.name.lower().endswith('.lock') for p in SOURCE.iterdir()),
            'El fixture original tiene locks; no copiar mientras pueda estar en uso.')
    baseline = json.loads((SOURCE.parent / 'fixture.json').read_text(encoding='utf-8'))
    require(baseline['estado'] == 'FIXTURE_PREPARADO' and baseline['modelo_sha256'] == BASE_SHA
            and len(baseline['clases']) == 76 and baseline['campos_modelo'] == 3340,
            'La referencia 1.8 no corresponde al modelo 11 completo.')
    original = gdb_files(SOURCE)
    folder = VALIDATION / ('cierre19_' + dt.datetime.now().strftime('%Y%m%d_%H%M%S_')
                           + uuid.uuid4().hex[:10])
    folder.mkdir()
    target = folder / 'ensayo.gdb'
    require(folder.resolve().parent == VALIDATION.resolve() and not target.exists(),
            'Solo se admite una copia nueva dentro del area de ensayos.')
    shutil.copytree(SOURCE, target, ignore=shutil.ignore_patterns('*.lock'))
    require(gdb_files(SOURCE) == original == gdb_files(target),
            'La copia debe ser identica y el fixture original debe permanecer intacto.')
    require(not any(p.name.lower().endswith('.lock') for p in SOURCE.iterdir()),
            'Se abrio el fixture original durante la copia.')
    manifest = dict(estado='FIXTURE_PREPARADO', version_paquete='1.9', version_modelo_origen=11,
        modelo_origen_sha256=BASE_SHA, carpeta=str(folder), geodatabase=str(target),
        clases=baseline['clases'], campos_modelo=3340, fuente=str(SOURCE),
        fuente_archivos_sha256=original, copia_archivos_sha256=gdb_files(target),
        metodo_copia='ARCHIVOS_SIN_LOCKS_Y_VERIFICACION_SHA256', fuente_inalterada=True,
        script_preparacion_sha256=sha(__file__))
    write_json(folder / 'fixture.json', manifest)
    print(json.dumps(dict(estado=manifest['estado'], carpeta=str(folder),
        archivos_copiados=len(original), clases=76, campos=3340), ensure_ascii=False), flush=True)


def prepare_parent(a, requested_folder):
    """Dato sintetico para probar el contrato padre; nunca sobre una SDE."""
    folder = Path(requested_folder).resolve()
    require(folder.parent == VALIDATION.resolve() and folder.name.startswith('cierre19_'),
            'La preparacion del padre solo admite la copia cierre19_.')
    fixture = json.loads((folder / 'fixture.json').read_text(encoding='utf-8'))
    gdb = (folder / 'ensayo.gdb').resolve()
    require(gdb.parent == folder and gdb_files(gdb) == fixture['copia_archivos_sha256'],
            'La copia debe permanecer en su estado inicial.')
    require(gdb_files(SOURCE) == fixture['fuente_archivos_sha256'], 'El fixture original cambio.')
    parent = gdb / 'mline_tc_proyecto'
    require(not a.Exists(str(parent)), 'La preparacion no reemplaza una tabla existente.')
    before = gdb_files(gdb)
    a.management.CreateTable(str(gdb), parent.name)
    a.management.AddField(str(parent), 'co_proyecto', 'TEXT', field_length=12,
                          field_is_nullable='NON_NULLABLE')
    with a.da.InsertCursor(str(parent), ['co_proyecto']) as cursor:
        cursor.insertRow(['ENSAYO_19'])
    require(a.Describe(str(parent)).hasOID, 'El padre sintetico debe tener ObjectID.')
    field = next(f for f in a.ListFields(str(parent)) if f.name == 'co_proyecto')
    require(field.type == 'String' and field.length == 12, 'Tipo/longitud del padre incorrectos.')
    with a.da.SearchCursor(str(parent), ['co_proyecto']) as cursor:
        require(list(cursor) == [('ENSAYO_19',)], 'Codigo sintetico no verificado.')
    require(gdb_files(SOURCE) == fixture['fuente_archivos_sha256'], 'Se altero el fixture original.')
    evidence = dict(estado='PADRE_SINTETICO_PREPARADO', tabla=str(parent),
        campo='co_proyecto', tipo='TEXT', longitud=12, codigo='ENSAYO_19',
        operaciones=['CreateTable', 'AddField', 'InsertCursor(1 fila sintetica)'],
        archivos_antes=before, archivos_despues=gdb_files(gdb),
        fuente_1_8_inalterada=True, validacion_sde=False,
        aclaracion='Preparacion del fixture de prueba; no es carga de datos KMZ ni creacion de tabla en SDE.')
    write_json(folder / 'preparacion_padre.json', evidence)
    print(json.dumps(dict(estado=evidence['estado'], tabla=str(parent), codigo='ENSAYO_19'),
        ensure_ascii=False), flush=True)


def base_name(field):
    return getattr(field, 'baseName', None) or field.name.rsplit('.', 1)[-1]


def fields_snapshot(a, gdb, names):
    """Solo ListFields y propiedades basicas; sin GetCount/Describe/indices."""
    result = {}
    for number, name in enumerate(sorted(names), 1):
        result[name] = {base_name(f): dict(tipo=f.type, longitud=f.length,
            nullable=f.isNullable, dominio=f.domain or '', alias=f.aliasName)
            for f in a.ListFields(str(gdb / 'Datos_Proyecto' / name))}
        if number % 25 == 0 or number == len(names):
            print(f'ESQUEMA MINIMO: {number}/{len(names)} clases.', flush=True)
    return result


def classes_snapshot(a, gdb, names):
    result = {}
    for name in sorted(names):
        path = str(gdb / 'Datos_Proyecto' / name)
        d = a.Describe(path)
        fields = {}
        for f in a.ListFields(path):
            fields[base_name(f)] = {p: getattr(f, p, None) for p in
                ('name', 'baseName', 'aliasName', 'type', 'length', 'precision', 'scale',
                 'isNullable', 'required', 'domain', 'defaultValue')}
        description = {p: getattr(d, p, None) for p in ('dataType', 'shapeType', 'hasZ', 'hasM',
            'hasGlobalID', 'editorTrackingEnabled', 'isTimeInUTC', 'isVersioned', 'creatorFieldName',
            'createdAtFieldName', 'editorFieldName', 'editedAtFieldName')}
        description['epsg'] = d.spatialReference.factoryCode
        indexes = sorted([dict(nombre=i.name, unico=i.isUnique, ascendente=i.isAscending,
            campos=[base_name(f) for f in i.fields]) for i in a.ListIndexes(path)],
            key=lambda i: i['nombre'])
        count = int(a.management.GetCount(path).getOutput(0))
        require(count == 0, 'El ensayo solo admite clases afectadas vacias: ' + name)
        result[name] = dict(campos=fields, descripcion=description, indices=indexes, filas=count)
        print('FOTOGRAFIA AFECTADA: ' + name, flush=True)
    return result


class Guarded:
    def __init__(self, a, gdb, calls, before):
        self._a, self._gdb, self._calls, self._before = a, gdb, calls, before
        self.management = Management(a, gdb, calls, before)
        self.da = ReadNamespace(a.da, {'ListDomains', 'SearchCursor'}, calls, 'arcpy.da')

    def __getattr__(self, name):
        return ReadNamespace(self._a, {'GetInstallInfo', 'Exists', 'Describe', 'EnvManager',
            'ValidateTableName', 'ValidateFieldName', 'ListDatasets', 'ListFeatureClasses',
            'ListTables', 'ListFields', 'ListIndexes', 'TestSchemaLock',
            'AddMessage', 'AddWarning', 'AddError'}, self._calls, 'arcpy').__getattr__(name)


class ReadNamespace:
    def __init__(self, wrapped, allowed, calls, prefix):
        self._wrapped, self._allowed, self._calls, self._prefix = wrapped, allowed, calls, prefix

    def __getattr__(self, name):
        require(name in self._allowed, 'API no admitida en el ensayo: ' + self._prefix + '.' + name)
        def call(*args, **kwargs):
            self._calls.append(dict(api=self._prefix + '.' + name))
            return getattr(self._wrapped, name)(*args, **kwargs)
        return call


class Management:
    def __init__(self, a, gdb, calls, before):
        self._a, self._gdb, self._calls, self._before = a, gdb, calls, before
        self.changed = set()
        self.preflight_unchanged = False

    def GetCount(self, path):
        self._calls.append(dict(api='arcpy.management.GetCount'))
        return self._a.management.GetCount(path)

    def AlterField(self, path, field, **kwargs):
        cls = Path(path).name
        key = cls, field
        require(Path(path).resolve() == self._gdb / 'Datos_Proyecto' / cls,
                'AlterField fuera del fixture local.')
        require(key in NUMERIC and kwargs == {'field_type': NUMERIC[key]},
                'AlterField distinto del lote exacto de ocho cambios.')
        require(key not in self.changed, 'Se intento modificar un campo mas de una vez.')
        if not self.changed:
            require(gdb_files(self._gdb) == self._before,
                    'La prevalidacion modifico archivos GDB antes del primer AlterField.')
            self.preflight_unchanged = True
        self._calls.append(dict(api='arcpy.management.AlterField', clase=cls, campo=field,
                                tipo=NUMERIC[key]))
        result = self._a.management.AlterField(path, field, **kwargs)
        self.changed.add(key)
        print(f'ALTERACION NATIVA: {cls}.{field} -> {NUMERIC[key]}', flush=True)
        return result

    def __getattr__(self, name):
        raise AssertionError('Mutacion no admitida: arcpy.management.' + name)


def verify(a, requested_folder):
    folder = Path(requested_folder).resolve()
    require(folder.parent == VALIDATION.resolve() and folder.name.startswith('cierre19_'),
            'Solo se admite un fixture nuevo cierre19_ dentro de _validacion.')
    fixture = json.loads((folder / 'fixture.json').read_text(encoding='utf-8'))
    gdb = (folder / 'ensayo.gdb').resolve()
    require(gdb.parent == folder and fixture['estado'] == 'FIXTURE_PREPARADO'
            and fixture['modelo_origen_sha256'] == BASE_SHA, 'Fixture incompatible.')
    require(gdb_files(SOURCE) == fixture['fuente_archivos_sha256'], 'El origen 1.8 cambio.')
    parent_prep_path = folder / 'preparacion_padre.json'
    parent_prep = json.loads(parent_prep_path.read_text(encoding='utf-8')) if parent_prep_path.exists() else None
    baseline_files = parent_prep['archivos_despues'] if parent_prep else fixture['copia_archivos_sha256']
    if parent_prep:
        require(parent_prep['estado'] == 'PADRE_SINTETICO_PREPARADO'
                and parent_prep['archivos_antes'] == fixture['copia_archivos_sha256'],
                'Preparacion del padre sin trazabilidad a la copia exacta.')
    require(gdb_files(gdb) == baseline_files, 'La copia ya fue modificada antes del ensayo.')
    sys.path.insert(0, str(OUT))
    import referencia_cierre_tipos
    base, model, config = referencia_cierre_tipos.read_reference(OUT)
    require(base['version'] == 11 and model['version'] == 12 and len(model['clases']) == 76,
            'Se requiere la transicion exacta de modelo11 a modelo12.')
    approved = {(r['clase'], r['campo']): r['tipo_objetivo'] for r in config['cambios_fisicos']}
    require(approved == NUMERIC, 'La aprobacion no coincide con los ocho cambios esperados.')
    names = {c['nombre'] for c in model['clases']}
    affected = {cls for cls, _ in NUMERIC}
    require(names == set(fixture['clases']), 'El inventario de clases cambio.')
    audit = folder / ('verificacion_' + uuid.uuid4().hex[:10])
    audit.mkdir()
    before = gdb_files(gdb)
    write_json(audit / 'archivos_antes.json', before)
    before_other = fields_snapshot(a, gdb, names - affected)
    before_affected = classes_snapshot(a, gdb, affected)
    write_json(audit / 'campos_73_antes.json', before_other)
    write_json(audit / 'clases_3_antes.json', before_affected)
    require(all(before_affected[cls]['campos'][field]['type'] == 'String'
                and before_affected[cls]['campos'][field]['length'] == 4000
                for cls, field in NUMERIC), 'Los ocho campos iniciales deben ser TEXT(4000).')
    input_names = [p.name for p in OUT.glob('*.py') if not p.name.startswith(('test_', 'probar_'))]
    input_names += ['Datos_Proyecto.pyt', 'esquema.json', 'esquema_anterior_1_8.json',
        'cierre_tipos_1_9.json', 'campos_aprobados_1_5.json', 'nombres_clases_1_6.json',
        'campos_por_ruta.csv', 'mapeo_capas_revision.csv', 'PERFIL_COMPLETO_KMZ_1_8.json',
        'PERFIL_COMPLETO_KMZ_1_8.sha256', 'PERFIL_COMPLETO_KMZ_1_9.json', 'PERFIL_COMPLETO_KMZ_1_9.sha256']
    input_hashes = {name: sha(OUT / name) for name in sorted(set(input_names))}
    loader = importlib.machinery.SourceFileLoader('toolbox_cierre19_native', str(OUT / 'Datos_Proyecto.pyt'))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    toolbox = importlib.util.module_from_spec(spec)
    loader.exec_module(toolbox)
    declared = toolbox.Toolbox().tools
    require(len(declared) == 9 and declared[-1] is toolbox.CerrarTiposKMZ,
            'La novena herramienta debe ser CerrarTiposKMZ.')
    tool = toolbox.CerrarTiposKMZ()
    params = tool.getParameterInfo()
    require([p.name for p in params] == ['workspace', 'accion', 'database', 'owner', 'reports', 'report'],
            'La interfaz no coincide con el contrato del ensayo.')
    require(params[1].valueAsText == 'Validar cierre (sin cambios)', 'La accion predeterminada debe ser lectura.')
    for p, value in zip(params, [str(gdb), 'Aplicar cierre de tipos', 'ArcGisAWS', 'gis', str(audit)]):
        p.value = value
    calls = []
    facade = Guarded(a, gdb, calls, before)
    toolbox.arcpy = facade
    print('EJECUTANDO HERRAMIENTA9: cierre de ocho tipos en copia local.', flush=True)
    tool.execute(params, None)
    result_path = Path(params[-1].valueAsText)
    result = json.loads(result_path.read_text(encoding='utf-8'))
    require(result['estado'] == 'TIPOS_CERRADOS_CON_PENDIENTES_DE_INGESTA'
            and result['cierre_verificado'] and result['cambios_pendientes_destino'] == 0
            and result['campos_pendientes_modelo'] == 0, 'El cierre no quedo verificado.')
    require(result['confirmaciones_texto'] == 722 and result['cambios_fisicos_aprobados'] == 8,
            'El cierre no conserva el alcance 722+8.')
    require(set(result['completadas']) == {'.'.join(k) for k in NUMERIC}
            and facade.management.changed == set(NUMERIC), 'No se aplicaron exactamente los ocho cambios.')
    require(facade.management.preflight_unchanged, 'No se acredito prevalidacion sin mutaciones.')
    for key in ('destino_antes', 'destino_despues'):
        physical = result[key]
        require(physical['verificado'] and physical['campos_verificados'] == 3340
                and physical['clases_esperadas'] == 76 and not physical['incidencias'],
                'Fallo la comprobacion fisica global: ' + key)
    after_affected = classes_snapshot(a, gdb, affected)
    after_other = fields_snapshot(a, gdb, names - affected)
    require(before_other == after_other, 'Se modifico el esquema de alguna de las otras 73 clases.')
    for name in affected:
        old, new = before_affected[name], after_affected[name]
        require(old.keys() == new.keys() and old['descripcion'] == new['descripcion']
                and old['indices'] == new['indices'] and old['filas'] == new['filas'] == 0,
                'Se modificaron geometria/auditoria/indices/filas en ' + name)
        require(old['campos'].keys() == new['campos'].keys(), 'Cambio la lista de columnas de ' + name)
        for field in old['campos']:
            previous, current = dict(old['campos'][field]), dict(new['campos'][field])
            if (name, field) in NUMERIC:
                require(current['type'] == TARGET_TYPES[NUMERIC[(name, field)]], 'Tipo final inesperado.')
                for prop in ('type', 'length', 'precision', 'scale'):
                    previous.pop(prop)
                    current.pop(prop)
            require(previous == current, 'Cambio no autorizado en ' + name + '.' + field)
    require(gdb_files(SOURCE) == fixture['fuente_archivos_sha256'], 'Cambio el fixture original 1.8.')
    require(all(sha(OUT / name) == digest for name, digest in input_hashes.items()),
            'Cambio el paquete durante el ensayo.')
    after_files = gdb_files(gdb)
    write_json(audit / 'archivos_despues.json', after_files)
    write_json(audit / 'campos_73_despues.json', after_other)
    write_json(audit / 'clases_3_despues.json', after_affected)
    evidence = dict(version_paquete='1.9', version_modelo=12, estado=result['estado'],
        arcgis=a.GetInstallInfo()['Version'], validacion_sde=False, geodatabase=str(gdb),
        clases_ensayadas_total=76, campos_ensayados=3340, campos_pendientes_modelo=0,
        cambios_pendientes_destino=0, cierre_verificado=True, diferencias_destino=0,
        confirmaciones_texto=722, cambios_fisicos_aplicados=8,
        cambios=[dict(clase=c, campo=f, tipo=t) for (c, f), t in sorted(NUMERIC.items())],
        toolbox_ejecutada=True, herramienta='CerrarTiposKMZ',
        herramientas_declaradas=[t.__name__ for t in declared],
        modo_validar_predeterminado=True, modo_validar_nativo_separado=False,
        prevalidacion_sin_mutaciones=True, otras_73_clases_preservadas=True,
        propiedades_3_clases_preservadas=True, clases_afectadas_vacias_antes_despues=True,
        indices_3_clases_preservados=True, fuente_1_8_inalterada=True,
        tabla_padre_sintetica_agregada=bool(parent_prep),
        preparacion_padre=str(parent_prep_path) if parent_prep else None,
        preparacion_padre_sha256=sha(parent_prep_path) if parent_prep else None,
        llamadas=dict(sorted(Counter(c['api'] for c in calls).items())),
        mutaciones_autorizadas=8, mutaciones_no_autorizadas=0,
        informe_herramienta=str(result_path), informe_herramienta_sha256=sha(result_path),
        carpeta_evidencia=str(audit), modelo_sha256=sha(OUT / 'esquema.json'),
        archivos_gdb_modificados=[n for n in sorted(before.keys() | after_files.keys())
            if before.get(n) != after_files.get(n)],
        archivos_sha256={**input_hashes, '03_scripts/probar_cierre_1_9_arcgis.py': sha(__file__)},
        alcance='Herramienta9 real en copia local sintetica con 76 clases. Ocho AlterField '
            'limitados por fachada a campos/tipos exactos. Validacion fisica global antes y despues '
            'de3340campos; fotografia minima sin cambios en73clases; propiedades, indices y '
            'recuentos vacios preservados en3clases. La fase previa al primer AlterField conserva '
            'todos los bytes GDB salvo locks. No acredita SDE, conversion de valores, ingesta, '
            'relaciones ni los otros datasets. La tabla padre sintetica se prepara antes del '
            'ensayo y sus operaciones se registran por separado. Idempotencia y fallos se '
            'cubren en pruebas unitarias.')
    write_json(audit / 'VALIDACION_CIERRE_1_9_ARCGIS.json', evidence)
    write_json(OUT / 'VALIDACION_CIERRE_1_9_ARCGIS.json', evidence)
    print(json.dumps(dict(estado=evidence['estado'], cambios=8, clases=76, campos=3340,
        informe=str(OUT / 'VALIDACION_CIERRE_1_9_ARCGIS.json')), ensure_ascii=False), flush=True)


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
