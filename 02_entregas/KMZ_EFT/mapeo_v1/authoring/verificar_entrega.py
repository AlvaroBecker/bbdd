"""Validar el XLSX exportado y conciliar la propuesta con el inventario recibido.

openpyxl se utiliza solo para lectura; la autoria del libro usa Artifact Tool.
"""
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import zipfile
import openpyxl
from openpyxl.formula.tokenizer import Tokenizer

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BOOK = ROOT.parent / "outputs/mapline_kmz_20261103_v1/Mapeo_KMZ_EFT_propuesta_v1.xlsx"
data = json.loads((HERE / "datos_workbook.json").read_text(encoding="utf-8"))
source = ROOT.parent / "01_fuentes" / "inventario_ArcGIS_20261103_114443"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


for name, expected in data["hashes_entrada"].items():
    assert sha(source / name) == expected, "Se modifico un archivo recibido."
with (source / "03_matriz_mapeo_EFT.csv").open(encoding="utf-8-sig", newline="") as stream:
    original = list(csv.DictReader(stream, delimiter=";"))
assert len(original) == len(data["detalle"]) == 3655
for old, proposed in zip(original, data["detalle"]):
    assert all(proposed[key] == value for key, value in old.items())
assert sum(g["placemarks"] for g in data["grupos"]) == 279623
assert sum(g["grupos_origen"] for g in data["grupos"]) == 3655
assert len(data["grupos"]) == 1403
with zipfile.ZipFile(BOOK) as archive:
    assert archive.testzip() is None
    assert len([n for n in archive.namelist() if n.startswith("xl/tables/") and n.endswith(".xml")]) == 5
formulas = openpyxl.load_workbook(BOOK, data_only=False)
cached = openpyxl.load_workbook(BOOK, data_only=True)
assert formulas.sheetnames == ["Revisión", "Proyectos", "Detalle", "MySQL"]
review = cached["Revisión"]
assert [review[ref].value for ref in ["A6", "C6", "E6", "G6", "I6", "K6"]] == [13,279623,3655,1403,0,0]
assert Counter(review.cell(row, 10).value for row in range(9,1412)) == {"Pendiente de revisión":1403}
assert all(review.cell(row, 8).value is None and review.cell(row, 9).value == "Pendiente" for row in range(9,1412))
assert all(cached["Proyectos"].cell(row, col).value is None for row in range(7,20) for col in [5,6,7])
assert formulas["Revisión"].freeze_panes == "C9"
assert formulas["Detalle"].freeze_panes == "C7"
assert len(formulas["Revisión"].data_validations.dataValidation) == 1
assert len(formulas["Proyectos"].data_validations.dataValidation) == 1
assert cached["Detalle"].max_row == 3661
assert sum(cached["Detalle"].cell(row,5).value for row in range(7,3662)) == 279623
assert sum(cached["Detalle"].cell(row,6).value for row in range(7,3662)) == 1287306
assert [cached["MySQL"].cell(row,2).value for row in range(8,48)] == [p["co"] for p in data["mysql_proyectos"]]
assert [cached["MySQL"].cell(row,1).value for row in range(53,173)] == [c["id"] for c in data["mysql_componentes"]]
formula_count = 0
for sheet in formulas:
    for row in sheet:
        for cell in row:
            if cell.data_type == "f":
                Tokenizer(cell.value)
                formula_count += 1
for sheet in cached:
    assert not [c.coordinate for row in sheet for c in row if c.data_type == "e"]
interaction = json.loads((HERE / "prueba_interaccion.json").read_text(encoding="utf-8"))
assert interaction["stateMissing"] == [["Confirmar proyecto"]]
assert interaction["statePartial"] == [["Validar atributos y vínculo"]]
assert interaction["restored"] is True
assert "matched 0 entries" in (HERE / "verificacion_errores.ndjson").read_text(encoding="utf-8")
report = {"resultado":"CORRECTO", "libro":str(BOOK), "sha256":sha(BOOK),
          "conteos":data["conteos"], "filas_recibidas_preservadas":3655,
          "columnas_originales_preservadas":len(original[0]), "columnas_derivadas_nuevas":8,
          "filas_mysql_proyectos":40, "filas_mysql_componentes":120, "formulas_analizadas":formula_count,
          "errores_formula_cache":0, "prueba_interaccion":interaction,
          "hojas_revisadas_visualmente":["Revisión","Proyectos","Detalle","MySQL"],
          "ejecucion_native_excel":False, "originales_modificados":False, "carga_sql":False,
          "carga_arcgis":False, "nuevas_aprobaciones":0}
(HERE.parent / "VALIDACION.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps({"resultado":report["resultado"],"libro":str(BOOK),"filas":3655,"grupos":1403,
                  "elementos":279623,"formulas":formula_count,"aprobaciones":0},ensure_ascii=False))
