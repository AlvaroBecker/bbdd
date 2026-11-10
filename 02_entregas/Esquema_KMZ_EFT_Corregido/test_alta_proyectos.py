"""Contrato del runtime con una geodatabase transaccional simulada.

Estas pruebas no certifican ArcPy/SDE. Comprueban que el runtime conserva los
datos, aplica las guardas antes de escribir y distingue rollback de commit
incierto, usando el mismo flujo publico ``run`` y su inspeccion real.
"""

import copy
import datetime as dt
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

import alta_proyectos as runtime
import alta_proyectos_logica as logic


def field(name, kind="String", length=128, nullable=True, domain=""):
    return NS(name=name, baseName=name, type=kind, length=length,
              isNullable=nullable, editable=True, domain=domain, defaultValue=None)


class FakeSearchCursor:
    def __init__(self, api, names):
        self.api, self.names = api, names

    def __enter__(self):
        if self.api.fail_search_after_commit and self.api.commits:
            raise RuntimeError("lectura posterior al commit fallida")
        rows = self.api.pending if self.api.pending is not None else self.api.rows
        snapshot = copy.deepcopy(rows)
        if self.api.reverse_search:
            self.api.reverse_search = False
            snapshot.reverse()
        return iter(tuple(row[name.casefold()] for name in self.names) for row in snapshot)

    def __exit__(self, *_):
        return False


class FakeInsertCursor:
    def __init__(self, api, names, explicit):
        self.api, self.names = api, names
        api.insert_cursor_calls += 1
        if explicit is not True:
            raise AssertionError("Se requiere explicit=True para no copiar defaults.")

    def __enter__(self):
        if self.api.pending is None:
            raise AssertionError("InsertCursor fuera de transaccion")
        return self

    def insertRow(self, values):
        api = self.api
        api.insert_calls += 1
        if api.fail_insert_at == api.insert_calls:
            raise RuntimeError("fallo de insercion simulado")
        row = {f.name.casefold(): None for f in api.fields}
        row.update(zip((name.casefold() for name in self.names), values))
        row["objectid"] = max((r["objectid"] for r in api.pending), default=0) + 1
        if not api.suppress_audit:
            row.update(created_user="gis", last_edited_user="gis",
                       created_date=dt.datetime(2026, 11, 9, 20, 0),
                       last_edited_date=dt.datetime(2026, 11, 9, 20, 0))
        if not api.suppress_globalid:
            row["globalid"] = "{00000000-0000-0000-0000-%012d}" % row["objectid"]
        api.pending.append(row)
        return row["objectid"]

    def __exit__(self, *_):
        return False


class FakeEditor:
    def __init__(self, api):
        self.api = api
        api.editor_calls += 1

    def startEditing(self, with_undo, multiuser_mode):
        self.api.actions.append(("startEditing", with_undo, multiuser_mode))
        if with_undo or multiuser_mode:
            raise AssertionError("La tabla no versionada requiere False, False.")
        self.api.pending = copy.deepcopy(self.api.rows)

    def startOperation(self):
        self.api.actions.append(("startOperation",))

    def stopOperation(self):
        self.api.actions.append(("stopOperation",))

    def abortOperation(self):
        self.api.actions.append(("abortOperation",))
        self.api.pending = copy.deepcopy(self.api.rows)

    def stopEditing(self, save):
        api = self.api
        api.actions.append(("stopEditing", save))
        if save:
            # Un fallo de respuesta puede ocurrir DESPUES de haber persistido.
            api.rows = copy.deepcopy(api.pending)
            api.pending = None
            api.commits += 1
            if api.commit_error:
                raise RuntimeError("respuesta del commit perdida")
        else:
            api.pending = None
            api.rollbacks += 1


