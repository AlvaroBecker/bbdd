"""Smoke tests reproducibles del helper 00, sin ArcPy ni servidor reales."""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch


PACKAGE = Path(__file__).resolve().parent.parent
HELPER = None
TEMPLATE = b""


class ArcPyReadOnlyMock:
    """Solo admite las superficies de lectura esperadas por el helper."""

    def __init__(self, mode="pass"):
        self.mode = mode
        self.queries = []
        self.inspections = []
        self.listed_fields = []

    @property
    def management(self):
        raise AssertionError("El helper intentó acceder a herramientas mutadoras.")

    @property
    def da(self):
        raise AssertionError("El helper intentó acceder a cursores no autorizados.")

    def Exists(self, path):
        return not (str(path) == "fake.sde" and self.mode == "no_connection")

    def Describe(self, path):
        if str(path) == "fake.sde":
            return NS(workspaceType="RemoteDatabase", connectionProperties=NS(database="ArcGisAWS"))
        name = str(path).split(".")[-1]
        self.inspections.append(name)
        desc = NS(dataType="Table", DSID=1, defaultSubtypeCode=0,
                  relationshipClassNames=[], aliasName=name, hasOID=True,
                  OIDFieldName="OBJECTID", isVersioned=False,
                  isTraditionalVersioned=False, isBranchVersioned=False, isArchived=False)
        if self.mode in ("isVersioned", "isTraditionalVersioned", "isBranchVersioned", "isArchived"):
            setattr(desc, self.mode, True)
        if self.mode == "unregistered":
            desc.DSID = -1
        if self.mode == "missing_gdb_property":
            del desc.aliasName
        if self.mode == "business_oid":
            desc.OIDFieldName = HELPER.TABLE_KEYS[name]
        if self.mode == "missing_state_property":
            del desc.isArchived
        return desc

    def ListFields(self, path):
        name = str(path).split(".")[-1]
        self.listed_fields.append(name)
        return [NS(name="OBJECTID", type="OID"),
                NS(name=HELPER.TABLE_KEYS[name], type="Integer")]

    def ArcSDESQLExecute(self, path):
        return NS(execute=self.execute)

    def execute(self, sql):
        if sql != HELPER.IDENTITY_QUERY or not sql.startswith("SELECT "):
            raise AssertionError("Se intentó ejecutar una consulta distinta del SELECT de identidad.")
        self.queries.append(sql)
        row = ["ArcGisAWS", "EEPAWSDBP01'X;--", "gis", "gis", "2026-11-02T14:00:00"]
        if self.mode == "wrong_owner":
            row[2] = "other_user"
        if self.mode == "incomplete_identity":
            row.pop()
        return [row]


class HelperSmokeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="mapline_helper00_test_")
        self.root = Path(self.temp.name).resolve()
        self.counter = 0

    def tearDown(self):
        # Limpiar solo el directorio temporal que creó este caso de prueba.
        self.assertEqual(self.root.parent, Path(tempfile.gettempdir()).resolve())
        self.assertTrue(self.root.name.startswith("mapline_helper00_test_"))
        self.temp.cleanup()

    def run_helper(self, mode="pass", overwrite=False, output_exists=False,
                   report_alias=False, output_alias=False, report_output_alias=False,
                   source=None):
        self.counter += 1
        root = self.root / str(self.counter)
        root.mkdir()
        source = TEMPLATE if source is None else source
        template = root / "base.sql"
        template.write_bytes(source)
        output = template if output_alias else root / "generated.sql"
        report = template if report_alias else output if report_output_alias else root / "nested" / "report.json"
        if output_exists and not output_alias:
            output.write_bytes(b"SENTINEL")
        fake = ArcPyReadOnlyMock(mode)
        argv = [str(PACKAGE / "00_verificar_estado_arcgis.py"), "--connection", "fake.sde",
                "--template", str(template), "--output", str(output), "--report", str(report)]
        if overwrite:
            argv.append("--overwrite")
        with patch.dict(sys.modules, {"arcpy": fake}), patch.object(sys, "argv", argv), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            result = HELPER.main()
        self.assertEqual(template.read_bytes(), source, "La plantilla fue modificada.")
        self.assertTrue(all(query == HELPER.IDENTITY_QUERY for query in fake.queries))
        return result, output, report, fake

    def test_pass_verifies_eight_tables_and_only_three_sql_lines_change(self):
        code, output, report, fake = self.run_helper()
        self.assertEqual(code, 0)
        self.assertEqual(set(fake.inspections), set(HELPER.TABLE_KEYS))
        self.assertEqual(len(fake.inspections), 8)
        self.assertEqual(len(fake.listed_fields), 8)
        old = TEMPLATE.decode("utf-8-sig").splitlines()
        new = output.read_bytes().decode("utf-8-sig").splitlines()
        self.assertEqual(len(old), len(new))
        self.assertEqual(sum(a != b for a, b in zip(old, new)), 3)
        state = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(len(state["tables"]), 8)
        self.assertFalse(state["server_modified"])
        self.assertEqual(state["output_sha256"], hashlib.sha256(output.read_bytes()).hexdigest())

    def test_server_name_is_sql_escaped_and_stamp_uses_server_utc(self):
        code, output, _, _ = self.run_helper()
        self.assertEqual(code, 0)
        text = output.read_bytes().decode("utf-8-sig")
        self.assertIn("N'EEPAWSDBP01''X;--'", text)
        self.assertIn("CONVERT(datetime2(0), N'2026-11-02T14:00:00', 126)", text)

    def test_only_identity_select_and_no_mutator_api(self):
        code, _, _, fake = self.run_helper()
        self.assertEqual(code, 0)
        self.assertEqual(fake.queries, [HELPER.IDENTITY_QUERY])
        self.assertIn("SYSUTCDATETIME", fake.queries[0])

    def test_four_unsafe_arcgis_states_never_generate_sql(self):
        for flag in ("isVersioned", "isTraditionalVersioned", "isBranchVersioned", "isArchived"):
            with self.subTest(flag=flag):
                code, output, report, _ = self.run_helper(flag)
                self.assertEqual(code, 1)
                self.assertFalse(output.exists())
                state = json.loads(report.read_text(encoding="utf-8"))
                self.assertEqual(state["status"], "fallo")
                self.assertFalse(state["sql_generated"])
                self.assertIn(flag, state["error"])

    def test_wrong_database_owner_never_generates_sql(self):
        code, output, report, _ = self.run_helper("wrong_owner")
        self.assertEqual(code, 1)
        self.assertFalse(output.exists())
        self.assertIn("usuario", json.loads(report.read_text(encoding="utf-8"))["error"])

    def test_missing_connection_does_not_query_server(self):
        code, output, _, fake = self.run_helper("no_connection")
        self.assertEqual(code, 1)
        self.assertFalse(output.exists())
        self.assertEqual(fake.queries, [])

    def test_missing_gdb_property_and_unregistered_dataset_fail_closed(self):
        for mode in ("missing_gdb_property", "unregistered"):
            with self.subTest(mode=mode):
                code, output, _, _ = self.run_helper(mode)
                self.assertEqual(code, 1)
                self.assertFalse(output.exists())

    def test_business_id_cannot_be_arcgis_objectid(self):
        code, output, _, _ = self.run_helper("business_oid")
        self.assertEqual(code, 1)
        self.assertFalse(output.exists())

    def test_absent_state_property_is_not_assumed_false(self):
        code, output, report, _ = self.run_helper("missing_state_property")
        self.assertEqual(code, 1)
        self.assertFalse(output.exists())
        self.assertIn("no expone", json.loads(report.read_text(encoding="utf-8"))["error"])

    def test_incomplete_identity_response_fails_closed(self):
        code, output, _, _ = self.run_helper("incomplete_identity")
        self.assertEqual(code, 1)
        self.assertFalse(output.exists())

    def test_duplicated_template_markers_fail_before_connection(self):
        broken = TEMPLATE + b"\n" + HELPER.STATE_MARKER.encode("utf-8") + b"\n"
        code, output, _, fake = self.run_helper(source=broken)
        self.assertEqual(code, 1)
        self.assertFalse(output.exists())
        self.assertEqual(fake.queries, [])

    def test_existing_output_is_preserved_without_overwrite(self):
        code, output, _, fake = self.run_helper(output_exists=True)
        self.assertEqual(code, 1)
        self.assertEqual(output.read_bytes(), b"SENTINEL")
        self.assertEqual(fake.queries, [])

    def test_existing_output_can_be_replaced_only_with_explicit_overwrite(self):
        code, output, _, fake = self.run_helper(output_exists=True, overwrite=True)
        self.assertEqual(code, 0)
        self.assertNotEqual(output.read_bytes(), b"SENTINEL")
        self.assertEqual(len(fake.queries), 1)

    def test_template_never_overwritten_even_with_alias_and_overwrite(self):
        for aliases in ({"report_alias": True}, {"output_alias": True}, {"report_output_alias": True}):
            with self.subTest(aliases=aliases):
                code, _, _, fake = self.run_helper(overwrite=True, **aliases)
                self.assertEqual(code, 1)
                self.assertEqual(fake.queries, [])

    def test_default_output_uses_new_name_without_overwriting(self):
        existing = self.root / "existing.sql"
        existing.write_bytes(b"SENTINEL")
        new = HELPER.choose_path(None, existing, False)
        self.assertNotEqual(new, existing)
        self.assertFalse(new.exists())
        self.assertEqual(existing.read_bytes(), b"SENTINEL")

    def test_byte_order_mark_and_crlf_are_preserved(self):
        text = TEMPLATE.decode("utf-8-sig").replace("\r\n", "\n").replace("\n", "\r\n")
        source = b"\xef\xbb\xbf" + text.encode("utf-8")
        code, output, _, _ = self.run_helper(source=source)
        self.assertEqual(code, 0)
        data = output.read_bytes()
        self.assertTrue(data.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(data.count(b"\r\n"), source.count(b"\r\n"))
        self.assertEqual(data.count(b"\n"), data.count(b"\r\n"))


def main():
    global PACKAGE, HELPER, TEMPLATE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, default=PACKAGE)
    parser.add_argument("--report", type=Path, default=Path(__file__).with_name("resultado_helper_00.json"))
    args = parser.parse_args()
    PACKAGE = args.package.resolve()
    helper_path = PACKAGE / "00_verificar_estado_arcgis.py"
    template_path = PACKAGE / "03_agregar_PK_FK_SQLServer.sql"
    spec = importlib.util.spec_from_file_location("_mapline_helper00_smoke", helper_path)
    HELPER = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = HELPER
    spec.loader.exec_module(HELPER)
    TEMPLATE = template_path.read_bytes()
    log = io.StringIO()
    result = unittest.TextTestRunner(stream=log, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(HelperSmokeTests))
    report = {"status": "PASS" if result.wasSuccessful() else "FAIL", "tests_run": result.testsRun,
              "failures": [{"test": str(test), "traceback": trace} for test, trace in result.failures],
              "errors": [{"test": str(test), "traceback": trace} for test, trace in result.errors],
              "helper_sha256": hashlib.sha256(helper_path.read_bytes()).hexdigest(),
              "template_sha256": hashlib.sha256(TEMPLATE).hexdigest(),
              "test_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "python_version": sys.version, "uses_real_arcpy": False, "real_database_accessed": False,
              "scope": "Mocks de las ocho tablas, transformación de tres marcas, estado seguro y protección de archivos.",
              "limitations": "No comprueba un runtime ArcGIS real ni ejecuta el SQL generado.",
              "unittest_output": log.getvalue()}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{report['status']}: {result.testsRun} pruebas; fallos={len(result.failures)}, errores={len(result.errors)}. Informe: {args.report}")
    if not result.wasSuccessful():
        print(log.getvalue(), file=sys.stderr)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
