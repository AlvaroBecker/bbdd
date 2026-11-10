"""Pruebas de importacion y ejecucion real; requieren el Python de ArcGIS Pro."""
import csv
import hashlib
import importlib.machinery
import importlib.util
import json
import logging
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
import uuid
import zipfile

import arcpy

from test_cargar_kmz_sde import CHANCHAMAYO, KML


HERE = Path(__file__).resolve().parent
MODES = ["Validar fuentes y conexion (sin cargar)",
         "Preparar solo geodatabases locales (sin SDE)",
         "Cargar a SDE (objetos nuevos en gis)",
         "Renombrar objetos ya cargados a nombres legibles"]


class ToolboxArcGISTests(unittest.TestCase):
    def test_import_and_parameters(self):
        alias = "kmzcheck" + uuid.uuid4().hex[:8]
        arcpy.ImportToolbox(str(HERE / "Mapline_KMZ_SDE.pyt"), alias)
        name = "TransferirKMZSDE_" + alias
        self.assertIn(name, arcpy.ListTools("*_" + alias))
        parameters = arcpy.GetParameterInfo(name)
        self.assertEqual(len(parameters), 8)
        self.assertTrue(parameters[0].multiValue)
        self.assertEqual(parameters[1].filter.list, MODES)
        self.assertEqual(parameters[2].filter.list, ["RemoteDatabase"])
        self.assertEqual(parameters[4].direction, "Output")
        self.assertEqual(parameters[5].direction, "Output")
        self.assertTrue(parameters[6].multiValue)
        self.assertEqual(parameters[7].name, "reanudar_ejecucion")
        source = importlib.machinery.SourceFileLoader("toolbox_parameters_test",
                                                     str(HERE / "Mapline_KMZ_SDE.pyt"))
        spec = importlib.util.spec_from_loader(source.name, source)
        module = importlib.util.module_from_spec(spec)
        source.exec_module(module)
        tool = module.TransferirKMZSDE()
        params = tool.getParameterInfo()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            (path / "sub").mkdir()
            kmz = path / "sub" / "one.KMZ"
            kmz.write_bytes(b"fixture")
            params[0].value = [str(path)]
            tool.updateParameters(params)
            self.assertEqual(params[6].filter.list, [str(kmz.resolve())])
            params[7].value = str(path)
            tool.updateParameters(params)
            self.assertFalse(params[3].enabled)
            resume = path / "ejecucion"
            resume.mkdir()
            (resume / "informe.json").write_text('{"state": "CARGADO_SDE_CON_PENDIENTES_ENGIE"}',
                                                 encoding="utf-8")
            calls = []

            def fake_main(argv, result_reports):
                calls.append(argv)
                result_reports.append(resume / "informe.json")
                return 0

            module.load_loader = lambda: SimpleNamespace(main=fake_main, LOG=logging.getLogger("fake_kmz"))
            params[1].value = MODES[3]
            params[2].value = str(path / "conexion.sde")
            params[6].values = [str(kmz.resolve())]
            params[7].value = None
            tool.updateParameters(params)
            tool.updateMessages(params)
            self.assertFalse(params[0].enabled or params[3].enabled or params[6].enabled)
            self.assertTrue(params[7].hasError())
            params[7].value = str(resume)
            tool.updateMessages(params)
            self.assertIn("trazabilidad.sqlite", params[7].message)
            (resume / "trazabilidad.sqlite").write_bytes(b"")
            params[7].clearMessage()
            tool.updateMessages(params)
            self.assertFalse(params[7].hasError(), params[7].message)
            tool.execute(params, None)
            argv = calls[0]
            self.assertEqual(argv[:2], ["--reanudar", str(resume)])
            self.assertIn("--renombrar", argv)
            self.assertEqual(argv[argv.index("--sde") + 1], str(path / "conexion.sde"))
            self.assertFalse({"--entrada", "--kmz", "--aplicar", "--solo-preparar"} & set(argv))

    def test_real_rename_of_legacy_loaded_objects(self):
        with tempfile.TemporaryDirectory(prefix="mapline_rename_") as folder:
            result = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), "--rename-worker", folder],
                capture_output=True, text=True, errors="replace", timeout=240)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def run_rename_worker(self, folder):
        import cargar_kmz_sde as loader
        root = Path(folder).resolve()
        output = root / "Mapline_KMZ_prueba"
        attempt = output / "intentos" / "t0"
        attempt.mkdir(parents=True)
        arcpy.management.CreateFileGDB(str(attempt), "preparado.gdb")
        local = attempt / "preparado.gdb"
        arcpy.management.CreateFeatureclass(str(local), "Points", "POINT",
                                            spatial_reference=arcpy.SpatialReference(4326))
        arcpy.management.AddField(str(local / "Points"), "KZ_PM_ID", "TEXT", field_length=100)
        with arcpy.da.InsertCursor(str(local / "Points"), ["KZ_PM_ID", "SHAPE@XY"]) as cursor:
            cursor.insertRow(("a", (-70.0, -10.0)))
            cursor.insertRow(("b", (-71.0, -11.0)))
        arcpy.management.CreateTable(str(local), "atributos_2d83ff1278ed")
        arcpy.management.AddField(str(local / "atributos_2d83ff1278ed"), "KZ_PM_ID", "TEXT", field_length=100)
        with arcpy.da.InsertCursor(str(local / "atributos_2d83ff1278ed"), ["KZ_PM_ID"]) as cursor:
            cursor.insertRow(("a",))
        arcpy.management.CreateFileGDB(str(root), "destino.gdb")
        dest = root / "destino.gdb"
        report_path = output / "informe.json"
        report = {"sources": [{"sha256": CHANCHAMAYO, "file": "Proyecto CHANCHAMAYO.kmz"}], "targets": [],
                  "state": "CARGADO_SDE_CON_PENDIENTES_ENGIE"}
        objects = [{"local": str(local / "Points"), "target_name": "kmz_2d83ff1278ed_puntos", "count": 2},
                   {"local": str(local / "atributos_2d83ff1278ed"), "target_name": "kmz_3b51369d6f32_atributos",
                    "count": 1, "table": True}]
        loader.copy_objects(arcpy, dest, objects, report, report_path, enterprise=False)
        for entry in report["targets"]:
            del entry["name"], entry["sha256"]
        loader.save_json(report_path, report)
        inventory = {row["sha256"]: row for row in loader.load_inventory(HERE / "01_archivos.csv")}
        legacy_points = str(dest / "kmz_2d83ff1278ed_puntos")
        with arcpy.da.UpdateCursor(legacy_points, ["KZ_PM_ID"]) as cursor:
            for row in cursor:
                if row[0] == "a":
                    cursor.updateRow(["alterado"])
        before = report_path.read_bytes()
        with self.assertRaises(loader.TransferValidationError):
            loader.rename_loaded(arcpy, output, report, report_path, inventory, dest, "t1", enterprise=False)
        self.assertEqual(report_path.read_bytes(), before)
        self.assertTrue(arcpy.Exists(legacy_points))
        self.assertFalse(arcpy.Exists(str(dest / "chanchamayo_puntos")))
        with arcpy.da.UpdateCursor(legacy_points, ["KZ_PM_ID"]) as cursor:
            for row in cursor:
                if row[0] == "alterado":
                    cursor.updateRow(["a"])
        self.assertEqual(loader.rename_loaded(arcpy, output, report, report_path, inventory, dest, "t2",
                                              enterprise=False), 2)
        for old, new in [("kmz_2d83ff1278ed_puntos", "chanchamayo_puntos"),
                         ("kmz_3b51369d6f32_atributos", "chanchamayo_atributos")]:
            self.assertFalse(arcpy.Exists(str(dest / old)))
            self.assertTrue(arcpy.Exists(str(dest / new)))
        saved = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual([Path(item["path"]).name for item in saved["targets"]],
                         ["chanchamayo_puntos", "chanchamayo_atributos"])
        self.assertTrue(all(item["renamed_from"] and item["sha256"] == CHANCHAMAYO for item in saved["targets"]))
        self.assertEqual(int(arcpy.management.GetCount(str(dest / "chanchamayo_puntos"))[0]), 2)
        self.assertEqual(loader.rename_loaded(arcpy, output, saved, report_path, inventory, dest, "t3",
                                              enterprise=False), 0)
        interrupted = json.loads((output / "informe_anterior_t2.json").read_text(encoding="utf-8"))
        self.assertEqual(loader.rename_loaded(arcpy, output, interrupted, report_path, inventory, dest, "t4",
                                              enterprise=False), 2)
        self.assertEqual(loader.loaded_shas(interrupted), {CHANCHAMAYO})
        arcpy.management.ClearWorkspaceCache()

    def test_real_gp_execution_and_repeat_do_not_leak_logging_or_environment(self):
        with tempfile.TemporaryDirectory(prefix="mapline_tool_") as folder:
            result = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), "--gp-worker", folder],
                capture_output=True, text=True, errors="replace", timeout=240)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def run_gp_worker(self, folder):
        if folder:
            root = Path(folder)
            for name in ["Mapline_KMZ_SDE.pyt", "cargar_kmz_sde.py"]:
                shutil.copyfile(HERE / name, root / name)
            inputs = root / "Fuentes con espacios"
            inputs.mkdir()
            source = inputs / "mixto.kmz"
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr("doc.kml", KML)
                archive.writestr("files/map.png", b"resource-original")
            sha = hashlib.sha256(source.read_bytes()).hexdigest()
            second = inputs / "segundo.kmz"
            with zipfile.ZipFile(second, "w") as archive:
                archive.writestr("doc.kml", KML.replace("Origen", "Segundo origen"))
                archive.writestr("files/map.png", b"resource-original")
            second_sha = hashlib.sha256(second.read_bytes()).hexdigest()
            with (root / "01_archivos.csv").open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=["archivo", "sha256", "Placemark"], delimiter=";")
                writer.writeheader()
                writer.writerow({"archivo": "mixto.kmz", "sha256": sha, "Placemark": 3})
                writer.writerow({"archivo": "segundo.kmz", "sha256": second_sha, "Placemark": 3})
                writer.writerow({"archivo": "ausente.kmz", "sha256": "b" * 64, "Placemark": 1})
            work = root / "Trabajo"
            work.mkdir()
            toolbox = arcpy.ImportToolbox(str(root / "Mapline_KMZ_SDE.pyt"), "kmz" + uuid.uuid4().hex[:8])
            logger = logging.getLogger("kmz_sde")
            previous = (list(logger.handlers), logger.level, logger.propagate)
            output_paths = []
            with arcpy.EnvManager(overwriteOutput=True, extent="0 0 1 1",
                                  outputCoordinateSystem=arcpy.SpatialReference(3857)):
                for _ in range(2):
                    resume = str(output_paths[0]) if output_paths else ""
                    result = toolbox.TransferirKMZSDE([str(inputs)], MODES[1], "", str(work),
                                                     kmz_seleccionados=[str(source)],
                                                     reanudar_ejecucion=resume)
                    report_path = Path(result.getOutput(0))
                    output_paths.append(Path(result.getOutput(1)))
                    report = json.loads(report_path.read_text(encoding="utf-8"))
                    self.assertEqual(report["state"], "PREPARADO_LOCAL_CON_PENDIENTES")
                    self.assertEqual(report["sources"][0]["placemarks_with_output"], 3)
                    self.assertEqual(report["sources"][0]["converted_rows"], 4)
                    self.assertEqual(output_paths[-1], report_path.parent)
                    log = (report_path.parent / "ejecucion.log").read_text(encoding="utf-8")
                    self.assertIn("PREPARADO_LOCAL_CON_PENDIENTES", log)
                    self.assertIn("reutilizada" if resume else "Atributos preservados", result.getMessages())
                    self.assertTrue(arcpy.env.overwriteOutput)
                    self.assertEqual(arcpy.env.outputCoordinateSystem.factoryCode, 3857)
                    self.assertEqual(arcpy.env.extent.XMin, 0)
                    self.assertEqual(arcpy.env.extent.XMax, 1)
                    self.assertEqual((list(logger.handlers), logger.level, logger.propagate), previous)
            self.assertEqual(output_paths[0], output_paths[1])
            self.assertEqual(len(list((output_paths[0] / "intentos").rglob("preparado_*.gdb"))), 1)
            self.assertTrue(list(output_paths[0].glob("informe_anterior_*.json")))
            report_path = output_paths[0] / "informe.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            legacy = output_paths[0] / "conversion"
            legacy.mkdir()
            arcpy.management.CreateFileGDB(str(legacy), "preparado_legacy.gdb")
            for obj in report["sources"][0]["feature_classes"]:
                dest = legacy / "preparado_legacy.gdb" / Path(obj["local"]).name
                arcpy.management.CopyFeatures(obj["local"], str(dest))
                obj["local"] = str(dest)
            report_path.write_text(json.dumps(report), encoding="utf-8")
            result = toolbox.TransferirKMZSDE([str(inputs)], MODES[1], "", "",
                                             kmz_seleccionados=[str(source)],
                                             reanudar_ejecucion=str(output_paths[0]))
            self.assertIn("reutilizada", result.getMessages())
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertTrue(all(Path(obj["local"]).is_relative_to(legacy)
                                for obj in report["sources"][0]["feature_classes"]))
            report["sources"].append({"sha256": second_sha, "file": "segundo.kmz"})
            report_path.write_text(json.dumps(report), encoding="utf-8")
            with sqlite3.connect(output_paths[0] / "trazabilidad.sqlite") as db:
                db.execute("INSERT INTO originals VALUES(?,?,?,?,?,?,?)",
                           ("unfinished", second_sha, "doc.kml", 1, "Placemark", "", "{}"))
            result = toolbox.TransferirKMZSDE([str(inputs)], MODES[1], "", "",
                                             kmz_seleccionados=[str(second)],
                                             reanudar_ejecucion=str(output_paths[0]))
            report = json.loads(Path(result.getOutput(0)).read_text(encoding="utf-8"))
            self.assertEqual(report["selected_sha256"], [second_sha])
            self.assertEqual(len(report["sources"]), 2)
            self.assertEqual(report["sources"][0]["converted_rows"], 4)
            balance = next(obj for obj in report["local_objects"]
                           if obj["target_name"].endswith("_balance"))
            self.assertEqual(balance["count"], 4)
            with sqlite3.connect(output_paths[0] / "trazabilidad.sqlite") as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM originals").fetchone()[0], 8)
            fc = report["sources"][0]["feature_classes"][0]["local"]
            with arcpy.da.UpdateCursor(fc, ["KZ_SHA256"]) as cursor:
                row = next(cursor)
                row[0] = "alterado"
                cursor.updateRow(row)
            before = report_path.read_bytes()
            with self.assertRaises(arcpy.ExecuteError):
                toolbox.TransferirKMZSDE([str(inputs)], MODES[1], "", "",
                                         kmz_seleccionados=[str(second)],
                                         reanudar_ejecucion=str(output_paths[0]))
            self.assertEqual(report_path.read_bytes(), before)
            self.assertTrue(list(output_paths[0].glob("error_*.json")))
            self.assertFalse((output_paths[0] / ".ejecucion.lock").exists())
            with self.assertRaises(arcpy.ExecuteError):
                toolbox.TransferirKMZSDE([str(inputs)], MODES[1], "", str(inputs))
            arcpy.management.ClearWorkspaceCache()


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--gp-worker":
        ToolboxArcGISTests().run_gp_worker(sys.argv[2])
    elif len(sys.argv) == 3 and sys.argv[1] == "--rename-worker":
        ToolboxArcGISTests().run_rename_worker(sys.argv[2])
    else:
        unittest.main()
