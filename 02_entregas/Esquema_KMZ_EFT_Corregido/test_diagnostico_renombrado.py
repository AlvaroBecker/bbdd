"""Diagnostico independiente: diferencias exactas y ninguna mutacion ArcPy."""
import copy
import hashlib
import json
import os
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import diagnostico_renombrado as tool
import test_renombrar_clases as fixture_module


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        fixture = fixture_module.RenameTests(methodName='runTest')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fx, self.f = fixture, fixture.f
        self.root, self.a = self.f.root, self.f.a
        self.old, self.new = fixture.old, fixture.new
        self.path = self.f.paths[self.old]
        self.other = next(name for name in self.f.paths if name != self.old)
        self.here = patch.object(tool, 'HERE', self.root)
        self.here.start()
        self.addCleanup(self.here.stop)
        payloads = {'esquema.json': fixture.source,
                    'nombres_clases_1_6.json': fixture.mapping,
                    'campos_aprobados_1_5.json': fixture.config}
        for filename, payload in payloads.items():
            (self.root / filename).write_text(json.dumps(payload), encoding='utf-8')
        baseline = {}
        for row in fixture.mapping['clases']:
            path = self.f.paths[row['nombre_anterior']]
            baseline[row['nombre_nuevo']] = dict(campos=tool.renamer.snapshot(self.a, path),
                indices=tool.index_snapshot(self.a, path), geometria=tool.renamer.geometry_snapshot(self.a, path))
        self.original = dict(version_paquete='1.6', modo='APLICAR_NOMBRES',
            estado='ERROR_DETENIDO', workspace=self.f.workspace, database='ArcGisAWS', owner='gis',
            clase_en_curso=self.new, operacion_en_curso='RENOMBRAR_CLASE',
            campos_y_metadatos_antes=baseline, plan=[])
        for filename, key in tool.INPUTS:
            self.original[key] = tool.sha256((self.root / filename).read_bytes())
        self.reference = self.root / 'referencia_original.json'
        self.write_reference()
        self.env = self.a.EnvManager
        self.a.EnvManager = Mock(side_effect=self.env)
        # Solo esta API de management esta disponible: cualquier otra falla.
        self.a.management = SimpleNamespace(GetCount=self.a.management.GetCount)
        self.a.AlterAliasName = Mock(side_effect=AssertionError('El diagnostico no cambia alias'))
        self.a.ListFields.reset_mock()
        self.a.ListIndexes.reset_mock()

    def write_reference(self):
        self.reference.write_text(json.dumps(self.original), encoding='utf-8')
        self.original_bytes = self.reference.read_bytes()

    def run_tool(self, **kwargs):
        return tool.run(self.f.workspace, self.reference, reports=self.root,
                        arcpy_module=self.a, emit=lambda text: None, **kwargs)

    def test_same_metadata_reads_all_baselines_without_writes(self):
        before = copy.deepcopy(self.f.fields)
        folder, report = self.run_tool()
        self.assertEqual(report['estado'], 'SIN_DIFERENCIAS_ACTUALES')
        self.assertEqual(set(report['clases']), {self.new, self.other})
        self.assertEqual(report['diferencias'], [])
        self.assertEqual(report['incidencias'], [])
        self.assertEqual(report['cambios_en_geodatabase'], 0)
        self.assertFalse(report['reanudacion_automatica_autorizada'])
        self.assertEqual(before, self.f.fields)
        self.assertEqual(self.reference.read_bytes(), self.original_bytes)
        self.assertEqual(report['informe_original_sha256'], hashlib.sha256(self.original_bytes).hexdigest())
        self.assertTrue((folder / 'resultado.json').is_file())
        self.assertTrue((folder / 'diferencias.csv').is_file())
        self.a.EnvManager.assert_any_call(overwriteOutput=False, extent=None)
        self.a.AlterAliasName.assert_not_called()

    def test_changed_field_alias_is_not_waived(self):
        field = self.f.field(self.old, 'medida')
        old = field.aliasName
        field.aliasName = 'GIS.zonas_vida_holdridge_recorte.medida'
        _, report = self.run_tool()
        self.assertEqual(report['estado'], 'DIFERENCIAS_DETECTADAS')
        self.assertEqual(len(report['diferencias']), 1)
        difference = report['diferencias'][0]
        self.assertEqual((difference['clase'], difference['elemento'], difference['propiedad']),
                         (self.new, 'medida', 'alias'))
        self.assertEqual((difference['antes'], difference['despues']), (old, field.aliasName))

    def test_type_and_length_changes_remain_separate_differences(self):
        field = self.f.field(self.old, 'medida')
        field.type, field.length = 'Double', 8
        _, report = self.run_tool()
        self.assertEqual({row['propiedad'] for row in report['diferencias']}, {'tipo', 'longitud'})
        self.assertTrue(all(row['tipo_cambio'] == 'MODIFICADO' for row in report['diferencias']))

    def test_added_and_removed_fields_and_property_keys_are_distinct(self):
        self.f.fields[self.path] = [field for field in self.f.fields[self.path] if field.baseName != 'medida']
        self.f.fields[self.path].append(self.f.make_field('nuevo', 'String', 40, True))
        self.original['campos_y_metadatos_antes'][self.new]['campos']['proyecto']['prop_extra'] = None
        self.write_reference()
        _, report = self.run_tool()
        changes = {(row['elemento'], row['propiedad'], row['tipo_cambio']) for row in report['diferencias']}
        self.assertIn(('medida', 'medida', 'ELIMINADO'), changes)
        self.assertIn(('nuevo', 'nuevo', 'AGREGADO'), changes)
        self.assertIn(('proyecto', 'prop_extra', 'ELIMINADO'), changes)

    def test_case_in_field_value_is_reported_even_if_key_is_casefolded(self):
        self.f.field(self.old, 'medida').baseName = 'MEDIDA'
        _, report = self.run_tool()
        self.assertEqual(len(report['diferencias']), 1)
        self.assertEqual(report['diferencias'][0]['propiedad'], 'nombre')

    def test_expected_table_name_and_class_alias_changes_are_progress_only(self):
        destination = os.path.join(self.f.ds, 'GIS.' + self.new)
        self.fx.rename(self.path, destination, 'FeatureClass')
        self.f.descriptions[destination].aliasName = 'Nuevo alias descriptivo'
        _, report = self.run_tool()
        self.assertEqual(report['estado'], 'SIN_DIFERENCIAS_ACTUALES')
        self.assertTrue(report['clases'][self.new]['nombre_objetivo_presente'])
        self.assertEqual(report['clases'][self.new]['alias_actual'], 'Nuevo alias descriptivo')

    def test_indexes_geometry_and_count_are_reported_without_guard_short_circuit(self):
        self.f.indices[self.path].append(SimpleNamespace(name='ix_nuevo',
            fields=[self.f.field(self.old, 'medida')], isUnique=True, isAscending=False))
        self.f.descriptions[self.path].hasZ = False
        self.f.records[self.path] = 9
        _, report = self.run_tool()
        self.assertEqual(report['estado'], 'DIFERENCIAS_DETECTADAS')
        self.assertEqual({row['seccion'] for row in report['diferencias']}, {'indices', 'geometria', 'recuento'})
        self.assertTrue(any(row['propiedad'] == 'hasZ' for row in report['diferencias']))
        self.assertEqual(report['clases'][self.new]['recuento_actual'], 9)

    def test_unreadable_fields_still_reads_other_sections_and_classes(self):
        def fields(path):
            if path == self.path:
                raise RuntimeError('Metadatos no disponibles')
            return list(self.f.fields[path])
        self.a.ListFields.side_effect = fields
        self.f.descriptions[self.path].hasM = True
        _, report = self.run_tool()
        self.assertEqual(report['estado'], 'DIAGNOSTICO_INCOMPLETO')
        self.assertIn('campos', {item['seccion'] for item in report['incidencias']})
        self.assertIn('campos', report['clases'][self.other]['despues'])
        self.assertIn('indices', report['clases'][self.new]['despues'])
        self.assertTrue(any(row['propiedad'] == 'hasM' for row in report['diferencias']))

    def test_both_names_report_incidence_and_do_not_choose_either(self):
        destination = os.path.join(self.f.ds, 'GIS.' + self.new)
        self.f.paths[self.new] = destination
        self.f.descriptions[destination] = copy.deepcopy(self.f.descriptions[self.path])
        _, report = self.run_tool()
        self.assertEqual(report['estado'], 'DIAGNOSTICO_INCOMPLETO')
        self.assertEqual(report['clases'][self.new]['despues'], {})
        self.assertTrue(any(item['seccion'] == 'resolucion' for item in report['incidencias']))
        self.assertIn('campos', report['clases'][self.other]['despues'])

    def test_missing_class_reports_incomplete_without_creating_it(self):
        self.f.paths.pop(self.old)
        _, report = self.run_tool()
        self.assertEqual(report['estado'], 'DIAGNOSTICO_INCOMPLETO')
        self.assertTrue(any(item['clase'] == self.new for item in report['incidencias']))

    def test_each_approval_hash_is_checked_before_arcpy(self):
        for _, key in tool.INPUTS:
            with self.subTest(key=key):
                original = self.original[key]
                self.original[key] = '0' * 64
                self.write_reference()
                with self.assertRaisesRegex(ValueError, 'no coincide'):
                    self.run_tool()
                self.original[key] = original
        self.a.ListFields.assert_not_called()
        self.a.management.GetCount.assert_not_called()

    def test_wrong_workspace_and_wrong_reference_mode_are_rejected(self):
        self.original['workspace'] = str(self.root / 'otro.sde')
        self.write_reference()
        with self.assertRaisesRegex(ValueError, 'workspace'):
            self.run_tool()
        self.original['workspace'] = self.f.workspace
        self.original['modo'] = 'VALIDAR_NOMBRES'
        self.write_reference()
        with self.assertRaisesRegex(ValueError, 'Aplicar nombres aprobados'):
            self.run_tool()
        self.a.ListFields.assert_not_called()

    def test_selecting_no_baseline_is_rejected_and_explicit_subset_is_supported(self):
        with self.assertRaisesRegex(ValueError, 'seleccion'):
            self.run_tool(names=['desconocida'])
        _, report = self.run_tool(names=[self.new])
        self.assertEqual(set(report['clases']), {self.new})

    def test_raw_field_evidence_includes_qualified_names_and_default_python_type(self):
        self.f.field(self.old, 'medida').name = 'GIS.' + self.old + '.medida'
        _, report = self.run_tool()
        raw = next(item for item in report['clases'][self.new]['campos_crudos_actuales'] if item['baseName'] == 'medida')
        self.assertEqual(raw['name'], 'GIS.' + self.old + '.medida')
        self.assertEqual(raw['defaultValue_repr'], 'None')
        self.assertEqual(raw['defaultValue_tipo_python'], 'NoneType')
        self.assertEqual(report['diferencias'], [])

    def test_source_change_during_read_is_detected_and_does_not_replace_reference(self):
        original = self.a.GetInstallInfo
        def installation():
            self.reference.write_bytes(self.original_bytes + b'\n')
            return original()
        self.a.GetInstallInfo = installation
        _, report = self.run_tool()
        self.assertEqual(report['estado'], 'DIAGNOSTICO_INCOMPLETO')
        self.assertTrue(any(item['seccion'] == 'informe_original' for item in report['incidencias']))
        self.assertEqual(self.reference.read_bytes(), self.original_bytes + b'\n')


if __name__ == '__main__':
    unittest.main()