class FakeEnv:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class FakeArcPy:
    def __init__(self, workspace):
        self.workspace = workspace
        self.rows, self.pending = [], None
        self.editor_calls = self.insert_cursor_calls = self.insert_calls = 0
        self.commits = self.rollbacks = 0
        self.fail_insert_at = None
        self.commit_error = self.fail_search_after_commit = False
        self.suppress_audit = self.suppress_globalid = self.reverse_search = False
        self.actions = []
        self.workspace_description = NS(workspaceType="RemoteDatabase",
                                        connectionProperties=NS(database="ArcGisAWS", user="gis"))
        self.table_description = NS(dataType="Table", hasOID=True, isVersioned=False,
            isArchived=False, attributeRules=[], hasAttachments=False,
            editorTrackingEnabled=True, creatorFieldName="created_user",
            createdAtFieldName="created_date", editorFieldName="last_edited_user",
            editedAtFieldName="last_edited_date", relationshipClassNames=[],
            isTimeInUTC=True)
        self.fields = [field("objectid", "OID", nullable=False),
            field("id_proyecto", "Integer", nullable=False), field("co_proyecto", length=12),
            field("no_proyecto"), field("de_proyecto"),
            field("id_tipo_proyecto", "Integer", domain="tipo"),
            field("id_estado_proyecto", "Integer", domain="estado"), field("es_registro", length=1),
            field("globalid", "GlobalID", nullable=False),
            field("created_user"), field("created_date", "Date"),
            field("last_edited_user"), field("last_edited_date", "Date"),
            field("fe_eliminacion", "Date"), field("us_eliminacion"), field("ip_eliminacion"),
            field("co_alternativa_reciente", "Integer"), field("us_creacion")]
        self.domains = {
            "tipo": NS(name="tipo", domainType="CodedValue", codedValues={8: "Línea de Transmisión"}),
            "estado": NS(name="estado", domainType="CodedValue", codedValues={3: "Registrado"}),
        }
        self.subtypes = {0: {"SubtypeField": ""}}
        self.da = NS(
            ListSubtypes=lambda _: self.subtypes,
            ListDomains=lambda _: list(self.domains.values()),
            SearchCursor=lambda _, names, **kwargs: FakeSearchCursor(self, names),
            InsertCursor=lambda _, names, explicit=False: FakeInsertCursor(self, names, explicit),
            Editor=lambda _: FakeEditor(self),
        )
        self.add_existing(40)

    def add_existing(self, identifier, name=None, description=None, state="1"):
        row = {f.name.casefold(): None for f in self.fields}
        row.update(objectid=identifier, id_proyecto=identifier, co_proyecto="PRY-%08d" % identifier,
                   no_proyecto=name or "Proyecto ajeno %d" % identifier, de_proyecto=description,
                   id_tipo_proyecto=8, id_estado_proyecto=3, es_registro=state,
                   us_creacion="usuario historico", globalid="{HISTORICO-%d}" % identifier,
                   created_user="original", last_edited_user="original",
                   created_date=dt.datetime(2020, 1, 1), last_edited_date=dt.datetime(2020, 1, 1))
        self.rows.append(row)

    def Exists(self, _):
        return True

    def Describe(self, path):
        return self.workspace_description if path == self.workspace else self.table_description

    def EnvManager(self, **_):
        return FakeEnv()

    def ListTables(self):
        return ["ArcGisAWS.gis.mline_tc_proyecto"]

    def ListFields(self, _):
        return self.fields


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="alta_proyectos_test_")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = os.path.abspath(str(self.root / "conexion.sde"))
        self.api = FakeArcPy(self.workspace)
        self.messages = []
        self.last_folder = None

    def run_tool(self, **kwargs):
        before = set(self.root.glob("Alta_Proyectos_*"))
        try:
            return runtime.run(self.workspace, reports=self.root, arcpy_module=self.api,
                               emit=self.messages.append, **kwargs)
        finally:
            created = set(self.root.glob("Alta_Proyectos_*")) - before
            if created:
                self.last_folder = created.pop()

    def report(self):
        return json.loads((self.last_folder / "resultado.json").read_text(encoding="utf-8"))

    def assert_no_writes(self):
        self.assertEqual(self.api.editor_calls, 0)
        self.assertEqual(self.api.insert_cursor_calls, 0)
        self.assertEqual(self.api.insert_calls, 0)
        self.assertEqual(self.api.commits, 0)

    def test_validation_uses_no_editor_or_insert_cursor(self):
        original = copy.deepcopy(self.api.rows)
        _, report = self.run_tool()
        self.assertEqual(report["estado"], "ALTAS_VALIDADAS_SIN_CAMBIOS")
        self.assertEqual(report["transaccion"], "NO_INICIADA")
        self.assertEqual(len(report["plan"]["altas"]), 2)
        self.assertEqual(self.api.rows, original)
        self.assert_no_writes()

    def test_two_insertions_are_atomic_audited_and_originals_preserved(self):
        original = copy.deepcopy(self.api.rows)
        folder, report = self.run_tool(apply=True, exclusive=True)
        self.assertEqual(report["estado"], "ALTAS_PROYECTOS_VERIFICADAS")
        self.assertEqual(report["transaccion"], "CONFIRMADA")
        self.assertEqual(report["nuevas_filas_confirmadas"], 2)
        self.assertEqual(self.api.commits, 1)
        self.assertEqual(self.api.rows[:1], original)
        self.assertEqual([r["co_proyecto"] for r in self.api.rows[1:]], ["PRY-00000041", "PRY-00000042"])
        for row in self.api.rows[1:]:
            self.assertEqual(row["created_user"], "gis")
            self.assertIsNotNone(row["created_date"])
            self.assertIsNotNone(row["globalid"])
            self.assertIsNone(row["us_creacion"])
            self.assertIsNone(row["co_alternativa_reciente"])
        self.assertTrue((folder / "verificacion_antes_commit.json").is_file())
        mapping = (folder / "confirmar_proyectos.csv").read_text(encoding="utf-8-sig")
        self.assertIn("Proyecto JAENNORTE.kmz;PRY-00000041;si", mapping)
        self.assertIn("Proyecto POROMA.kmz;PRY-00000042;si", mapping)

    def test_repeat_does_not_open_editor_or_reactivate_existing(self):
        self.api.add_existing(41, "Proyecto JAENNORTE", "LT 220 kV Caclic-Jaen Norte", "0")
        self.api.add_existing(42, "Proyecto POROMA", "LT 220 kV Ica-Poroma")
        original = copy.deepcopy(self.api.rows)
        _, report = self.run_tool(apply=True)
        self.assertEqual(report["estado"], "ALTAS_PROYECTOS_VERIFICADAS")
        self.assertEqual(report["nuevas_filas_confirmadas"], 0)
        self.assertEqual(self.api.rows, original)
        self.assertTrue(report["plan_final"]["existentes"][0]["inactivo"])
        self.assert_no_writes()

    def test_explicit_exclusivity_required_before_editor(self):
        with self.assertRaisesRegex(ValueError, "ventana sin otras altas"):
            self.run_tool(apply=True)
        self.assert_no_writes()
        self.assertEqual(self.report()["transaccion"], "NO_INICIADA")

    def test_error_on_second_insert_rolls_back_first(self):
        original = copy.deepcopy(self.api.rows)
        self.api.fail_insert_at = 2
        with self.assertRaisesRegex(RuntimeError, "insercion"):
            self.run_tool(apply=True, exclusive=True)
        self.assertEqual(self.api.insert_calls, 2)
        self.assertEqual(self.api.rows, original)
        self.assertEqual(self.api.rollbacks, 1)
        self.assertEqual(self.api.commits, 0)
        self.assertEqual(self.report()["transaccion"], "REVERTIDA")
        self.assertEqual(self.report()["nuevas_filas_confirmadas"], 0)

    def test_missing_native_audit_rolls_back(self):
        original = copy.deepcopy(self.api.rows)
        self.api.suppress_audit = True
        with self.assertRaisesRegex(ValueError, "auditoria nativa"):
            self.run_tool(apply=True, exclusive=True)
        self.assertEqual(self.api.rows, original)
        self.assertEqual(self.report()["transaccion"], "REVERTIDA")

    def test_missing_native_globalid_rolls_back(self):
        self.api.suppress_globalid = True
        with self.assertRaisesRegex(ValueError, "GlobalID"):
            self.run_tool(apply=True, exclusive=True)
        self.assertEqual(self.report()["transaccion"], "REVERTIDA")

    def test_uncertain_commit_does_not_claim_rollback_or_retry(self):
        self.api.commit_error = True
        with self.assertRaisesRegex(RuntimeError, "commit"):
            self.run_tool(apply=True, exclusive=True)
        self.assertEqual(len(self.api.rows), 3)  # Persistio, pero la respuesta fallo.
        self.assertEqual(self.api.rollbacks, 0)
        self.assertEqual(self.api.insert_calls, 2)
        report = self.report()
        self.assertEqual(report["transaccion"], "ESTADO_INCIERTO")
        self.assertEqual(report["nuevas_filas_confirmadas"], 0)
        self.assertIn("no se afirma rollback", report["error"])

    def test_read_failure_after_commit_reports_confirmed_not_rolled_back(self):
        self.api.fail_search_after_commit = True
        with self.assertRaisesRegex(RuntimeError, "posterior"):
            self.run_tool(apply=True, exclusive=True)
        report = self.report()
        self.assertEqual(report["estado"], "ALTA_CONFIRMADA_REVISION_POSTERIOR_PENDIENTE")
        self.assertEqual(report["transaccion"], "CONFIRMADA")
        self.assertEqual(report["nuevas_filas_confirmadas"], 2)
        self.assertEqual(self.api.rollbacks, 0)

    def test_final_report_failure_after_commit_preserves_honest_status(self):
        with patch.object(runtime, "write_report", side_effect=OSError("fallo guardando informe posterior")):
            with self.assertRaisesRegex(RuntimeError, "ALTA_CONFIRMADA_REVISION_POSTERIOR_PENDIENTE"):
                self.run_tool(apply=True, exclusive=True)
        self.assertEqual(self.api.commits, 1)
        self.assertEqual(self.api.rollbacks, 0)
        self.assertEqual(len(self.api.rows), 3)
        self.assertTrue(any("Transaccion: CONFIRMADA" in message for message in self.messages))
        self.assertTrue(any("altas confirmadas: 2" in message for message in self.messages))

    def test_precommit_report_failure_rolls_back(self):
        original_write = runtime.write_json

        def fail_verification(path, value):
            if Path(path).name == "verificacion_antes_commit.json":
                raise OSError("sin espacio antes del commit")
            return original_write(path, value)

        with patch.object(runtime, "write_json", side_effect=fail_verification):
            with self.assertRaisesRegex(OSError, "antes del commit"):
                self.run_tool(apply=True, exclusive=True)
        self.assertEqual(self.api.commits, 0)
        self.assertEqual(self.api.rollbacks, 1)
        self.assertEqual(self.report()["transaccion"], "REVERTIDA")

    def test_wrong_database_or_owner_blocks_before_writes(self):
        for attr, value in (("database", "otra"), ("user", "otro")):
            with self.subTest(attr=attr):
                setattr(self.api.workspace_description.connectionProperties, attr, value)
                with self.assertRaises(ValueError):
                    self.run_tool(apply=True, exclusive=True)
                setattr(self.api.workspace_description.connectionProperties, attr, "ArcGisAWS" if attr == "database" else "gis")
                self.assert_no_writes()

    def test_versioning_and_missing_tracking_are_reported_and_block_apply(self):
        for attr, value in (("isVersioned", True), ("isArchived", True), ("editorTrackingEnabled", False)):
            with self.subTest(attr=attr):
                original = getattr(self.api.table_description, attr)
                setattr(self.api.table_description, attr, value)
                _, report = self.run_tool()
                self.assertEqual(report["estado"], "ALTAS_BLOQUEADAS_SIN_CAMBIOS")
                with self.assertRaisesRegex(ValueError, "No se puede aplicar"):
                    self.run_tool(apply=True, exclusive=True)
                self.assert_no_writes()
                setattr(self.api.table_description, attr, original)

    def test_wrong_domain_meaning_and_forbidden_value_block_before_writes(self):
        self.api.domains["tipo"].codedValues = {8: "Central de Generacion"}
        with self.assertRaisesRegex(ValueError, "dominio"):
            self.run_tool(apply=True, exclusive=True)
        self.assert_no_writes()
        self.api.domains["tipo"].codedValues = {8: "Línea de Transmisión"}
        self.api.domains["es"] = NS(name="es", domainType="CodedValue", codedValues={"0": "Inactivo"})
        next(f for f in self.api.fields if f.name == "es_registro").domain = "es"
        with self.assertRaisesRegex(ValueError, "fuera del dominio"):
            self.run_tool(apply=True, exclusive=True)
        self.assert_no_writes()

    def test_conflicting_csv_for_missing_project_blocks_before_writes(self):
        path = self.root / "conflicto.csv"
        path.write_text("archivo_kmz;co_proyecto;confirmado\nProyecto JAENNORTE.kmz;PRY-00000099;no\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.run_tool(apply=True, exclusive=True, project_csv=path)
        self.assert_no_writes()

    def test_confirmed_csv_nonexistent_code_blocks_before_writes(self):
        path = self.root / "inexistente.csv"
        path.write_text("archivo_kmz;co_proyecto;confirmado\nProyecto HUARAZ.kmz;PRY-00000099;si\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "inexistente"):
            self.run_tool(apply=True, exclusive=True, project_csv=path)
        self.assert_no_writes()

    def test_input_csv_is_not_modified_and_existing_confirmations_preserved(self):
        path = self.root / "confirmados.csv"
        original = "archivo_kmz;co_proyecto;confirmado\nProyecto OTRO.kmz;PRY-00000040;si\nProyecto JAENNORTE.kmz;;no\n"
        path.write_text(original, encoding="utf-8")
        folder, _ = self.run_tool(apply=True, exclusive=True, project_csv=path)
        self.assertEqual(path.read_text(encoding="utf-8"), original)
        output = (folder / "confirmar_proyectos.csv").read_text(encoding="utf-8-sig")
        self.assertIn("Proyecto OTRO.kmz;PRY-00000040;si", output)
        self.assertIn("Proyecto JAENNORTE.kmz;PRY-00000041;si", output)


if __name__ == "__main__":
    unittest.main()
