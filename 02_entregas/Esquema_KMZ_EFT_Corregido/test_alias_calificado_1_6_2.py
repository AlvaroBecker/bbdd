"""Regresion del alias SDE y reanudacion contra la evidencia original."""
import copy
import hashlib
import json
import os
from pathlib import Path
import unittest

import renombrar_clases as tool
import test_renombrar_clases as fixtures


class QualifiedAliasTests(unittest.TestCase):
    def setUp(self):
        fixture = fixtures.RenameTests(methodName='runTest')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fx, self.f = fixture, fixture.f
        self.old, self.new = fixture.old, fixture.new
        self.old_path = self.f.paths[self.old]
        self.new_path = tool.desired_path(self.old_path, self.old, self.new)
        self.field = self.f.field(self.old, 'medida')
        self.field.aliasName = os.path.basename(self.old_path) + '.medida'
        self.reference = self.f.root / 'informe_original.json'
        self.original = self.make_reference()
        self.write_reference()
        self.messages = []

    def make_reference(self):
        baseline, plan = {}, []
        for row in self.fx.mapping['clases']:
            name = row['nombre_nuevo']
            path = self.f.paths[row['nombre_anterior']]
            baseline[name] = dict(campos=tool.snapshot(self.f.a, path),
                indices=tool.migration.indexes_snapshot(self.f.a, path, set()),
                geometria=tool.geometry_snapshot(self.f.a, path))
            plan.append(dict(nombre_nuevo=name, ruta_actual=path))
        return dict(version_paquete='1.6', modo='APLICAR_NOMBRES', estado='ERROR_DETENIDO',
            workspace=self.f.workspace, database='ArcGisAWS', owner='gis',
            modelo_sha256=self.sha(self.fx.model_path), mapeo_sha256=self.sha(self.fx.mapping_path),
            aprobacion_tipos_sha256=self.sha(self.fx.config_path),
            campos_y_metadatos_antes=baseline, plan=plan)

    @staticmethod
    def sha(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def write_reference(self):
        self.reference.write_text(json.dumps(self.original), encoding='utf-8')
        self.original_raw = self.reference.read_bytes()

    def run_tool(self, apply=False, previous=True, **kwargs):
        self.messages = []
        return tool.run(self.f.workspace, apply=apply, reports=self.f.root,
            arcpy_module=self.f.a, emit=self.messages.append, model_path=self.fx.model_path,
            mapping_path=self.fx.mapping_path, config_path=self.fx.config_path,
            previous_report_path=self.reference if previous else None, **kwargs)

    def final_report(self):
        paths = [message.removeprefix('Resultado JSON: ') for message in self.messages
                 if message.startswith('Resultado JSON: ')]
        self.assertTrue(paths, 'La ejecucion debe emitir su informe final.')
        return json.loads(Path(paths[-1]).read_text(encoding='utf-8'))

    def automatic_rename(self, path, destination, kind):
        self.fx.rename(path, destination, kind)
        self.field.aliasName = os.path.basename(destination) + '.medida'

    def emulate_already_renamed(self):
        self.automatic_rename(self.old_path, self.new_path, 'FeatureClass')
        self.fx.calls.clear()
        self.f.a.management.Rename.reset_mock()

    def test_alias_changed_by_rename_is_recognized_audited_and_deduplicated(self):
        self.f.a.management.Rename.side_effect = self.automatic_rename
        _, report = self.run_tool(apply=True, previous=False)
        self.assertEqual(report['estado'], 'NOMBRES_VERIFICADOS')
        changes = report['aliases_calificados_reconocidos']
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]['antes'], 'GIS.' + self.old + '.medida')
        self.assertEqual(changes[0]['despues'], 'GIS.' + self.new + '.medida')
        self.assertEqual(report['campos_y_metadatos_antes'][self.new]['campos']['medida']['alias'],
                         'GIS.' + self.old + '.medida')
        self.assertEqual(report['rutas_referencia'][self.new], self.old_path)
        self.assertEqual(self.f.a.management.Rename.call_count, 1)
        self.f.a.management.AlterField.assert_not_called()

    def test_resume_compares_original_and_never_repeats_completed_rename(self):
        self.emulate_already_renamed()
        _, validation = self.run_tool()
        self.assertEqual(validation['estado'], 'VALIDACION_OK_SIN_CAMBIOS')
        self.assertEqual(len(validation['aliases_calificados_reconocidos']), 1)
        self.assertTrue(any(message.startswith('ALIAS CALIFICADO reconocido: ') for message in self.messages))
        self.assertEqual(self.fx.calls, [])
        _, report = self.run_tool(apply=True)
        self.assertEqual(report['estado'], 'NOMBRES_VERIFICADOS')
        self.f.a.management.Rename.assert_not_called()
        self.assertEqual(self.f.a.AlterAliasName.call_count, 2)
        self.assertEqual(report['campos_y_metadatos_antes'], self.original['campos_y_metadatos_antes'])
        self.assertEqual(self.reference.read_bytes(), self.original_raw)
        self.assertEqual(report['informe_referencia']['sha256'], self.sha(self.reference))

    def test_version_162_resume_uses_immutable_paths_not_the_completed_plan(self):
        self.emulate_already_renamed()
        _, completed = self.run_tool(apply=True)
        emitted_path = Path(completed['archivo_resultado'])
        self.assertEqual(next(entry['ruta_actual'] for entry in completed['plan'] if entry['nombre_nuevo'] == self.new),
                         self.new_path)
        self.assertEqual(completed['rutas_referencia'][self.new], self.old_path)
        self.fx.calls.clear()
        _, second = tool.run(self.f.workspace, apply=True, reports=self.f.root, arcpy_module=self.f.a,
            emit=lambda message: None, model_path=self.fx.model_path, mapping_path=self.fx.mapping_path,
            config_path=self.fx.config_path, previous_report_path=emitted_path)
        self.assertEqual(second['estado'], 'NOMBRES_VERIFICADOS')
        self.assertEqual(second['campos_y_metadatos_antes'], self.original['campos_y_metadatos_antes'])
        self.assertEqual(self.fx.calls, [])

    def test_alias_plus_type_change_is_rejected_before_any_write(self):
        self.emulate_already_renamed()
        self.field.type, self.field.length = 'Double', 8
        with self.assertRaisesRegex(ValueError, 'modificaron campos'):
            self.run_tool(apply=True)
        report = self.final_report()
        self.assertEqual(report['estado'], 'ERROR_DETENIDO')
        self.assertEqual(report['aliases_calificados_reconocidos'], [])
        self.assertTrue(any(item['campo'] == 'medida' and item['propiedad'] == 'tipo'
                            for item in report['diferencias_campos_no_admitidas']))
        self.assertIn(self.new, report['campos_observados_al_detener'])
        self.assertEqual(self.fx.calls, [])

    def test_other_owner_field_or_custom_description_is_not_normalized(self):
        self.emulate_already_renamed()
        candidates = ('OTRO.' + self.new + '.medida', 'GIS.' + self.new + '.otro',
                      'Descripcion GIS.' + self.new + '.medida', 'GIS.' + self.new.upper() + '.medida')
        for alias in candidates:
            with self.subTest(alias=alias):
                self.field.aliasName = alias
                with self.assertRaisesRegex(ValueError, 'medida.alias'):
                    self.run_tool(apply=True)
                report = self.final_report()
                self.assertEqual(report['aliases_calificados_reconocidos'], [])
                self.assertEqual(report['diferencias_campos_no_admitidas'][0]['despues'], alias)
                self.assertEqual(self.fx.calls, [])

    def test_custom_original_alias_cannot_be_rewritten_as_qualified_alias(self):
        self.original['campos_y_metadatos_antes'][self.new]['campos']['medida']['alias'] = 'Medida descriptiva'
        self.write_reference()
        self.emulate_already_renamed()
        with self.assertRaisesRegex(ValueError, 'medida.alias'):
            self.run_tool(apply=True)
        self.assertEqual(self.fx.calls, [])

    def test_missing_or_added_field_and_changed_domain_remain_errors(self):
        before = copy.deepcopy(self.original['campos_y_metadatos_antes'][self.new]['campos'])
        context = tool.reference_context(next(row for row in self.fx.mapping['clases'] if row['nombre_nuevo'] == self.new), self.old_path)
        for mode in ('missing', 'added', 'domain', 'name', 'length', 'precision', 'scale', 'nullable', 'default'):
            after = copy.deepcopy(before)
            after['medida']['alias'] = 'GIS.' + self.new + '.medida'
            if mode == 'missing':
                del after['proyecto']
            elif mode == 'added':
                after['extra'] = copy.deepcopy(after['proyecto'])
            else:
                prop, value = {'domain': ('dominio', 'otro'), 'name': ('nombre', 'otra_medida'),
                    'length': ('longitud', 99), 'precision': ('precision', 11), 'scale': ('escala', 2),
                    'nullable': ('nullable', False), 'default': ('defecto', "'otro'")}[mode]
                after['medida'][prop] = value
            with self.subTest(mode=mode):
                differences, _ = tool.compare_fields(before, after, context, self.new_path)
                self.assertTrue(differences)
                self.assertEqual(before, self.original['campos_y_metadatos_antes'][self.new]['campos'])

    def test_hash_or_destination_mismatch_blocks_before_arcpy(self):
        correct = copy.deepcopy(self.original)
        for key in ('modelo_sha256', 'mapeo_sha256', 'aprobacion_tipos_sha256', 'workspace', 'database', 'owner'):
            self.original = copy.deepcopy(correct)
            self.original[key] = 'otro'
            self.write_reference()
            self.f.a.ListFields.reset_mock()
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.run_tool(apply=True)
            self.f.a.ListFields.assert_not_called()
            self.assertEqual(self.fx.calls, [])

    def test_reference_missing_class_or_escaped_path_is_not_rebuilt(self):
        correct = copy.deepcopy(self.original)
        for change in ('class', 'path', 'dataset', 'name'):
            self.original = copy.deepcopy(correct)
            entry = next(item for item in self.original['plan'] if item['nombre_nuevo'] == self.new)
            if change == 'class':
                del self.original['campos_y_metadatos_antes'][self.new]
            elif change == 'path':
                entry['ruta_actual'] = str(self.f.root / 'otra.gdb' / 'GIS.Datos_Proyecto' / ('GIS.' + self.old))
            elif change == 'dataset':
                entry['ruta_actual'] = str(Path(self.f.workspace) / 'Otro_Dataset' / ('GIS.' + self.old))
            else:
                entry['ruta_actual'] = str(Path(self.f.ds) / 'GIS.otro_nombre')
            self.write_reference()
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.run_tool(apply=True)
            self.assertEqual(self.fx.calls, [])

    def test_real_index_and_geometry_changes_are_not_covered_by_alias_rule(self):
        self.emulate_already_renamed()
        self.original['campos_y_metadatos_antes'][self.new]['indices'] = [{'nombre': 'indice_perdido'}]
        self.write_reference()
        with self.assertRaisesRegex(ValueError, 'indices'):
            self.run_tool(apply=True)
        self.assertEqual(self.fx.calls, [])
        self.original['campos_y_metadatos_antes'][self.new]['indices'] = []
        self.original['campos_y_metadatos_antes'][self.new]['geometria']['hasZ'] = False
        self.write_reference()
        with self.assertRaisesRegex(ValueError, 'geometria'):
            self.run_tool(apply=True)
        self.assertEqual(self.fx.calls, [])

    def test_reference_changed_while_reading_stops_before_mutation(self):
        self.emulate_already_renamed()
        original_read = self.f.a.ListFields.side_effect
        modified = False
        def change_reference(path):
            nonlocal modified
            if not modified:
                self.reference.write_bytes(self.original_raw + b' ')
                modified = True
            return original_read(path)
        self.f.a.ListFields.side_effect = change_reference
        with self.assertRaisesRegex(ValueError, 'informe original cambio'):
            self.run_tool(apply=True)
        self.assertEqual(self.fx.calls, [])


if __name__ == '__main__':
    unittest.main()
