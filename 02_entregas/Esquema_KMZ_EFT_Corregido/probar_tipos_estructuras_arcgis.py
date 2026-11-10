"""Ensayo 1.4 local en copia aislada; etapas en procesos separados."""
import argparse
import datetime as dt
import hashlib
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import uuid

import arcpy as a
import ajustar_tipos_estructuras as migration

HERE = Path(__file__).resolve().parent
SOURCE = HERE / '_validacion/norm13_20261105_000852_426b10ef/ensayo.gdb'


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def checked(path):
    path = Path(path).resolve()
    assert path.suffix == '.gdb' and path.is_relative_to(HERE / '_validacion')
    assert path.parent.name.startswith('tipos14_') and path != SOURCE.resolve()
    return path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--workspace')
    p.add_argument('--etapa', choices=['preparar', 'validar', 'aplicar', 'repetir', 'ui'], default='preparar')
    v = p.parse_args()
    if v.etapa == 'preparar':
        assert not v.workspace
        folder = HERE / '_validacion' / ('tipos14_' + dt.datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:8])
        folder.mkdir(parents=True)
        path = checked(folder / 'ensayo.gdb')
        source_fc = str(SOURCE / 'Datos_Proyecto/estructuras')
        before = migration.snapshot(a, source_fc)
        assert all(before[n]['tipo'] == 'String' for n in migration.FIELDS)
        assert not a.Exists(str(path))
        try:
            a.management.Copy(str(SOURCE), str(path))
            after = migration.snapshot(a, source_fc)
            assert before == after
            fixture = migration.snapshot(a, str(path / 'Datos_Proyecto/estructuras'))
            assert before == fixture
            write(folder / 'preparacion.json', dict(origen_solo_lectura=str(SOURCE),destino=str(path),
                  fuente_campos_sin_cambios=True,tipos_originales=before,metodo='ArcGIS Copy de GDB completa'))
            print(str(path), flush=True)
        except Exception as exc:
            write(folder / 'error_preparacion.json', dict(error=str(exc),origen=str(SOURCE),destino=str(path)))
            raise
        return
    assert v.workspace
    path = checked(v.workspace)
    fc = str(path / 'Datos_Proyecto/estructuras')
    before = migration.snapshot(a, fc)
    initial = json.loads((path.parent / 'preparacion.json').read_text(encoding='utf-8'))['tipos_originales']
    cls = next(c for c in json.loads((HERE / 'esquema.json').read_text(encoding='utf-8'))['clases'] if c['nombre'] == 'estructuras')
    own_text = {f['nombre'] for f in cls['campos'] if f.get('campo_fuente') and f['nombre'] not in migration.FIELDS}
    assert len(own_text) == 14
    if v.etapa == 'ui':
        loader = importlib.machinery.SourceFileLoader('toolbox_tipos_ensayo',str(HERE/'Datos_Proyecto.pyt'))
        spec = importlib.util.spec_from_loader(loader.name,loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        assert module.Toolbox().label.endswith('1.4')
        assert module.AjustarTiposEstructuras in module.Toolbox().tools
        tool = module.AjustarTiposEstructuras()
        params = tool.getParameterInfo()
        assert params[1].valueAsText == 'Validar (sin cambios)'
        params[0].value = str(path)
        params[4].value = str(path.parent)
        tool.execute(params,None)
        result = json.loads(Path(params[5].valueAsText).read_text(encoding='utf-8'))
        assert result['estado'] == 'VALIDACION_OK_SIN_CAMBIOS'
        assert result['completadas'] == [] and before == migration.snapshot(a,fc)
        write(path.parent/'ui.json',dict(informe=params[5].valueAsText,validacion_sin_cambios=True,
              herramienta='Actualizar tipos de estructuras',label=module.Toolbox().label))
        report_path = HERE/'VALIDACION_TIPOS_ESTRUCTURAS_ARCGIS.json'
        report = json.loads(report_path.read_text(encoding='utf-8'))
        report.update(validacion_sin_cambios=True,preservacion_restantes=True,
                      toolbox_cargada_y_validada=True,informe_toolbox=params[5].valueAsText)
        write(report_path,report)
        print('Toolbox 1.4: carga, parametros, salida JSON y validacion sin cambios verificados.',flush=True)
        return
    try:
        _, report = migration.run(str(path), apply=v.etapa != 'validar', reports=path.parent, arcpy_module=a)
        after = migration.snapshot(a, fc)
        if v.etapa == 'validar':
            assert report['estado'] == 'VALIDACION_OK_SIN_CAMBIOS'
            assert before == after and all(after[n]['tipo'] == 'String' for n in migration.FIELDS)
        else:
            assert report['estado'] == 'TIPOS_VERIFICADOS'
            assert all(after[n]['tipo'] == 'Double' for n in migration.FIELDS)
            for name, original in initial.items():
                if name not in migration.FIELDS:
                    assert after[name] == original, name
            assert all(after[n]['tipo'] == 'String' and after[n]['longitud'] == 4000 for n in own_text)
            if v.etapa == 'repetir':
                assert report['completadas'] == [] and before == after
        write(path.parent / (v.etapa + '.json'),dict(etapa=v.etapa,informe=report['archivo_resultado'],
              estado=report['estado'],campos_completados=report['completadas'],campos=after))
        if v.etapa == 'repetir':
            stages = {n:json.loads((path.parent / (n + '.json')).read_text(encoding='utf-8')) for n in ['validar','aplicar','repetir']}
            result = dict(version_paquete='1.4',version_modelo=8,arcgis=a.GetInstallInfo()['Version'],
                          validacion_sin_escritura=True,siete_campos_double_verificados=True,
                          catorce_text_sin_cambios=True,resto_campos_sin_cambios=True,
                          repeticion_sin_cambios=True,validacion_sde=False,gdb=str(path),
                          esquema_sha256=hashlib.sha256((HERE/'esquema.json').read_bytes()).hexdigest(),
                          informes={n:s['informe'] for n,s in stages.items()},
                          alcance='Copia aislada de una geodatabase de archivos; no conecta a SQL Server/SDE. Etapas en procesos separados.')
            write(HERE / 'VALIDACION_TIPOS_ESTRUCTURAS_ARCGIS.json', result)
            print(json.dumps(result, ensure_ascii=True, indent=2), flush=True)
        else:
            print(v.etapa + ': verificada', flush=True)
    except Exception as exc:
        write(path.parent / ('error_' + v.etapa + '.json'),dict(etapa=v.etapa,error=str(exc)))
        raise


if __name__ == '__main__':
    main()
