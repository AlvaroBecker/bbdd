"""Regresion del cierre 1.9 con ArcPy simulado y el modelo completo 76/3340."""
import copy
from contextlib import nullcontext
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import cerrar_tipos_kmz as tool


class ProjectCursor:
    def __enter__(self):
        return iter([('000000000001',)])

    def __exit__(self, *args):
        return False


class CloseTypesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(tool.__file__).parent
        cls.base_reference = json.loads((root / 'esquema_anterior_1_8.json').read_text(encoding='utf-8-sig'))
        cls.target_reference = json.loads((root / 'esquema.json').read_text(encoding='utf-8-sig'))
        cls.config_reference = json.loads((root / 'cierre_tipos_1_9.json').read_text(encoding='utf-8-sig'))

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.workspace = str(self.root / 'fixture.gdb')
        self.ds = os.path.join(self.workspace, 'Datos_Proyecto')
        self.parent = os.path.join(self.workspace, 'mline_tc_proyecto')
        self.base = copy.deepcopy(self.base_reference)
        self.target = copy.deepcopy(self.target_reference)
        self.config = copy.deepcopy(self.config_reference)
        self.write_reference()
        self.paths = {cls['nombre']: os.path.join(self.ds, cls['nombre']) for cls in self.base['clases']}
        self.fields, self.records, self.indices, self.locks, self.descriptions = {}, {}, {}, {}, {}
        for cls in self.base['clases']:
            name, path = cls['nombre'], self.paths[cls['nombre']]
            self.fields[path] = [self.make_field(field['nombre'], tool.runner.engine.TYPE[field['tipo']],
                field.get('longitud') or 0, field['nullable'], alias=field.get('alias'),
                domain=field.get('dominio') or '') for field in cls['campos']]
            for native, kind in [('OBJECTID', 'OID'), ('Shape', 'Geometry'), ('GlobalID', 'GlobalID'),
                ('created_user', 'String'), ('created_date', 'Date'), ('last_edited_user', 'String'),
                ('last_edited_date', 'Date')]:
                self.fields[path].append(self.make_field(native, kind, 255 if kind == 'String' else 0,
                                                       True, required=True))
            self.records[path], self.indices[path] = 0, []
            self.descriptions[path] = SimpleNamespace(dataType='FeatureClass', path=self.ds,
                shapeType=cls['geometria'].title(), spatialReference=SimpleNamespace(factoryCode=4326),
                hasZ=True, hasM=False, hasGlobalID=True, editorTrackingEnabled=True,
                isTimeInUTC=True, isVersioned=False, creatorFieldName='created_user',
                createdAtFieldName='created_date', editorFieldName='last_edited_user',
                editedAtFieldName='last_edited_date', hasAttachments=False, isArchived=False,
                relationshipClassNames=[], controllerMemberships=[], attributeRules=[])
        self.fields[self.parent] = [self.make_field('co_proyecto', 'String', 12, False)]
        self.descriptions[self.workspace] = SimpleNamespace(workspaceType='LocalDatabase',
            connectionProperties=SimpleNamespace(database='ArcGisAWS', user='gis'))
        self.descriptions[self.ds] = SimpleNamespace(dataType='FeatureDataset',
            spatialReference=SimpleNamespace(factoryCode=4326), isVersioned=False)
        self.descriptions[self.parent] = SimpleNamespace(hasOID=True)
        self.domains = [SimpleNamespace(name=name, type='Text', domainType='CodedValue',
            codedValues={value: value for value in definition['valores']})
            for name, definition in self.base['dominios'].items()]
        self.a = SimpleNamespace(GetInstallInfo=lambda: {'Version': 'SIMULADA'},
            EnvManager=lambda **kwargs: nullcontext(), Exists=lambda path: path in self.descriptions,
            Describe=lambda path: self.descriptions[path], ValidateTableName=lambda name, workspace: name,
            ValidateFieldName=lambda name, workspace: name, ListDatasets=lambda **kwargs: ['Datos_Proyecto'],
            ListFeatureClasses=lambda feature_dataset='': list(self.paths) if feature_dataset else [],
            ListTables=lambda: ['mline_tc_proyecto'],
            ListFields=Mock(side_effect=lambda path: list(self.fields[path])),
            ListIndexes=Mock(side_effect=lambda path: list(self.indices[path])),
            TestSchemaLock=Mock(side_effect=lambda path: self.locks.get(path, True)),
            da=SimpleNamespace(ListDomains=lambda workspace: self.domains,
                               SearchCursor=lambda *args: ProjectCursor()),
            management=SimpleNamespace(GetCount=Mock(side_effect=lambda path:
                SimpleNamespace(getOutput=lambda index: str(self.records[path]))),
                AlterField=Mock(side_effect=self.alter)))

    @staticmethod
    def make_field(name, kind, length, nullable, alias=None, required=False, domain=''):
        return SimpleNamespace(name=name, baseName=name, type=kind, length=length,
            aliasName=alias or name, isNullable=nullable, domain=domain, defaultValue=None,
            required=required, precision=0, scale=0)

    def write_reference(self):
        for name, value in [('esquema.json', self.target), ('esquema_anterior_1_8.json', self.base),
                            ('cierre_tipos_1_9.json', self.config)]:
            (self.root / name).write_text(json.dumps(value), encoding='utf-8')

    def field(self, cls, name):
        return next(field for field in self.fields[self.paths[cls]] if field.baseName == name)

    def alter(self, path, name, *, field_type):
        field = next(field for field in self.fields[path] if field.baseName == name)
        field.type = tool.runner.engine.TYPE[field_type]
        field.length = 4 if field_type == 'LONG' else 8

    def complete(self, count=8):
        for (cls, field), kind in sorted(tool.NUMERIC.items())[:count]:
            self.alter(self.paths[cls], field, field_type=kind)

    def run_tool(self, apply=False):
        self.final_report_path = None
        self.messages = []
        def capture(message):
            self.messages.append(message)
            if message.startswith('Resultado JSON: '):
                self.final_report_path = Path(message.removeprefix('Resultado JSON: '))
        with patch.object(tool, 'load_reference', return_value=(self.base, self.target, self.config)):
            return tool.run(self.workspace, apply=apply, reports=self.root, model_dir=self.root,
                            arcpy_module=self.a, emit=capture)

    def latest(self):
        self.assertIsNotNone(self.final_report_path)
        return json.loads(self.final_report_path.read_text(encoding='utf-8'))

    def assert_closed(self, report):
        self.assertEqual(report['estado'], 'TIPOS_CERRADOS_CON_PENDIENTES_DE_INGESTA')
        self.assertTrue(report['cierre_verificado'])
        self.assertEqual(report['cambios_pendientes_destino'], 0)
        self.assertEqual(report['campos_pendientes_modelo'], 0)
        self.assertEqual(report['destino_despues']['campos_verificados'], 3340)
        self.assertEqual(report['destino_despues']['incidencias'], [])
        self.assertFalse(report['ingesta_autorizada'])
        self.assertEqual(report['bloqueos_ingesta'], self.config['bloqueos_ingesta'])
        self.assertTrue(all(row['resuelto'] is False for row in report['bloqueos_ingesta']))
        self.assertEqual(len(report['incidencias_campos_ingesta']), 4)

    def test_default_validation_has_no_writes_and_does_not_claim_physical_closure(self):
        before = copy.deepcopy(self.fields)
        references = tool.input_hashes(self.root)
        folder, report = self.run_tool()
        self.assertEqual(report['estado'], 'CIERRE_VALIDADO_SIN_CAMBIOS')
        self.assertFalse(report['cierre_verificado'])
        self.assertEqual(report['cambios_pendientes_destino'], 8)
        self.assertEqual(report['campos_pendientes_modelo'], 0)
        self.assertEqual(report['confirmaciones_texto'], 722)
        self.assertEqual(report['destino_antes']['campos_verificados'], 3340)
        self.assertNotIn('destino_despues', report)
        self.a.management.AlterField.assert_not_called()
        self.assertEqual(before, self.fields)
        self.assertEqual(tool.input_hashes(self.root), references)
        self.assertTrue(Path(report['archivo_plan']).is_relative_to(folder))

    def test_apply_changes_exact_eight_and_preserves_remaining_model_fields(self):
        before = {name: tool.migration.snapshot(self.a, path) for name, path in self.paths.items()}
        _, report = self.run_tool(apply=True)
        self.assert_closed(report)
        self.assertEqual(len(report['completadas']), 8)
        self.assertEqual(self.a.management.AlterField.call_count, 8)
        expected = {(self.paths[cls], field, kind) for (cls, field), kind in tool.NUMERIC.items()}
        actual = {(call.args[0], call.args[1], call.kwargs['field_type'])
                  for call in self.a.management.AlterField.call_args_list}
        self.assertEqual(actual, expected)
        self.assertTrue(all(set(call.kwargs) == {'field_type'}
                            for call in self.a.management.AlterField.call_args_list))
        for name, path in self.paths.items():
            allowed = [field for (cls, field) in tool.NUMERIC if cls == name]
            tool.migration.require_preserved(before[name], tool.migration.snapshot(self.a, path), allowed)

    def test_partial_resume_skips_already_applied_fields(self):
        self.complete(3)
        _, report = self.run_tool(apply=True)
        self.assert_closed(report)
        self.assertEqual(len(report['completadas']), 5)
        self.assertEqual(self.a.management.AlterField.call_count, 5)
        self.assertEqual(sum(row['accion'] == 'YA_OBJETIVO' for row in report['plan']), 3)

    def test_reapply_is_idempotent_and_validation_of_closed_dest_has_no_writes(self):
        self.complete()
        for apply in (False, True):
            _, report = self.run_tool(apply=apply)
            self.assert_closed(report)
            self.assertTrue(report['verificacion_final_reutiliza_lectura_previa'])
            self.assertEqual(report['completadas'], [])
        self.a.management.AlterField.assert_not_called()

    def test_nonempty_last_class_blocks_entire_batch_before_first_mutation(self):
        self.records[self.paths['suelos_recorte']] = 1
        with self.assertRaisesRegex(ValueError, 'suelos_recorte contiene 1 registros'):
            self.run_tool(apply=True)
        self.a.management.AlterField.assert_not_called()
        self.assertEqual(self.latest()['clase_en_curso'], 'suelos_recorte')

    def test_locked_last_class_blocks_entire_apply_but_readonly_can_report(self):
        self.locks[self.paths['suelos_recorte']] = False
        _, validation_report = self.run_tool()
        self.assertEqual(validation_report['cambios_pendientes_destino'], 8)
        self.assertTrue(any('TestSchemaLock no disponible' in item for item in validation_report['advertencias']))
        with self.assertRaisesRegex(ValueError, 'bloqueo de esquema'):
            self.run_tool(apply=True)
        self.a.management.AlterField.assert_not_called()

    def test_unrelated_class_type_difference_blocks_all_mutations(self):
        cls = next(cls for cls in self.base['clases'] if cls['nombre'] not in {x[0] for x in tool.NUMERIC})
        own = next(field for field in cls['campos'] if field['tipo'] == 'TEXT')
        self.field(cls['nombre'], own['nombre']).type = 'Integer'
        with self.assertRaisesRegex(ValueError, 'Validacion global antes'):
            self.run_tool(apply=True)
        self.a.management.AlterField.assert_not_called()
        report = self.latest()
        self.assertFalse(report['destino_antes']['verificado'])
        self.assertFalse(report['cierre_verificado'])

    def test_unexpected_field_in_affected_class_blocks_before_first_mutation(self):
        self.fields[self.paths['suelos_recorte']].append(self.make_field('extension', 'String', 10, True))
        with self.assertRaisesRegex(ValueError, 'fuera del esquema EFT'):
            self.run_tool(apply=True)
        self.a.management.AlterField.assert_not_called()

    def test_candidate_index_and_dependency_block_before_first_mutation(self):
        field = self.field('suelos_recorte', 'p_aui_suel')
        self.indices[self.paths['suelos_recorte']] = [SimpleNamespace(name='idx_protegido', fields=[field],
            isUnique=False, isAscending=True)]
        with self.assertRaisesRegex(ValueError, 'Indice idx_protegido'):
            self.run_tool(apply=True)
        self.indices[self.paths['suelos_recorte']] = []
        self.descriptions[self.paths['suelos_recorte']].attributeRules = ['regla']
        with self.assertRaisesRegex(ValueError, 'reglas de atributos'):
            self.run_tool(apply=True)
        self.a.management.AlterField.assert_not_called()

    def test_wrong_source_type_and_default_value_block_before_first_mutation(self):
        field = self.field('suelos_recorte', 'p_aui_suel')
        field.type = 'Double'
        with self.assertRaisesRegex(ValueError, 'solo se admite TEXT'):
            self.run_tool(apply=True)
        field.type = 'String'
        field.defaultValue = '0'
        with self.assertRaisesRegex(ValueError, 'valor predeterminado'):
            self.run_tool(apply=True)
        self.a.management.AlterField.assert_not_called()

    def test_versioned_dataset_or_wrong_audit_binding_blocks_before_first_mutation(self):
        self.descriptions[self.ds].isVersioned = True
        with self.assertRaisesRegex(ValueError, 'ya esta versionado'):
            self.run_tool(apply=True)
        self.descriptions[self.ds].isVersioned = False
        self.descriptions[self.paths['suelos_recorte']].creatorFieldName = 'other_user'
        with self.assertRaisesRegex(ValueError, 'auditoria incorrecto'):
            self.run_tool(apply=True)
        self.a.management.AlterField.assert_not_called()

    def test_last_class_missing_blocks_before_first_mutation(self):
        self.paths.pop('suelos_recorte')
        with self.assertRaisesRegex(ValueError, 'No existe suelos_recorte'):
            self.run_tool(apply=True)
        self.a.management.AlterField.assert_not_called()

    def test_gp_failure_preserves_diagnostic_and_resumes_without_repeating_success(self):
        def fail_second(path, name, **kwargs):
            if name == 'base':
                raise RuntimeError('Fallo GP simulado')
            self.alter(path, name, **kwargs)
        self.a.management.AlterField.side_effect = fail_second
        with self.assertRaisesRegex(RuntimeError, 'Fallo GP simulado'):
            self.run_tool(apply=True)
        failed = self.latest()
        self.assertEqual(failed['estado'], 'ERROR_DETENIDO')
        self.assertEqual(failed['campo_en_curso'], 'base')
        self.assertEqual(failed['completadas'], ['sitios_arqueologicos_poligono_recorte.alt_mode'])
        self.assertEqual(failed['cambios_pendientes_destino'], 7)
        self.assertTrue(failed['cambios_en_sde'])
        self.a.management.AlterField.reset_mock(side_effect=True)
        self.a.management.AlterField.side_effect = self.alter
        _, report = self.run_tool(apply=True)
        self.assert_closed(report)
        self.assertEqual(self.a.management.AlterField.call_count, 7)

    def test_failure_after_db_change_is_observed_and_not_repeated_on_resume(self):
        def change_then_fail(path, name, **kwargs):
            self.alter(path, name, **kwargs)
            raise RuntimeError('Error posterior al cambio')
        self.a.management.AlterField.side_effect = change_then_fail
        with self.assertRaisesRegex(RuntimeError, 'Error posterior al cambio'):
            self.run_tool(apply=True)
        failed = self.latest()
        self.assertEqual(failed['completadas'], [])
        self.assertEqual(failed['cambios_pendientes_destino'], 7)
        self.assertTrue(failed['cambios_en_sde'])
        self.assertFalse(failed['cierre_verificado'])
        self.a.management.AlterField.reset_mock(side_effect=True)
        self.a.management.AlterField.side_effect = self.alter
        _, report = self.run_tool(apply=True)
        self.assert_closed(report)
        self.assertEqual(self.a.management.AlterField.call_count, 7)

    def test_unexpected_alias_change_stops_and_never_claims_closure(self):
        def bad_alter(path, name, **kwargs):
            self.alter(path, name, **kwargs)
            next(field for field in self.fields[path] if field.baseName == name).aliasName = 'cambiado'
        self.a.management.AlterField.side_effect = bad_alter
        with self.assertRaisesRegex(ValueError, 'cambio inesperado de propiedades'):
            self.run_tool(apply=True)
        self.assertEqual(self.a.management.AlterField.call_count, 1)
        self.assertFalse(self.latest()['cierre_verificado'])

    def test_inputs_changed_after_global_read_block_before_first_mutation(self):
        inspect = tool.inspect_global
        def change_reference(*args, **kwargs):
            result = inspect(*args, **kwargs)
            with (self.root / 'cierre_tipos_1_9.json').open('a') as stream:
                stream.write(' ')
            return result
        with patch.object(tool, 'inspect_global', side_effect=change_reference):
            with self.assertRaisesRegex(ValueError, 'cambiaron durante la ejecucion'):
                self.run_tool(apply=True)
        self.a.management.AlterField.assert_not_called()

    def test_zero_effect_alter_is_detected(self):
        self.a.management.AlterField.side_effect = None
        with self.assertRaisesRegex(ValueError, 'ArcGIS no confirma el tipo objetivo'):
            self.run_tool(apply=True)
        self.assertEqual(self.a.management.AlterField.call_count, 1)
        self.assertEqual(self.latest()['cambios_pendientes_destino'], 8)

    def test_final_global_check_detects_unrelated_effect(self):
        def alter_and_damage_other_class(path, name, **kwargs):
            self.alter(path, name, **kwargs)
            if name == 'p_aui_suel':
                self.field('accesos', 'proyecto').length = 1
        self.a.management.AlterField.side_effect = alter_and_damage_other_class
        with self.assertRaisesRegex(ValueError, 'Validacion global despues'):
            self.run_tool(apply=True)
        failed = self.latest()
        self.assertEqual(len(failed['completadas']), 8)
        self.assertEqual(failed['cambios_pendientes_destino'], 0)
        self.assertFalse(failed['cierre_verificado'])
        self.assertFalse(failed['destino_despues']['verificado'])

    def test_scope_cannot_add_fields_or_approve_arbitrary_numeric_target(self):
        self.config['cambios_fisicos'][0]['tipo_objetivo'] = 'SHORT'
        with self.assertRaisesRegex(ValueError, 'seis LONG y dos DOUBLE'):
            self.run_tool(apply=True)
        self.a.management.AlterField.assert_not_called()
        self.assertEqual(self.latest()['estado'], 'ERROR_DETENIDO')

    def test_reports_are_immutable_per_stage_and_the_plan_matches_final_json(self):
        folder, report = self.run_tool(apply=True)
        revisions = sorted((folder / 'estados').iterdir())
        self.assertEqual(len(revisions), 19)  # INICIADO, PREVALIDADO, 8 antes/8 despues, final.
        contents = {str(path): path.read_bytes() for path in folder.rglob('*') if path.is_file()}
        self.run_tool()
        self.assertTrue(all(Path(path).read_bytes() == raw for path, raw in contents.items()))
        self.assertIn('ALTERADA_VERIFICADA', Path(report['archivo_plan']).read_text(encoding='utf-8-sig'))
        self.assertEqual(self.latest()['bloqueos_ingesta'], report['bloqueos_ingesta'])


if __name__ == '__main__':
    unittest.main()
