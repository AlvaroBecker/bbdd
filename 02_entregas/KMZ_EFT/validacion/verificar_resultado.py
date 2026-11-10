"""Comprobar el inventario real y los originales sin ArcPy ni SQL."""
from collections import Counter
import csv
import datetime as dt
import hashlib
import json
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
OUT = BASE / "inventario"
WORKSPACE = BASE.parent.parent


def original_path(value):
    path = Path(value)
    if path.parent == WORKSPACE / "kmz":
        return WORKSPACE / "01_fuentes" / "kmz" / path.name
    return path


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_csv(name):
    with (OUT / name).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream, delimiter=";"))


control = json.loads((OUT / "control_inventario.json").read_text(encoding="utf-8"))
tests = json.loads((BASE / "validacion/resultado_inventario.json").read_text(encoding="utf-8"))
assert tests["status"] == "PASS" and tests["tests_run"] == 18 and not tests["failures"] and not tests["errors"]
assert tests["analyzer_sha256"] == sha(BASE / "01_inventariar_kmz.py")
assert not control["errores"] and control["fuentes_unicas"] == 13 and control["archivos_fisicos"] == 22
assert len(control["copias_identicas"]) == 9
assert control["totales"]["Placemark"] == 279623 and control["diferencia_placemarks_vs_279623_eft"] == 0
assert control["filas_aprobadas_para_carga"] == 0
files = read_csv("01_archivos.csv")
folders = read_csv("02_carpetas.csv")
mapping = read_csv("03_matriz_mapeo_EFT.csv")
objects = read_csv("04_objetos_no_placemark.csv")
themes = read_csv("05_resumen_candidatos.csv")
assert len(files) == 13 and sum(int(row["Placemark"]) for row in files) == 279623
assert len(folders) == 3400 and Counter(row["kind"] for row in folders) == {"Folder": 3146, "Document": 254}
folder_ids = {(row["source_id"], row["kml"], row["id"]) for row in folders}
assert len(folder_ids) == len(folders)
for row in folders:
    assert isinstance(json.loads(row["ruta_componentes_json"]), list)
    if row["parent"]:
        assert (row["source_id"], row["kml"], row["parent"]) in folder_ids
assert len(mapping) == control["grupos_mapeo"] == 3655
assert sum(int(row["placemarks"]) for row in mapping) == control["totales"]["Asignaciones_geometria"]
assert len({(r["source_id"], r["kml"], r["carpeta_id"], r["geometria"]) for r in mapping}) == len(mapping)
for row in mapping:
    if row["carpeta_id"] != "0":
        assert (row["source_id"], row["kml"], row["carpeta_id"]) in folder_ids
    assert row["estado_revision"] == "PENDIENTE"
    assert all(not row[field] for field in ["incluir_aprobado", "dataset_aprobado", "clase_aprobada", "co_proyecto_validado",
                                          "id_componente_validado", "id_alternativa_validado", "id_analisis_validado"])
assert Counter(row["tipo"] for row in objects) == {"GroundOverlay": 342, "ScreenOverlay": 8}
assert sum(int(row["placemarks"]) for row in themes) == sum(int(row["placemarks"]) for row in mapping)
for source in control["archivos"]:
    assert source["estado"] == "OK" and sha(original_path(source["ruta"])) == source["sha256"]
for duplicate in control["copias_identicas"]:
    assert sha(original_path(duplicate["copia"])) == duplicate["sha256"]
report = {"status": "PASS", "fecha_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
          "fuentes_unicas": 13, "copias_identicas_verificadas": 9, "hashes_originales_sin_cambios": True,
          "placemarks": 279623, "coincide_cifra_eft": True, "folders_xml": 3146, "documents_xml": 254,
          "grupos_mapeo": 3655, "filas_aprobadas": 0, "geometrias_gis_validadas": False,
          "carga_sql_ejecutada": False, "herramienta_original_modificada": False,
          "tests": {"run": 18, "failures": 0, "errors": 0},
          "archivos_sha256": {str(p.relative_to(BASE)): sha(p) for p in sorted(OUT.iterdir()) if p.is_file()},
          "analyzer_sha256": sha(BASE / "01_inventariar_kmz.py")}
(BASE / "VALIDACION.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print("PASS: 13 KMZ, 279623 Placemarks, 3655 grupos; hashes de 22 archivos intactos y cero filas aprobadas.")
