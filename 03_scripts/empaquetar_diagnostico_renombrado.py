"""Distribuye el diagnostico de lectura con el informe original conservado."""
import hashlib
import io
import json
from pathlib import Path
import shutil
import sys
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "02_entregas/Esquema_KMZ_EFT_Corregido"
DEST = ROOT / "02_entregas/Diagnostico_Renombrado_1_6"
ORIGINAL = ROOT / "resultado.json"
ORIGINAL_SHA = "edaf5db7bd1b1b61f9ed07236c8781ca5f27e09959e5efda7edf6a59e63524a1"
FILES = (
    "Diagnostico_Renombrado.pyt", "diagnostico_renombrado.py", "crear_esquema.py",
    "datos_proyecto.py", "ajustar_tipos_estructuras.py", "validacion_texto_sqlserver.py",
    "actualizar_campos_aprobados.py", "renombrar_clases.py", "esquema.json",
    "nombres_clases_1_6.json", "campos_aprobados_1_5.json",
    "LEEME_DIAGNOSTICO_RENOMBRADO.md", "VALIDACION_DIAGNOSTICO_RENOMBRADO_ARCGIS.json",
)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    assert sha(ORIGINAL) == ORIGINAL_SHA, "El informe original no coincide."
    # La entrega de diagnostico no cambia el runtime o los ZIP de migracion 1.6.
    validation = json.loads((SOURCE / "VALIDACION_UNITARIA_1_6.json").read_text(encoding="utf-8"))
    for name, digest in validation["archivos_sha256"].items():
        assert sha(SOURCE / name) == digest, name
    native = json.loads((SOURCE / "VALIDACION_DIAGNOSTICO_RENOMBRADO_ARCGIS.json").read_text(encoding="utf-8"))
    assert native["estado"] == "SIN_DIFERENCIAS_ACTUALES" and native["mutaciones_geodatabase"] == 0
    assert native["toolbox_ejecutada"] and not native["validacion_sde"]
    assert native["informe_usuario_sha256"] == ORIGINAL_SHA
    for name, digest in native["archivos_sha256"].items():
        assert sha(SOURCE / name) == digest, name
    sys.path.insert(0, str(SOURCE))
    output = io.StringIO()
    suite = unittest.defaultTestLoader.loadTestsFromName("test_diagnostico_renombrado")
    result = unittest.TextTestRunner(stream=output, verbosity=2).run(suite)
    assert result.wasSuccessful() and not result.skipped, output.getvalue()
    unit = dict(diagnostico_version="1.6-diagnostico-1", pruebas=result.testsRun,
        fallos=len(result.failures), errores=len(result.errors), omitidas=len(result.skipped),
        validacion_sde=False, salida=output.getvalue(),
        archivos_sha256={name: sha(SOURCE / name) for name in (
            "test_diagnostico_renombrado.py", "diagnostico_renombrado.py",
            "test_renombrar_clases.py", "test_actualizar_campos_aprobados.py",
            "test_datos_proyecto.py")})
    # Validar tambien la referencia real sin importar ArcPy ni conectar a SDE.
    import diagnostico_renombrado
    original = json.loads(ORIGINAL.read_text(encoding="utf-8-sig"))
    reference = diagnostico_renombrado.read_reference(
        original["workspace"], ORIGINAL, original["database"], original["owner"])
    assert len(reference[4]) == 76
    assert original["clase_en_curso"] == "mapa_nacional_ecosistemas_minam_recorte"
    DEST.mkdir(exist_ok=True)
    for name in FILES:
        shutil.copyfile(SOURCE / name, DEST / name)
    shutil.copyfile(ORIGINAL, DEST / "resultado_origen.json")
    (DEST / "VALIDACION_DIAGNOSTICO_RENOMBRADO_UNITARIA.json").write_text(
        json.dumps(unit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    filenames = sorted((*FILES, "resultado_origen.json", "VALIDACION_DIAGNOSTICO_RENOMBRADO_UNITARIA.json"))
    manifest = dict(version="1.6-diagnostico-1", solo_lectura=True,
        informe_original_sha256=ORIGINAL_SHA, campos_del_informe_original_conservados=True,
        clases_con_referencia=76, validacion_sde=False,
        archivos_sha256={name: sha(DEST / name) for name in filenames})
    manifest_name = "MANIFIESTO_DIAGNOSTICO.json"
    (DEST / manifest_name).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    archive = DEST.with_suffix(".zip")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zipped:
        for name in filenames + [manifest_name]:
            zipped.write(DEST / name, name)
    with zipfile.ZipFile(archive) as zipped:
        assert zipped.testzip() is None
        assert len(zipped.namelist()) == len(filenames) + 1
        for name, digest in manifest["archivos_sha256"].items():
            assert hashlib.sha256(zipped.read(name)).hexdigest() == digest, name
        assert zipped.read("resultado_origen.json") == ORIGINAL.read_bytes()
    print(json.dumps({"paquete": str(archive), "archivos": len(filenames) + 1,
                      "pruebas": result.testsRun, "referencias_validadas": 76,
                      "informe_original_conservado": True, "crc_y_sha_verificados": True}))


if __name__ == "__main__":
    main()
