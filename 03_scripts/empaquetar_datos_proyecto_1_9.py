"""Entrega1.9: cierre controlado de730tipos; solo8cambios fisicos autorizados."""
import ast
import hashlib
import io
import json
import sys
import unittest
import zipfile

from empaquetar_datos_proyecto_1_6_1 import ROOT, OUT, archive, read, sha

BASELINE = OUT.parent / 'Datos_Proyecto_Controlado_v1_8.zip'
NEW_FILES = set('''
CAMBIOS_1_9.md PLAN_CIERRE_TIPOS_1_9.csv cierre_tipos_1_9.json
referencia_cierre_tipos.py cerrar_tipos_kmz.py
test_referencia_cierre_tipos.py test_cerrar_tipos_kmz.py
esquema_anterior_1_8.json PERFIL_COMPLETO_KMZ_1_9.json PERFIL_COMPLETO_KMZ_1_9.sha256
VALIDACION_MODELO_CIERRE_1_9.json VALIDACION_PERFIL_CIERRE_1_9.json
VALIDACION_CIERRE_1_9_ARCGIS.json VALIDACION_UNITARIA_1_9.json
VALIDACION_GENERADOR_PROTEGIDO_1_9.json'''.split())


def baseline():
    with zipfile.ZipFile(BASELINE) as zipped:
        manifest = json.loads(zipped.read('MANIFIESTO_DATOS_PROYECTO.json'))
        assert manifest['version'] == '1.8' and zipped.testzip() is None
        for name, digest in manifest['archivos'].items():
            assert hashlib.sha256(zipped.read(name)).hexdigest() == digest, name
        return manifest, zipped.read('Datos_Proyecto.pyt').decode('utf-8-sig')


def unit_inputs():
    previous, _ = baseline()
    return sorted({name for name in set(previous['archivos']) | NEW_FILES if name.endswith('.py')} |
                  {'Datos_Proyecto.pyt','esquema.json','esquema_anterior_1_8.json','cierre_tipos_1_9.json'})


