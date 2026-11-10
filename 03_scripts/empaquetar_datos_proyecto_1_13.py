"""Entrega 1.13: preparación de reglas/cobertura y lectura de identidades reales."""
import ast
import hashlib
import io
import json
import sys
import unittest
import zipfile
from empaquetar_datos_proyecto_1_6_1 import ROOT, OUT, archive, read, sha

BASELINE=OUT.parent/'Datos_Proyecto_Controlado_v1_12.zip'
NEW_FILES=set('''preparar_carga_inicial.py reglas_sunarp_ingesta.py reglas_sunarp_1_13.json
cobertura_ingesta.py reglas_cobertura_1_13.json inspeccionar_negocio_ingesta.py
descripciones_ingesta.py descripciones_1_13.json confirmar_proyectos_13_confirmados.csv
test_preparar_carga_inicial.py test_carga_inicial_toolbox.py test_reglas_sunarp_ingesta.py
test_cobertura_ingesta.py test_inspeccionar_negocio_ingesta.py CAMBIOS_1_13.md
VALIDACION_UNITARIA_1_13.json VALIDACION_PREPARACION_1_13_ARCGIS.json
VALIDACION_REGLAS_SUNARP_1_13.json'''.split())
ALLOWED={'Datos_Proyecto.pyt','test_diagnostico_integrado.py','test_configuracion_toolbox.py',
         'GUIA_DATOS_PROYECTO.md','LEEME.md'}


def baseline():
    with zipfile.ZipFile(BASELINE) as z:
        manifest=json.loads(z.read('MANIFIESTO_DATOS_PROYECTO.json'))
        assert manifest['version']=='1.12' and z.testzip() is None
        for name,digest in manifest['archivos'].items():
            assert hashlib.sha256(z.read(name)).hexdigest()==digest,name
        return manifest,z.read('Datos_Proyecto.pyt').decode('utf-8-sig')


def unit_inputs():
    previous,_=baseline()
    return sorted({n for n in set(previous['archivos'])|NEW_FILES if n.endswith('.py')} |
        {'Datos_Proyecto.pyt','esquema.json','cierre_tipos_1_9.json','reglas_sunarp_1_13.json',
         'reglas_cobertura_1_13.json','descripciones_1_13.json','confirmar_proyectos_13_confirmados.csv'})


