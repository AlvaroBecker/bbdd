"""Entrega 1.8: perfil completo y octava herramienta de validacion, sin migracion."""
import ast
import hashlib
import io
import json
import sys
import unittest
import zipfile

from empaquetar_datos_proyecto_1_6_1 import ROOT, OUT, archive, read, sha

BASELINE = OUT.parent / 'Datos_Proyecto_Controlado_v1_7.zip'


def unit_inputs():
    return sorted({path.name for path in OUT.glob('*.py')} |
                  {'Datos_Proyecto.pyt', 'esquema.json'})


def run_tests():
    sys.path.insert(0, str(OUT))
    stream = io.StringIO()
    suite = unittest.defaultTestLoader.discover(str(OUT), pattern='test_*.py')
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    assert result.wasSuccessful() and not result.skipped, stream.getvalue()
    unit = dict(version_paquete='1.8', pruebas=result.testsRun, fallos=len(result.failures),
        errores=len(result.errors), omitidas=len(result.skipped), validacion_sde=False,
        salida=stream.getvalue(), archivos_sha256={name:sha(OUT / name) for name in unit_inputs()})
    (OUT / 'VALIDACION_UNITARIA_1_8.json').write_text(
        json.dumps(unit, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'{result.testsRun} pruebas unitarias aprobadas, sin errores ni omisiones.')


def main():
    baseline_sha = sha(BASELINE)
    target = OUT.parent / 'Datos_Proyecto_Controlado_v1_8.zip'
    assert not target.exists(), 'La entrega numerada ya existe; no se sobrescribe.'
    with zipfile.ZipFile(BASELINE) as zipped:
        assert zipped.testzip() is None
        previous = json.loads(zipped.read('MANIFIESTO_DATOS_PROYECTO.json'))
        assert previous['version'] == '1.7'
        for name, digest in previous['archivos'].items():
            assert hashlib.sha256(zipped.read(name)).hexdigest() == digest, name
        assert (OUT / 'esquema.json').read_bytes() == zipped.read('esquema.json')
        old_toolbox = zipped.read('Datos_Proyecto.pyt').decode('utf-8-sig')
    old_classes = {node.name:ast.dump(node) for node in ast.parse(old_toolbox).body
        if isinstance(node, ast.ClassDef) and node.name != 'Toolbox'}
    new_classes = {node.name:ast.dump(node) for node in ast.parse(
        (OUT / 'Datos_Proyecto.pyt').read_text(encoding='utf-8-sig')).body
        if isinstance(node, ast.ClassDef)}
    assert all(new_classes[name] == value for name, value in old_classes.items())
    assert set(new_classes) - set(old_classes) == {'Toolbox', 'ValidarTodosTiposKMZ'}
    allowed_updates = {'Datos_Proyecto.pyt', 'test_diagnostico_integrado.py',
        'GUIA_DATOS_PROYECTO.md', 'LEEME.md'}
    for name, digest in previous['archivos'].items():
        if name not in allowed_updates:
            assert sha(OUT / name) == digest, f'Componente ajeno a 1.8 modificado: {name}'
    native = read('VALIDACION_TIPOS_1_8_ARCGIS.json')
    assert native['estado'] == 'VALIDACION_TIPOS_COMPLETA_CON_PENDIENTES'
    assert native['toolbox_ejecutada'] and not native['validacion_sde']
    assert native['clases_ensayadas_total'] == 76 and native['campos_ensayados'] == 3340
    assert native['diferencias_destino'] == 0 and native['perfil_incluido_verificado']
    assert native['mutaciones_geodatabase_durante_verificacion'] == 0 and native['archivos_gdb_identicos']
    assert native['metodo_preservacion'] == 'SHA256_TODOS_ARCHIVOS_GDB_EXCEPTO_LOCKS'
    assert native['huella_gdb_antes_sha256'] == native['huella_gdb_despues_sha256']
    profile = read('VALIDACION_PERFIL_COMPLETO_1_8.json')
    assert profile['cobertura_completa'] and profile['lectura_fuentes_actuales']
    assert profile['conteos']['kmz_leidos'] == 13
    assert profile['conteos']['rutas_coincidentes'] == 3638
    assert profile['conteos']['elementos_observados'] == 279623
    assert profile['campos_revisados'] == 3340 and profile['campos_tipo_pendiente'] == 730
    assert sum(profile['tipos_recomendados_pendientes'].values()) == 730
    assert not profile['cambios_en_modelo'] and not profile['cambios_en_sde']
    for evidence in (native, profile):
        for name, digest in evidence['archivos_sha256'].items():
            path = ROOT / name if name.startswith('03_scripts/') else OUT / name
            assert sha(path) == digest, name
    unit = read('VALIDACION_UNITARIA_1_8.json')
    assert unit['version_paquete'] == '1.8' and unit['pruebas'] > 0
    assert not (unit['fallos'] or unit['errores'] or unit['omitidas'])
    assert unit['archivos_sha256'] == {name:sha(OUT / name) for name in unit_inputs()}
    tests = sorted(path.name for path in OUT.glob('test_*.py'))
    names = set(previous['archivos']) | set(tests) | set('''
        CAMBIOS_1_8.md RESUMEN_TIPOS_KMZ_1_8.md REVISION_TIPOS_KMZ_1_8.csv
        inspeccion_kmz.py validar_tipos_kmz.py
        PERFIL_COMPLETO_KMZ_1_8.json PERFIL_COMPLETO_KMZ_1_8.sha256
        VALIDACION_UNITARIA_1_8.json VALIDACION_TIPOS_1_8_ARCGIS.json
        VALIDACION_PERFIL_COMPLETO_1_8.json'''.split())
    model = read('esquema.json')
    manifest = dict(previous, version='1.8', version_modelo=11, herramientas=8,
        pruebas_unitarias=unit['pruebas'], campos_tipo_provisional=730,
        cambios_fisicos_en_1_8=False, carga_datos_en_1_8=False,
        validacion_arcgis='VALIDACION_TIPOS_1_8_ARCGIS.json', alcance_arcgis=native['alcance'],
        validacion_perfil_completo='VALIDACION_PERFIL_COMPLETO_1_8.json',
        perfil_completo='PERFIL_COMPLETO_KMZ_1_8.json',
        lectura_kmz=profile['conteos'],
        paquete_anterior=BASELINE.name, paquete_anterior_sha256=baseline_sha,
        validaciones_historicas=previous['validaciones_historicas'] + [
            'VALIDACION_UNITARIA_1_7.json', 'VALIDACION_TEXTOS_1_7_ARCGIS.json',
            'VALIDACION_GENERACION_1_7.json'],
        archivos={name:sha(OUT / name) for name in sorted(names)})
    (OUT / 'MANIFIESTO_DATOS_PROYECTO.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    for path in (target, OUT.parent / 'Datos_Proyecto_Controlado.zip'):
        archive(path, names, manifest)
    wrappers = sorted((OUT / 'por_clase').glob('*.py'))
    assert {path.stem for path in wrappers} == {cls['nombre'] for cls in model['clases']}
    archive(OUT.parent / 'Esquema_KMZ_EFT_Corregido.zip', names, manifest, wrappers)
    assert sha(BASELINE) == baseline_sha
    print(f"{unit['pruebas']} pruebas aprobadas. 13 KMZ completos; 76 clases; 730 propuestas sin aplicar.")


if __name__ == '__main__':
    if sys.argv[1:] == ['--pruebas']:
        run_tests()
    else:
        assert not sys.argv[1:], 'Argumento no admitido.'
        main()
