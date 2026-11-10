"""Ensayo nativo 1.6 en copia aislada de una GDB; nunca conecta a SDE.

Preparacion y ejercicio usan procesos distintos para liberar los bloqueos de
Copy. El ejercicio une las comprobaciones de lectura y evita repetir pruebas
de texto largo ya cubiertas por la version 1.5.1.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import uuid

import arcpy as a

HERE = Path(__file__).resolve().parent
ROOT = HERE / '_validacion'
OLD = 'predios_inscritos_en_sunarp_recorte'
NEW = 'predios_inscritos_sunarp_recorte'
SELECTED = ('accesos', 'limite_departamento_recorte', NEW)
OBSERVED = ('estructuras',) + SELECTED
RESULT = HERE / 'VALIDACION_NOMBRES_1_6_ARCGIS.json'


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def file_manifest(path):
    """Huella de todos los datos del origen; los locks efimeros no son datos."""
    return {str(p.relative_to(path)): digest(p) for p in sorted(path.rglob('*'))
            if p.is_file() and not p.name.lower().endswith('.lock')}


def checked(value):
    path = Path(value).resolve()
    assert path.suffix == '.gdb' and path.is_relative_to(ROOT.resolve())
    assert path.parent.name.startswith('nombres16_')
    return path


def fc(path, name):
    return str(path / 'Datos_Proyecto' / name)


def state(path, renamed=False):
    from ajustar_tipos_estructuras import snapshot
    import actualizar_campos_aprobados as migration
    result = {}
    for name in OBSERVED:
        physical = NEW if name == NEW and renamed else OLD if name == NEW else name
        table = fc(path, physical)
        d = a.Describe(table)
        result[name] = dict(campos=snapshot(a, table), alias=d.aliasName,
            registros=int(a.management.GetCount(table).getOutput(0)),
            geometria=d.shapeType, referencia_espacial=d.spatialReference.factoryCode,
            has_z=d.hasZ, has_m=d.hasM, globalid=d.hasGlobalID,
            editor_tracking=d.editorTrackingEnabled, utc=d.isTimeInUTC,
            creator=d.creatorFieldName, created=d.createdAtFieldName,
            editor=d.editorFieldName, edited=d.editedAtFieldName,
            indices=migration.indexes_snapshot(a, table, ()))
    return result


def assert_preserved(before, after, aliases):
    assert before.keys() == after.keys()
    for name, original in before.items():
        old, current = dict(original), dict(after[name])
        expected_alias = aliases.get(name)
        if expected_alias is not None:
            assert current['alias'] == expected_alias, (name, current['alias'], expected_alias)
            old.pop('alias'); current.pop('alias')
        assert current == old, 'Cambio ajeno al nombre/alias: ' + name
        assert after[name]['registros'] == 0


def hashes():
    files = dict(esquema_sha256='esquema.json', aprobacion_sha256='campos_aprobados_1_5.json',
        mapeo_sha256='nombres_clases_1_6.json', modulo_sha256='renombrar_clases.py',
        modulo_general_sha256='actualizar_campos_aprobados.py',
        modulo_reparacion_sha256='reparar_texto_largo.py',
        verificador_sql_sha256='validacion_texto_sqlserver.py',
        engine_sha256='crear_esquema.py', runner_sha256='datos_proyecto.py',
        toolbox_sha256='Datos_Proyecto.pyt', script_sha256=Path(__file__).name)
    return {key: digest(HERE / name) for key, name in files.items()}


class TrackedManagement:
    def __init__(self, mutations):
        self.mutations = mutations

    def __getattr__(self, name):
        tool = getattr(a.management, name)
        if name in {'GetCount', 'ClearWorkspaceCache'}:
            return tool

        def tracked(*args, **kwargs):
            self.mutations.append(dict(herramienta=name,
                argumentos=[str(value) for value in args], parametros=kwargs))
            return tool(*args, **kwargs)
        return tracked


class TrackedArcPy:
    def __init__(self):
        self.mutations = []
        self.management = TrackedManagement(self.mutations)

    def __getattr__(self, name):
        if name == 'AlterAliasName':
            tool = getattr(a, name)
            def tracked(*args, **kwargs):
                self.mutations.append(dict(herramienta=name,
                    argumentos=[str(value) for value in args], parametros=kwargs))
                return tool(*args, **kwargs)
            return tracked
        return getattr(a, name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace')
    parser.add_argument('--etapa', choices=['preparar', 'ejecutar'], required=True)
    values = parser.parse_args()
    if values.etapa == 'preparar':
        assert not values.workspace
        sources = sorted(ROOT.glob('reparacion151_*/ensayo.gdb'))
        assert sources, 'No existe fixture reparacion151.'
        source = sources[-1].resolve()
        assert source.is_relative_to(ROOT.resolve()) and source.suffix == '.gdb'
        original_files = file_manifest(source)
        original = state(source)
        assert all(item['registros'] == 0 for item in original.values())
        assert original[NEW]['campos']['cargas_y_gravamenes']['longitud'] >= 10000
        folder = ROOT / ('nombres16_' + dt.datetime.now().strftime('%Y%m%d_%H%M%S')
                         + '_' + uuid.uuid4().hex[:8])
        folder.mkdir(parents=True)
        path = checked(folder / 'ensayo.gdb')
        assert not a.Exists(str(path)) and path != source
        a.management.Copy(str(source), str(path))
        assert file_manifest(source) == original_files
        assert state(path) == original
        write(folder / 'preparacion.json', dict(origen_solo_lectura=str(source),
            destino=str(path), archivos_origen=original_files, estado_inicial=original,
            fuente_sin_cambios=True, metodo='ArcGIS Copy de GDB sintetica; nunca SDE'))
        print(str(path), flush=True)
        return

    assert values.workspace
    path = checked(values.workspace)
    preparation = read(path.parent / 'preparacion.json')
    source = Path(preparation['origen_solo_lectura']).resolve()
    assert source != path and source.parent.name.startswith('reparacion151_')
    assert file_manifest(source) == preparation['archivos_origen']
    baseline = preparation['estado_inicial']
    assert state(path) == baseline
    current_hashes = hashes()
    mapping = read(HERE / 'nombres_clases_1_6.json')
    aliases = {row['nombre_nuevo']: row.get('alias') for row in mapping['clases']
               if row['nombre_nuevo'] in SELECTED}
    model = read(HERE / 'esquema.json')
    assert len(model['clases']) == len(mapping['clases']) == 76
    all_names = [c['nombre'] for c in model['clases']]
    relation_names = [r['nombre'] for r in model['relaciones'] + model['relaciones_negocio']]
    rejected = [(name, a.ValidateTableName(name, str(path)))
                for name in all_names + relation_names
                if a.ValidateTableName(name, str(path)) != name]
    assert not rejected, rejected
    tracked = TrackedArcPy()
    reports = {}
    try:
        import renombrar_clases as rename
        _, report = rename.run(str(path), reports=path.parent, arcpy_module=tracked,
                               names=list(SELECTED))
        assert report['estado'] == 'VALIDACION_OK_SIN_CAMBIOS'
        assert not tracked.mutations and state(path) == baseline
        reports['validar'] = report['archivo_resultado']
        print('Validacion nativa: cero escrituras.', flush=True)

        _, report = rename.run(str(path), apply=True, reports=path.parent,
                               arcpy_module=tracked, names=list(SELECTED))
        assert report['estado'] == 'NOMBRES_VERIFICADOS'
        assert not a.Exists(fc(path, OLD)) and a.Exists(fc(path, NEW))
        calls = [item['herramienta'] for item in tracked.mutations]
        assert calls.count('Rename') == 1, calls
        assert set(calls) <= {'Rename', 'AlterAliasName'}, calls
        after = state(path, renamed=True)
        assert_preserved(baseline, after, aliases)
        applied = list(tracked.mutations)
        reports['aplicar'] = report['archivo_resultado']
        write(path.parent / 'aplicacion.json', dict(hashes=current_hashes,
            operaciones_escritura_gdb=applied, estado_final=after))
        print('Renombrado y aliases verificados; esquema y filas preservados.', flush=True)

        tracked.mutations.clear()
        _, report = rename.run(str(path), apply=True, reports=path.parent,
                               arcpy_module=tracked, names=list(SELECTED))
        assert report['estado'] == 'NOMBRES_VERIFICADOS'
        assert not tracked.mutations and state(path, renamed=True) == after
        reports['repetir'] = report['archivo_resultado']
        print('Repeticion nativa: cero escrituras.', flush=True)

        import reparar_texto_largo as repair
        _, report = repair.run(str(path), apply=True, reports=path.parent, arcpy_module=tracked)
        assert report['estado'] == 'TEXTO_LARGO_VERIFICADO'
        assert not tracked.mutations
        reports['reparacion_ya_aplicada'] = report['archivo_resultado']

        import actualizar_campos_aprobados as migration
        _, report = migration.run(str(path), apply=True, reports=path.parent,
                                  arcpy_module=tracked, names=list(SELECTED))
        assert report['estado'] == 'CAMPOS_VERIFICADOS'
        assert all(row['accion'] == 'YA_OBJETIVO' for row in report['plan'])
        assert not tracked.mutations and state(path, renamed=True) == after
        reports['lote_general'] = report['archivo_resultado']
        print('Reparacion y lote general reconocen los nombres nuevos sin escribir.', flush=True)

        loader = importlib.machinery.SourceFileLoader('toolbox_nombres_ensayo',
                                                    str(HERE / 'Datos_Proyecto.pyt'))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        toolbox = module.Toolbox()
        assert toolbox.label.endswith('1.6') and len(toolbox.tools) == 5
        name_tool = toolbox.tools[4]()
        parameters = name_tool.getParameterInfo()
        assert parameters and any(p.valueAsText == 'Validar (sin cambios)' for p in parameters)
        assert not tracked.mutations
        assert file_manifest(source) == preparation['archivos_origen']
        assert hashes() == current_hashes, 'El codigo/modelo cambio durante el ensayo.'
        result = dict(version_paquete='1.6', version_modelo=model['version'],
            arcgis=a.GetInstallInfo()['Version'], gdb=str(path), validacion_sde=False,
            clases_ensayadas=list(SELECTED), clases_modelo=len(all_names),
            nombres_validos_en_gdb_local=True, relaciones_nombres_validos=True,
            nombres_rechazados=[], validacion_sin_cambios=True,
            renombrado_nativo_verificado=True, aliases_verificados=True,
            preservacion_campos_y_metadatos=True, clases_permanecen_vacias=True,
            repeticion_sin_cambios=True, fuente_original_sin_cambios=True,
            reparacion_reconoce_nombre_nuevo=True, lote_general_reconoce_nombres_nuevos=True,
            toolbox_cargada_y_parametros_verificados=True, informes=reports,
            operaciones_escritura_gdb=applied,
            alcance='Copia aislada de GDB de archivos: tres clases, un renombrado y aliases; '
                'validacion de los76 nombres y relaciones en GDB local. No conecta a SQL Server '
                'y no certifica el renombrado en SDE. Sin repetir prueba de texto largo1.5.1.',
            **current_hashes)
        write(RESULT, result)
        print(json.dumps(result, ensure_ascii=True, indent=2), flush=True)
    except Exception as exc:
        write(path.parent / 'error_ensayo.json', dict(error=str(exc),
            informes=reports, operaciones_escritura_gdb=tracked.mutations))
        raise


if __name__ == '__main__':
    main()
