"""Entrega 1.11: altas limitadas de proyectos mediante ArcGIS; modelo 12 intacto."""
import ast
import hashlib
import io
import json
import sys
import unittest
import zipfile

from empaquetar_datos_proyecto_1_6_1 import ROOT, OUT, archive, read, sha


BASELINE = OUT.parent / 'Datos_Proyecto_Controlado_v1_10.zip'
NEW_FILES = set('''alta_proyectos.py alta_proyectos_logica.py
test_alta_proyectos.py test_alta_proyectos_logica.py test_alta_toolbox.py
CAMBIOS_1_11.md confirmar_proyectos_por_nombre.csv VALIDACION_UNITARIA_1_11.json VALIDACION_ALTAS_1_11_ARCGIS.json'''.split())
ALLOWED = {'Datos_Proyecto.pyt', 'test_diagnostico_integrado.py', 'GUIA_DATOS_PROYECTO.md', 'LEEME.md'}


def baseline():
    with zipfile.ZipFile(BASELINE) as zipped:
        manifest = json.loads(zipped.read('MANIFIESTO_DATOS_PROYECTO.json'))
        assert manifest['version'] == '1.10' and zipped.testzip() is None
        for name, digest in manifest['archivos'].items():
            assert hashlib.sha256(zipped.read(name)).hexdigest() == digest, name
        return manifest, zipped.read('Datos_Proyecto.pyt').decode('utf-8-sig')


def unit_inputs():
    previous, _ = baseline()
    return sorted({n for n in set(previous['archivos']) | NEW_FILES if n.endswith('.py')} |
                  {'Datos_Proyecto.pyt', 'esquema.json', 'cierre_tipos_1_9.json'})


def run_tests():
    sys.path.insert(0, str(OUT))
    stream = io.StringIO()
    suite = unittest.defaultTestLoader.discover(str(OUT), pattern='test_*.py')
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    assert result.wasSuccessful() and not result.skipped, stream.getvalue()
    proof = dict(version_paquete='1.11', pruebas=result.testsRun, fallos=len(result.failures),
        errores=len(result.errors), omitidas=len(result.skipped), validacion_sde=False,
        salida=stream.getvalue(), archivos_sha256={n: sha(OUT / n) for n in unit_inputs()})
    (OUT / 'VALIDACION_UNITARIA_1_11.json').write_text(
        json.dumps(proof, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'{result.testsRun} pruebas aprobadas, sin errores ni omisiones.')


def main():
    target = OUT.parent / 'Datos_Proyecto_Controlado_v1_11.zip'
    assert not target.exists(), 'La version numerada ya existe; no se sobrescribe.'
    before_sha = sha(BASELINE)
    previous, old_source = baseline()
    for name, digest in previous['archivos'].items():
        if name not in ALLOWED:
            assert sha(OUT / name) == digest, 'Cambio fuera del alcance de altas: ' + name
    old = {n.name: ast.dump(n) for n in ast.parse(old_source).body if isinstance(n, ast.ClassDef)}
    new = {n.name: ast.dump(n) for n in ast.parse((OUT / 'Datos_Proyecto.pyt').read_text(encoding='utf-8-sig')).body
           if isinstance(n, ast.ClassDef)}
    assert set(new) - set(old) == {'RegistrarProyectosFaltantes'}
    assert all(new[n] == code for n, code in old.items() if n != 'Toolbox'), 'Herramienta previa alterada.'
    sys.path.insert(0, str(OUT))
    import referencia_cierre_tipos as ref
    import validar_tipos_kmz as validation
    _, model, _ = ref.read_reference(OUT)
    profile, _ = validation.read_profile_snapshot(OUT)
    assert model['version'] == 12 and len(profile['perfil']['fuentes']) == 13
    unit = read('VALIDACION_UNITARIA_1_11.json')
    assert unit['version_paquete'] == '1.11'
    assert unit['pruebas'] > 346 and not (unit['fallos'] or unit['errores'] or unit['omitidas'])
    assert unit['archivos_sha256'] == {n: sha(OUT / n) for n in unit_inputs()}
    native = read('VALIDACION_ALTAS_1_11_ARCGIS.json')
    assert native['version_paquete'] == '1.11'
    assert not native['validacion_sde']
    assert native['runtime_ejecutado'] and not native['toolbox_ejecutada']
    assert native['validacion_sin_cambios'] and native['altas_creadas'] == 2
    assert native['reejecucion_sin_altas'] and native['rollback_verificado']
    assert native['esquema_inalterado'] and native['modelo_inalterado']
    required_native_hashes = {'alta_proyectos.py', 'alta_proyectos_logica.py', 'crear_esquema.py',
        'esquema.json', '03_scripts/probar_alta_proyectos_1_11_arcgis.py'}
    assert required_native_hashes <= set(native['archivos_sha256'])
    for name, digest in native['archivos_sha256'].items():
        assert sha(ROOT / name if name.startswith('03_scripts/') else OUT / name) == digest, name
    assert sha(OUT / 'confirmar_proyectos_por_nombre.csv') == '5d8bbcc54afc6c6e4b657d025667da3c1a58f1891251d882158ce2fda879b16f'
    names = set(previous['archivos']) | NEW_FILES
    manifest = dict(previous, version='1.11', version_modelo=12, herramientas=11,
        pruebas_unitarias=unit['pruebas'], cambios_esquema_en_1_11=0,
        altas_autorizadas_en_1_11=['JAENNORTE', 'POROMA'],
        mecanismo_altas='ArcPy Editor e InsertCursor; sin SQL directo ni cambios al esquema.',
        control_concurrencia='Exclusividad operativa declarada; no establece un bloqueo de otros escritores.',
        ingesta_autorizada=False, altas_aplicadas_sde=False,
        validacion_arcgis='VALIDACION_ALTAS_1_11_ARCGIS.json',
        alcance_arcgis='Runtime probado en geodatabase de archivos local: validacion, altas, reejecucion y rollback. '
            'Contrato de toolbox probado con dobles; no se ejecuto .pyt nativo ni SDE.',
        paquete_anterior=BASELINE.name, paquete_anterior_sha256=before_sha,
        validaciones_historicas=previous.get('validaciones_historicas', []) + [
            'VALIDACION_UNITARIA_1_10.json', 'VALIDACION_PREINGESTA_1_10_ARCGIS.json'],
        archivos={n: sha(OUT / n) for n in sorted(names)})
    (OUT / 'MANIFIESTO_DATOS_PROYECTO.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    for path in (target, OUT.parent / 'Datos_Proyecto_Controlado.zip'):
        archive(path, names, manifest)
    wrappers = sorted((OUT / 'por_clase').glob('*.py'))
    assert {p.stem for p in wrappers} == {c['nombre'] for c in model['clases']}
    archive(OUT.parent / 'Esquema_KMZ_EFT_Corregido.zip', names, manifest, wrappers)
    assert sha(BASELINE) == before_sha
    print(f"Version 1.11: {unit['pruebas']} pruebas; once herramientas; sin cambios al modelo ni aplicacion SDE local.")


if __name__ == '__main__':
    if sys.argv[1:] == ['--pruebas']:
        run_tests()
    else:
        assert not sys.argv[1:]
        main()
