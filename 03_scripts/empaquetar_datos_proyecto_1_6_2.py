"""Entrega 1.6.2: alias cualificados y referencia original al reanudar."""
import ast
import hashlib
import io
import json
import sys
import unittest
import zipfile

from empaquetar_datos_proyecto_1_6_1 import ROOT, OUT, archive, read, sha

BASELINE = OUT.parent / 'Datos_Proyecto_Controlado_v1_6_1.zip'


def main():
    baseline_sha = sha(BASELINE)
    with zipfile.ZipFile(BASELINE) as zipped:
        assert zipped.testzip() is None
        previous = json.loads(zipped.read('MANIFIESTO_DATOS_PROYECTO.json'))
        assert previous['version'] == '1.6.1'
        for name, digest in previous['archivos'].items():
            assert hashlib.sha256(zipped.read(name)).hexdigest() == digest, name
        old_toolbox = zipped.read('Datos_Proyecto.pyt').decode('utf-8-sig')
    unchanged_classes = {node.name: ast.dump(node) for node in ast.parse(old_toolbox).body
        if isinstance(node, ast.ClassDef) and node.name not in ('Toolbox', 'RenombrarClases')}
    current_classes = {node.name: ast.dump(node) for node in ast.parse((OUT/'Datos_Proyecto.pyt').read_text(encoding='utf-8-sig')).body
        if isinstance(node, ast.ClassDef)}
    assert all(current_classes[name] == value for name, value in unchanged_classes.items())
    allowed_updates = {'Datos_Proyecto.pyt', 'renombrar_clases.py', 'diagnostico_renombrado.py',
        'test_diagnostico_integrado.py', 'test_diagnostico_renombrado.py',
        'GUIA_DATOS_PROYECTO.md', 'NORMALIZACION_EFT.md', 'LEEME.md'}
    for name, digest in previous['archivos'].items():
        if name not in allowed_updates:
            assert sha(OUT/name) == digest, f'Componente ajeno a la correccion modificado: {name}'
    native = read('VALIDACION_REANUDACION_1_6_2_ARCGIS.json')
    assert native['estado'] == 'NOMBRES_VERIFICADOS'
    assert native['toolbox_ejecutada'] and native['mutaciones_geodatabase'] == 0
    assert not native['validacion_sde']
    for name, digest in native['archivos_sha256'].items():
        assert sha(OUT/name) == digest, name
    assert (OUT/'resultado_origen.json').read_bytes() == (ROOT/'resultado.json').read_bytes()
    assert sha(ROOT/'resultado.json') == native['informe_usuario_sha256']
    sys.path.insert(0, str(OUT))
    suite = unittest.defaultTestLoader.discover(str(OUT), pattern='test_*.py')
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    assert result.wasSuccessful() and not result.skipped, stream.getvalue()
    tests = sorted(path.name for path in OUT.glob('test_*.py'))
    unit = dict(version_paquete='1.6.2', pruebas=result.testsRun,
        fallos=len(result.failures), errores=len(result.errors), omitidas=len(result.skipped),
        validacion_sde=False, salida=stream.getvalue(), archivos_sha256={name: sha(OUT/name)
            for name in tests + ['Datos_Proyecto.pyt', 'renombrar_clases.py', 'diagnostico_renombrado.py']})
    (OUT/'VALIDACION_UNITARIA_1_6_2.json').write_text(json.dumps(unit,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    names = set(previous['archivos']) | set(tests) | set('''CAMBIOS_1_6_2.md
VALIDACION_UNITARIA_1_6_2.json VALIDACION_REANUDACION_1_6_2_ARCGIS.json
probar_reanudacion_1_6_2_arcgis.py'''.split())
    manifest = dict(previous, version='1.6.2', version_mapeo='1.6', herramientas=6,
        pruebas_unitarias=result.testsRun, referencia_original_para_reanudar=True,
        excepcion_alias='Solo mismo esquema, mismo campo y sustitucion exacta del nombre de clase aprobado.',
        paquete_anterior=BASELINE.name, paquete_anterior_sha256=baseline_sha,
        validacion_arcgis='VALIDACION_REANUDACION_1_6_2_ARCGIS.json',
        alcance_arcgis='Validacion y reanudacion desde referencia original sobre tres clases locales ya normalizadas; cero escrituras. Sin SDE.',
        validaciones_historicas=previous['validaciones_historicas'] + [
            'VALIDACION_UNITARIA_1_6_1.json', 'VALIDACION_DIAGNOSTICO_INTEGRADO_1_6_1_ARCGIS.json'],
        archivos={name: sha(OUT/name) for name in sorted(names)})
    (OUT/'MANIFIESTO_DATOS_PROYECTO.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    for name in ('Datos_Proyecto_Controlado_v1_6_2.zip', 'Datos_Proyecto_Controlado.zip'):
        archive(OUT.parent/name, names, manifest)
    wrappers = sorted((OUT/'por_clase').glob('*.py'))
    assert {path.stem for path in wrappers} == {cls['nombre'] for cls in read('esquema.json')['clases']}
    archive(OUT.parent/'Esquema_KMZ_EFT_Corregido.zip', names, manifest, wrappers)
    assert sha(BASELINE) == baseline_sha
    print(f'{result.testsRun} pruebas aprobadas; modelo y mapeo conservados; versiones anteriores preservadas.')


if __name__ == '__main__':
    main()
