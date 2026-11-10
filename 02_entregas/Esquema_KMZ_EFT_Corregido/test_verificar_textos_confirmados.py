"""Lote completo sintetico: 1356 textos aprobados, 730 pendientes, 76 clases."""
from contextlib import nullcontext
import copy
import json
import os
import sys
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import verificar_textos_confirmados as tool


class ConfirmedTextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.model_path, self.config_path = self.root / 'esquema.json', self.root / 'textos.json'
        self.workspace = str(self.root / 'fixture.gdb')
        self.dataset = os.path.join(self.workspace, 'Datos_Proyecto')
        self.model = dict(version=11, referencia_espacial=4326, datasets=['Datos_Proyecto'],
                          tabla_proyecto='mline_tc_proyecto', clave_proyecto='co_proyecto',
                          dominios={}, relaciones=[], relaciones_negocio=[], clases=[])
        self.config = dict(version_paquete='1.7', version_modelo=11,
            modelo_origen_sha256='a' * 64, modelo_objetivo_sha256='', revision_sha256='b' * 64,
            campos_confirmados=1356, campos_pendientes_antes=2086,
            campos_pendientes_despues=730, clases_modelo=76, campos=[])
        for index in range(76):
            self.model['clases'].append(dict(nombre=f'clase_{index:02d}', dataset='Datos_Proyecto',
                geometria='POINT', rol='proyecto', relacion_proyecto=True,
                campos=[self.field_spec('proyecto', 12, 'EFT 5.8.7', False),
                        self.field_spec('id_analisis', 64, 'EFT 5.8.7', False)]))
        # Las seis ultimas clases no forman parte de este lote y no deben leerse.
        for index in range(1356):
            cls = self.model['clases'][index % 70]
            name = f'texto_{index:04d}'
            field = self.field_spec(name, 4000, tool.CONFIRMED_ORIGIN)
            field['tipo_confirmado'] = True
            cls['campos'].append(field)
            self.config['campos'].append(dict(clase=cls['nombre'], campo=name, tipo='TEXT',
                longitud=4000, longitud_maxima_utf16=120, valores_utiles=5,
                cobertura='COMPLETA_RUTAS_DEL_CAMPO', propuesta_historica='MANTENER_TEXT_CONTENIDO'))
        for index in range(730):
            self.model['clases'][index % 76]['campos'].append(self.field_spec(
                f'pendiente_{index:04d}', 4000, 'Atributo KMZ; texto conservador pendiente de revision de tipo'))
        self.write_inputs()
        self.paths = {cls['nombre']: os.path.join(self.dataset, cls['nombre'])
                      for cls in self.model['clases'][:70]}
        self.fields = {}
        self.descriptions = {
            self.workspace: SimpleNamespace(workspaceType='LocalDatabase'),
            self.dataset: SimpleNamespace(dataType='FeatureDataset', spatialReference=SimpleNamespace(factoryCode=4326))}
        for cls in self.model['clases'][:70]:
            path = self.paths[cls['nombre']]
            # Los campos ajenos al lote ni siquiera existen en el destino simulado.
            self.fields[path] = [SimpleNamespace(name=field['nombre'], baseName=field['nombre'],
                type='String', length=field['longitud'], isNullable=field['nullable'], domain='')
                for field in cls['campos'] if field.get('tipo_confirmado')]
            self.descriptions[path] = SimpleNamespace(dataType='FeatureClass', path=self.dataset,
                shapeType='Point', spatialReference=SimpleNamespace(factoryCode=4326),
                hasZ=True, hasM=False, hasGlobalID=True, editorTrackingEnabled=True, isTimeInUTC=True)
        self.a = SimpleNamespace(GetInstallInfo=lambda: {'Version': 'SIMULADA'},
            EnvManager=lambda **kwargs: nullcontext(),
            Exists=Mock(side_effect=lambda path: path in self.descriptions),
            Describe=Mock(side_effect=lambda path: self.descriptions[path]),
            ValidateTableName=lambda name, workspace: name,
            ValidateFieldName=lambda name, workspace: name,
            ListDatasets=lambda **kwargs: ['Datos_Proyecto'],
            ListFeatureClasses=lambda feature_dataset='': list(self.paths) if feature_dataset else [],
            ListTables=lambda: [], ListFields=Mock(side_effect=lambda path: self.fields[path]),
            da=SimpleNamespace(ListDomains=lambda workspace: [],
                SearchCursor=Mock(side_effect=AssertionError('No debe leer registros'))),
            management=Mock(), ArcSDESQLExecute=Mock(side_effect=AssertionError('No debe ejecutar SQL')))
        self.output_path = None

    @staticmethod
    def field_spec(name, length, origin, nullable=True):
        result = dict(nombre=name, tipo='TEXT', longitud=length, nullable=nullable,
                      dominio=None, origen=origin, alias=name)
        if origin.startswith('Atributo KMZ'):
            result['campo_fuente'] = name
        return result

    def write_inputs(self):
        self.model_path.write_text(json.dumps(self.model), encoding='utf-8')
        self.config['modelo_objetivo_sha256'] = tool.sha256(self.model_path.read_bytes())
        self.config_path.write_text(json.dumps(self.config), encoding='utf-8')

    def execute(self):
        def capture(message):
            if message.startswith('Resultado JSON: '):
                self.output_path = Path(message.removeprefix('Resultado JSON: '))
        return tool.run(self.workspace, reports=self.root, arcpy_module=self.a,
                        model_path=self.model_path, config_path=self.config_path, emit=capture)

    def report(self):
        self.assertIsNotNone(self.output_path)
        return json.loads(self.output_path.read_text(encoding='utf-8'))

    def first_field(self):
        return self.fields[self.paths['clase_00']][0]

    def reject_inputs(self, message):
        self.write_inputs()
        with self.assertRaisesRegex(ValueError, message):
            self.execute()
        self.a.Exists.assert_not_called()
        self.assertEqual(self.report()['estado'], 'ERROR_DETENIDO')
        self.assertEqual(self.report()['campos_verificados'], 0)

    def test_full_batch_reads_only_approved_fields_without_mutations_or_project_rows(self):
        before = copy.deepcopy(self.fields)
        original = (self.model_path.read_bytes(), self.config_path.read_bytes())
        folder, report = self.execute()
        self.assertEqual(report['estado'], 'TEXTOS_CONFIRMADOS_VERIFICADOS')
        self.assertEqual(report['campos_verificados'], 1356)
        self.assertEqual(report['campos_pendientes_modelo'], 730)
        self.assertEqual(len(report['clases_solicitadas']), 70)
        self.assertEqual(len(report['clases_verificadas']), 70)
        self.assertEqual(self.fields, before)
        self.assertEqual((self.model_path.read_bytes(), self.config_path.read_bytes()), original)
        self.assertEqual(report['cambios_en_geodatabase'], 0)
        self.assertFalse(report['carga_datos_verificada'])
        self.assertEqual(self.a.management.mock_calls, [])
        self.a.da.SearchCursor.assert_not_called()
        self.a.ArcSDESQLExecute.assert_not_called()
        self.assertTrue((folder / 'campos_verificados.csv').is_file())
        self.assertTrue((folder / 'diferencias.csv').is_file())
        self.assertEqual(len((folder / 'campos_verificados.csv').read_text(encoding='utf-8-sig').splitlines()), 1357)

    def test_reports_are_new_and_do_not_overwrite_previous_execution(self):
        first, _ = self.execute()
        original = (first / 'resultado.json').read_bytes()
        second, _ = self.execute()
        self.assertNotEqual(first, second)
        self.assertEqual((first / 'resultado.json').read_bytes(), original)

    def test_readonly_facade_denies_all_mutation_and_sql_entrypoints(self):
        readonly = tool.ReadOnlyArcPy(self.a)
        for name in ('management', 'ArcSDESQLExecute', 'conversion', 'edit', 'TestSchemaLock'):
            with self.assertRaises(AttributeError):
                getattr(readonly, name)
        with self.assertRaises(AttributeError):
            readonly.da.SearchCursor

    def test_hash_mismatch_rejects_before_database_access(self):
        self.model_path.write_bytes(self.model_path.read_bytes() + b' ')
        with self.assertRaisesRegex(ValueError, 'SHA256'):
            self.execute()
        self.a.Exists.assert_not_called()
        self.assertEqual(self.report()['estado'], 'ERROR_DETENIDO')

    def test_duplicate_and_unknown_keys_are_rejected(self):
        original = copy.deepcopy(self.config)
        self.config['campos'][1] = copy.deepcopy(self.config['campos'][0])
        self.reject_inputs('duplicado')
        self.config = original
        self.config['campos'][0]['campo'] = 'desconocido'
        self.reject_inputs('no pertenece')

    def test_small_subset_cannot_be_used_as_production_approval(self):
        self.config['campos'] = self.config['campos'][:3]
        self.config['campos_confirmados'] = 3
        self.reject_inputs('campos_confirmados=1356')

    def test_requires_exact_model_and_remaining_pending_totals(self):
        self.model['version'] = 10
        self.reject_inputs('modelo 11')
        self.model['version'] = 11
        self.model['clases'][0]['campos'][-1]['origen'] = 'Atributo KMZ aprobado'
        self.reject_inputs('730 campos pendientes')

    def test_requires_explicit_confirmation_and_source_attribute(self):
        field = self.model['clases'][0]['campos'][2]
        field['tipo_confirmado'] = False
        self.reject_inputs('confirmacion explicita')
        field['tipo_confirmado'] = True
        field['campo_fuente'] = ''
        self.reject_inputs('campo sin fundamento EFT')

    def test_rejects_empty_partial_or_oversized_profile_evidence(self):
        original = copy.deepcopy(self.config)
        for prop, value in [('valores_utiles', 0), ('longitud_maxima_utf16', 4001),
                            ('cobertura', 'PARCIAL'), ('propuesta_historica', 'NUMERICO')]:
            self.config = copy.deepcopy(original)
            self.config['campos'][0][prop] = value
            self.reject_inputs('evidencia|cobertura')

    def test_collects_multiple_field_differences_in_one_readonly_pass(self):
        field = self.first_field()
        field.type, field.length, field.isNullable, field.domain = 'Integer', 4, False, 'no_aprobado'
        with self.assertRaisesRegex(ValueError, 'Validacion incompleta'):
            self.execute()
        report = self.report()
        self.assertEqual(report['campos_verificados'], 1355)
        self.assertEqual(len(report['discrepancias']), 4)
        self.assertEqual(len(report['campos']), 1356)
        self.assertNotIn('clase_00', report['clases_verificadas'])
        self.assertEqual(report['estado'], 'ERROR_DETENIDO')

    def test_accepts_larger_text_and_qualified_field_name_without_changing_it(self):
        field = self.first_field()
        field.length = 5000
        field.name = 'GIS.clase_00.' + field.baseName
        _, report = self.execute()
        self.assertEqual(report['estado'], 'TEXTOS_CONFIRMADOS_VERIFICADOS')
        item = next(row for row in report['campos'] if row['campo'] == field.baseName)
        self.assertEqual(item['longitud_actual'], 5000)

    def test_detects_capitalized_field_base_name(self):
        self.first_field().baseName = self.first_field().baseName.upper()
        with self.assertRaisesRegex(ValueError, 'Validacion incompleta'):
            self.execute()
        self.assertEqual(self.report()['discrepancias'][0]['propiedad'], 'nombre_actual')

    def test_missing_field_or_class_never_counts_as_verified(self):
        self.fields[self.paths['clase_00']].pop(0)
        del self.paths['clase_01']
        with self.assertRaisesRegex(ValueError, 'Validacion incompleta'):
            self.execute()
        report = self.report()
        self.assertEqual(len(report['campos']), 1356)
        self.assertTrue(any(row['clase'] == 'clase_00' and row['propiedad'] == 'campo' for row in report['discrepancias']))
        self.assertTrue(any(row['clase'] == 'clase_01' and row['propiedad'] == 'clase' for row in report['discrepancias']))
        self.assertLess(report['campos_verificados'], 1355)

    def test_read_error_and_geometry_errors_record_incomplete_classes(self):
        self.descriptions[self.paths['clase_00']].hasZ = False
        normal = self.a.ListFields.side_effect
        def fields(path):
            if path == self.paths['clase_01']:
                raise RuntimeError('Lectura interrumpida')
            return normal(path)
        self.a.ListFields.side_effect = fields
        with self.assertRaisesRegex(ValueError, 'Validacion incompleta'):
            self.execute()
        self.assertEqual(len(self.report()['discrepancias']), 2)
        self.assertEqual(len(self.report()['campos']), 1356)

    def test_inputs_changed_during_read_reject_success(self):
        normal = self.a.ListFields.side_effect
        changed = False
        def fields(path):
            nonlocal changed
            if not changed:
                self.config_path.write_bytes(self.config_path.read_bytes() + b' ')
                changed = True
            return normal(path)
        self.a.ListFields.side_effect = fields
        with self.assertRaisesRegex(ValueError, 'cambio durante la lectura'):
            self.execute()
        self.assertEqual(self.report()['estado'], 'ERROR_DETENIDO')
        self.assertEqual(self.report()['campos_verificados'], 1356)

    def test_wrong_database_rejects_before_class_reads(self):
        self.workspace = str(self.root / 'fixture.sde')
        self.descriptions[self.workspace] = SimpleNamespace(workspaceType='RemoteDatabase',
            connectionProperties=SimpleNamespace(database='otra', user='gis'))
        with self.assertRaisesRegex(ValueError, 'otra base de datos'):
            self.execute()
        self.a.ListFields.assert_not_called()
        self.assertEqual(self.report()['estado'], 'ERROR_DETENIDO')

    def close_fixture(self):
        original=self.model_path.read_bytes()
        base=json.loads(original)
        self.model=copy.deepcopy(base)
        self.model['version']=12
        for cls in self.model['clases']:
            for field in cls['campos']:
                if tool.runner.provisional(field):
                    field['origen']='Atributo KMZ; almacenamiento TEXT confirmado por decision 1.9'
                    field['tipo_confirmado']=True
        self.model_path.write_text(json.dumps(self.model),encoding='utf-8')
        (self.root/'esquema_anterior_1_8.json').write_bytes(original)
        (self.root/'cierre_tipos_1_9.json').write_text('{}',encoding='utf-8')
        (self.root/'referencia_cierre_tipos.py').write_text('# fixture de cierre',encoding='utf-8')
        return base,copy.deepcopy(self.model)

    def test_model12_keeps_historical_approval_and_verifies_only_same_1356(self):
        base,target=self.close_fixture()
        old_config=self.config_path.read_bytes()
        fields_before=copy.deepcopy(self.fields)
        with patch.dict(sys.modules,{'referencia_cierre_tipos':SimpleNamespace(
                read_reference=lambda folder:(base,target,{}))}):
            _,report=self.execute()
        self.assertEqual((report['version_paquete'],report['version_modelo'],report['lote_verificado']),('1.9',12,'1.7'))
        self.assertEqual(report['estado'],'TEXTOS_CONFIRMADOS_VERIFICADOS')
        self.assertEqual(report['campos_pendientes_modelo'],0)
        self.assertEqual(report['campos_verificados'],1356)
        self.assertEqual(len(report['clases_solicitadas']),70)
        self.assertEqual(report['modelo_historico_sha256'],self.config['modelo_objetivo_sha256'])
        self.assertNotEqual(report['modelo_sha256'],report['modelo_historico_sha256'])
        self.assertEqual(self.config_path.read_bytes(),old_config)
        self.assertEqual(self.fields,fields_before)
        self.assertEqual(self.a.management.mock_calls,[])

    def test_model12_rejects_invalid_lineage_before_sde_and_records_current_version(self):
        self.close_fixture()
        def invalid(_):raise ValueError('Cierre invalido')
        with patch.dict(sys.modules,{'referencia_cierre_tipos':SimpleNamespace(read_reference=invalid)}):
            with self.assertRaisesRegex(ValueError,'Cierre invalido'):
                self.execute()
        self.a.Exists.assert_not_called()
        self.assertEqual((self.report()['version_paquete'],self.report()['version_modelo']),('1.9',12))
        self.assertEqual(self.report()['estado'],'ERROR_DETENIDO')

    def test_model12_does_not_accept_rewriting_old_approval_hash_to_new_model(self):
        base,target=self.close_fixture()
        self.config['modelo_objetivo_sha256']=tool.sha256(self.model_path.read_bytes())
        self.config_path.write_text(json.dumps(self.config),encoding='utf-8')
        with patch.dict(sys.modules,{'referencia_cierre_tipos':SimpleNamespace(
                read_reference=lambda folder:(base,target,{}))}):
            with self.assertRaisesRegex(ValueError,'SHA256'):
                self.execute()
        self.a.Exists.assert_not_called()

    def test_model12_closure_reference_mutation_during_read_rejects_success(self):
        base,target=self.close_fixture()
        normal=self.a.ListFields.side_effect
        changed=False
        def fields(path):
            nonlocal changed
            if not changed:
                (self.root/'cierre_tipos_1_9.json').write_text('{"cambio":true}',encoding='utf-8')
                changed=True
            return normal(path)
        self.a.ListFields.side_effect=fields
        with patch.dict(sys.modules,{'referencia_cierre_tipos':SimpleNamespace(
                read_reference=lambda folder:(base,target,{}))}):
            with self.assertRaisesRegex(ValueError,'referencia de cierre cambio'):
                self.execute()
        self.assertEqual(self.report()['estado'],'ERROR_DETENIDO')
        self.assertEqual(self.report()['campos_verificados'],1356)


if __name__ == '__main__':
    unittest.main()
