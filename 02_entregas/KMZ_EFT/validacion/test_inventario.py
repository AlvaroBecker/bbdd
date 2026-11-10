"""Pruebas del inventario XML con fixtures mínimos; sin ArcPy, SQL ni red."""
from __future__ import annotations

import contextlib
import csv
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile


SCRIPT = Path(__file__).resolve().parent.parent / "01_inventariar_kmz.py"
SPEC = importlib.util.spec_from_file_location("_inventario_kmz_test", SCRIPT)
INV = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INV)
POINT = "<Point><coordinates>-75.1,-12.1,123.4</coordinates></Point>"
LINE = "<LineString><coordinates>-75,-12,0 -76,-13,2</coordinates></LineString>"
POLYGON = "<Polygon><outerBoundaryIs><LinearRing><coordinates>-75,-12,0 -76,-12,0 -76,-13,0 -75,-12,0</coordinates></LinearRing></outerBoundaryIs></Polygon>"


def kml(body, named=True, xsi=True):
    declaration = ' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"' if xsi else ""
    root = '<kml xmlns="http://www.opengis.net/kml/2.2" xmlns:gx="http://www.google.com/kml/ext/2.2"' + declaration + ">"
    return (root + ("<Document><name>Proyecto</name>" + body + "</Document>" if named else body) + "</kml>").encode("utf-8")


def placemark(geometry=POINT, extra=""):
    return "<Placemark>" + extra + geometry + "</Placemark>"


def scan(data):
    return INV.scan_kml(io.BytesIO(data), "SHA_SOURCE", "doc.kml")