def run_tests():
    sys.path.insert(0,str(OUT))
    stream=io.StringIO()
    result=unittest.TextTestRunner(stream=stream,verbosity=2).run(
        unittest.defaultTestLoader.discover(str(OUT),pattern='test_*.py'))
    assert result.wasSuccessful() and not result.skipped,stream.getvalue()
    proof=dict(version_paquete='1.13',pruebas=result.testsRun,fallos=len(result.failures),
        errores=len(result.errors),omitidas=len(result.skipped),validacion_sde=False,
        salida=stream.getvalue(),archivos_sha256={n:sha(OUT/n) for n in unit_inputs()})
    (OUT/'VALIDACION_UNITARIA_1_13.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'{result.testsRun} pruebas aprobadas, sin errores ni omisiones.',flush=True)


def check_proof_hashes(proof):
    for name,digest in proof['archivos_sha256'].items():
        assert sha(ROOT/name if name.startswith('03_scripts/') else OUT/name)==digest,name


def main():
    target=OUT.parent/'Datos_Proyecto_Controlado_v1_13.zip'
    assert not target.exists(),'La version numerada existe; no se sobrescribe.'
    before_sha=sha(BASELINE)
    previous,old_source=baseline()
    for name,digest in previous['archivos'].items():
        if name not in ALLOWED:assert sha(OUT/name)==digest,'Cambio previo fuera de alcance: '+name
    old={n.name:ast.dump(n) for n in ast.parse(old_source).body if isinstance(n,ast.ClassDef)}
    new={n.name:ast.dump(n) for n in ast.parse((OUT/'Datos_Proyecto.pyt').read_text(encoding='utf-8-sig')).body if isinstance(n,ast.ClassDef)}
    assert set(new)-set(old)=={'PrepararCargaInicialKMZ'}
    assert all(new[n]==code for n,code in old.items() if n!='Toolbox'),'Herramienta previa modificada'
    unit=read('VALIDACION_UNITARIA_1_13.json')
    assert unit['pruebas']>previous['pruebas_unitarias'] and not(unit['fallos'] or unit['errores'] or unit['omitidas'])
    assert unit['archivos_sha256']=={n:sha(OUT/n) for n in unit_inputs()}
    native=read('VALIDACION_PREPARACION_1_13_ARCGIS.json')
    assert native['version_paquete']=='1.13' and native['runtime_ejecutado'] and not native['validacion_sde']
    for name in ('geodatabase_inalterada','fuentes_inalteradas','modelo_inalterado','sin_rutas_autorizadas','lectura_negocio_completa'):
        assert native[name],name
    assert native['reglas_comunes']==152 and native['identidades_pendientes']==4
    assert native['fuentes_verificadas']==native['proyectos_verificados']==13
    assert native['rutas']==3638 and native['registros_insertados']==0
    check_proof_hashes(native)
    sunarp=read('VALIDACION_REGLAS_SUNARP_1_13.json')
    assert sunarp['estado']=='VERIFICACION_KMZ_REAL_OK' and not sunarp['errores']
    assert sunarp['registros']==1019 and sunarp['valores']==1378
    assert sunarp['pares_distintos']==253 and sunarp['pares_iguales']==35
    assert not sunarp['ddl'] and not sunarp['carga_ejecutada']
    check_proof_hashes(sunarp)
    names=set(previous['archivos'])|NEW_FILES
    model=read('esquema.json')
    assert model['version']==12 and len(model['clases'])==76
    manifest=dict(previous,version='1.13',herramientas=13,version_modelo=12,
        pruebas_unitarias=unit['pruebas'],ingesta_autorizada=False,registros_insertados=0,
        alcance_preparacion='Reglas de proyecto/analisis, SUNARP sin DDL, cobertura revisable, '
            'descripciones e identidades reales de negocio. No crea clases ni carga datos.',
        configuracion_aplicada_sde=False,validacion_sde=False,
        validacion_arcgis='VALIDACION_PREPARACION_1_13_ARCGIS.json',
        alcance_arcgis='Runtime ejecutado con ArcPy real en copia local con catalogos sinteticos. '
            '13 KMZ reales, 76 clases y 3340 campos. SDE remota y UI nativa no ejecutadas.',
        paquete_anterior=BASELINE.name,paquete_anterior_sha256=before_sha,
        validaciones_historicas=previous.get('validaciones_historicas',[])+[
            'VALIDACION_UNITARIA_1_12.json','VALIDACION_CONFIGURACION_1_12_ARCGIS.json'],
        archivos={n:sha(OUT/n) for n in sorted(names)})
    (OUT/'MANIFIESTO_DATOS_PROYECTO.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    for path in (target,OUT.parent/'Datos_Proyecto_Controlado.zip'):archive(path,names,manifest)
    wrappers=sorted((OUT/'por_clase').glob('*.py'))
    assert {p.stem for p in wrappers}=={c['nombre'] for c in model['clases']}
    archive(OUT.parent/'Esquema_KMZ_EFT_Corregido.zip',names,manifest,wrappers)
    assert sha(BASELINE)==before_sha
    with zipfile.ZipFile(target) as z:
        assert z.testzip() is None
        assert sum(n.endswith('.pyt') for n in z.namelist())==1
        for n,digest in manifest['archivos'].items():assert hashlib.sha256(z.read(n)).hexdigest()==digest,n
    print(f'Version 1.13 empaquetada: {unit["pruebas"]} pruebas, 13 herramientas.',flush=True)


if __name__=='__main__':
    if sys.argv[1:]==['--pruebas']:run_tests()
    else:
        assert not sys.argv[1:]
        main()
