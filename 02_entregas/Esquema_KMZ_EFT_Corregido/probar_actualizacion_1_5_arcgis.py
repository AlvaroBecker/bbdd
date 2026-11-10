"""Ensayo nativo 1.5 en tres clases de una GDB local nueva y aislada.

Preparar copia una GDB sintetica 1.4 sin modificarla. Crear usa el modelo
anterior; validar/aplicar/repetir usan el modelo 1.5 y procesos separados.
No conecta a SDE ni demuestra el almacenamiento nativo de SQL Server.
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
SOURCE = HERE / '_validacion/tipos14_20261105_120813_1bc415c4/ensayo.gdb'
OLD_MODEL = HERE / '_validacion/esquema_pre_1_5.json'
CLASSES = ('accesos', 'limite_departamento_recorte',
           'predios_inscritos_en_sunarp_recorte')
TARGETS = {
    ('accesos', 'longitud'): ('Double', None),
    ('limite_departamento_recorte', 'poblacion'): ('Integer', None),
    ('predios_inscritos_en_sunarp_recorte', 'src_area_ha'): ('Double', None),
    ('predios_inscritos_en_sunarp_recorte', 'cargas_y_gravamenes'): ('String', 10000),
}


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checked(path):
    path = Path(path).resolve()
    assert path.suffix == '.gdb' and path.is_relative_to(HERE / '_validacion')
    assert path.parent.name.startswith('general15_') and path != SOURCE.resolve()
    return path


def args_for(path):
    return SimpleNamespace(workspace=str(path), database='ArcGisAWS', owner='gis', aplicar=False)


def field_snapshot(path, cls):
    return migration.snapshot(a, str(path / 'Datos_Proyecto' / cls))


def source_snapshot():
    """Solo lecturas semanticas de la GDB fuente y su estructuras 1.4."""
    args = args_for(SOURCE)
    objects = migration.runner.engine.find_objects(a, args)
    fields = field_snapshot(SOURCE, 'estructuras')
    assert all(fields[name]['tipo'] == 'Double'
               for name in ('este', 'norte', 'east', 'north', 'x', 'y', 'vano'))
    parent = objects['mline_tc_proyecto']
    _, keys = migration.runner.engine.parent_keys(a, parent, 'co_proyecto')
    return dict(objetos=sorted(objects), estructuras=fields, proyectos=sorted(keys),
                registros_estructuras=int(a.management.GetCount(
                    str(SOURCE / 'Datos_Proyecto/estructuras')).getOutput(0)))


def verify_source(path):
    initial = read(path.parent / 'preparacion.json')['fuente_original']
    assert source_snapshot() == initial, 'La fuente sintetica 1.4 cambio.'
    assert field_snapshot(path, 'estructuras') == initial['estructuras'], (
        'estructuras 1.4 cambio en la copia del ensayo.')
    return True


def snapshots(path):
    return {name: field_snapshot(path, name) for name in CLASSES}


def metadata_snapshot(path):
    result = {}
    for name in CLASSES:
        fc = str(path / 'Datos_Proyecto' / name)
        d = a.Describe(fc)
        result[name] = dict(
            registros=int(a.management.GetCount(fc).getOutput(0)),
            geometria=d.shapeType, referencia_espacial=d.spatialReference.factoryCode,
            has_z=d.hasZ, has_m=d.hasM, globalid=d.hasGlobalID,
            editor_tracking=d.editorTrackingEnabled, utc=d.isTimeInUTC,
            creator=d.creatorFieldName, created=d.createdAtFieldName,
            editor=d.editorFieldName, edited=d.editedAtFieldName,
            indices=migration.indexes_snapshot(a, fc, ()),
        )
    return result


class TrackedManagement:
    """Registra herramientas GP de escritura; deja GetCount como solo lectura."""
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


def assert_preserved(initial, current):
    for name in CLASSES:
        allowed = [field for cls, field in TARGETS if cls == name]
        migration.require_preserved(initial[name], current[name], allowed)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace')
    parser.add_argument('--etapa', choices=['preparar', 'crear', 'validar', 'aplicar', 'repetir', 'ui'],
                        default='preparar')
    parser.add_argument('--clase', choices=CLASSES)
    values = parser.parse_args()
    if values.etapa == 'preparar':
        assert not values.workspace and not values.clase
        folder = HERE / '_validacion' / ('general15_' + dt.datetime.now().strftime('%Y%m%d_%H%M%S')
                                        + '_' + uuid.uuid4().hex[:8])
        folder.mkdir(parents=True)
        path = checked(folder / 'ensayo.gdb')
        before = source_snapshot()
        assert not a.Exists(str(path))
        a.management.Copy(str(SOURCE), str(path))
        assert source_snapshot() == before
        assert field_snapshot(path, 'estructuras') == before['estructuras']
        write(folder / 'preparacion.json', dict(origen_solo_lectura=str(SOURCE),
            destino=str(path), fuente_original=before, fuente_sin_cambios=True,
            metodo='ArcGIS Copy de GDB sintetica completa',
            modelo_anterior_sha256=digest(OLD_MODEL)))
        print(str(path), flush=True)
        return

    assert values.workspace
    path = checked(values.workspace)
    assert a.Exists(str(path))
    verify_source(path)
    if values.etapa == 'crear':
        assert read(OLD_MODEL)['version'] == 8
        names = [values.clase] if values.clase else list(CLASSES)
        model = migration.runner.scoped_model(read(OLD_MODEL), names)
        args = args_for(path)
        inventory, domains = migration.runner.engine.inspect(a, args, model, [])
        # Preparar dominios antes del runner evita mezclar su creacion y la
        # verificacion de nuevas clases en una cache de workspace de Pro.
        migration.runner.engine.create(a, args, model, [], inventory, domains)
        _, report = migration.runner.run(str(path), names=names, apply=True,
            model_path=OLD_MODEL, reports=path.parent, arcpy_module=a)
        assert report['estado'] == 'CREACION_VERIFICADA'
        verify_source(path)
        write(path.parent / ('crear_' + (values.clase or 'tres_clases') + '.json'),
              dict(estado=report['estado'], informe=report['archivo_resultado'],
                   fuente_sin_cambios=True, clases=names))
        if all(a.Exists(str(path / 'Datos_Proyecto' / name)) for name in CLASSES):
            fields = snapshots(path)
            for cls, field in TARGETS:
                assert fields[cls][field]['tipo'] == 'String'
                assert fields[cls][field]['longitud'] == 4000
            write(path.parent / 'fixture_anterior.json', dict(campos=fields,
                  metadatos=metadata_snapshot(path), fuente_sin_cambios=True))
        print('crear: verificada ' + ', '.join(names), flush=True)
        return

    assert not values.clase
    model_path, config_path = HERE / 'esquema.json', HERE / 'campos_aprobados_1_5.json'
    assert read(model_path)['version'] == 9
    assert len(read(config_path)['cambios']) == 99
    hashes = dict(modelo_sha256=digest(model_path), aprobacion_sha256=digest(config_path),
                  modulo_sha256=digest(HERE / 'actualizar_campos_aprobados.py'))
    baseline = read(path.parent / 'fixture_anterior.json')
    before, meta_before = snapshots(path), metadata_snapshot(path)
    if values.etapa == 'ui':
        loader = importlib.machinery.SourceFileLoader('toolbox_campos_ensayo', str(HERE / 'Datos_Proyecto.pyt'))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        assert module.Toolbox().label.endswith('1.5')
        assert module.ActualizarCamposAprobados in module.Toolbox().tools
        tool = module.ActualizarCamposAprobados()
        assert tool.label == 'Actualizar campos aprobados de Datos_Proyecto'
        params = tool.getParameterInfo()
        assert params[1].valueAsText == 'Validar (sin cambios)'
        assert set(CLASSES) <= set(params[2].filter.list)
        params[0].value = str(path)
        params[2].value = ';'.join(CLASSES)
        params[5].value = str(path.parent)
        tracked = TrackedArcPy()
        module.arcpy = tracked
        tool.execute(params, None)
        report = read(Path(params[6].valueAsText))
        assert report['estado'] == 'VALIDACION_OK_SIN_CAMBIOS'
        assert report['completadas'] == [] and not tracked.mutations
        assert before == snapshots(path) and meta_before == metadata_snapshot(path)
        assert len(report['clases']) == 3 and len(report['plan']) == 4
        verify_source(path)
        write(path.parent / 'ui.json', dict(informe=params[6].valueAsText,
            validacion_sin_escritura=True, operaciones_escritura_gdb=[],
            herramienta=tool.label, label=module.Toolbox().label, clases=list(CLASSES)))
        result_path = HERE / 'VALIDACION_ACTUALIZACION_1_5_ARCGIS.json'
        result = read(result_path)
        assert result['esquema_sha256'] == hashes['modelo_sha256']
        assert result['modulo_sha256'] == hashes['modulo_sha256']
        result.update(toolbox_cargada_y_validada=True,
                      toolbox_validar_tres_clases_sin_escritura=True,
                      informe_toolbox=params[6].valueAsText)
        write(result_path, result)
        print('Toolbox1.5: tercera herramienta, parametros y Validar tres clases sin escritura verificados.', flush=True)
        return
    if values.etapa != 'validar':
        assert read(path.parent / 'validar.json')['hashes'] == hashes, (
            'El modulo, modelo o aprobacion cambio desde validar; vuelva a validar.')
    tracked = TrackedArcPy()
    try:
        _, report = migration.run(str(path), apply=values.etapa != 'validar',
            reports=path.parent, arcpy_module=tracked, names=list(CLASSES))
        after, meta_after = snapshots(path), metadata_snapshot(path)
        assert meta_before == meta_after == baseline['metadatos']
        assert_preserved(baseline['campos'], after)
        verify_source(path)
        if values.etapa == 'validar':
            assert report['estado'] == 'VALIDACION_OK_SIN_CAMBIOS'
            assert not report['completadas'] and before == after
            assert not tracked.mutations
            assert len(report['plan']) == 4
            assert all(row['accion'] != 'YA_OBJETIVO' for row in report['plan'])
        else:
            assert report['estado'] == 'CAMPOS_VERIFICADOS'
            for (cls, field), (kind, length) in TARGETS.items():
                assert after[cls][field]['tipo'] == kind
                if length:
                    assert after[cls][field]['longitud'] == length
            if values.etapa == 'aplicar':
                assert len(report['completadas']) == 4
                assert len(tracked.mutations) == 4
                assert all(item['herramienta'] == 'AlterField' for item in tracked.mutations)
            else:
                assert not report['completadas'] and before == after
                assert not tracked.mutations
                assert all(row['accion'] == 'YA_OBJETIVO' for row in report['plan'])
        write(path.parent / (values.etapa + '.json'), dict(etapa=values.etapa,
            informe=report['archivo_resultado'], estado=report['estado'],
            completadas=report['completadas'], operaciones_escritura_gdb=tracked.mutations,
            campos=after, metadatos=meta_after, hashes=hashes, fuente_sin_cambios=True))
        if values.etapa == 'repetir':
            stages = {name: read(path.parent / (name + '.json'))
                      for name in ('validar', 'aplicar', 'repetir')}
            result = dict(version_paquete='1.5', version_modelo=9,
                arcgis=a.GetInstallInfo()['Version'], clases_ensayadas=list(CLASSES),
                clases_ensayadas_total=3, operaciones_aprobadas_ensayadas=4,
                validacion_sin_escritura=True, dos_double_verificados=True,
                un_long_verificado=True, texto_4000_a_10000_verificado=True,
                validacion_sin_cambios=True, double_verificado=True,
                long_verificado=True, texto_largo_verificado=True,
                cuatro_alterfield_nativos=True, demas_campos_sin_cambios=True,
                preservacion_restantes=True,
                metadatos_globalid_auditoria_geometria_indices_sin_cambios=True,
                clases_permanecen_vacias=True, repeticion_sin_escritura=True,
                repeticion_sin_cambios=True,
                fuente_1_4_sin_cambios=True, estructuras_1_4_copia_sin_cambios=True,
                validacion_sde=False, gdb=str(path), esquema_sha256=hashes['modelo_sha256'],
                aprobacion_sha256=hashes['aprobacion_sha256'],
                modulo_sha256=hashes['modulo_sha256'],
                informes={name: stage['informe'] for name, stage in stages.items()},
                alcance='Tres clases en copia aislada de una geodatabase de archivos. '
                    'Cuatro de las99operaciones aprobadas; no ensaya las otras95operaciones '
                    'ni conecta a SQL Server/SDE. Etapas en procesos separados.')
            write(HERE / 'VALIDACION_ACTUALIZACION_1_5_ARCGIS.json', result)
            print(json.dumps(result, ensure_ascii=True, indent=2), flush=True)
        else:
            print(values.etapa + ': verificada', flush=True)
    except Exception as exc:
        write(path.parent / ('error_' + values.etapa + '.json'), dict(
            etapa=values.etapa, error=str(exc), operaciones_escritura_gdb=tracked.mutations))
        raise


if __name__ == '__main__':
    main()
