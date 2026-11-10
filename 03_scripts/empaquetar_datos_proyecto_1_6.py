"""Empaqueta 1.6 con evidencias vigentes y comprueba cada archivo distribuido."""
import hashlib
import json
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'02_entregas/Esquema_KMZ_EFT_Corregido'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(name):
    return json.loads((OUT/name).read_text(encoding='utf-8'))


def archive(path,files,manifest=None):
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
        for file in files:
            z.write(file,file.relative_to(OUT))
    with zipfile.ZipFile(path) as z:
        assert z.testzip() is None
        if manifest:
            for name,digest in manifest['archivos'].items():
                assert hashlib.sha256(z.read(name)).hexdigest()==digest,name
        assert not any('_validacion/' in n or '__pycache__/' in n for n in z.namelist())
    print(f'{path.name}: {len(files)} archivos; CRC y SHA-256 verificados.')


def main():
    audit=read('VALIDACION_NORMALIZACION.json')
    unit=read('VALIDACION_UNITARIA_1_6.json')
    static=read('VALIDACION_NOMBRES_1_6_ESTATICA.json')
    native=read('VALIDACION_NOMBRES_1_6_ARCGIS.json')
    mapping=read('nombres_clases_1_6.json')
    model=read('esquema.json')
    assert all(x['version_paquete']=='1.6' for x in (audit,unit,static,native,mapping))
    assert model['version']==10 and len(model['clases'])==76
    assert unit['fallos']==unit['errores']==0 and unit['omitidas']==0
    assert static['pruebas_sin_fallos'] and static['generacion_repetida_identica']
    assert audit['esquema_sha256']==static['esquema_sha256']==mapping['modelo_objetivo_sha256']==sha(OUT/'esquema.json')
    assert mapping['modelo_anterior_sha256']==sha(OUT/'esquema_anterior_1_5_1.json')
    assert not native['validacion_sde']
    keys={'esquema_sha256':'esquema.json','aprobacion_sha256':'campos_aprobados_1_5.json',
          'mapeo_sha256':'nombres_clases_1_6.json','modulo_sha256':'renombrar_clases.py',
          'modulo_general_sha256':'actualizar_campos_aprobados.py',
          'modulo_reparacion_sha256':'reparar_texto_largo.py',
          'verificador_sql_sha256':'validacion_texto_sqlserver.py','toolbox_sha256':'Datos_Proyecto.pyt',
          'engine_sha256':'crear_esquema.py','runner_sha256':'datos_proyecto.py',
          'script_sha256':'probar_nombres_1_6_arcgis.py'}
    for key,name in keys.items():
        assert native[key]==sha(OUT/name),name
    for key in ('nombres_validos_en_gdb_local','relaciones_nombres_validos',
        'renombrado_nativo_verificado','aliases_verificados','preservacion_campos_y_metadatos',
        'clases_permanecen_vacias','repeticion_sin_cambios','fuente_original_sin_cambios',
        'reparacion_reconoce_nombre_nuevo','lote_general_reconoce_nombres_nuevos',
        'toolbox_cargada_y_parametros_verificados'):
        assert native[key],key
    for name,digest in unit['archivos_sha256'].items():
        assert sha(OUT/name)==digest,name
    for name,digest in static['archivos_fuente_sha256'].items():
        assert sha(ROOT/'03_scripts'/name)==digest,name
    for name,spec in audit['fuentes'].items():
        assert sha(ROOT/'inventario_kmz_resumen'/name)==spec['sha256'],name
    names='''Datos_Proyecto.pyt datos_proyecto.py crear_esquema.py normalizacion_kmz.py
ajustar_tipos_estructuras.py actualizar_campos_aprobados.py reparar_texto_largo.py
validacion_texto_sqlserver.py renombrar_clases.py esquema.json esquema_anterior_1_5_1.json
nombres_clases_1_6.json nombres_clases_1_6.csv catalogo_clases.csv
GUIA_DATOS_PROYECTO.md NORMALIZACION_EFT.md CAMBIOS_1_6.md
equivalencias_nombres.csv revision_equivalencias.csv campos_por_ruta.csv
campos_matriz_a_esquema.csv mapeo_capas_revision.csv revision_tipos.csv relaciones_negocio.csv
REVISION_CAMPOS_EFT.md REVISION_CAMPOS_EFT.json
tipos_estructuras_aprobados.json decision_tipos_estructuras.csv PERFIL_ESTRUCTURAS_ORIGEN.json
campos_aprobados_1_5.json plan_actualizacion_1_5.csv PERFIL_GENERAL_ORIGEN.json
DIAGNOSTICO_OFICINAS_ORIGEN.json PROPUESTA_MAPEO_OFICINAS.csv
VALIDACION_NORMALIZACION.json VALIDACION_NOMBRES_1_6_ESTATICA.json
VALIDACION_UNITARIA_1_6.json VALIDACION_NOMBRES_1_6_ARCGIS.json probar_nombres_1_6_arcgis.py
VALIDACION_REPARACION_1_5_1_ARCGIS.json VALIDACION_ACTUALIZACION_1_5_ARCGIS.json
VALIDACION_TIPOS_ESTRUCTURAS_ARCGIS.json'''.split()
    names += [p.name for p in sorted(OUT.glob('test_*.py'))]
    assert len(set(names))==len(names)
    manifest=dict(version='1.6',version_modelo=10,clases_revisadas=76,
        renombres_fisicos=sum(r['renombrar'] for r in mapping['clases']),
        nombres_conservados=sum(not r['renombrar'] for r in mapping['clases']),
        aliases_descriptivos=sum(r['alias'] is not None for r in mapping['clases']),
        pruebas_unitarias=unit['pruebas'],pruebas_nomenclatura=static['pruebas_nomenclatura'],
        pruebas_reglas_inventario=static['pruebas_reglas_inventario'],validacion_sde=False,
        validacion_arcgis='VALIDACION_NOMBRES_1_6_ARCGIS.json',alcance_arcgis=native['alcance'],
        fuentes=audit['fuentes'],
        validaciones_historicas=['VALIDACION_REPARACION_1_5_1_ARCGIS.json',
            'VALIDACION_ACTUALIZACION_1_5_ARCGIS.json','VALIDACION_TIPOS_ESTRUCTURAS_ARCGIS.json'],
        archivos={name:sha(OUT/name) for name in names})
    (OUT/'MANIFIESTO_DATOS_PROYECTO.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    files=[OUT/name for name in names]+[OUT/'MANIFIESTO_DATOS_PROYECTO.json']
    for name in ('Datos_Proyecto_Controlado.zip','Datos_Proyecto_Controlado_v1_6.zip'):
        archive(OUT.parent/name,files,manifest)
    wrappers=sorted((OUT/'por_clase').glob('*.py'))
    assert {p.stem for p in wrappers}=={c['nombre'] for c in model['clases']}
    archive(OUT.parent/'Esquema_KMZ_EFT_Corregido.zip',files+wrappers,manifest)


if __name__=='__main__':
    main()
