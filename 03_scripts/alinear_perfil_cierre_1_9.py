"""Reevalua evidencia 1.8 intacta contra el modelo12; no relee XML ni toca SDE."""
import ast
import copy
import datetime as dt
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '02_entregas/Esquema_KMZ_EFT_Corregido'
sys.path.insert(0, str(OUT))
import referencia_cierre_tipos as ref
import validar_tipos_kmz as validator


def main():
    ref.read_reference(OUT)
    original_raw = (OUT / 'PERFIL_COMPLETO_KMZ_1_8.json').read_bytes()
    assert ref.sha(original_raw) == ref.PROFILE18_SHA
    original = json.loads(original_raw)
    with zipfile.ZipFile(OUT.parent / 'Datos_Proyecto_Controlado_v1_8.zip') as archive:
        manifest = json.loads(archive.read('MANIFIESTO_DATOS_PROYECTO.json'))
        for name in ('inspeccion_kmz.py', 'normalizacion_kmz.py', 'campos_por_ruta.csv', 'mapeo_capas_revision.csv'):
            assert ref.sha((OUT/name).read_bytes()) == manifest['archivos'][name], name
        functions = ('value_flags','observe_validation','evaluate_source_declaration','evaluate_field')
        old = {node.name:ast.dump(node) for node in ast.parse(archive.read('validar_tipos_kmz.py').decode('utf-8-sig')).body
               if isinstance(node,ast.FunctionDef) and node.name in functions}
        new = {node.name:ast.dump(node) for node in ast.parse((OUT/'validar_tipos_kmz.py').read_text(encoding='utf-8-sig')).body
               if isinstance(node,ast.FunctionDef) and node.name in functions}
        assert old == new and len(old) == 4, 'Cambio el analisis de valores: se requiere nueva lectura de fuentes.'
    sources = []
    for row in original['perfil']['fuentes']:
        path = Path(row['ruta_lectura'])
        assert path.is_file() and validator.digest(path) == row['sha256'], row['archivo']
        sources.append(dict(archivo=row['archivo'],sha256=row['sha256']))
    assert len(sources) == 13
    aligned = copy.deepcopy(original)
    aligned.update(version_paquete='1.9',version_modelo=12,
        generado_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
        lectura_fuentes_utc=original['generado_utc'],
        perfil_original_sha256=ref.PROFILE18_SHA,
        metodo='EVIDENCIA_DE_VALORES_1_8_INTACTA_REEVALUADA_CON_MODELO_12',
        relectura_xml=False, fuentes_reverificadas_por_sha256=True,
        referencias_sha256=validator.input_hashes(OUT))
    assert aligned['perfil'] == original['perfil']
    snapshot = validator.write_profile_snapshot(aligned, OUT)
    folder, report = validator.run(None, model_dir=OUT, reports=OUT/'_validacion', emit=print)
    assert report['campos_revisados'] == 3340 and report['campos_tipo_pendiente'] == 0
    assert report['cobertura_completa'] and report['campos_con_incidencias'] == 4
    assert not report['ingesta_autorizada'] and report['estado'] == 'VALIDACION_TIPOS_COMPLETA_CON_PENDIENTES'
    result = dict(version_paquete='1.9',version_modelo=12,estado=report['estado'],
        campos_revisados=3340,campos_tipo_provisional=0,incidencias_de_valores_o_mapeo=4,
        fuentes=sources,fuentes_reverificadas_por_sha256=True,relectura_xml=False,
        evidencia_valores_identica=True,perfil_original_sha256=ref.PROFILE18_SHA,
        perfil_alineado_sha256=validator.digest(snapshot),
        informe_evaluacion=str(folder/'resultado.json'),
        informe_evaluacion_sha256=validator.digest(folder/'resultado.json'),
        cambios_en_sde=False,ingesta_autorizada=False,
        archivos_sha256={**validator.input_hashes(OUT),snapshot.name:validator.digest(snapshot),
            'PERFIL_COMPLETO_KMZ_1_9.sha256':validator.digest(OUT/'PERFIL_COMPLETO_KMZ_1_9.sha256'),
            '03_scripts/alinear_perfil_cierre_1_9.py':validator.digest(__file__)})
    (OUT/'VALIDACION_PERFIL_CIERRE_1_9.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Perfil1.9 listo: evidencia13KMZ intacta,3340definiciones,0provisionales,4incidencias de carga.')


if __name__ == '__main__':
    main()
