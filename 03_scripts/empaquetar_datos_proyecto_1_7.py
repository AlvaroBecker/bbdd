"""Entrega 1.7: confirma metadatos de texto y agrega verificacion de solo lectura."""
import ast
import copy
import hashlib
import io
import json
import sys
import unittest
import zipfile

from empaquetar_datos_proyecto_1_6_1 import ROOT, OUT, archive, read, sha
from aplicar_confirmacion_textos import load_verified_review, apply_text_confirmation

BASELINE = OUT.parent / 'Datos_Proyecto_Controlado_v1_6_2.zip'


def main():
    baseline_sha = sha(BASELINE)
    with zipfile.ZipFile(BASELINE) as zipped:
        assert zipped.testzip() is None
        previous = json.loads(zipped.read('MANIFIESTO_DATOS_PROYECTO.json'))
        assert previous['version'] == '1.6.2'
        for name, digest in previous['archivos'].items():
            assert hashlib.sha256(zipped.read(name)).hexdigest() == digest, name
        old_model = json.loads(zipped.read('esquema.json'))
        old_config = json.loads(zipped.read('campos_aprobados_1_5.json'))
        old_names = json.loads(zipped.read('nombres_clases_1_6.json'))
        old_toolbox = zipped.read('Datos_Proyecto.pyt').decode('utf-8-sig')
        assert (OUT/'esquema_anterior_1_6_2.json').read_bytes() == zipped.read('esquema.json')
    model, confirmation = apply_text_confirmation(old_model, load_verified_review(ROOT))
    assert read('esquema.json') == model
    assert read('textos_confirmados_1_7.json') == confirmation
    assert read('campos_aprobados_1_5.json') == dict(old_config, version_modelo=11)
    assert read('nombres_clases_1_6.json') == dict(old_names, version_modelo=11,
        modelo_objetivo_sha256=sha(OUT/'esquema.json'))
    # Revertir solo los metadatos autorizados debe recuperar exactamente el modelo anterior.
    physical = copy.deepcopy(model)
    keys = {(row['clase'],row['campo']) for row in confirmation['campos']}
    old_fields = {(cls['nombre'],field['nombre']):field for cls in old_model['clases'] for field in cls['campos']}
    for cls in physical['clases']:
        for field in cls['campos']:
            key = cls['nombre'],field['nombre']
            if key in keys:
                field['origen'] = old_fields[key]['origen']
                del field['tipo_confirmado']
    physical['version'] = 10
    assert physical == old_model and len(keys) == 1356
    allowed_classes = {'Toolbox','RenombrarClases','DiagnosticarRenombrado'}
    old_classes = {node.name:ast.dump(node) for node in ast.parse(old_toolbox).body
        if isinstance(node,ast.ClassDef) and node.name not in allowed_classes}
    new_classes = {node.name:ast.dump(node) for node in ast.parse((OUT/'Datos_Proyecto.pyt').read_text(encoding='utf-8')).body
        if isinstance(node,ast.ClassDef)}
    assert all(new_classes[name] == value for name,value in old_classes.items())
    for name in ('RenombrarClases','DiagnosticarRenombrado'):
        methods = []
        for source in (old_toolbox,(OUT/'Datos_Proyecto.pyt').read_text(encoding='utf-8')):
            cls = next(node for node in ast.parse(source).body if isinstance(node,ast.ClassDef) and node.name == name)
            methods.append(ast.dump(next(node for node in cls.body if isinstance(node,ast.FunctionDef) and node.name == 'execute')))
        assert methods[0] == methods[1], f'Accion historica modificada: {name}'
    allowed_updates = {'Datos_Proyecto.pyt','esquema.json','campos_aprobados_1_5.json',
        'nombres_clases_1_6.json','campos_matriz_a_esquema.csv','campos_por_ruta.csv','revision_tipos.csv',
        'VALIDACION_NORMALIZACION.json','test_diagnostico_integrado.py',
        'GUIA_DATOS_PROYECTO.md','LEEME.md','NORMALIZACION_EFT.md'}
    for name,digest in previous['archivos'].items():
        if name not in allowed_updates and name != 'resultado_origen.json':
            assert sha(OUT/name) == digest, f'Componente ajeno a 1.7 modificado: {name}'
    native = read('VALIDACION_TEXTOS_1_7_ARCGIS.json')
    assert native['estado'] == 'TEXTOS_CONFIRMADOS_VERIFICADOS'
    assert native['toolbox_ejecutada'] and not native['validacion_sde']
    assert native['campos_ensayados'] == 1356 and native['clases_ensayadas_total'] == 70
    assert native['mutaciones_geodatabase_durante_verificacion'] == 0 and native['esquemas_iguales']
    for name,digest in native['archivos_sha256'].items():
        path = ROOT/name if name.startswith('03_scripts/') else OUT/name
        assert sha(path) == digest, name
    sys.path.insert(0,str(OUT))
    stream = io.StringIO()
    suite = unittest.defaultTestLoader.discover(str(OUT),pattern='test_*.py')
    result = unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    assert result.wasSuccessful() and not result.skipped, stream.getvalue()
    tests = sorted(path.name for path in OUT.glob('test_*.py'))
    unit = dict(version_paquete='1.7',pruebas=result.testsRun,fallos=len(result.failures),
        errores=len(result.errors),omitidas=len(result.skipped),validacion_sde=False,
        salida=stream.getvalue(),archivos_sha256={name:sha(OUT/name) for name in tests + [
            'Datos_Proyecto.pyt','verificar_textos_confirmados.py','esquema.json','textos_confirmados_1_7.json']})
    (OUT/'VALIDACION_UNITARIA_1_7.json').write_text(json.dumps(unit,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    review_raw = (ROOT/'02_entregas/Revision_Pendientes_2086/revision_pendientes_2086.json').read_bytes()
    assert hashlib.sha256(review_raw).hexdigest() == confirmation['revision_sha256']
    (OUT/'revision_pendientes_2086_origen.json').write_bytes(review_raw)
    names = (set(previous['archivos']) - {'resultado_origen.json'}) | set(tests) | set('''
        CAMBIOS_1_7.md textos_confirmados_1_7.json verificar_textos_confirmados.py
        esquema_anterior_1_6_2.json revision_pendientes_2086_origen.json
        VALIDACION_UNITARIA_1_7.json VALIDACION_TEXTOS_1_7_ARCGIS.json
        VALIDACION_GENERACION_1_7.json rutas_pendientes.csv'''.split())
    generation = read('VALIDACION_GENERACION_1_7.json')
    assert generation['estado'] == 'OK' and generation['model_sha256'] == sha(OUT/'esquema.json')
    for name,digest in generation['archivos_sha256'].items():
        assert sha(ROOT/name) == digest,name
    manifest = dict(previous,version='1.7',version_modelo=11,herramientas=7,
        pruebas_unitarias=result.testsRun,pruebas_generacion=generation['pruebas'],
        textos_confirmados=1356,campos_tipo_provisional=730,
        cambios_fisicos_en_1_7=False,carga_datos_en_1_7=False,
        validacion_arcgis='VALIDACION_TEXTOS_1_7_ARCGIS.json',alcance_arcgis=native['alcance'],
        paquete_anterior=BASELINE.name,paquete_anterior_sha256=baseline_sha,
        fuentes=read('VALIDACION_NORMALIZACION.json')['fuentes'],
        informe_original_autoseleccionado=False,
        validaciones_historicas=previous['validaciones_historicas'] + [
            'VALIDACION_UNITARIA_1_6_2.json','VALIDACION_REANUDACION_1_6_2_ARCGIS.json',
            'VALIDACION_NOMBRES_1_6_ESTATICA.json'],
        archivos={name:sha(OUT/name) for name in sorted(names)})
    (OUT/'MANIFIESTO_DATOS_PROYECTO.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    for name in ('Datos_Proyecto_Controlado_v1_7.zip','Datos_Proyecto_Controlado.zip'):
        archive(OUT.parent/name,names,manifest)
    wrappers = sorted((OUT/'por_clase').glob('*.py'))
    assert {path.stem for path in wrappers} == {cls['nombre'] for cls in model['clases']}
    archive(OUT.parent/'Esquema_KMZ_EFT_Corregido.zip',names,manifest,wrappers)
    assert sha(BASELINE) == baseline_sha
    print(f'{result.testsRun} pruebas aprobadas. 1356 textos confirmados; 730 pendientes; esquema fisico intacto.')


if __name__ == '__main__':
    main()
