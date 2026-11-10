"""Entrega 1.10 de prevalidación de ingesta, con el modelo 12 intacto."""
import ast
import hashlib
import io
import json
import sys
import unittest
import zipfile

from empaquetar_datos_proyecto_1_6_1 import ROOT, OUT, archive, read, sha

BASELINE = OUT.parent / 'Datos_Proyecto_Controlado_v1_9.zip'
NEW_FILES = set('''prevalidar_ingesta.py fuentes_ingesta.py proyectos_ingesta.py plan_ingesta.py
test_prevalidar_ingesta.py test_fuentes_ingesta.py test_proyectos_ingesta.py test_plan_ingesta.py
CAMBIOS_1_10.md VALIDACION_UNITARIA_1_10.json VALIDACION_PREINGESTA_1_10_ARCGIS.json'''.split())
ALLOWED = {'Datos_Proyecto.pyt', 'test_diagnostico_integrado.py', 'GUIA_DATOS_PROYECTO.md', 'LEEME.md'}


def baseline():
    with zipfile.ZipFile(BASELINE) as zipped:
        manifest = json.loads(zipped.read('MANIFIESTO_DATOS_PROYECTO.json'))
        assert manifest['version'] == '1.9' and zipped.testzip() is None
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
    proof = dict(version_paquete='1.10', pruebas=result.testsRun, fallos=len(result.failures),
        errores=len(result.errors), omitidas=len(result.skipped), validacion_sde=False,
        salida=stream.getvalue(), archivos_sha256={n: sha(OUT / n) for n in unit_inputs()})
    (OUT / 'VALIDACION_UNITARIA_1_10.json').write_text(
        json.dumps(proof, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'{result.testsRun} pruebas aprobadas, sin errores ni omisiones.')


def main():
    target = OUT.parent / 'Datos_Proyecto_Controlado_v1_10.zip'
    assert not target.exists(), 'La versión numerada ya existe; no se sobrescribe.'
    before_sha = sha(BASELINE)
    previous, old_source = baseline()
    for name, digest in previous['archivos'].items():
        if name not in ALLOWED:
            assert sha(OUT / name) == digest, 'Cambio fuera del alcance de prevalidación: ' + name
    old = {n.name: ast.dump(n) for n in ast.parse(old_source).body if isinstance(n, ast.ClassDef)}
    new = {n.name: ast.dump(n) for n in ast.parse((OUT / 'Datos_Proyecto.pyt').read_text(encoding='utf-8-sig')).body
           if isinstance(n, ast.ClassDef)}
    assert set(new) - set(old) == {'PrevalidarIngesta'}
    assert all(new[n] == code for n, code in old.items() if n != 'Toolbox'), 'Herramienta previa alterada.'
    sys.path.insert(0, str(OUT))
    import referencia_cierre_tipos as ref
    import validar_tipos_kmz as validation
    _, model, _ = ref.read_reference(OUT)
    profile, _ = validation.read_profile_snapshot(OUT)
    assert model['version'] == 12 and len(profile['perfil']['fuentes']) == 13
    unit = read('VALIDACION_UNITARIA_1_10.json')
    assert unit['pruebas'] > 283 and not (unit['fallos'] or unit['errores'] or unit['omitidas'])
    assert unit['archivos_sha256'] == {n: sha(OUT / n) for n in unit_inputs()}
    native = read('VALIDACION_PREINGESTA_1_10_ARCGIS.json')
    assert native['estado'] == 'PLAN_INGESTA_CON_PENDIENTES' and native['toolbox_ejecutada']
    assert not native['validacion_sde']
    assert native['clases_ensayadas'] == 76 and native['campos_ensayados'] == 3340
    assert native['fuentes_verificadas'] == 13
    assert native['gdb_inalterada'] and native['fuente_1_9_inalterada']
    assert native['modelo_inalterado'] and native['fuentes_kmz_inalteradas']
    assert native['filas_padre_leidas'] == 1 and native['asociaciones_confirmadas'] == 0
    assert (native['rutas'], native['placemarks'], native['mapeados'], native['sin_destino']) == (3638,279623,139304,140319)
    for name, digest in native['archivos_sha256'].items():
        assert sha(ROOT / name if name.startswith('03_scripts/') else OUT / name) == digest, name
    names = set(previous['archivos']) | NEW_FILES
    manifest = dict(previous, version='1.10', version_modelo=12, herramientas=10,
        pruebas_unitarias=unit['pruebas'], prevalidacion_ingesta_solo_lectura=True,
        cambios_esquema_en_1_10=0, registros_insertados_en_1_10=0, ingesta_autorizada=False,
        validacion_arcgis='VALIDACION_PREINGESTA_1_10_ARCGIS.json',
        alcance_arcgis='Lectura de 13 KMZ por SHA-256, 76 clases/3340 campos y catálogo sintético local. Sin SDE.',
        paquete_anterior=BASELINE.name, paquete_anterior_sha256=before_sha,
        validaciones_historicas=previous.get('validaciones_historicas', []) + [
            'VALIDACION_UNITARIA_1_9.json', 'VALIDACION_CIERRE_1_9_ARCGIS.json'],
        archivos={n: sha(OUT / n) for n in sorted(names)})
    manifest.pop('cierre_aplicado_sde', None)
    (OUT / 'MANIFIESTO_DATOS_PROYECTO.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    for path in (target, OUT.parent / 'Datos_Proyecto_Controlado.zip'):
        archive(path, names, manifest)
    wrappers = sorted((OUT / 'por_clase').glob('*.py'))
    assert {p.stem for p in wrappers} == {c['nombre'] for c in model['clases']}
    archive(OUT.parent / 'Esquema_KMZ_EFT_Corregido.zip', names, manifest, wrappers)
    assert sha(BASELINE) == before_sha
    print(f"Versión 1.10: {unit['pruebas']} pruebas; diez herramientas; esquema y datos sin cambios.")


if __name__ == '__main__':
    if sys.argv[1:] == ['--pruebas']:
        run_tests()
    else:
        assert not sys.argv[1:]
        main()
