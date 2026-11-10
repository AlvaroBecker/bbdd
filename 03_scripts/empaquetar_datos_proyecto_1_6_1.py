"""Paquete integrado 1.6.1: diagnostico nuevo, componentes de migracion conservados."""
import ast
import hashlib
import io
import json
from pathlib import Path
import sys
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '02_entregas/Esquema_KMZ_EFT_Corregido'
BASELINE = ROOT / '02_entregas/Datos_Proyecto_Controlado_v1_6.zip'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(name):
    return json.loads((OUT / name).read_text(encoding='utf-8'))


def archive(path, names, manifest, wrappers=()):
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as zipped:
        for name in sorted(names):
            zipped.write(OUT / name, name)
        zipped.write(OUT / 'MANIFIESTO_DATOS_PROYECTO.json', 'MANIFIESTO_DATOS_PROYECTO.json')
        for wrapper in wrappers:
            zipped.write(wrapper, str(wrapper.relative_to(OUT)).replace('\\', '/'))
    with zipfile.ZipFile(path) as zipped:
        assert zipped.testzip() is None
        for name, digest in manifest['archivos'].items():
            assert hashlib.sha256(zipped.read(name)).hexdigest() == digest, name
        assert [name for name in zipped.namelist() if name.endswith('.pyt')] == ['Datos_Proyecto.pyt']
        assert not any('_validacion/' in name or '__pycache__/' in name for name in zipped.namelist())
    print(f'{path.name}: {len(names) + 1 + len(wrappers)} archivos; una toolbox; CRC y SHA verificados.')


def main():
    # Evidencia de procedencia: la version numerada previa es inmutable.
    baseline_digest = sha(BASELINE)
    with zipfile.ZipFile(BASELINE) as zipped:
        assert zipped.testzip() is None
        baseline = json.loads(zipped.read('MANIFIESTO_DATOS_PROYECTO.json'))
        assert baseline['version'] == '1.6'
        for name, digest in baseline['archivos'].items():
            assert hashlib.sha256(zipped.read(name)).hexdigest() == digest, name
        previous_toolbox = zipped.read('Datos_Proyecto.pyt')
        assert previous_toolbox == (OUT / 'validacion_fixture_toolbox_1_6.txt').read_bytes()
    old_classes = {node.name: ast.dump(node) for node in ast.parse(previous_toolbox.decode('utf-8-sig')).body
                   if isinstance(node, ast.ClassDef) and node.name != 'Toolbox'}
    new_classes = {node.name: ast.dump(node) for node in ast.parse((OUT / 'Datos_Proyecto.pyt').read_text(encoding='utf-8-sig')).body
                   if isinstance(node, ast.ClassDef)}
    assert all(new_classes[name] == code for name, code in old_classes.items()), 'Cambio en una herramienta anterior.'
    allowed_updates = {'Datos_Proyecto.pyt', 'GUIA_DATOS_PROYECTO.md', 'NORMALIZACION_EFT.md',
        # Los helpers de pruebas leen ahora el JSON final emitido, no el UUID mayor.
        'test_actualizar_campos_aprobados.py', 'test_ajustar_tipos.py',
        'test_renombrar_clases.py', 'test_reparar_texto_largo.py', 'test_datos_proyecto.py'}
    for name, digest in baseline['archivos'].items():
        if name not in allowed_updates:
            assert sha(OUT / name) == digest, f'Componente 1.6 modificado inesperadamente: {name}'
    native = read('VALIDACION_DIAGNOSTICO_INTEGRADO_1_6_1_ARCGIS.json')
    assert native['estado'] == 'SIN_DIFERENCIAS_ACTUALES'
    assert native['mutaciones_geodatabase'] == 0 and not native['validacion_sde']
    assert native['toolbox_ejecutada']
    for name, digest in native['archivos_sha256'].items():
        assert sha(OUT / name) == digest, name
    assert (OUT / 'resultado_origen.json').read_bytes() == (ROOT / 'resultado.json').read_bytes()
    assert sha(ROOT / 'resultado.json') == native['informe_usuario_sha256']
    sys.path.insert(0, str(OUT))
    stream = io.StringIO()
    suite = unittest.defaultTestLoader.discover(str(OUT), pattern='test_*.py')
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    assert result.wasSuccessful() and not result.skipped, stream.getvalue()
    test_files = sorted(p.name for p in OUT.glob('test_*.py'))
    unit = dict(version_paquete='1.6.1', pruebas=result.testsRun, fallos=len(result.failures),
        errores=len(result.errors), omitidas=len(result.skipped), validacion_sde=False,
        salida=stream.getvalue(), archivos_sha256={name: sha(OUT / name) for name in test_files + [
            'Datos_Proyecto.pyt', 'diagnostico_renombrado.py', 'validacion_fixture_toolbox_1_6.txt']})
    (OUT / 'VALIDACION_UNITARIA_1_6_1.json').write_text(json.dumps(unit, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    names = set(baseline['archivos']) | set(test_files) | set('''diagnostico_renombrado.py
validacion_fixture_toolbox_1_6.txt resultado_origen.json CAMBIOS_1_6_1.md LEEME.md
CAMBIOS_1_5.md CAMBIOS_1_5_1.md VALIDACION_UNITARIA_1_6_1.json
VALIDACION_DIAGNOSTICO_INTEGRADO_1_6_1_ARCGIS.json probar_diagnostico_integrado_arcgis.py'''.split())
    model = read('esquema.json')
    assert model['version'] == 10 and len(model['clases']) == 76
    manifest = dict(baseline, version='1.6.1', version_mapeo='1.6', herramientas=6,
        diagnostico_integrado_solo_lectura=True, pruebas_unitarias=result.testsRun,
        paquete_anterior=BASELINE.name, paquete_anterior_sha256=baseline_digest,
        validacion_arcgis='VALIDACION_DIAGNOSTICO_INTEGRADO_1_6_1_ARCGIS.json',
        alcance_arcgis='Integracion de las seis herramientas y ejecucion de diagnostico de solo lectura sobre tres clases locales. Sin SDE.',
        validaciones_historicas=baseline.get('validaciones_historicas', []) + [
            'VALIDACION_UNITARIA_1_6.json', 'VALIDACION_NOMBRES_1_6_ARCGIS.json'],
        archivos={name: sha(OUT / name) for name in sorted(names)})
    (OUT / 'MANIFIESTO_DATOS_PROYECTO.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    for name in ('Datos_Proyecto_Controlado_v1_6_1.zip', 'Datos_Proyecto_Controlado.zip'):
        archive(OUT.parent / name, names, manifest)
    wrappers = sorted((OUT / 'por_clase').glob('*.py'))
    assert {path.stem for path in wrappers} == {cls['nombre'] for cls in model['clases']}
    archive(OUT.parent / 'Esquema_KMZ_EFT_Corregido.zip', names, manifest, wrappers)
    assert sha(BASELINE) == baseline_digest
    print(f'Pruebas aprobadas: {result.testsRun}. Version 1.6 preservada. Informe original conservado.')


if __name__ == '__main__':
    main()
