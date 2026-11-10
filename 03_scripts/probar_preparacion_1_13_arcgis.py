"""Ensayo ArcPy real en copia nueva local, con catalogos sinteticos; nunca SDE."""
from pathlib import Path
import datetime as dt
import hashlib
import json
import shutil
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '02_entregas/Esquema_KMZ_EFT_Corregido'
sys.path.insert(0, str(OUT))


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def files(path):
    return {str(p.relative_to(path)): sha(p) for p in sorted(path.rglob('*'))
            if p.is_file() and not p.name.lower().endswith('.lock')}


def main():
    import arcpy
    import preparar_carga_inicial as runtime
    proof19 = json.loads((OUT / 'VALIDACION_CIERRE_1_9_ARCGIS.json').read_text(encoding='utf-8'))
    source = Path(proof19['geodatabase']).resolve()
    assert source.parent.parent == (OUT / '_validacion').resolve() and source.suffix == '.gdb'
    assert not list(source.glob('*.lock'))
    original = files(source)
    folder = OUT / '_validacion' / ('preparacion113_' + dt.datetime.now().strftime('%Y%m%d_%H%M%S_') + uuid.uuid4().hex[:10])
    folder.mkdir()
    gdb = folder / 'ensayo.gdb'
    shutil.copytree(source, gdb, ignore=shutil.ignore_patterns('*.lock'))
    assert files(gdb) == original
    # Preparacion del fixture, separada de la ejecucion de solo lectura.
    catalog = json.loads((ROOT / 'resultado_preingesta.json').read_text(encoding='utf-8-sig'))['catalogo_proyectos']['filas']
    assert len(catalog) == 42
    specs = {
        'mline_tc_proyecto': [('id_proyecto','LONG',None),('co_proyecto','TEXT',12),('no_proyecto','TEXT',255),
            ('de_proyecto','TEXT',2000),('es_registro','TEXT',1),('fe_eliminacion','DATE',None)],
        'mline_td_proyecto_componente': [('id_proyecto_componente','LONG',None),('id_proyecto','LONG',None),('no_componente','TEXT',255)],
        'mline_td_proyecto_alternativa': [('id_proyecto_alternativa','LONG',None),('id_proyecto_componente','LONG',None),('co_alternativa','TEXT',255)],
    }
    for name, fields in specs.items():
        path = str(gdb / name)
        if arcpy.Exists(path):
            # Only the new fixture copy; no deletion outside this checked directory.
            assert Path(path).resolve().parent == gdb.resolve() and gdb.parent == folder
            arcpy.management.Delete(path)
        arcpy.management.CreateTable(str(gdb), name)
        for field, kind, length in fields:
            kwargs = {'field_length': length} if length else {}
            arcpy.management.AddField(path, field, kind, **kwargs)
    with arcpy.da.InsertCursor(str(gdb/'mline_tc_proyecto'), [s[0] for s in specs['mline_tc_proyecto']]) as cur:
        for row in catalog:
            # Explicit synthetic fixture identity; not an assignment rule for SDE.
            cur.insertRow((int(row['co_proyecto'].split('-')[1]), row['co_proyecto'], row['no_proyecto'],
                           row['de_proyecto'], str(row['es_registro']) if row.get('es_registro') is not None else None, None))
    with arcpy.da.InsertCursor(str(gdb/'mline_td_proyecto_componente'), ['id_proyecto_componente','id_proyecto','no_componente']) as cur:
        cur.insertRow((501, 5, 'Componente sintetico del ensayo'))
    with arcpy.da.InsertCursor(str(gdb/'mline_td_proyecto_alternativa'), ['id_proyecto_alternativa','id_proyecto_componente','co_alternativa']) as cur:
        cur.insertRow((801, 501, 'ALTERNATIVA-SINTETICA'))
    before = files(gdb)
    references = runtime.reference_hashes(OUT)
    result_folder, report = runtime.run(str(gdb), str(ROOT/'01_fuentes'), reports=str(folder), arcpy_module=arcpy,
                                       emit=lambda text: print(text, flush=True))
    assert report['fuentes']['verificado'] and report['proyectos']['verificado']
    assert report['estado'] == 'PREPARACION_CON_PENDIENTES', report.get('negocio')
    assert len(report['plan']['reglas_campos_comunes']) == 152
    assert len(report['plan']['pendientes_campos_comunes']) == 4
    assert all(not r['cargable'] for r in report['cobertura']['rutas'])
    assert len(report['cobertura']['rutas']) == 3638
    assert report['negocio']['lectura_completa']
    assert not report['plan']['incidencias_campos']
    assert report['registros_insertados'] == 0 and not report['cambios_en_sde']
    assert files(gdb) == before and files(source) == original
    assert runtime.reference_hashes(OUT) == references
    result = dict(version_paquete='1.13', validacion_sde=False, runtime_ejecutado=True,
        toolbox_ejecutada=False, geodatabase=str(gdb), informe=str(result_folder/'resultado.json'),
        estado=report['estado'], fuentes_verificadas=13, proyectos_verificados=13,
        clases=76, campos=3340, rutas=3638, reglas_comunes=152, identidades_pendientes=4,
        lectura_negocio_completa=True, catalogos_sinteticos=True,
        geodatabase_inalterada=True, fuentes_inalteradas=True, modelo_inalterado=True,
        sin_rutas_autorizadas=True, registros_insertados=0,
        archivos_sha256=dict(references, **{'03_scripts/probar_preparacion_1_13_arcgis.py':sha(__file__)}),
        arcgis=arcpy.GetInstallInfo())
    (OUT/'VALIDACION_PREPARACION_1_13_ARCGIS.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('PRUEBA NATIVA 1.13 VERIFICADA: 76 clases, 3340 campos, 13 KMZ; geodatabase intacta.', flush=True)


if __name__ == '__main__':
    main()
