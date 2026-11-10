"""Registra pruebas de procedencia, confirmacion y generacion determinista 1.7."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import unittest

import generar_esquema_kmz_eft_corregido as generator
import auditar_normalizacion_kmz as audit

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'02_entregas/Esquema_KMZ_EFT_Corregido'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    artifacts = ['esquema.json','textos_confirmados_1_7.json','nombres_clases_1_6.json',
        'campos_aprobados_1_5.json','campos_matriz_a_esquema.csv','campos_por_ruta.csv',
        'revision_tipos.csv','VALIDACION_NORMALIZACION.json','mapeo_capas_revision.csv']
    before = {name:sha(OUT/name) for name in artifacts}
    source = ROOT/'inventario_kmz_resumen/inventario_kmz_matriz_campos.csv'
    original = source.read_bytes()
    source_mtime = source.stat().st_mtime_ns
    with contextlib.redirect_stdout(io.StringIO()):
        generator.build()
        audit.main()
    assert before == {name:sha(OUT/name) for name in artifacts}, 'Generacion no determinista.'
    assert source.read_bytes() == original and source.stat().st_mtime_ns == source_mtime
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream,verbosity=2).run(
        unittest.defaultTestLoader.discover(str(ROOT/'03_scripts'),pattern='test_*.py'))
    assert result.wasSuccessful() and not result.skipped,stream.getvalue()
    sources = sorted(path for path in (ROOT/'03_scripts').glob('test_*.py')) + [
        ROOT/'03_scripts'/name for name in ('validar_generacion_1_7.py',
        'generar_esquema_kmz_eft_corregido.py','aplicar_confirmacion_textos.py',
        'fuentes_inventario_verificadas.py','aplicar_nombres_clases.py','auditar_normalizacion_kmz.py')]
    report = dict(version_paquete='1.7',estado='OK',pruebas=result.testsRun,
        errores=len(result.errors),fallos=len(result.failures),omitidas=len(result.skipped),
        model_sha256=sha(OUT/'esquema.json'),generacion_determinista=True,
        matriz_actual_conservada=True,matriz_actual_sha256=sha(source),
        artefactos_sha256=before,archivos_sha256={str(path.relative_to(ROOT)).replace('\\','/'):sha(path) for path in sources},
        salida=stream.getvalue(),validacion_sde=False)
    (OUT/'VALIDACION_GENERACION_1_7.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'{result.testsRun} pruebas OK; generacion determinista; matriz actual preservada.')


if __name__ == '__main__':
    main()
