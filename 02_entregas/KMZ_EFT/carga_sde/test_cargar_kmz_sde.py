import csv
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET
import zipfile

import cargar_kmz_sde as loader


CHANCHAMAYO = "2d83ff1278edfaccce46f8d654c134b5827f817fbafb4a2421e9a2266e6cf8af"
KML = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
<Document><name>Origen</name><Folder><name>LT / Sector</name>
<Placemark id="a"><name>T01</name>
<description><![CDATA[<table><tr><td>Texto</td><td>Perú & torre</td></tr></table>]]></description>
<ExtendedData><Data name="Set"><value>2</value></Data></ExtendedData>
<MultiGeometry><Point><altitudeMode>absolute</altitudeMode><coordinates>-70,-10,5</coordinates></Point>
<LineString><coordinates>-70,-10,5 -71,-11,6</coordinates></LineString></MultiGeometry>
</Placemark><Placemark><name>T01</name><Point><coordinates>-71,-11,6</coordinates></Point></Placemark>
<Placemark><description>Sin nombre</description><Point><coordinates>-72,-12,7</coordinates></Point></Placemark>
<GroundOverlay><name>Imagen</name><Icon><href>files/map.png</href></Icon></GroundOverlay>
</Folder></Document></kml>"""


class LoaderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_report_retries_temporary_windows_lock(self):
        path = self.root / "informe.json"
        path.write_text('{"previous": true}', encoding="utf-8")
        original_replace = Path.replace
        calls = []

        def locked_then_available(source, destination):
            calls.append(destination)
            if len(calls) <= 2:
                raise PermissionError("WinError 5")
            return original_replace(source, destination)

        with patch.object(Path, "replace", locked_then_available), \
                patch.object(loader.time, "sleep") as sleep, \
                self.assertLogs(loader.LOG, level="WARNING"):
            loader.save_json(path, {"state": "VALIDADO"})
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"state": "VALIDADO"})
        self.assertEqual(sleep.call_count, 2)
        self.assertFalse(path.with_suffix(".json.tmp").exists())

    def test_persistent_report_lock_preserves_both_versions_and_fails(self):
        path = self.root / "informe.json"
        previous = '{"previous": true}'
        path.write_text(previous, encoding="utf-8")
        with patch.object(Path, "replace", side_effect=PermissionError("WinError 5")) as replace, \
                patch.object(loader.time, "sleep"), self.assertLogs(loader.LOG, level="WARNING"):
            with self.assertRaisesRegex(PermissionError, "tras 6 intentos"):
                loader.save_json(path, {"state": "NUEVO"})
        self.assertEqual(replace.call_count, 6)
        self.assertEqual(path.read_text(encoding="utf-8"), previous)
        self.assertEqual(json.loads(path.with_suffix(".json.tmp").read_text(encoding="utf-8")),
                         {"state": "NUEVO"})

    def test_error_reporting_failure_does_not_hide_original_error(self):
        api = SimpleNamespace(env=SimpleNamespace(), GetInstallInfo=Mock())
        with patch.dict("sys.modules", {"arcpy": api}), \
                patch.object(loader, "discover", side_effect=ValueError("ORIGINAL TEST ERROR")), \
                patch.object(loader, "save_json", side_effect=PermissionError("REPORT TEST ERROR")):
            code = loader.main(["--salida", str(self.root / "execution"), "--solo-preparar"])
        self.assertEqual(code, 1)
        log = (self.root / "execution" / "ejecucion.log").read_text(encoding="utf-8")
        self.assertIn("ORIGINAL TEST ERROR", log)
        self.assertIn("REPORT TEST ERROR", log)

    def test_logging_setup_failure_releases_execution_lock(self):
        output = self.root / "execution"
        with patch.object(loader.logging, "FileHandler", side_effect=PermissionError("log blocked")), \
                self.assertLogs(loader.LOG, level="ERROR"):
            self.assertEqual(loader.main(["--salida", str(output), "--solo-preparar"]), 1)
        self.assertFalse((output / ".ejecucion.lock").exists())

    def test_resume_validation_returns_snapshot_without_replacing_checkpoint(self):
        output = self.root / "prior"
        output.mkdir()
        sha = "a" * 64
        checkpoint = {"sources": [{"sha256": sha}], "targets": [], "state": "INICIADO"}
        loader.save_json(output / "informe.json", checkpoint)
        db = loader.connect_cache(output / "trazabilidad.sqlite")
        db.close()
        row = {"sha256": sha, "archivo": "one.kmz", "path": str(self.root / "one.kmz"),
               "Placemark": 3, "nombre_sde": "one"}
        api = SimpleNamespace(env=SimpleNamespace(), GetInstallInfo=Mock(return_value={}))
        reports = []
        with patch.dict("sys.modules", {"arcpy": api}), \
                patch.object(loader, "discover", return_value=([row], [])), \
                patch.object(loader, "verify_workspace"), patch.object(loader, "verify_targets_absent"):
            code = loader.main(["--reanudar", str(output)], result_reports=reports)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads((output / "informe.json").read_text(encoding="utf-8")), checkpoint)
        self.assertEqual(len(reports), 1)
        self.assertTrue(reports[0].name.startswith("validacion_"))
        self.assertEqual(json.loads(reports[0].read_text(encoding="utf-8"))["state"],
                         "VALIDACION_PREVIA_SIN_CARGA")

    def archive(self, name="fuente.kmz", kml=KML):
        path = self.root / name
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("doc.kml", kml)
            archive.writestr("files/map.png", b"resource-original")
        return path

    def test_traceability_and_original_attributes(self):
        source = self.archive()
        before = source.read_bytes()
        sha = loader.digest(source)
        db = loader.connect_cache(self.root / "audit.sqlite")
        try:
            result = loader.prepare_archive(source, self.root / "derivado.kmz", db, sha)
            self.assertEqual(source.read_bytes(), before)
            self.assertEqual(result["counts"]["Placemark"], 3)
            self.assertEqual(result["counts"]["GroundOverlay"], 1)
            records = db.execute("SELECT id, kind, name, payload FROM originals ORDER BY ordinal, kind").fetchall()
            self.assertEqual(len(records), 4)
            payload = json.loads(db.execute(
                "SELECT payload FROM originals WHERE kind='Placemark' AND ordinal=1").fetchone()[0])
            self.assertEqual([x["name"] for x in payload["containers"]], ["Origen", "LT / Sector"])
            self.assertEqual(payload["geometry_counts"], {"MultiGeometry": 1, "Point": 1, "LineString": 1})
            self.assertEqual(payload["altitude_modes"], ["absolute"])
            self.assertTrue(any("Perú &amp; torre" in item for item in payload["attribute_xml"]))
            self.assertTrue(any("ExtendedData" in item and ">2<" in item for item in payload["attribute_xml"]))
            with zipfile.ZipFile(self.root / "derivado.kmz") as archive:
                self.assertEqual(archive.read("files/map.png"), b"resource-original")
                tree = ET.fromstring(archive.read("doc.kml"))
            namespace = {"k": "http://www.opengis.net/kml/2.2"}
            placemarks = tree.findall(".//k:Placemark", namespace)
            self.assertEqual([pm.find("k:name", namespace).text for pm in placemarks],
                             [loader.feature_id(sha, 1, "Placemark", i) for i in [1, 2, 3]])
            self.assertEqual(placemarks[0].find("k:description", namespace).text,
                             "<table><tr><td>Texto</td><td>Perú & torre</td></tr></table>")
        finally:
            db.close()

    def test_namespace_repair_is_only_in_derived_copy(self):
        original = KML.replace("<Point>", '<Point xsi:type="x">', 1)
        source = self.archive(kml=original)
        db = loader.connect_cache(self.root / "audit.sqlite")
        try:
            loader.prepare_archive(source, self.root / "derivado.kmz", db, loader.digest(source))
            with zipfile.ZipFile(source) as archive:
                self.assertNotIn(b"xmlns:xsi", archive.read("doc.kml"))
            with zipfile.ZipFile(self.root / "derivado.kmz") as archive:
                ET.fromstring(archive.read("doc.kml"))
        finally:
            db.close()

    def test_discovery_uses_hash_not_name_and_deduplicates(self):
        source = self.archive()
        sha = loader.digest(source)
        (self.root / "copia.kmz").write_bytes(source.read_bytes())
        manifest = self.root / "inventario.csv"
        with manifest.open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.DictWriter(stream, fieldnames=["archivo", "sha256", "Placemark"], delimiter=";")
            writer.writeheader()
            writer.writerow({"archivo": "nombre_diferente.kmz", "sha256": sha, "Placemark": 3})
        rows, ignored = loader.discover(manifest, [self.root], [])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["sha256"], sha)
        self.assertEqual(ignored, [])
        with self.assertRaises(ValueError):
            loader.discover(manifest, [self.root], ["a" * 64])
        source.write_bytes(b"changed")
        (self.root / "copia.kmz").write_bytes(b"changed")
        with self.assertRaises(FileNotFoundError):
            loader.discover(manifest, [self.root], [])

    def test_select_one_file_does_not_require_other_inventory_sources(self):
        source = self.archive()
        sha = loader.digest(source)
        manifest = self.root / "inventario.csv"
        with manifest.open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.DictWriter(stream, fieldnames=["archivo", "sha256", "Placemark"], delimiter=";")
            writer.writeheader()
            writer.writerow({"archivo": "fuente.kmz", "sha256": sha, "Placemark": 3})
            writer.writerow({"archivo": "faltante.kmz", "sha256": "b" * 64, "Placemark": 1})
        rows, _ = loader.discover(manifest, [self.root], [], [source])
        self.assertEqual([row["sha256"] for row in rows], [sha])
        with self.assertRaises(FileNotFoundError):
            loader.discover(manifest, [self.root], [])
        with self.assertRaisesRegex(ValueError, "dentro"):
            loader.discover(manifest, [self.root], [], [self.root.parent / "fuera.kmz"])
        unknown = self.archive("desconocido.kmz", KML.replace("T01", "T99"))
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            loader.discover(manifest, [self.root], [], [unknown])

    def test_resume_accepts_only_verified_prior_sde_loads(self):
        for state in ["INICIADO", "ERROR"]:
            with self.assertRaisesRegex(RuntimeError, "SDE"):
                loader.check_resume_report({"sources": [{}], "targets": [{"state": "VERIFICADO"},
                                                                         {"state": state}]})
        loader.check_resume_report({"sources": [{}], "targets": [{"state": "VERIFICADO"}]})
        loader.check_resume_report({"sources": [{}], "targets": []})

    def write_inventory(self, rows, fieldnames=("archivo", "sha256", "Placemark", "nombre_sde")):
        manifest = self.root / "inventario.csv"
        with manifest.open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(fieldnames), delimiter=";")
            writer.writeheader()
            writer.writerows(rows)
        return manifest

    def test_inventory_sde_names_are_readable_valid_and_unique(self):
        rows = loader.load_inventory(loader.HERE / "01_archivos.csv")
        self.assertEqual(len(rows), 13)
        names = {row["archivo"]: row["nombre_sde"] for row in rows}
        self.assertEqual(names["Proyecto CHANCHAMAYO.kmz"], "chanchamayo")
        self.assertEqual(len(set(names.values())), 13)
        self.assertEqual(loader.automatic_name("Proyecto PARIÑAS.kmz"), "parinas")
        self.assertEqual(loader.automatic_name("G1 Nueva SE Palián 22060 kV y LT.kmz"),
                         "g1_nueva_se_palian_22060_kv_y_lt")
        manifest = self.write_inventory([{"archivo": "Proyecto PALIAN.kmz", "sha256": "a" * 64, "Placemark": 1}],
                                        ("archivo", "sha256", "Placemark"))
        self.assertEqual(loader.load_inventory(manifest)[0]["nombre_sde"], "palian")
        for bad in ["Chanchamayo", "1felam", "kmz_felam", "sde_felam", "a-b", "x" * 41]:
            manifest = self.write_inventory([{"archivo": "x.kmz", "sha256": "a" * 64, "Placemark": 1,
                                              "nombre_sde": bad}])
            with self.assertRaisesRegex(ValueError, "no valido"):
                loader.load_inventory(manifest)
        manifest = self.write_inventory([
            {"archivo": "x.kmz", "sha256": "a" * 64, "Placemark": 1, "nombre_sde": "felam"},
            {"archivo": "Proyecto FELAM.kmz", "sha256": "b" * 64, "Placemark": 1, "nombre_sde": ""}])
        with self.assertRaisesRegex(ValueError, "repetido"):
            loader.load_inventory(manifest)

    def test_target_names_are_readable_and_legacy_loads_are_blocked(self):
        row = {"sha256": CHANCHAMAYO, "nombre_sde": "chanchamayo"}
        self.assertEqual(loader.target_names([row]),
                         ["chanchamayo_puntos", "chanchamayo_lineas", "chanchamayo_poligonos",
                          "chanchamayo_multipatch", "chanchamayo_multipuntos",
                          "chanchamayo_atributos", "chanchamayo_balance"])
        legacy = loader.legacy_target_names([row])
        self.assertIn("kmz_2d83ff1278ed_puntos", legacy)
        self.assertIn("kmz_3b51369d6f32_atributos", legacy)
        self.assertIn("kmz_3b51369d6f32_balance", legacy)
        sde = Path(r"C:\conexion.sde")
        arcpy = SimpleNamespace(Exists=Mock(side_effect=lambda path: path.endswith("kmz_2d83ff1278ed_lineas")))
        with self.assertRaisesRegex(RuntimeError, "Renombrar"):
            loader.verify_targets_absent(arcpy, sde, loader.target_names([row]), legacy)
        arcpy.Exists = Mock(side_effect=lambda path: path.endswith("chanchamayo_balance"))
        with self.assertRaisesRegex(RuntimeError, "ya existe"):
            loader.verify_targets_absent(arcpy, sde, loader.target_names([row]), legacy)

    def test_loaded_sources_are_derived_from_legacy_and_new_targets(self):
        other = "c" * 64
        sde = r"C:\x\SQLServer-EEPAWSDBP01-ArcGisAWS(gis).sde"
        report = {"sources": [{"sha256": CHANCHAMAYO}, {"sha256": other}, {"sha256": "d" * 64}], "targets": [
            {"path": sde + r"\ArcGisAWS.gis.kmz_2d83ff1278ed_puntos", "state": "VERIFICADO"},
            {"path": sde + r"\ArcGisAWS.gis.kmz_3b51369d6f32_atributos", "state": "VERIFICADO"},
            {"path": sde + r"\ArcGisAWS.gis.otro_lineas", "state": "VERIFICADO", "sha256": other}]}
        self.assertEqual(loader.loaded_shas(report), {CHANCHAMAYO, other})
        self.assertEqual(loader.legacy_owner(report, "kmz_3b51369d6f32_balance"), (CHANCHAMAYO, "balance"))
        self.assertIsNone(loader.legacy_owner(report, "chanchamayo_puntos"))
        with self.assertRaisesRegex(RuntimeError, "unico KMZ"):
            loader.legacy_owner(report, "kmz_ffffffffffff_atributos")

    def test_already_loaded_source_is_rejected_before_any_work(self):
        output = self.root / "prior"
        output.mkdir()
        checkpoint = {"sources": [{"sha256": CHANCHAMAYO}], "state": "CARGADO_SDE_CON_PENDIENTES_ENGIE",
                      "targets": [{"path": r"C:\c.sde\ArcGisAWS.gis.kmz_2d83ff1278ed_puntos",
                                   "state": "VERIFICADO"}]}
        loader.save_json(output / "informe.json", checkpoint)
        loader.connect_cache(output / "trazabilidad.sqlite").close()
        row = {"sha256": CHANCHAMAYO, "archivo": "Proyecto CHANCHAMAYO.kmz", "path": "x", "Placemark": 1,
               "nombre_sde": "chanchamayo"}
        api = SimpleNamespace(env=SimpleNamespace(), GetInstallInfo=Mock(return_value={}))
        before = (output / "informe.json").read_bytes()
        with patch.dict("sys.modules", {"arcpy": api}), \
                patch.object(loader, "discover", return_value=([row], [])), \
                patch.object(loader, "verify_workspace") as workspace, self.assertLogs(loader.LOG, "ERROR"):
            code = loader.main(["--reanudar", str(output), "--aplicar"])
        self.assertEqual(code, 1)
        workspace.assert_not_called()
        self.assertEqual((output / "informe.json").read_bytes(), before)
        error = json.loads(next(output.glob("error_*.json")).read_text(encoding="utf-8"))
        self.assertIn("ya se cargaron", error["error"])
        self.assertFalse((output / ".ejecucion.lock").exists())

    def test_rename_arguments_are_strict(self):
        for argv in (["--renombrar"], ["--renombrar", "--reanudar", str(self.root), "--aplicar"],
                     ["--renombrar", "--reanudar", str(self.root), "--kmz", "x.kmz"]):
            with self.assertRaisesRegex(ValueError, "renombrar"):
                loader.main(argv)

    def test_rename_stops_before_changes_when_object_is_locked(self):
        output = self.root.resolve()
        report_path = output / "informe.json"
        report = {"sources": [{"sha256": CHANCHAMAYO}], "targets": [
            {"path": str(output / "d.gdb" / "kmz_2d83ff1278ed_puntos"), "state": "VERIFICADO",
             "source": str(output / "l.gdb" / "Points"), "expected_count": 1, "actual_count": 1}]}
        loader.save_json(report_path, report)
        before = report_path.read_bytes()
        management = SimpleNamespace(GetCount=Mock(return_value=["1"]), Rename=Mock())
        arcpy = SimpleNamespace(Exists=Mock(side_effect=lambda path: path.endswith("kmz_2d83ff1278ed_puntos")),
                                TestSchemaLock=Mock(return_value=False), management=management)
        with patch.object(loader, "verify_transfer"), self.assertRaisesRegex(RuntimeError, "en uso"):
            loader.rename_loaded(arcpy, output, report, report_path, {CHANCHAMAYO: {"nombre_sde": "chanchamayo"}},
                                 output / "d.gdb", "t", enterprise=False)
        management.Rename.assert_not_called()
        self.assertEqual(report_path.read_bytes(), before)
        self.assertFalse(list(output.glob("informe_anterior_*.json")))

    def test_resumed_cache_checks_schema_and_keeps_originals(self):
        path = self.root / "cache.sqlite"
        db = loader.connect_cache(path)
        db.execute("INSERT INTO originals VALUES (?,?,?,?,?,?,?)", ("id", "sha", "doc", 1, "Placemark", "n", "{}"))
        db.commit()
        db.close()
        db = loader.connect_cache(path, resume=True)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM originals").fetchone()[0], 1)
        db.execute("DROP TABLE outputs")
        db.close()
        with self.assertRaisesRegex(RuntimeError, "incompatible"):
            loader.connect_cache(path, resume=True)

    def test_resume_never_accepts_paths_outside_execution(self):
        output = self.root.resolve()
        previous = Path(r"C:\old\execution")
        with self.assertRaisesRegex(RuntimeError, "fuera"):
            loader.contained_path(str(self.root.parent / "outside.gdb"), output, previous)
        with self.assertRaisesRegex(RuntimeError, "fuera"):
            loader.contained_path(r"..\outside.gdb", output, previous)
        expected = output / "conversion" / "points"
        self.assertEqual(loader.contained_path(str(previous / "conversion" / "points"), output, previous),
                         expected)

    def test_resume_refuses_active_or_stale_lock_without_modifying_report(self):
        output = self.root / "prior"
        output.mkdir()
        report_path = output / "informe.json"
        report_path.write_text('{"sources":[{}],"targets":[]}', encoding="utf-8")
        db = loader.connect_cache(output / "trazabilidad.sqlite")
        db.close()
        lock_path = output / ".ejecucion.lock"
        lock_path.write_text('{"pid":123}', encoding="utf-8")
        before = report_path.read_bytes()
        with self.assertRaisesRegex(RuntimeError, "bloqueada"):
            loader.main(["--reanudar", str(output), "--solo-preparar"])
        self.assertEqual(report_path.read_bytes(), before)
        self.assertTrue(lock_path.exists())

    def test_network_links_fail_explicitly(self):
        source = self.archive(kml=KML.replace("</Document>", "<NetworkLink><name>Remote</name>"
                              "<Link><href>https://invalid.example/test.kml</href></Link>"
                              "</NetworkLink></Document>"))
        db = loader.connect_cache(self.root / "audit.sqlite")
        try:
            with self.assertRaisesRegex(RuntimeError, "NetworkLink"):
                loader.prepare_archive(source, self.root / "derivado.kmz", db, loader.digest(source))
        finally:
            db.close()

    def test_payload_chunking_is_lossless_for_long_unicode(self):
        payload = json.dumps({"description": "Línea 😀" * 3000}, ensure_ascii=False)
        chunks = [payload[n:n + 2000] for n in range(0, len(payload), 2000)]
        self.assertEqual("".join(chunks), payload)
        self.assertTrue(all(len(chunk.encode("utf-16-le")) // 2 <= 4000 for chunk in chunks))

    def test_copy_error_is_reported_and_other_objects_are_attempted(self):
        class GPError(Exception):
            pass
        management = SimpleNamespace(
            CopyFeatures=Mock(side_effect=[GPError("No compatible"), None]),
            GetCount=Mock(return_value=["1"]),
        )
        arcpy = SimpleNamespace(Exists=Mock(return_value=False), management=management, ExecuteError=GPError)
        objects = [{"local": "first", "target_name": "first", "count": 1},
                   {"local": "second", "target_name": "second", "count": 1}]
        report = {"targets": []}
        with patch.object(loader, "verify_transfer"), self.assertLogs(loader.LOG, level="ERROR"):
            with self.assertRaisesRegex(RuntimeError, "1 objetos"):
                loader.copy_objects(arcpy, self.root, objects, report, self.root / "report.json", enterprise=False)
        self.assertEqual([item["state"] for item in report["targets"]], ["ERROR", "VERIFICADO"])
        self.assertEqual(management.CopyFeatures.call_count, 2)
        saved = json.loads((self.root / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(saved, report)

    def test_existing_targets_are_never_overwritten(self):
        arcpy = SimpleNamespace(Exists=Mock(return_value=True), management=Mock())
        with self.assertRaisesRegex(RuntimeError, "ya existe"):
            loader.copy_objects(arcpy, self.root, [{"local": "a", "target_name": "a", "count": 1}],
                                {"targets": []}, self.root / "report.json", enterprise=False)
        arcpy.management.CopyFeatures.assert_not_called()

    def test_sde_schema_is_checked_not_inferred_from_filename(self):
        connection = SimpleNamespace(workspaceType="RemoteDatabase",
                                     connectionProperties=SimpleNamespace(database="ArcGisAWS"))
        query = Mock()
        query.execute.return_value = [["ArcGisAWS", "dbo", "dbo"]]
        arcpy = SimpleNamespace(Exists=Mock(return_value=True), Describe=Mock(return_value=connection),
                                ArcSDESQLExecute=Mock(return_value=query))
        with self.assertRaisesRegex(RuntimeError, "esquema predeterminado gis"):
            loader.verify_workspace(arcpy, Path("connection(gis).sde"))
        query.execute.return_value = [["ArcGisAWS", "gis", "gis"]]
        loader.verify_workspace(arcpy, Path("connection(gis).sde"))


if __name__ == "__main__":
    unittest.main()