def run_tests():
    sys.path.insert(0, str(OUT))
    stream = io.StringIO()
    suite = unittest.defaultTestLoader.discover(str(OUT), pattern='test_*.py')
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    assert result.wasSuccessful() and not result.skipped, stream.getvalue()
    unit = dict(version_paquete='1.9', pruebas=result.testsRun, fallos=len(result.failures),
        errores=len(result.errors), omitidas=len(result.skipped), validacion_sde=False,
        salida=stream.getvalue(), archivos_sha256={name:sha(OUT/name) for name in unit_inputs()})
    (OUT/'VALIDACION_UNITARIA_1_9.json').write_text(json.dumps(unit,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'{result.testsRun} pruebas aprobadas, sin errores ni omisiones.')


def evidence_hashes(evidence):
    for name, digest in evidence['archivos_sha256'].items():
        path = ROOT/name if name.startswith('03_scripts/') else OUT/name
        assert sha(path) == digest, name


def main():
    target = OUT.parent/'Datos_Proyecto_Controlado_v1_9.zip'
    assert not target.exists(), 'La version numerada ya existe; no se sobrescribe.'
    before_sha = sha(BASELINE)
    previous, old_source = baseline()
    sys.path.insert(0,str(OUT))
    import referencia_cierre_tipos as reference
    base, model, config = reference.read_reference(OUT)
    assert len(config['campos']) == 730 and len(config['cambios_fisicos']) == 8
    with zipfile.ZipFile(BASELINE) as archive_source:
        assert (OUT/'esquema_anterior_1_8.json').read_bytes() == archive_source.read('esquema.json')
    old_classes = {n.name:n for n in ast.parse(old_source).body if isinstance(n,ast.ClassDef)}
    new_classes = {n.name:n for n in ast.parse((OUT/'Datos_Proyecto.pyt').read_text(encoding='utf-8-sig')).body if isinstance(n,ast.ClassDef)}
    assert set(new_classes)-set(old_classes) == {'CerrarTiposKMZ'}
    for name, node in old_classes.items():
        if name == 'Toolbox':
            continue
        old_methods = {n.name:ast.dump(n) for n in node.body if isinstance(n,ast.FunctionDef)}
        new_methods = {n.name:ast.dump(n) for n in new_classes[name].body if isinstance(n,ast.FunctionDef)}
        for method, code in old_methods.items():
            if name == 'ValidarTextosConfirmados' and method == '__init__':
                continue
            assert new_methods[method] == code, f'UI previa alterada: {name}.{method}'
    allowed = {'Datos_Proyecto.pyt','esquema.json','campos_aprobados_1_5.json',
        'nombres_clases_1_6.json','campos_matriz_a_esquema.csv','revision_tipos.csv',
        'validar_tipos_kmz.py','verificar_textos_confirmados.py',
        'test_validar_tipos_kmz.py','test_verificar_textos_confirmados.py',
        'test_diagnostico_integrado.py','GUIA_DATOS_PROYECTO.md','LEEME.md'}
    for name, digest in previous['archivos'].items():
        if name not in allowed:
            assert sha(OUT/name) == digest, f'Cambio ajeno a1.9: {name}'
    unit = read('VALIDACION_UNITARIA_1_9.json')
    assert unit['version_paquete'] == '1.9' and unit['pruebas'] > 0
    assert not (unit['fallos'] or unit['errores'] or unit['omitidas'])
    assert unit['archivos_sha256'] == {name:sha(OUT/name) for name in unit_inputs()}
    preparation = read('VALIDACION_MODELO_CIERRE_1_9.json')
    profile = read('VALIDACION_PERFIL_CIERRE_1_9.json')
    protected = read('VALIDACION_GENERADOR_PROTEGIDO_1_9.json')
    native = read('VALIDACION_CIERRE_1_9_ARCGIS.json')
    assert preparation['campos_provisionales_objetivo'] == 0 and not preparation['cambios_en_sde']
    assert profile['evidencia_valores_identica'] and profile['fuentes_reverificadas_por_sha256']
    assert profile['campos_tipo_provisional'] == 0 and profile['incidencias_de_valores_o_mapeo'] == 4
    assert protected['regresion_rechazada'] and protected['archivos_intactos']
    assert native['estado'] == 'TIPOS_CERRADOS_CON_PENDIENTES_DE_INGESTA'
    assert native['toolbox_ejecutada'] and not native['validacion_sde']
    assert native['campos_ensayados'] == 3340 and native['clases_ensayadas_total'] == 76
    assert native['cambios_fisicos_aplicados'] == 8 and native['campos_pendientes_modelo'] == 0
    assert native['cambios_pendientes_destino'] == 0 and native['cierre_verificado']
    assert native['otras_73_clases_preservadas'] and native['propiedades_3_clases_preservadas']
    assert native['indices_3_clases_preservados'] and native['fuente_1_8_inalterada']
    assert native['diferencias_destino'] == 0
    for evidence in (preparation, profile, protected, native):
        evidence_hashes(evidence)
    names = set(previous['archivos']) | NEW_FILES
    manifest = dict(previous, version='1.9',version_modelo=12,herramientas=9,
        pruebas_unitarias=unit['pruebas'],campos_tipo_provisional=0,
        tipos_confirmados_en_1_9=730,textos_conservados_en_1_9=722,cambios_fisicos_lote_1_9=8,
        cierre_aplicado_sde=False,ingesta_autorizada=False,
        validacion_arcgis='VALIDACION_CIERRE_1_9_ARCGIS.json',alcance_arcgis=native['alcance'],
        validacion_perfil_completo='VALIDACION_PERFIL_CIERRE_1_9.json',
        perfil_completo='PERFIL_COMPLETO_KMZ_1_9.json',
        paquete_anterior=BASELINE.name,paquete_anterior_sha256=before_sha,
        validaciones_historicas=previous['validaciones_historicas']+[
            'VALIDACION_UNITARIA_1_8.json','VALIDACION_TIPOS_1_8_ARCGIS.json',
            'VALIDACION_PERFIL_COMPLETO_1_8.json','VALIDACION_NORMALIZACION.json'],
        archivos={name:sha(OUT/name) for name in sorted(names)})
    (OUT/'MANIFIESTO_DATOS_PROYECTO.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    for path in (target,OUT.parent/'Datos_Proyecto_Controlado.zip'):
        archive(path,names,manifest)
    wrappers=sorted((OUT/'por_clase').glob('*.py'))
    assert {p.stem for p in wrappers} == {c['nombre'] for c in model['clases']}
    archive(OUT.parent/'Esquema_KMZ_EFT_Corregido.zip',names,manifest,wrappers)
    assert sha(BASELINE) == before_sha
    print(f"Version1.9: {unit['pruebas']} pruebas;730tipos cerrados enmodelo,8AlterField ensayados; SDE pendiente de ejecucion porusuario.")


if __name__ == '__main__':
    if sys.argv[1:] == ['--pruebas']:
        run_tests()
    else:
        assert not sys.argv[1:]
        main()
