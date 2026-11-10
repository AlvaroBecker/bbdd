"""Ensayo nativo de reparacion 1.5.1 en copia aislada de una GDB de archivos.

Nunca conecta a SDE. Cada etapa se ejecuta en un proceso independiente para
evitar que caches de ArcGIS oculten cambios de esquema. El origen es solo lectura.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.machinery
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import uuid

import arcpy as a
import actualizar_campos_aprobados as migration

HERE = Path(__file__).resolve().parent
ROOT = HERE / '_validacion'
CLASS = 'predios_inscritos_en_sunarp_recorte'
FIELD = 'cargas_y_gravamenes'
TEMP = 'tmp_cargas_y_gravamenes_151'
BACKUP = 'bak_cargas_y_gravamenes_151'
CLASSES = ('estructuras', 'accesos', 'limite_departamento_recorte', CLASS)
RESULT = HERE / 'VALIDACION_REPARACION_1_5_1_ARCGIS.json'


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def args_for(path):
    return SimpleNamespace(workspace=str(path), database='ArcGisAWS', owner='gis', aplicar=False)


def checked(path):
    path = Path(path).resolve()
    assert path.suffix == '.gdb' and path.is_relative_to(ROOT.resolve())
    assert path.parent.name.startswith('reparacion151_')
    return path


def fc(path, name=CLASS):
    return str(path / 'Datos_Proyecto' / name)


def snapshots(path):
    return {name: migration.snapshot(a, fc(path, name)) for name in CLASSES}


def metadata(path):
    result = {}
    for name in CLASSES:
        table = fc(path, name)
        d = a.Describe(table)
        result[name] = dict(registros=int(a.management.GetCount(table).getOutput(0)),
            geometria=d.shapeType, referencia_espacial=d.spatialReference.factoryCode,
            has_z=d.hasZ, has_m=d.hasM, globalid=d.hasGlobalID,
            editor_tracking=d.editorTrackingEnabled, utc=d.isTimeInUTC,
            creator=d.creatorFieldName, created=d.createdAtFieldName,
            editor=d.editorFieldName, edited=d.editedAtFieldName,
            indices=migration.indexes_snapshot(a, table, ()))
    return result


def source_snapshot(path):
    objects = migration.runner.engine.find_objects(a, args_for(path))
    _, keys = migration.runner.engine.parent_keys(a, objects['mline_tc_proyecto'], 'co_proyecto')
    return dict(objetos=sorted(objects), campos=snapshots(path), metadatos=metadata(path),
                proyectos=sorted(keys))


def verify_source(path):
    preparation = read(path.parent / 'preparacion.json')
    source = Path(preparation['origen_solo_lectura']).resolve()
    assert source != path and source.parent.name.startswith('general15_')
    assert source_snapshot(source) == preparation['fuente_original'], 'Cambio en la GDB fuente.'


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
        return getattr(a, name)


def hashes():
    return dict(modelo_sha256=digest(HERE / 'esquema.json'),
        aprobacion_sha256=digest(HERE / 'campos_aprobados_1_5.json'),
        modulo_sha256=digest(HERE / 'reparar_texto_largo.py'),
        modulo_general_sha256=digest(HERE / 'actualizar_campos_aprobados.py'),
        verificador_sql_sha256=digest(HERE / 'validacion_texto_sqlserver.py'))


def preserved(baseline, current):
    for name in CLASSES:
        migration.require_preserved(baseline['campos'][name], current[name],
                                    [FIELD] if name == CLASS else [])
    assert TEMP not in current[CLASS] and BACKUP not in current[CLASS]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace')
    parser.add_argument('--etapa', required=True,
        choices=['preparar', 'restablecer', 'validar', 'aplicar', 'repetir', 'roundtrip', 'reanudar', 'ui'])
    values = parser.parse_args()
    if values.etapa == 'preparar':
        assert not values.workspace
        sources = sorted(ROOT.glob('general15_*/ensayo.gdb'))
        assert sources, 'No existe fixture general15.'
        source = sources[-1].resolve()
        assert source.is_relative_to(ROOT.resolve()) and source.suffix == '.gdb'
        original = source_snapshot(source)
        assert all(item['registros'] == 0 for item in original['metadatos'].values())
        assert original['campos'][CLASS][FIELD]['longitud'] >= 10000
        folder = ROOT / ('reparacion151_' + dt.datetime.now().strftime('%Y%m%d_%H%M%S')
                         + '_' + uuid.uuid4().hex[:8])
        folder.mkdir(parents=True)
        path = checked(folder / 'ensayo.gdb')
        assert not a.Exists(str(path)) and path != source
        a.management.Copy(str(source), str(path))
        assert source_snapshot(source) == original
        assert snapshots(path) == original['campos']
        assert metadata(path) == original['metadatos']
        write(folder / 'preparacion.json', dict(origen_solo_lectura=str(source),
            destino=str(path), fuente_original=original, fuente_sin_cambios=True,
            metodo='ArcGIS Copy de GDB sintetica; nunca SDE'))
        print(str(path), flush=True)
        return

    assert values.workspace
    path = checked(values.workspace)
    assert a.Exists(str(path))
    verify_source(path)
    if values.etapa == 'restablecer':
        original = read(path.parent / 'preparacion.json')['fuente_original']
        assert all(item['registros'] == 0 for item in metadata(path).values())
        assert snapshots(path) == original['campos']
        a.management.AlterField(fc(path), FIELD, field_type='TEXT', field_length=4000)
        current = snapshots(path)
        assert current[CLASS][FIELD]['tipo'] == 'String'
        assert current[CLASS][FIELD]['longitud'] == 4000
        preserved(original, current)
        assert metadata(path) == original['metadatos']
        verify_source(path)
        write(path.parent / 'fixture_anterior.json', dict(campos=current,
              metadatos=metadata(path), fuente_sin_cambios=True))
        print('Fixture vacio TEXT(4000) preparado en copia aislada.', flush=True)
        return

    baseline = read(path.parent / 'fixture_anterior.json')
    before, meta_before = snapshots(path), metadata(path)
    tracked = TrackedArcPy()
    current_hashes = hashes()
    try:
        if values.etapa in {'validar', 'aplicar', 'repetir'}:
            import reparar_texto_largo as repair
            if values.etapa != 'validar':
                assert read(path.parent / 'validar.json')['hashes'] == current_hashes, (
                    'El codigo/modelo cambio desde validar; vuelva a validar antes de aplicar.')
            _, report = repair.run(str(path), apply=values.etapa != 'validar',
                reports=path.parent, arcpy_module=tracked)
            after, meta_after = snapshots(path), metadata(path)
            preserved(baseline, after)
            assert meta_after == meta_before == baseline['metadatos']
            verify_source(path)
            if values.etapa == 'validar':
                assert report['estado'] == 'VALIDACION_OK_SIN_CAMBIOS'
                assert not tracked.mutations and before == after
                assert after[CLASS][FIELD]['longitud'] == 4000
            else:
                assert report['estado'] == 'TEXTO_LARGO_VERIFICADO'
                assert after[CLASS][FIELD]['tipo'] == 'String'
                assert after[CLASS][FIELD]['longitud'] >= 10000
                if values.etapa == 'aplicar':
                    calls = [item['herramienta'] for item in tracked.mutations]
                    assert calls.count('AddField') == 1
                    assert calls.count('AlterField') == 2
                    assert calls.count('DeleteField') == 1
                    assert set(calls) == {'AddField', 'AlterField', 'DeleteField'}
                else:
                    assert not tracked.mutations and before == after
            write(path.parent / (values.etapa + '.json'), dict(etapa=values.etapa,
                estado=report['estado'], informe=report['archivo_resultado'],
                operaciones_escritura_gdb=tracked.mutations, campos=after,
                metadatos=meta_after, hashes=current_hashes, fuente_sin_cambios=True))
            print(values.etapa + ': verificada', flush=True)
            return

        assert before[CLASS][FIELD]['longitud'] >= 10000
        if values.etapa == 'reanudar':
            _, report = migration.run(str(path), apply=True, reports=path.parent,
                arcpy_module=tracked, names=['accesos', 'limite_departamento_recorte', CLASS])
            assert report['estado'] == 'CAMPOS_VERIFICADOS'
            assert len(report['plan']) == 4
            assert all(item['accion'] == 'YA_OBJETIVO' for item in report['plan'])
            assert not tracked.mutations and not report['completadas']
            assert before == snapshots(path) and meta_before == metadata(path)
            verify_source(path)
            write(path.parent / 'reanudar.json', dict(informe=report['archivo_resultado'],
                estado=report['estado'], lote_general_reanudado_sin_cambios=True,
                operaciones_escritura_gdb=[], hashes=current_hashes))
            print('Lote general: reanudacion de tres clases sin cambios verificada.', flush=True)
            return
        if values.etapa == 'roundtrip':
            table = str(path / 'ensayo_roundtrip_texto151')
            assert not a.Exists(table), 'La tabla de roundtrip ya existe; no se sobrescribe.'
            text = ('\u00e1\u00e9\u00ed\u00f3\u00fa\u00f1 Acentos y cargas registrales. ' * 300)[:8084]
            assert len(text) == 8084 and len(text.encode('utf-16-le')) // 2 == 8084
            a.management.CreateTable(str(path), 'ensayo_roundtrip_texto151')
            a.management.AddField(table, 'texto_largo', 'TEXT', field_length=10000)
            with a.da.InsertCursor(table, ['texto_largo']) as cursor:
                cursor.insertRow((text,))
            with a.da.SearchCursor(table, ['texto_largo']) as cursor:
                rows = list(cursor)
            assert rows == [(text,)]
            assert before == snapshots(path) and meta_before == metadata(path)
            verify_source(path)
            write(path.parent / 'roundtrip.json', dict(tabla=table, caracteres=8084,
                unidades_utf16=8084, sha256_utf8=hashlib.sha256(text.encode()).hexdigest(),
                texto_identico=True, predios_permanece_vacio=True, fuente_sin_cambios=True))
            print('Roundtrip de 8084 caracteres con tildes verificado en tabla separada.', flush=True)
            return

        assert values.etapa == 'ui'
        loader = importlib.machinery.SourceFileLoader('toolbox_reparacion_ensayo',
                                                    str(HERE / 'Datos_Proyecto.pyt'))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        assert module.Toolbox().label.endswith('1.5.1')
        assert module.Toolbox().tools[3] is module.RepararTextoLargo
        tool = module.RepararTextoLargo()
        assert tool.label == 'Reparar texto largo de predios'
        params = tool.getParameterInfo()
        by_name = {parameter.name: parameter for parameter in params}
        assert by_name['mode'].valueAsText == 'Validar (sin cambios)'
        by_name['workspace'].value = str(path)
        by_name['reports'].value = str(path.parent)
        module.arcpy = tracked
        tool.execute(params, None)
        report_path = by_name['report'].valueAsText
        report = read(Path(report_path))
        assert report['estado'] == 'VALIDACION_OK_SIN_CAMBIOS'
        assert not tracked.mutations
        assert before == snapshots(path) and meta_before == metadata(path)
        verify_source(path)
        stages = {stage: read(path.parent / (stage + '.json'))
                  for stage in ('validar', 'aplicar', 'repetir')}
        assert all(stage['hashes'] == current_hashes for stage in stages.values())
        roundtrip = read(path.parent / 'roundtrip.json')
        resume = read(path.parent / 'reanudar.json')
        assert resume['hashes'] == current_hashes
        result = dict(version_paquete='1.5.1', version_modelo=9,
            arcgis=a.GetInstallInfo()['Version'], gdb=str(path), validacion_sde=False,
            clase_reparada=CLASS, campo_reparado=FIELD,
            validacion_sin_cambios=True, reparacion_4000_a_10000=True,
            addfield_nativo_verificado=True, dos_renombres_nativos_verificados=True,
            retirada_respaldo_vacio_verificada=True, temporales_ausentes=True,
            preservacion_restantes=True, clases_permanecen_vacias=True,
            metadatos_globalid_auditoria_geometria_indices_sin_cambios=True,
            fuente_original_sin_cambios=True, repeticion_sin_cambios=True,
            toolbox_cargada_y_validada=True, toolbox_validacion_sin_cambios=True,
            roundtrip_8084_caracteres_con_tildes=True, roundtrip=roundtrip,
            lote_general_reanudado_sin_cambios=True,
            informe_reanudacion=resume['informe'],
            esquema_sha256=current_hashes['modelo_sha256'],
            aprobacion_sha256=current_hashes['aprobacion_sha256'],
            modulo_sha256=current_hashes['modulo_sha256'],
            modulo_general_sha256=current_hashes['modulo_general_sha256'],
            verificador_sql_sha256=current_hashes['verificador_sql_sha256'],
            toolbox_sha256=digest(HERE / 'Datos_Proyecto.pyt'),
            script_sha256=digest(Path(__file__)),
            informes={stage: item['informe'] for stage, item in stages.items()},
            informe_toolbox=report_path,
            operaciones_escritura_gdb=stages['aplicar']['operaciones_escritura_gdb'],
            alcance='Copia aislada de GDB de archivos, una reparacion de campo vacio; '
                'no conecta a SQL Server y no demuestra NVARCHAR(MAX) en SDE. '
                'Roundtrip de 8084 caracteres en tabla separada, no en predios.')
        write(RESULT, result)
        print(json.dumps(result, ensure_ascii=True, indent=2), flush=True)
    except Exception as exc:
        write(path.parent / ('error_' + values.etapa + '.json'), dict(etapa=values.etapa,
            error=str(exc), operaciones_escritura_gdb=tracked.mutations))
        raise


if __name__ == '__main__':
    main()
