"""Pruebas del alcance y de las guardas sin requerir ArcGIS."""
import copy
from contextlib import nullcontext
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch, MagicMock

import datos_proyecto as runner


class ScopeTests(unittest.TestCase):
    def setUp(self):
        self.model = json.loads((Path(__file__).parent / "esquema.json").read_text(encoding="utf-8"))

    def test_only_selected_dataset_class_and_domains(self):
        before = copy.deepcopy(self.model)
        result = runner.scoped_model(self.model, ["estructuras"])
        self.assertEqual(result["datasets"], ["Datos_Proyecto"])
        self.assertEqual([c["nombre"] for c in result["clases"]], ["estructuras"])
        used = {f["dominio"] for f in result["clases"][0]["campos"] if f.get("dominio")}
        self.assertEqual(set(result["dominios"]), used)
        self.assertEqual(self.model, before)

    def test_all_proposed_classes_pass_static_validation(self):
        self.assertEqual(len(runner.scoped_model(self.model)["clases"]), 76)

    def test_structures_only_applicable_common_fields_and_original_attributes(self):
        c = runner.scoped_model(self.model, ["estructuras"])["clases"][0]
        self.assertEqual(len(c["campos"]), 32)
        self.assertFalse({"descripcion_origen", "tipo_tema", "codigo_estacion", "tema", "id_origen"} & {f["nombre"] for f in c["campos"]})
        self.assertEqual(sum(bool(f.get("campo_fuente")) for f in c["campos"]), 21)

    def test_station_only_in_field_study_and_theme_in_cutouts(self):
        for c in self.model["clases"]:
            common = {f["nombre"] for f in c["campos"] if not f.get("campo_fuente")}
            self.assertEqual("codigo_estacion" in common, c["nombre"] == "area_estudio_campo")
            self.assertEqual("tema" in common, c["rol"] == "recorte")
            self.assertEqual("id_origen" in common, c["rol"] == "recorte")

    def test_extension_cannot_be_added_even_with_common_eft_label(self):
        for origin in ["Extension de trazabilidad", "EFT 5.8.7"]:
            m = copy.deepcopy(self.model)
            c = next(c for c in m["clases"] if c["nombre"] == "estructuras")
            f = copy.deepcopy(c["campos"][0])
            f.update(nombre="descripcion_origen", origen=origin)
            c["campos"].append(f)
            with self.assertRaisesRegex(ValueError, "sin fundamento EFT"):
                runner.scoped_model(m, ["estructuras"])

    def test_unlisted_source_attribute_preserved_under_eft_own_attributes_rule(self):
        c = next(c for c in self.model["clases"] if c["nombre"] == "estructuras")
        f = copy.deepcopy(c["campos"][0])
        f.update(nombre="atributo_real_kmz", origen="Atributo KMZ; revisar tipo", campo_fuente="ATRIBUTO_REAL_KMZ")
        c["campos"].append(f)
        runner.scoped_model(self.model, ["estructuras"])

    def test_existing_extra_field_is_detected_without_treating_system_fields_as_extra(self):
        c = next(c for c in self.model["clases"] if c["nombre"] == "estructuras")
        fields = [SimpleNamespace(name=f["nombre"]) for f in c["campos"]]
        fields += [SimpleNamespace(name=n) for n in ["OBJECTID", "Shape", "GlobalID", "created_user", "created_date", "last_edited_user", "last_edited_date", "descripcion_origen"]]
        self.assertEqual(runner.unexpected_fields(fields, SimpleNamespace(), c), ["descripcion_origen"])

    def test_empty_gp_output_resolves_created_class_without_recreating_it(self):
        c = next(c for c in self.model["clases"] if c["nombre"] == "estructuras")
        a = MagicMock()
        a.Exists.return_value = True
        a.Describe.return_value.isVersioned = False
        a.management.CreateFeatureclass.return_value.getOutput.return_value = ''
        args = SimpleNamespace(workspace='fixture.gdb', database='ArcGisAWS', owner='gis')
        ds = 'fixture.gdb/Datos_Proyecto'
        path = ds + '/estructuras'
        with patch.object(runner.engine, 'find_objects', return_value={'datos_proyecto': ds, 'estructuras': path}), patch('builtins.print'):
            runner.engine.create(a, args, {'dominios': {}, 'datasets': ['Datos_Proyecto']}, [c], {'datos_proyecto': ds}, {})
        a.management.CreateFeatureclass.assert_called_once()
        self.assertEqual(a.management.AddFields.call_args.args[0], path)

    def test_unknown_selection_rejected(self):
        with self.assertRaises(ValueError):
            runner.scoped_model(self.model, ["estructuras", "desconocida"])

    def test_missing_required_project_rejected(self):
        c = next(c for c in self.model["clases"] if c["nombre"] == "estructuras")
        c["campos"] = [f for f in c["campos"] if f["nombre"] != "proyecto"]
        with self.assertRaisesRegex(ValueError, "obligatorio"):
            runner.scoped_model(self.model, ["estructuras"])

    def test_duplicate_field_case_rejected(self):
        c = next(c for c in self.model["clases"] if c["nombre"] == "estructuras")
        field = copy.deepcopy(c["campos"][0])
        field["nombre"] = field["nombre"].upper()
        c["campos"].append(field)
        with self.assertRaisesRegex(ValueError, "duplicados"):
            runner.scoped_model(self.model, ["estructuras"])

    def test_apply_requires_explicit_selection_before_importing_arcpy(self):
        with self.assertRaisesRegex(ValueError, "indique clases"):
            runner.run("does_not_exist.sde", apply=True)

    def test_existing_validated_batch_performs_no_writes_or_redundant_preflight(self):
        fake = SimpleNamespace(GetInstallInfo=lambda: {"Version": "SIMULADA"},
                               EnvManager=lambda **kwargs: nullcontext())
        inventory = {"datos_proyecto": "fixture/Datos_Proyecto", "estructuras": "fixture/Datos_Proyecto/estructuras"}
        with tempfile.TemporaryDirectory() as temp, \
                patch.object(runner, "preflight", return_value=(inventory, {}, 1, True)) as preflight, \
                patch.object(runner.engine, "create") as create:
            _, report = runner.run("fixture.gdb", ["estructuras"], apply=True,
                                   reports=temp, arcpy_module=fake, emit=lambda s: None)
            preflight.assert_called_once()
            create.assert_not_called()
            self.assertEqual(report['completadas'], [])
            self.assertEqual(report['estado'], 'CREACION_VERIFICADA')
            self.assertEqual(report['clases'][0]['accion'], 'VALIDADA_EXISTENTE')

    def check_operation_error(self, state_complete):
        class GPError(Exception):
            pass
        fake = SimpleNamespace(ExecuteError=GPError, GetInstallInfo=lambda: {"Version": "SIMULADA"},
                               EnvManager=lambda **kwargs: nullcontext(),
                               management=SimpleNamespace(ClearWorkspaceCache=lambda p: None))
        inventory = {"datos_proyecto": "fixture/Datos_Proyecto"}
        with tempfile.TemporaryDirectory() as temp, \
                patch.object(runner, "preflight", return_value=(inventory, {}, 1, True)), \
                patch.object(runner.engine, "inspect", return_value=(inventory, {})), \
                patch.object(runner.engine, "create", side_effect=GPError("error simulado de GP")), \
                patch.object(runner, "verify_created") as verify:
            verify.return_value = (inventory, {})
            if not state_complete:
                verify.side_effect = ValueError("falta GlobalID")
                emitted = []
                with self.assertRaisesRegex(RuntimeError, "falta GlobalID"):
                    runner.run("fixture.gdb", ["estructuras"], apply=True, reports=temp, arcpy_module=fake, emit=emitted.append)
                reports = [Path(message.removeprefix('Resultado JSON: ')) for message in emitted
                           if message.startswith('Resultado JSON: ')]
                self.assertEqual(len(reports), 1, 'La ejecucion debe emitir su Resultado JSON final.')
                latest = reports[0]
                self.assertTrue(latest.is_relative_to(Path(temp)))
                report = json.loads(latest.read_text(encoding="utf-8"))
                self.assertEqual(report["estado"], "ERROR_DETENIDO")
                self.assertEqual(report["completadas"], [])
                self.assertEqual(report["clase_en_curso"], "estructuras")
            else:
                _, report = runner.run("fixture.gdb", ["estructuras"], apply=True, reports=temp, arcpy_module=fake, emit=lambda s: None)
                self.assertEqual(report["estado"], "CREACION_VERIFICADA")
                self.assertEqual(report["completadas"], ["estructuras"])
                self.assertTrue(any("error simulado de GP" in s for s in report["advertencias"]))

    def test_operation_error_with_incomplete_state_stops_and_records_partial(self):
        self.check_operation_error(False)

    def test_operation_error_requires_complete_verified_state_to_continue(self):
        self.check_operation_error(True)

    def sample_report(self):
        return dict(estado="INICIADO", modo="VALIDAR", workspace="fixture.gdb", modelo_sha256="test",
                    clases=[], advertencias=[])

    def test_reports_do_not_replace_files_and_preserve_prior_states(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(Path, "replace", side_effect=PermissionError("WinError 5")) as replace:
            report = self.sample_report()
            runner.report_files(temp, report, {"clases": []})
            first = Path(report["archivo_resultado"])
            report["estado"] = "VALIDACION_OK_SIN_CAMBIOS"
            runner.report_files(temp, report, {"clases": []})
            second = Path(report["archivo_resultado"])
            self.assertNotEqual(first, second)
            self.assertEqual(json.loads(first.read_text(encoding="utf-8"))["estado"], "INICIADO")
            self.assertEqual(json.loads(second.read_text(encoding="utf-8"))["estado"], "VALIDACION_OK_SIN_CAMBIOS")
            self.assertTrue(Path(report["archivo_informe"]).is_file())
            replace.assert_not_called()

    @unittest.skipUnless(os.name == "nt", "Requiere bloqueo nativo de Windows")
    def test_windows_locked_previous_json_csv_and_markdown_do_not_block_new_state(self):
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                      wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        with tempfile.TemporaryDirectory() as temp:
            report = self.sample_report()
            runner.report_files(temp, report, {"clases": []})
            handles = []
            try:
                for key in ("archivo_resultado", "archivo_informe", "archivo_campos"):
                    handle = kernel.CreateFileW(report[key], 0x80000000, 1, None, 3, 0x80, None)
                    self.assertNotEqual(handle, ctypes.c_void_p(-1).value)
                    handles.append(handle)
                report["estado"] = "VALIDACION_OK_SIN_CAMBIOS"
                runner.report_files(temp, report, {"clases": []})
                self.assertEqual(json.loads(Path(report["archivo_resultado"]).read_text(encoding="utf-8"))["estado"], "VALIDACION_OK_SIN_CAMBIOS")
            finally:
                for handle in handles:
                    kernel.CloseHandle(handle)

    def test_final_report_failure_does_not_mask_original_validation_error(self):
        fake = SimpleNamespace(GetInstallInfo=lambda: {"Version": "SIMULADA"},
                               EnvManager=lambda **kwargs: nullcontext())
        with tempfile.TemporaryDirectory() as temp, \
                patch.object(runner, "preflight", side_effect=ValueError("proyecto incompatible")), \
                patch.object(runner, "report_files", side_effect=[None, PermissionError("informe bloqueado")]):
            with self.assertRaisesRegex(ValueError, "proyecto incompatible"):
                runner.run("fixture.gdb", ["estructuras"], reports=temp, arcpy_module=fake, emit=lambda s: None)


if __name__ == "__main__":
    unittest.main()