def csv_rows(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream, delimiter=";"))


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="mapline_kmz_inventory_test_")
        self.root = Path(self.temp.name).resolve()

    def tearDown(self):
        self.assertEqual(self.root.parent, Path(tempfile.gettempdir()).resolve())
        self.assertTrue(self.root.name.startswith("mapline_kmz_inventory_test_"))
        self.temp.cleanup()

    def archive(self, directory, name, members):
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / name
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as stream:
            for member, body in members.items():
                stream.writestr(member, body)
        return path

    def run_inventory(self, inputs, output):
        with contextlib.redirect_stdout(io.StringIO()), patch("socket.create_connection", side_effect=AssertionError("No debe acceder a red")):
            return INV.run(inputs, output)

    def test_nested_folder_document_and_literal_slash_path(self):
        body = "<Folder><name>Ingeniería / Predial</name><Document><name>Anidado</name><Folder><name>Subestación</name>" + placemark() + "</Folder></Document></Folder>"
        folders, groups, objects, stats, _ = scan(kml(body))
        self.assertEqual(stats["Document"], 2)
        self.assertEqual(stats["Folder"], 2)
        self.assertEqual(groups[0]["path_parts"], ["Proyecto", "Ingeniería / Predial", "Anidado", "Subestación"])
        leaf = next(folder for folder in folders if folder["name"] == "Subestación")
        self.assertEqual(json.loads(leaf["ruta_componentes_json"]), groups[0]["path_parts"])
        self.assertEqual(leaf["placemarks_directos"], 1)
        self.assertEqual(objects, [])

    def test_mixed_geometry_placemarks_and_components_are_distinct(self):
        geometry = "<MultiGeometry>" + POINT + POINT + LINE + POLYGON + "</MultiGeometry>"
        _, groups, _, stats, _ = scan(kml(placemark(geometry)))
        self.assertEqual(stats["Placemark"], 1)
        self.assertEqual(stats["Placemark_MultiGeometry"], 1)
        self.assertEqual(stats["Placemark_geometria_mixta"], 1)
        self.assertEqual(stats["Asignaciones_geometria"], 3)
        self.assertEqual({g["geometry"]: g["partes"] for g in groups}, {"PUNTO": 2, "LINEA": 1, "POLIGONO": 1})
        self.assertEqual(sum(g["placemarks"] for g in groups), 3)

    def test_multipart_same_geometry_is_not_mixed(self):
        _, groups, _, stats, _ = scan(kml(placemark("<MultiGeometry>" + POINT + POINT + "</MultiGeometry>")))
        self.assertEqual(stats.get("Placemark_geometria_mixta", 0), 0)
        self.assertEqual(len(groups), 1)
        self.assertEqual((groups[0]["placemarks"], groups[0]["partes"], groups[0]["multi"]), (1, 2, 1))

    def test_root_placemark_without_document_is_inventoried(self):
        folders, groups, _, stats, _ = scan(kml(placemark(), named=False))
        self.assertEqual(folders, [])
        self.assertEqual(groups[0]["container"], 0)
        self.assertEqual(groups[0]["path_parts"], [])
        self.assertEqual(stats["Placemark"], 1)

    def test_models_tracks_and_overlays_remain_separate(self):
        body = placemark("<Model><Location><longitude>-75</longitude><latitude>-12</latitude></Location></Model>")
        body += placemark("<gx:Track><when>2026-01-01T00:00:00Z</when><gx:coord>-75 -12 2</gx:coord></gx:Track>")
        body += "".join("<" + kind + "><name>Objeto</name></" + kind + ">" for kind in INV.OTHER_FEATURES)
        _, groups, objects, stats, _ = scan(kml(body))
        self.assertEqual({group["geometry"] for group in groups}, {"MODELO_3D", "TRAZA_GX"})
        self.assertEqual({obj["tipo"] for obj in objects}, INV.OTHER_FEATURES)
        self.assertEqual(stats["Placemark"], 2)
        self.assertTrue(all(stats[kind] == 1 for kind in INV.OTHER_FEATURES))
        self.assertTrue(all(INV.candidate("Torres", group["geometry"])[0] == "" for group in groups))

    def test_unknown_geometry_has_no_automatic_candidate(self):
        _, groups, _, stats, _ = scan(kml(placemark("<gx:UnknownGeometry/>")))
        self.assertEqual(groups[0]["geometry"], "SIN_GEOMETRIA")
        self.assertEqual(groups[0]["partes"], 0)
        self.assertEqual(stats["Placemark"], 1)
        self.assertEqual(INV.candidate("Torres", "SIN_GEOMETRIA")[0], "")

    def test_description_and_extendeddata_export_labels_not_fixture_values(self):
        html = lambda name: "<table><tr><th>Field Name</th><th>Value</th></tr><tr><td>" + name + "</td><td>VALOR_SECRETO</td></tr></table>"
        extra = "<description><![CDATA[" + html("Etiqueta descripción") + "]]></description>"
        extra += "<ExtendedData><Data name='RAW_A'><value>VALOR_SECRETO_A</value></Data><SchemaData>"
        extra += "<SimpleData name='RAW_B'>VALOR_SECRETO_B</SimpleData>"
        extra += "<SimpleData name='HTML_B'><![CDATA[" + html("Etiqueta SimpleData") + "]]></SimpleData></SchemaData>"
        extra += "<Data name='HTML_A'><value><![CDATA[" + html("Etiqueta Data") + "]]></value></Data></ExtendedData>"
        _, groups, _, stats, _ = scan(kml(placemark(extra=extra)))
        self.assertEqual(groups[0]["fields"], {"RAW_A", "RAW_B", "HTML_A", "HTML_B"})
        self.assertEqual(groups[0]["html_fields"], {"Etiqueta descripción", "Etiqueta SimpleData", "Etiqueta Data"})
        self.assertNotIn("VALOR_SECRETO", repr(groups))
        self.assertEqual(stats["Placemark_con_HTML_en_ExtendedData"], 1)
        self.assertEqual(stats["Placemark_con_tabla_HTML"], 1)

    def test_html_nested_rows_do_not_crash_or_invert_labels(self):
        parser = INV.PopupFields()
        parser.feed("<table><tr><td><table><tr><td>CODIGO</td><td>VALOR_SECRETO</td></tr></table></td></tr></table>")
        parser.close()
        self.assertEqual(parser.rows, ["CODIGO"])

    def test_html_omitted_td_close_keeps_label_before_value(self):
        parser = INV.PopupFields()
        parser.feed("<table><tr><td>CODIGO<td>VALOR_SECRETO</tr></table>")
        parser.close()
        self.assertEqual(parser.rows, ["CODIGO"])

    def test_incomplete_html_does_not_throw(self):
        for html in ("<table><tr><td>CODIGO<td>VALOR", "<table><tr><td><table><tr><td>C<td>V</table>"):
            parser = INV.PopupFields()
            parser.feed(html)
            parser.close()

    def test_namespace_patch_is_read_only_and_existing_declaration_not_repeated(self):
        data = kml(placemark(extra="<ExtendedData xsi:schemaLocation='dummy'/>"), xsi=False)
        before = hashlib.sha256(data).hexdigest()
        result = scan(data)
        self.assertTrue(result[-1])
        self.assertEqual(result[3]["Placemark"], 1)
        self.assertEqual(hashlib.sha256(data).hexdigest(), before)
        self.assertFalse(scan(kml(placemark(), xsi=True))[-1])

    def test_completed_placemarks_are_removed_from_document_during_stream(self):
        count = 2000
        data = kml("".join(placemark(extra="<name>Elemento</name>") for _ in range(count)))
        original = INV.ET.iterparse
        document = []
        retained = []
        def tracked(*args, **kwargs):
            for event, elem in original(*args, **kwargs):
                if event == "start" and INV.local(elem.tag) == "Document":
                    document.append(elem)
                if event == "end" and INV.local(elem.tag) == "Placemark":
                    retained.append(sum(INV.local(child.tag) == "Placemark" for child in document[0]))
                yield event, elem
        with patch.object(INV.ET, "iterparse", tracked):
            _, groups, _, stats, _ = scan(data)
        self.assertEqual(stats["Placemark"], count)
        self.assertEqual(groups[0]["placemarks"], count)
        self.assertLess(max(retained), count // 2, "Se retienen todos los Placemarks bajo Document.")
        self.assertEqual(len(document[0]), 0)

    def test_identical_files_deduplicated_but_equal_entities_from_distinct_sources_kept(self):
        first = self.archive(self.root / "a", "Proyecto A.kmz", {"doc.kml": kml(placemark())})
        duplicate = self.root / "b" / "copia.kmz"
        duplicate.parent.mkdir()
        duplicate.write_bytes(first.read_bytes())
        second = self.archive(self.root / "b", "Proyecto B.kmz", {"doc.kml": kml("<Folder><name>Otro</name>" + placemark() + "</Folder>")})
        originals = {path: INV.digest(path) for path in (first, duplicate, second)}
        output = self.root / "out"
        self.assertEqual(self.run_inventory([first.parent, duplicate.parent], output), 0)
        control = json.loads((output / "control_inventario.json").read_text(encoding="utf-8"))
        self.assertEqual((control["archivos_fisicos"], control["fuentes_unicas"], len(control["copias_identicas"])), (3, 2, 1))
        self.assertEqual(control["totales"]["Placemark"], 2)
        self.assertEqual({path: INV.digest(path) for path in originals}, originals)

    def test_no_mapping_approved_and_no_sql_project_or_analysis_ids_invented(self):
        body = "<Folder><name>Subestación</name>" + placemark() + "</Folder>"
        self.archive(self.root / "input", "Proyecto PRY-00000099.kmz", {"doc.kml": kml(body)})
        output = self.root / "out"
        self.assertEqual(self.run_inventory([self.root / "input"], output), 0)
        rows = csv_rows(output / "03_matriz_mapeo_EFT.csv")
        self.assertEqual(rows[0]["clase_candidata"], "Subestacion")
        for row in rows:
            self.assertEqual(row["estado_revision"], "PENDIENTE")
            self.assertTrue(all(row[field] == "" for field in ("incluir_aprobado", "dataset_aprobado", "clase_aprobada", "co_proyecto_validado", "id_componente_validado", "id_alternativa_validado", "id_analisis_validado")))
        control = json.loads((output / "control_inventario.json").read_text(encoding="utf-8"))
        self.assertEqual(control["filas_aprobadas_para_carga"], 0)
        self.assertTrue((output / "05_resumen_candidatos.csv").exists())

    def test_multiple_kml_members_have_separate_identity(self):
        self.archive(self.root / "input", "multiple.kmz", {"doc.kml": kml(placemark()), "sub/otro.kml": kml(placemark())})
        output = self.root / "out"
        self.assertEqual(self.run_inventory([self.root / "input"], output), 0)
        rows = csv_rows(output / "03_matriz_mapeo_EFT.csv")
        self.assertEqual({row["kml"] for row in rows}, {"doc.kml", "sub/otro.kml"})
        self.assertEqual(len({(row["source_id"], row["kml"], row["carpeta_id"]) for row in rows}), 2)

    def test_invalid_second_member_does_not_accept_partial_file(self):
        self.archive(self.root / "input", "broken.kmz", {"doc.kml": kml(placemark()), "bad.kml": b"<kml><Document>"})
        output = self.root / "out"
        self.assertEqual(self.run_inventory([self.root / "input"], output), 1)
        control = json.loads((output / "control_inventario.json").read_text(encoding="utf-8"))
        self.assertEqual(control["archivos"][0]["estado"], "ERROR")
        self.assertTrue(control["errores"])
        self.assertEqual(control["grupos_mapeo"], 0)
        self.assertEqual(control["totales"].get("Placemark", 0), 0)

    def test_existing_output_and_output_inside_input_are_rejected(self):
        self.archive(self.root / "input", "base.kmz", {"doc.kml": kml(placemark())})
        existing = self.root / "existing"
        existing.mkdir()
        sentinel = existing / "sentinel.txt"
        sentinel.write_text("sin cambios")
        with self.assertRaises(FileExistsError):
            self.run_inventory([self.root / "input"], existing)
        self.assertEqual(sentinel.read_text(), "sin cambios")
        with self.assertRaises(ValueError):
            self.run_inventory([self.root / "input"], self.root / "input" / "output")

    def test_duplicate_sibling_folder_names_keep_distinct_container_ids(self):
        branch = "<Folder><name>Ríos</name>" + placemark() + "</Folder>"
        folders, groups, _, stats, _ = scan(kml(branch + branch))
        self.assertEqual(len(groups), 2)
        self.assertEqual(len({group["container"] for group in groups}), 2)
        self.assertEqual(stats["Placemark"], 2)
        self.assertEqual(sum(folder["placemarks_directos"] for folder in folders), 2)


def main():
    log = io.StringIO()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(InventoryTests)
    result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    report = {"status": "PASS" if result.wasSuccessful() else "FAIL", "tests_run": result.testsRun,
              "failures": [{"test": str(test), "traceback": trace} for test, trace in result.failures],
              "errors": [{"test": str(test), "traceback": trace} for test, trace in result.errors],
              "analyzer_sha256": hashlib.sha256(SCRIPT.read_bytes()).hexdigest(),
              "test_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "uses_arcpy": False, "accesses_sql": False, "uses_network": False,
              "scope": "Fixtures XML/KMZ pequeños y stream de 2000 Placemarks; no valida geometrías GIS ni aprueba mapeos.",
              "unittest_output": log.getvalue()}
    output = Path(__file__).with_name("resultado_inventario.json")
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{report['status']}: {result.testsRun} pruebas, {len(result.failures)} fallos y {len(result.errors)} errores. {output}")
    if not result.wasSuccessful():
        print(log.getvalue(), file=sys.stderr)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
