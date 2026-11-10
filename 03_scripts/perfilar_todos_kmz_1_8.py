"""Prepara evidencia completa 1.8 de los KMZ, sin modificar modelo ni geodatabase."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '02_entregas/Esquema_KMZ_EFT_Corregido'
sys.path.insert(0, str(OUT))
import validar_tipos_kmz as validator


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    model_before = sha(OUT / 'esquema.json')
    envelope = validator.build_profile(ROOT / '01_fuentes', OUT,
        emit=lambda message: print(message, flush=True))
    # Conservar tambien una lectura incompleta para diagnosticarla sin repetir
    # los trece archivos. Solo un perfil reconciliado pasa al paquete portable.
    trace = OUT / '_validacion' / ('Perfil_Bruto_1_8_' +
        datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ_') + uuid.uuid4().hex[:10] + '.json')
    with trace.open('x', encoding='utf-8') as stream:
        json.dump(envelope, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print('Lectura archivada: ' + str(trace), flush=True)
    profile = envelope['perfil']
    counts = profile['conteos']
    assert profile['estado'] == 'LECTURA_COMPLETA', counts
    assert counts['kmz_leidos'] == counts['kmz_esperados'] == 13
    assert counts['rutas_coincidentes'] == counts['rutas_esperadas'] == 3638
    assert counts['elementos_observados'] == counts['elementos_esperados'] == 279623
    assert not profile['fuentes_ausentes'] and not profile['rutas_no_inventariadas']
    snapshot = validator.write_profile_snapshot(envelope, OUT)
    folder, report = validator.run(None, model_dir=OUT, reports=OUT / '_validacion',
        emit=lambda message: print(message, flush=True))
    assert report['cobertura_completa'] and report['campos_revisados'] == 3340
    assert report['campos_tipo_pendiente'] == 730
    pending = [row for row in report['campos'] if row['tipo_pendiente_modelo']]
    assert len(pending) == 730 and all(row['tipo_destino_recomendado'] for row in pending)
    assert not report['cambios_en_modelo'] and not report['cambios_en_sde']
    assert not report['tipos_aprobados_en_esta_ejecucion'] and not report['ingesta_autorizada']
    assert sha(OUT / 'esquema.json') == model_before
    review = OUT / 'REVISION_TIPOS_KMZ_1_8.csv'
    assert not review.exists(), 'La revision ya existe; no se sobrescribe.'
    shutil.copyfile(folder / 'campos.csv', review)
    evidence = dict(version_paquete='1.8', version_modelo=11,
        estado=report['estado'], lectura_fuentes_actuales=True,
        validacion_sde=False, validacion_arcgis_en_este_ensayo=False,
        cobertura_completa=True, conteos=counts,
        campos_revisados=3340, campos_tipo_pendiente=730,
        campos_fuente_revisados=report['campos_fuente_revisados'],
        validacion_tipos_fuente=report['validacion_tipos_fuente'],
        campos_fuente_con_incidencias=report['campos_fuente_con_incidencias'],
        propuestas_pendientes=report['propuestas_pendientes'],
        tipos_recomendados_pendientes=report['tipos_recomendados_pendientes'],
        compatibilidad_tipos=dict(Counter(row['compatibilidad_tipo'] for row in report['campos'])),
        campos_con_incidencias=report['campos_con_incidencias'],
        incidencias_perfil=dict(Counter(row['codigo'] for row in profile['incidencias'])),
        fuentes=[dict(archivo=row['archivo'], sha256=row['sha256']) for row in profile['fuentes']],
        perfil_sha256=sha(snapshot), modelo_sha256=model_before,
        informe_completo=str(folder / 'resultado.json'),
        informe_completo_sha256=sha(folder / 'resultado.json'),
        cambios_en_modelo=False, cambios_en_sde=False, cambios_en_fuentes=False,
        tipos_aprobados=0, ingesta_autorizada=False,
        archivos_sha256={**envelope['referencias_sha256'],
            snapshot.name:sha(snapshot), 'PERFIL_COMPLETO_KMZ_1_8.sha256':sha(OUT / 'PERFIL_COMPLETO_KMZ_1_8.sha256'),
            review.name:sha(review), '03_scripts/perfilar_todos_kmz_1_8.py':sha(__file__)})
    (OUT / 'VALIDACION_PERFIL_COMPLETO_1_8.json').write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: evidence[key] for key in ('estado', 'conteos',
        'propuestas_pendientes', 'tipos_recomendados_pendientes',
        'campos_fuente_con_incidencias', 'incidencias_perfil')}, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
