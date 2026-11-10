"""Pruebas simuladas de sustitucion y recuperacion; no abren una geodatabase."""
import copy
import json
from pathlib import Path
import re
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import reparar_texto_largo as tool
import test_actualizar_campos_aprobados as fixtures


class RepairTextTests(unittest.TestCase):
    def setUp(self):
        self.f = self.fixture()

    def fixture(self):
        f = fixtures.ApprovedFieldsTests(methodName='runTest')
        f.setUp()
        self.addCleanup(f.doCleanups)
        old = 'predios_inscritos_en_sunarp_recorte'
        old_path=f.paths.pop(old)
        new_path=old_path.replace(old,tool.CLASS)
        f.paths[tool.CLASS]=new_path
        for attribute in ('fields','records','indices','locks','descriptions'):
            values=getattr(f,attribute)
            if old_path in values:
                values[new_path]=values.pop(old_path)
        for cls in f.source['clases']:
            if cls['nombre']==old:
                cls['nombre']=tool.CLASS
        for change in f.config['cambios']:
            if change['clase']==old:
                change['clase']=tool.CLASS
        f.write_inputs()
        f.use_sde()
        f.path = f.paths[tool.CLASS]
        f.writes = []
        f.add_length = 10000
        f.sql_overrides = {}
        f.descriptions[f.path].relationshipClassNames = []
        f.descriptions[f.path].attributeRules = []
        f.a.da.ListSubtypes = Mock(return_value={0: {'SubtypeField': '', 'FieldValues': {}}})

        def add(path, name, kind, **kwargs):
            self.assertEqual((path, name, kind), (f.path, tool.TEMP, 'TEXT'))
            self.assertEqual(kwargs['field_length'], 10000)
            self.assertEqual(f.records[path], 0)
            self.assertFalse(any(x.baseName == name for x in f.fields[path]))
            f.fields[path].append(f.make_field(name, 'String', f.add_length, True,
                                             alias=kwargs['field_alias']))
            f.writes.append(tool.OPERATIONS[0])

        def rename(path, name, **kwargs):
            self.assertEqual(set(kwargs), {'new_field_name', 'new_field_alias'})
            new = kwargs['new_field_name']
            self.assertIn((name, new), {(tool.FIELD, tool.BACKUP), (tool.TEMP, tool.FIELD)})
            self.assertEqual(f.records[path], 0)
            self.assertFalse(any(x.baseName == new for x in f.fields[path]))
            value = f.field(tool.CLASS, name)
            value.name = value.baseName = new
            value.aliasName = kwargs['new_field_alias']
            f.writes.append(tool.OPERATIONS[1 if name == tool.FIELD else 2])

        def delete(path, names):
            self.assertEqual(path, f.path)
            self.assertEqual(names, [tool.BACKUP])
            self.assertEqual(f.records[path], 0)
            self.assertGreaterEqual(f.field(tool.CLASS, tool.FIELD).length, 10000)
            f.fields[path] = [value for value in f.fields[path] if value.baseName not in names]
            f.writes.append(tool.OPERATIONS[3])

        def sql(query):
            name = re.search(r"LOWER\(col.name\)=N'([^']+)'", query).group(1)
            matches = [v for v in f.fields[f.path] if v.baseName == name]
            if not matches:
                return []
            value = matches[0]
            return [f.sql_overrides.get(name,
                ['nvarchar', -1 if value.length >= 10000 else value.length * 2])]

        f.a.management.AddField = Mock(side_effect=add)
        f.a.management.AlterField = Mock(side_effect=rename)
        f.a.management.DeleteField = Mock(side_effect=delete)
        f.a.ArcSDESQLExecute.return_value.execute.side_effect = sql
        return f

    def run_tool(self, f=None, **kwargs):
        f = f or self.f
        f.last_repair_report_path = None
        def capture(message):
            if message.startswith('Resultado JSON: '):
                f.last_repair_report_path = Path(message.removeprefix('Resultado JSON: '))
        return tool.run(f.workspace, reports=f.root, arcpy_module=f.a,
                        emit=capture, model_path=f.model_path,
                        config_path=f.config_path, **kwargs)

    def last(self, f=None):
        f = f or self.f
        path = getattr(f, 'last_repair_report_path', None)
        self.assertIsNotNone(path, 'La ejecucion no emitio su Resultado JSON final.')
        self.assertTrue(path.is_relative_to(f.root))
        return path, json.loads(path.read_text(encoding='utf-8'))

    def test_validation_never_changes_schema(self):
        before = copy.deepcopy(self.f.fields)
        _, report = self.run_tool()
        self.assertEqual(report['estado'], 'VALIDACION_OK_SIN_CAMBIOS')
        self.assertEqual(report['etapa'], 'ORIGINAL_4000')
        self.assertEqual(self.f.writes, [])
        self.assertEqual(before, self.f.fields)

    def test_repair_preserves_metadata_numeric_fields_and_repeats_without_writes(self):
        before = tool.snapshot(self.f.a, self.f.path)
        _, report = self.run_tool(apply=True)
        self.assertEqual(report['estado'], 'TEXTO_LARGO_VERIFICADO')
        self.assertEqual(self.f.writes, list(tool.OPERATIONS))
        after = tool.snapshot(self.f.a, self.f.path)
        tool.migration.require_preserved(before, after, [tool.FIELD])
        self.assertEqual(after['numerico']['tipo'], 'String')
        self.assertEqual(after['conteo']['tipo'], 'String')
        self.f.writes.clear()
        self.f.locks[self.f.path] = False
        _, repeated = self.run_tool(apply=True)
        self.assertEqual(repeated['estado'], 'TEXTO_LARGO_VERIFICADO')
        self.assertEqual(self.f.writes, [])

    def test_already_numeric_fields_are_accepted_without_reconversion(self):
        self.f.field(tool.CLASS, 'numerico').type = 'Double'
        self.f.field(tool.CLASS, 'numerico').length = 8
        self.run_tool(apply=True)
        self.assertEqual(self.f.field(tool.CLASS, 'numerico').type, 'Double')
        self.assertEqual(self.f.writes, list(tool.OPERATIONS))

    def test_fault_before_or_after_each_operation_can_resume_from_last_journal(self):
        for stage in range(4):
            for after in (False, True):
                with self.subTest(stage=stage, after=after):
                    f = self.fixture()
                    name = ('AddField', 'AlterField', 'AlterField', 'DeleteField')[stage]
                    operation = getattr(f.a.management, name)
                    original = operation.side_effect
                    failed = [False]

                    def injected(*args, **kwargs):
                        expected = ((stage == 0 and args[1] == tool.TEMP)
                            or (stage == 1 and args[1] == tool.FIELD)
                            or (stage == 2 and args[1] == tool.TEMP)
                            or (stage == 3 and args[1] == [tool.BACKUP]))
                        if expected and not failed[0]:
                            failed[0] = True
                            if after:
                                original(*args, **kwargs)
                            raise RuntimeError('Fallo inyectado de GP')
                        return original(*args, **kwargs)

                    operation.side_effect = injected
                    with self.assertRaisesRegex(RuntimeError, 'Fallo inyectado'):
                        self.run_tool(f, apply=True)
                    recovery, failed_report = self.last(f)
                    self.assertEqual(failed_report['estado'], 'ERROR_DETENIDO')
                    self.assertEqual(failed_report['operacion_pendiente'], tool.OPERATIONS[stage])
                    operation.side_effect = original
                    _, resumed = self.run_tool(f, apply=True, recovery_path=recovery)
                    self.assertEqual(resumed['estado'], 'TEXTO_LARGO_VERIFICADO')
                    self.assertEqual(f.writes, list(tool.OPERATIONS))
                    self.assertEqual(set(tool.snapshot(f.a, f.path)) & {tool.TEMP, tool.BACKUP}, set())

    def stop_after_add(self, f=None):
        f = f or self.f
        original = f.a.management.AddField.side_effect
        def fail(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError('Interrupcion despues de AddField')
        f.a.management.AddField.side_effect = fail
        with self.assertRaises(RuntimeError):
            self.run_tool(f, apply=True)
        f.a.management.AddField.side_effect = original
        return self.last(f)[0]

    def test_temporaries_without_journal_block_and_are_never_deleted(self):
        self.stop_after_add()
        count = len(self.f.writes)
        with self.assertRaisesRegex(ValueError, 'Hay columnas temporales'):
            self.run_tool(apply=True)
        self.assertEqual(len(self.f.writes), count)
        self.f.a.management.DeleteField.assert_not_called()

    def test_recovery_validation_is_read_only_then_can_be_applied(self):
        recovery = self.stop_after_add()
        before = tool.snapshot(self.f.a, self.f.path)
        _, report = self.run_tool(recovery_path=recovery)
        self.assertEqual(report['etapa'], 'TEMPORAL_VERIFICADO')
        self.assertEqual(before, tool.snapshot(self.f.a, self.f.path))
        self.run_tool(apply=True, recovery_path=report['archivo_resultado'])
        self.assertEqual(self.f.writes, list(tool.OPERATIONS))

    def test_wrong_connection_model_and_journal_identity_block_recovery(self):
        recovery = self.stop_after_add()
        content = json.loads(recovery.read_text(encoding='utf-8'))
        for key, value in [('modelo_sha256', 'otro'), ('aprobacion_sha256', 'otro'),
                           ('procedimiento', 'otro'), ('identidad', {})]:
            with self.subTest(key=key):
                invalid = dict(content, **{key: value})
                path = self.f.root / 'incorrecto.json'
                path.write_text(json.dumps(invalid), encoding='utf-8')
                with self.assertRaises(ValueError):
                    self.run_tool(apply=True, recovery_path=path)
        self.assertEqual(self.f.writes, [tool.OPERATIONS[0]])

    def test_foreign_column_or_changed_alias_during_recovery_blocks_deletion(self):
        recovery = self.stop_after_add()
        value = self.f.field(tool.CLASS, tool.TEMP)
        value.aliasName = 'Alias ajeno'
        with self.assertRaisesRegex(ValueError, 'propiedades distintas'):
            self.run_tool(apply=True, recovery_path=recovery)
        self.f.a.management.DeleteField.assert_not_called()
        value.aliasName = self.f.field(tool.CLASS, tool.FIELD).aliasName
        self.f.fields[self.f.path].append(self.f.make_field('campo_ajeno', 'String', 10, True))
        with self.assertRaisesRegex(ValueError, 'Campos ajenos'):
            self.run_tool(apply=True, recovery_path=recovery)
        self.f.a.management.DeleteField.assert_not_called()

    def test_short_or_nonunicode_new_column_stops_before_original_is_renamed(self):
        for kind, length in [('nvarchar', 8000), ('varchar', -1)]:
            with self.subTest(kind=kind):
                f = self.fixture()
                f.sql_overrides[tool.TEMP] = [kind, length]
                with self.assertRaises(ValueError):
                    self.run_tool(f, apply=True)
                self.assertEqual(f.field(tool.CLASS, tool.FIELD).length, 4000)
                f.a.management.AlterField.assert_not_called()
                f.a.management.DeleteField.assert_not_called()

    def test_original_sql_nonunicode_blocks_before_any_write(self):
        self.f.sql_overrides[tool.FIELD] = ['varchar', 4000]
        with self.assertRaisesRegex(ValueError, 'preservar Unicode'):
            self.run_tool(apply=True)
        self.assertEqual(self.f.writes, [])

    def test_old_column_guards_block_before_any_write(self):
        value = self.f.field(tool.CLASS, tool.FIELD)
        for prop, invalid in [('required', True), ('domain', 'd'), ('isNullable', False),
                              ('defaultValue', 'x'), ('length', 8000), ('type', 'Double')]:
            with self.subTest(prop=prop):
                before = getattr(value, prop)
                setattr(value, prop, invalid)
                with self.assertRaises(ValueError):
                    self.run_tool(apply=True)
                setattr(value, prop, before)
        self.assertEqual(self.f.writes, [])

    def test_rows_version_audit_dependencies_and_index_block_before_writes(self):
        d = self.f.descriptions[self.f.path]
        for prop, invalid in [('isVersioned', True), ('hasGlobalID', False), ('isTimeInUTC', False),
                              ('relationshipClassNames', ['rel']), ('attributeRules', [{'name': 'r'}]),
                              ('isArchived', True), ('isReplicated', True), ('subtypeFieldName', 'tipo')]:
            with self.subTest(prop=prop):
                present, before = hasattr(d, prop), getattr(d, prop, None)
                setattr(d, prop, invalid)
                with self.assertRaises(ValueError):
                    self.run_tool(apply=True)
                if present:
                    setattr(d, prop, before)
                else:
                    delattr(d, prop)
        self.f.records[self.f.path] = 1
        with self.assertRaises(ValueError):
            self.run_tool(apply=True)
        self.f.records[self.f.path] = 0
        self.f.indices[self.f.path] = [SimpleNamespace(name='ix_texto', fields=[self.f.field(tool.CLASS, tool.FIELD)])]
        with self.assertRaisesRegex(ValueError, 'Indice ix_texto'):
            self.run_tool(apply=True)
        self.assertEqual(self.f.writes, [])

    def test_subtype_domain_and_defaults_block(self):
        for item in [{'SubtypeField': 'tipo'}, {'SubtypeField': '', 'FieldValues': {tool.FIELD: ('x', None)}},
                     {'SubtypeField': '', 'FieldValues': {tool.FIELD: (None, SimpleNamespace(name='d'))}}]:
            self.f.a.da.ListSubtypes.return_value = {0: item}
            with self.assertRaises(ValueError):
                self.run_tool(apply=True)
        self.assertEqual(self.f.writes, [])

    def test_unavailable_lock_blocks_before_writes(self):
        self.f.locks[self.f.path] = False
        self.run_tool()
        with self.assertRaisesRegex(ValueError, 'bloqueo de esquema'):
            self.run_tool(apply=True)
        self.assertEqual(self.f.writes, [])

    def test_row_arriving_before_delete_blocks_deletion(self):
        original = self.f.a.management.AlterField.side_effect
        def insert_after_rename(path, name, **kwargs):
            original(path, name, **kwargs)
            if name == tool.TEMP:
                self.f.records[path] = 1
        self.f.a.management.AlterField.side_effect = insert_after_rename
        with self.assertRaisesRegex(ValueError, 'contiene 1 registros'):
            self.run_tool(apply=True)
        self.f.a.management.DeleteField.assert_not_called()
        self.assertIn(tool.BACKUP, tool.snapshot(self.f.a, self.f.path))

    def test_sql_statements_are_only_select(self):
        self.run_tool(apply=True)
        for call in self.f.a.ArcSDESQLExecute.return_value.execute.call_args_list:
            self.assertTrue(call.args[0].startswith('SELECT '))
            self.assertNotIn(';', call.args[0])


if __name__ == '__main__':
    unittest.main()
