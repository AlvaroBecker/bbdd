"""Pruebas con ArcPy simulado: ninguna conexion ni geodatabase real se abre."""
import copy
from contextlib import nullcontext
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import actualizar_campos_aprobados as tool


class Cursor:
    def __enter__(self):
        return iter([('000000000001',)])

    def __exit__(self, *args):
        return False


class ApprovedFieldsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = str(self.root / 'fixture.gdb')
        self.ds = os.path.join(self.workspace, 'GIS.Datos_Proyecto')
        self.paths = {name: os.path.join(self.ds, 'GIS.' + name) for name in ('predios_inscritos_en_sunarp_recorte', 'zonas_de_vida_holdridge_recorte')}
        self.parent = os.path.join(self.workspace, 'GIS.mline_tc_proyecto')
        self.connection = SimpleNamespace(database='ArcGisAWS', user='gis')
        self.source = dict(referencia_espacial=4326, datasets=['Datos_Proyecto'],
            tabla_proyecto='mline_tc_proyecto', clave_proyecto='co_proyecto',
            dominios={}, relaciones=[], relaciones_negocio=[], clases=[])
        for name, own in [('predios_inscritos_en_sunarp_recorte', [('conteo', 'LONG', None), ('numerico', 'DOUBLE', None),
                                    ('cargas_y_gravamenes', 'TEXT', 10000), ('comentario', 'TEXT', 4000)]),
                          ('zonas_de_vida_holdridge_recorte', [('medida', 'DOUBLE', None)])]:
            fields = [self.spec('proyecto', 'TEXT', 12, False, 'EFT 5.8.7'),
                      self.spec('id_analisis', 'TEXT', 64, False, 'EFT 5.8.7')]
            fields += [self.spec(field, kind, length, True, 'Atributo KMZ aprobado')
                       for field, kind, length in own]
            self.source['clases'].append(dict(nombre=name, dataset='Datos_Proyecto',
                geometria='POINT', rol='proyecto', relacion_proyecto=True, campos=fields))
        self.config = dict(version_paquete='1.5', cambios=[
            dict(clase=cls, campo=field, tipo_anterior='TEXT', longitud_anterior=4000,
                 tipo_objetivo=kind, longitud_objetivo=length)
            for cls, field, kind, length in [('predios_inscritos_en_sunarp_recorte', 'conteo', 'LONG', None),
                ('predios_inscritos_en_sunarp_recorte', 'numerico', 'DOUBLE', None), ('predios_inscritos_en_sunarp_recorte', 'cargas_y_gravamenes', 'TEXT', 10000),
                ('zonas_de_vida_holdridge_recorte', 'medida', 'DOUBLE', None)]])
        self.model_path = self.root / 'modelo.json'
        self.config_path = self.root / 'aprobados.json'
        self.write_inputs()
        self.fields, self.records, self.indices, self.locks, self.descriptions = {}, {}, {}, {}, {}
        changes = {(c['clase'], c['campo']) for c in self.config['cambios']}
        for cls in self.source['clases']:
            name = cls['nombre']
            path = self.paths[name]
            self.fields[path] = [self.make_field(spec['nombre'],
                'String' if (name, spec['nombre']) in changes else tool.runner.engine.TYPE[spec['tipo']],
                4000 if (name, spec['nombre']) in changes else (spec['longitud'] or 0),
                spec['nullable'], alias=spec['alias']) for spec in cls['campos']]
            for native, kind in [('OBJECTID', 'OID'), ('Shape', 'Geometry'),
                ('GlobalID', 'GlobalID'), ('created_user', 'String'), ('created_date', 'Date'),
                ('last_edited_user', 'String'), ('last_edited_date', 'Date')]:
                self.fields[path].append(self.make_field(native, kind,
                    255 if kind == 'String' else 0, True, required=True))
            self.records[path] = 0
            self.indices[path] = []
            self.descriptions[path] = SimpleNamespace(dataType='FeatureClass', path=self.ds,
                shapeType='Point', spatialReference=SimpleNamespace(factoryCode=4326),
                hasZ=True, hasM=False, hasGlobalID=True, editorTrackingEnabled=True,
                isTimeInUTC=True, isVersioned=False, creatorFieldName='created_user',
                createdAtFieldName='created_date', editorFieldName='last_edited_user',
                editedAtFieldName='last_edited_date')
        self.fields[self.parent] = [self.make_field('co_proyecto', 'String', 12, False)]
        self.descriptions[self.workspace] = SimpleNamespace(workspaceType='LocalDatabase',
                                                            connectionProperties=self.connection)
        self.descriptions[self.ds] = SimpleNamespace(dataType='FeatureDataset',
            spatialReference=SimpleNamespace(factoryCode=4326), isVersioned=False)
        self.descriptions[self.parent] = SimpleNamespace(hasOID=True)
        self.sql_type = 'nvarchar'
        self.sql_length_override = None
        self.a = SimpleNamespace(GetInstallInfo=lambda: {'Version': 'SIMULADA'},
            EnvManager=lambda **kwargs: nullcontext(), Exists=lambda path: path in self.descriptions,
            Describe=lambda path: self.descriptions[path],
            ValidateTableName=lambda name, workspace: name,
            ValidateFieldName=lambda name, workspace: name,
            ListDatasets=lambda **kwargs: ['GIS.Datos_Proyecto'],
            ListFeatureClasses=lambda feature_dataset='':
                ['GIS.' + name for name in self.paths] if feature_dataset else [],
            ListTables=lambda: ['GIS.mline_tc_proyecto'],
            ListFields=Mock(side_effect=lambda path: list(self.fields[path])),
            ListIndexes=Mock(side_effect=lambda path: list(self.indices[path])),
            TestSchemaLock=Mock(side_effect=lambda path: self.locks.get(path, True)),
            ArcSDESQLExecute=Mock(return_value=SimpleNamespace(execute=Mock(side_effect=self.sql_result))),
            da=SimpleNamespace(ListDomains=lambda workspace: [], SearchCursor=lambda *args: Cursor()),
            management=SimpleNamespace(
                GetCount=Mock(side_effect=lambda path:
                    SimpleNamespace(getOutput=lambda n: str(self.records[path]))),
                AlterField=Mock(side_effect=self.alter)))

    @staticmethod
    def spec(name, kind, length, nullable, origin):
        result = dict(nombre=name, tipo=kind, longitud=length, nullable=nullable,
                      dominio=None, alias='Alias ' + name, origen=origin)
        if origin.startswith('Atributo KMZ'):
            result['campo_fuente'] = name
        return result

    @staticmethod
    def make_field(name, kind, length, nullable, alias=None, required=False):
        return SimpleNamespace(name=name, baseName=name, type=kind, length=length,
            aliasName=alias or name, isNullable=nullable, domain='', defaultValue=None,
            required=required, precision=0, scale=0)

    def write_inputs(self):
        self.model_path.write_text(json.dumps(self.source), encoding='utf-8')
        self.config_path.write_text(json.dumps(self.config), encoding='utf-8')

    def field(self, cls, name):
        return next(field for field in self.fields[self.paths[cls]] if field.baseName == name)

    def alter(self, path, name, *, field_type, field_length=None):
        field = next(f for f in self.fields[path] if f.baseName == name)
        field.type = tool.runner.engine.TYPE[field_type]
        field.length = field_length if field_type == 'TEXT' else 8 if field_type == 'DOUBLE' else 4

    def sql_result(self, query):
        length = -1 if self.field('predios_inscritos_en_sunarp_recorte', 'cargas_y_gravamenes').length >= 10000 else 8000
        if self.sql_length_override is not None:
            length = self.sql_length_override
        return [[self.sql_type, length]]

    def run_tool(self, apply=False, names=None):
        self.last_report_path = None
        def capture(message):
            if message.startswith('Resultado JSON: '):
                self.last_report_path = Path(message.removeprefix('Resultado JSON: '))
        return tool.run(self.workspace, apply=apply, reports=self.root, arcpy_module=self.a,
            emit=capture, model_path=self.model_path, config_path=self.config_path, names=names)

    def use_sde(self):
        old = self.workspace
        self.workspace = str(self.root / 'fixture.sde')
        replace = lambda p: p.replace(old, self.workspace)
        self.ds, self.parent = replace(self.ds), replace(self.parent)
        self.paths = {name: replace(path) for name, path in self.paths.items()}
        for attribute in ('fields','records','indices','locks','descriptions'):
            values=getattr(self,attribute)
            setattr(self,attribute,{replace(path):value for path,value in values.items()})
        for description in self.descriptions.values():
            if hasattr(description,'path'):
                description.path=replace(description.path)
        self.descriptions[self.workspace].workspaceType='RemoteDatabase'

    def latest_report(self):
        path = getattr(self, 'last_report_path', None)
        self.assertIsNotNone(path, 'La ejecucion no emitio su Resultado JSON final.')
        self.assertTrue(path.is_relative_to(self.root))
        return json.loads(path.read_text(encoding='utf-8'))

    def complete_all(self):
        for change in self.config['cambios']:
            self.alter(self.paths[change['clase']], change['campo'],
                       field_type=change['tipo_objetivo'], field_length=change['longitud_objetivo'])

    def test_validation_reads_real_preflight_helpers_without_writes_or_input_mutation(self):
        before = {name: tool.snapshot(self.a, path) for name, path in self.paths.items()}
        model_bytes, config_bytes = self.model_path.read_bytes(), self.config_path.read_bytes()
        folder, report = self.run_tool()
        self.assertEqual(report['estado'], 'VALIDACION_OK_SIN_CAMBIOS')
        self.assertEqual(len(report['plan']), 4)
        self.assertEqual(report['completadas'], [])
        self.assertTrue((folder / 'plan.csv').is_file())
        self.assertEqual(self.model_path.read_bytes(), model_bytes)
        self.assertEqual(self.config_path.read_bytes(), config_bytes)
        self.assertEqual({name: tool.snapshot(self.a, path) for name, path in self.paths.items()}, before)
        self.a.management.AlterField.assert_not_called()

    def test_nonempty_last_class_blocks_whole_batch_before_first_write(self):
        self.records[self.paths['zonas_de_vida_holdridge_recorte']] = 1
        with self.assertRaisesRegex(ValueError, 'zonas_de_vida_holdridge_recorte contiene 1 registros'):
            self.run_tool(apply=True)
        self.a.management.AlterField.assert_not_called()
        self.assertEqual(self.latest_report()['clase_en_curso'], 'zonas_de_vida_holdridge_recorte')

    def test_apply_changes_double_long_and_text_length_preserving_other_properties(self):
        before = {name: tool.snapshot(self.a, path) for name, path in self.paths.items()}
        with patch.object(tool.runner, 'preflight', wraps=tool.runner.preflight) as preflight:
            _, report = self.run_tool(apply=True)
        self.assertEqual(report['estado'], 'CAMPOS_VERIFICADOS')
        self.assertEqual(report['completadas'], ['predios_inscritos_en_sunarp_recorte.cargas_y_gravamenes', 'predios_inscritos_en_sunarp_recorte.conteo', 'predios_inscritos_en_sunarp_recorte.numerico', 'zonas_de_vida_holdridge_recorte.medida'])
        self.assertEqual(self.a.management.AlterField.call_count, 4)
        self.assertEqual(preflight.call_count, 6)  # Lote inicial/final y una vez antes/despues por clase.
        self.assertEqual(self.field('predios_inscritos_en_sunarp_recorte', 'conteo').type, 'Integer')
        self.assertEqual(self.field('predios_inscritos_en_sunarp_recorte', 'numerico').type, 'Double')
        self.assertEqual(self.field('predios_inscritos_en_sunarp_recorte', 'cargas_y_gravamenes').length, 10000)
        text_call = next(call for call in self.a.management.AlterField.call_args_list if call.args[1] == 'cargas_y_gravamenes')
        self.assertEqual(text_call.kwargs, {'field_type': 'TEXT', 'field_length': 10000})
        for name, path in self.paths.items():
            allowed = [c['campo'] for c in self.config['cambios'] if c['clase'] == name]
            tool.require_preserved(before[name], tool.snapshot(self.a, path), allowed)

    def test_partial_resume_skips_numeric_and_longer_text_targets(self):
        self.alter(self.paths['predios_inscritos_en_sunarp_recorte'], 'numerico', field_type='DOUBLE')
        self.alter(self.paths['predios_inscritos_en_sunarp_recorte'], 'cargas_y_gravamenes', field_type='TEXT', field_length=12000)
        _, report = self.run_tool(apply=True)
        self.assertEqual(report['estado'], 'CAMPOS_VERIFICADOS')
        self.assertEqual(report['completadas'], ['predios_inscritos_en_sunarp_recorte.conteo', 'zonas_de_vida_holdridge_recorte.medida'])
        self.assertEqual(self.field('predios_inscritos_en_sunarp_recorte', 'cargas_y_gravamenes').length, 12000)

    def test_failure_records_class_field_observed_state_and_resumes(self):
        def fail_second(path, name, **kwargs):
            if name == 'conteo':
                raise RuntimeError('Fallo GP simulado')
            self.alter(path, name, **kwargs)
        self.a.management.AlterField.side_effect = fail_second
        with self.assertRaisesRegex(RuntimeError, 'Fallo GP simulado'):
            self.run_tool(apply=True)
        failed = self.latest_report()
        self.assertEqual(failed['completadas'], ['predios_inscritos_en_sunarp_recorte.cargas_y_gravamenes'])
        self.assertEqual(failed['clase_en_curso'], 'predios_inscritos_en_sunarp_recorte')
        self.assertEqual(failed['campo_en_curso'], 'conteo')
        self.assertEqual(failed['campos_observados_al_detener']['predios_inscritos_en_sunarp_recorte']['cargas_y_gravamenes']['longitud'], 10000)
        self.assertEqual(len(failed['plan']), 4)
        self.a.management.AlterField.reset_mock(side_effect=True)
        self.a.management.AlterField.side_effect = self.alter
        _, resumed = self.run_tool(apply=True)
        self.assertEqual(resumed['estado'], 'CAMPOS_VERIFICADOS')
        self.assertNotIn('cargas_y_gravamenes', [call.args[1] for call in self.a.management.AlterField.call_args_list])

    def test_gp_error_after_real_change_is_reported_and_not_repeated_on_resume(self):
        def change_then_raise(path, name, **kwargs):
            self.alter(path, name, **kwargs)
            raise RuntimeError('Error posterior al cambio')
        self.a.management.AlterField.side_effect = change_then_raise
        with self.assertRaisesRegex(RuntimeError, 'Error posterior'):
            self.run_tool(apply=True)
        failed = self.latest_report()
        self.assertEqual(failed['completadas'], [])
        self.assertEqual(failed['campo_en_curso'], 'cargas_y_gravamenes')
        self.assertEqual(failed['campos_observados_al_detener']['predios_inscritos_en_sunarp_recorte']['cargas_y_gravamenes']['longitud'], 10000)
        self.a.management.AlterField.reset_mock(side_effect=True)
        self.a.management.AlterField.side_effect = self.alter
        self.run_tool(apply=True)
        self.assertNotIn('cargas_y_gravamenes', [call.args[1] for call in self.a.management.AlterField.call_args_list])

    def test_intermediate_text_lengths_and_wrong_types_block_before_writes(self):
        cases = [('predios_inscritos_en_sunarp_recorte', 'cargas_y_gravamenes', 'String', 6000), ('predios_inscritos_en_sunarp_recorte', 'cargas_y_gravamenes', 'Double', 8),
                 ('zonas_de_vida_holdridge_recorte', 'medida', 'Integer', 4), ('predios_inscritos_en_sunarp_recorte', 'conteo', 'Double', 8),
                 ('predios_inscritos_en_sunarp_recorte', 'numerico', 'String', 3000)]
        for cls, name, kind, length in cases:
            with self.subTest(cls=cls, name=name, kind=kind, length=length):
                field = self.field(cls, name)
                old = field.type, field.length
                field.type, field.length = kind, length
                try:
                    with self.assertRaises(ValueError):
                        self.run_tool(apply=True)
                finally:
                    field.type, field.length = old
        self.a.management.AlterField.assert_not_called()

    def test_required_domain_nullability_and_default_guard_all_candidates(self):
        field = self.field('zonas_de_vida_holdridge_recorte', 'medida')
        for prop, value in [('required', True), ('domain', 'dom_externo'),
                            ('isNullable', False), ('defaultValue', 0)]:
            with self.subTest(prop=prop):
                old = getattr(field, prop)
                setattr(field, prop, value)
                try:
                    with self.assertRaises(ValueError):
                        self.run_tool(apply=True)
                finally:
                    setattr(field, prop, old)
        self.a.management.AlterField.assert_not_called()

    def test_candidate_index_in_last_class_blocks_before_any_change(self):
        self.indices[self.paths['zonas_de_vida_holdridge_recorte']] = [SimpleNamespace(name='ix_medida',
                                                           fields=[self.field('zonas_de_vida_holdridge_recorte', 'medida')])]
        with self.assertRaisesRegex(ValueError, 'Indice ix_medida'):
            self.run_tool(apply=True)
        self.a.management.AlterField.assert_not_called()

    def test_unrelated_index_change_after_alter_is_not_silently_accepted(self):
        def alter_index(path, name, **kwargs):
            self.alter(path, name, **kwargs)
            self.indices[path].append(SimpleNamespace(name='ix_comentario',
                                                     fields=[self.field('predios_inscritos_en_sunarp_recorte', 'comentario')]))
        self.a.management.AlterField.side_effect = alter_index
        with self.assertRaisesRegex(ValueError, 'cambio inesperado de indices'):
            self.run_tool(apply=True)
        self.assertEqual(self.latest_report()['completadas'], [])
        self.assertEqual(self.a.management.AlterField.call_count, 1)

    def test_foreign_alias_change_after_alter_stops_without_marking_complete(self):
        def alter_alias(path, name, **kwargs):
            self.alter(path, name, **kwargs)
            self.field('predios_inscritos_en_sunarp_recorte', 'comentario').aliasName = 'Alias ajeno'
        self.a.management.AlterField.side_effect = alter_alias
        with self.assertRaisesRegex(ValueError, 'comentario: cambio inesperado'):
            self.run_tool(apply=True)
        self.assertEqual(self.latest_report()['completadas'], [])
        self.assertEqual(self.a.management.AlterField.call_count, 1)

    def test_foreign_change_to_another_approved_field_is_also_rejected(self):
        def alter_another(path, name, **kwargs):
            self.alter(path, name, **kwargs)
            self.alter(path, 'numerico', field_type='DOUBLE')
        self.a.management.AlterField.side_effect = alter_another
        with self.assertRaisesRegex(ValueError, 'numerico: cambio inesperado'):
            self.run_tool(apply=True)
        self.assertEqual(self.a.management.AlterField.call_count, 1)

    def test_snapshot_rechecked_after_lock_before_the_write(self):
        # Dos ensayos de lock sobre predios_inscritos_en_sunarp_recorte durante los planes y un tercero justo
        # antes de la escritura; el cambio ajeno en ese tercero debe impedirla.
        count = [0]
        def lock(path):
            if path == self.paths['predios_inscritos_en_sunarp_recorte']:
                count[0] += 1
                if count[0] == 3:
                    self.field('predios_inscritos_en_sunarp_recorte', 'comentario').aliasName = 'Cambio externo'
            return True
        self.a.TestSchemaLock.side_effect = lock
        with self.assertRaisesRegex(ValueError, 'comentario: cambio inesperado'):
            self.run_tool(apply=True)
        self.a.management.AlterField.assert_not_called()

    def test_successful_gp_without_confirmed_target_is_a_failure(self):
        self.a.management.AlterField.side_effect = lambda *args, **kwargs: None
        with self.assertRaisesRegex(ValueError, 'ArcGIS no confirma'):
            self.run_tool(apply=True)
        self.assertEqual(self.latest_report()['campo_en_curso'], 'cargas_y_gravamenes')
        self.assertEqual(self.latest_report()['completadas'], [])

    def test_connection_owner_is_checked_by_real_engine_before_any_write(self):
        self.use_sde()
        self.connection.user = 'otro'
        with self.assertRaisesRegex(ValueError, 'conexion del propietario'):
            self.run_tool(apply=True)
        self.a.management.AlterField.assert_not_called()

    def test_versioning_globalid_audit_utc_and_active_audit_names_block_the_batch(self):
        description = self.descriptions[self.paths['zonas_de_vida_holdridge_recorte']]
        for prop, value in [('isVersioned', True), ('hasGlobalID', False),
                            ('isTimeInUTC', False), ('creatorFieldName', 'autor_externo')]:
            with self.subTest(prop=prop):
                old = getattr(description, prop)
                setattr(description, prop, value)
                try:
                    with self.assertRaises(ValueError):
                        self.run_tool(apply=True)
                finally:
                    setattr(description, prop, old)
        self.a.management.AlterField.assert_not_called()

    def test_extra_columns_and_case_differences_are_rejected(self):
        path = self.paths['zonas_de_vida_holdridge_recorte']
        self.fields[path].append(self.make_field('columna_ajena', 'String', 100, True))
        with self.assertRaisesRegex(ValueError, 'campos fuera del esquema EFT'):
            self.run_tool(apply=True)
        self.fields[path].pop()
        field = self.field('zonas_de_vida_holdridge_recorte', 'medida')
        field.name = field.baseName = 'MEDIDA'
        with self.assertRaisesRegex(ValueError, 'MEDIDA -> medida'):
            self.run_tool(apply=True)
        self.a.management.AlterField.assert_not_called()

    def test_selection_changes_only_explicit_class_and_never_creates_missing_classes(self):
        _, report = self.run_tool(apply=True, names=['zonas_de_vida_holdridge_recorte'])
        self.assertEqual([c['nombre'] for c in report['clases']], ['zonas_de_vida_holdridge_recorte'])
        self.assertEqual(report['completadas'], ['zonas_de_vida_holdridge_recorte.medida'])
        self.assertEqual(self.a.management.AlterField.call_count, 1)
        self.assertEqual(self.field('predios_inscritos_en_sunarp_recorte', 'conteo').type, 'String')
        self.a.ArcSDESQLExecute.assert_not_called()
        self.paths.pop('zonas_de_vida_holdridge_recorte')
        self.a.management.AlterField.reset_mock()
        with self.assertRaisesRegex(ValueError, 'No existe zonas_de_vida_holdridge_recorte; esta herramienta no crea clases'):
            self.run_tool(apply=True, names=['zonas_de_vida_holdridge_recorte'])
        self.a.management.AlterField.assert_not_called()
        self.assertFalse(hasattr(self.a.management, 'CreateFeatureclass'))

    def test_empty_unknown_or_unapproved_selection_is_rejected(self):
        for names in ([], ['desconocida'], 'predios_inscritos_en_sunarp_recorte'):
            with self.subTest(names=names), self.assertRaises(ValueError):
                self.run_tool(apply=True, names=names)
        self.a.management.AlterField.assert_not_called()

    def test_lock_on_last_class_blocks_apply_but_validation_records_observation(self):
        self.locks[self.paths['zonas_de_vida_holdridge_recorte']] = False
        _, report = self.run_tool()
        self.assertFalse(report['bloqueos_disponibles']['zonas_de_vida_holdridge_recorte'])
        with self.assertRaisesRegex(ValueError, 'No hay bloqueo de esquema disponible sobre zonas_de_vida_holdridge_recorte'):
            self.run_tool(apply=True)
        self.a.management.AlterField.assert_not_called()

    def test_already_completed_batch_needs_no_alter_or_schema_lock(self):
        self.complete_all()
        self.locks.update({path: False for path in self.paths.values()})
        _, report = self.run_tool(apply=True)
        self.assertEqual(report['estado'], 'CAMPOS_VERIFICADOS')
        self.assertEqual(report['completadas'], [])
        self.a.management.AlterField.assert_not_called()

    def test_sql_nonunicode_text_blocks_entire_batch_before_writes(self):
        self.use_sde()
        self.sql_type = 'varchar'
        with self.assertRaisesRegex(ValueError, 'se requiere NVARCHAR'):
            self.run_tool(apply=True)
        self.a.management.AlterField.assert_not_called()

    def test_sde_pending_text_never_attempts_rejected_alter_length(self):
        self.use_sde()
        with self.assertRaisesRegex(ValueError,'Reparar texto largo de predios'):
            self.run_tool(apply=True)
        self.a.management.AlterField.assert_not_called()
        self.assertEqual(self.latest_report()['completadas'],[])
        _,report=self.run_tool()
        self.assertEqual(report['estado'],'VALIDACION_OK_SIN_CAMBIOS')
        self.assertTrue(any('NVARCHAR(MAX)' in text for text in report['advertencias']))

    def test_sql_max_must_be_confirmed_before_resuming_numeric_changes(self):
        self.use_sde()
        self.alter(self.paths['predios_inscritos_en_sunarp_recorte'],
                   'cargas_y_gravamenes',field_type='TEXT',field_length=10000)
        self.sql_length_override = 8000
        with self.assertRaisesRegex(ValueError, 'no se confirma como NVARCHAR'):
            self.run_tool(apply=True)
        failed = self.latest_report()
        self.assertEqual(failed['completadas'], [])
        self.a.management.AlterField.assert_not_called()
        self.sql_length_override = None
        self.a.management.AlterField.reset_mock()
        _, report = self.run_tool(apply=True)
        self.assertNotIn('cargas_y_gravamenes', [call.args[1] for call in self.a.management.AlterField.call_args_list])
        self.assertTrue(report['texto_sqlserver_antes']['unicode'])
        self.assertTrue(report['texto_sqlserver_antes']['es_max'])

    def test_configuration_cannot_authorize_an_eft_field_or_duplicate_operation(self):
        duplicate = copy.deepcopy(self.config)
        duplicate['cambios'].append(copy.deepcopy(duplicate['cambios'][0]))
        with self.assertRaisesRegex(ValueError, 'Cambio duplicado'):
            tool.selected_model(self.source, duplicate)
        invalid = copy.deepcopy(self.config)
        invalid['cambios'][0].update(campo='id_analisis', tipo_objetivo='TEXT', longitud_objetivo=10000)
        source = copy.deepcopy(self.source)
        source['clases'][0]['campos'][1]['longitud'] = 10000
        with self.assertRaisesRegex(ValueError, 'no es un atributo propio'):
            tool.selected_model(source, invalid)


if __name__ == '__main__':
    unittest.main()
