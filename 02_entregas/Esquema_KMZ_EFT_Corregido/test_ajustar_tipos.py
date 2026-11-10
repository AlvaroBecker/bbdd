"""Pruebas de migracion controlada con ArcPy simulado; no accede a SDE."""
import copy
from contextlib import contextmanager, nullcontext
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import ajustar_tipos_estructuras as tool


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.model = tool.runner.scoped_model(
            json.loads((Path(__file__).parent / 'esquema.json').read_text(encoding='utf-8')),
            ['estructuras'])
        self.path = 'fixture.gdb/Datos_Proyecto/estructuras'
        self.args = SimpleNamespace(workspace='fixture.gdb', database='ArcGisAWS', owner='gis')
        self.fields = []
        self.records = 0
        for spec in self.model['clases'][0]['campos']:
            name = spec['nombre']
            old_numeric = name in tool.FIELDS
            self.fields.append(SimpleNamespace(
                name=name, baseName=name, type='String' if old_numeric else tool.runner.engine.TYPE[spec['tipo']],
                length=4000 if old_numeric else (spec['longitud'] or 0), aliasName=spec['alias'],
                isNullable=spec['nullable'], domain=spec.get('dominio') or '', defaultValue=None,
                required=False, precision=0, scale=0))
        for name, kind in [('OBJECTID','OID'), ('Shape','Geometry'), ('GlobalID','GlobalID'),
                           ('created_user','String'), ('created_date','Date'),
                           ('last_edited_user','String'), ('last_edited_date','Date')]:
            self.fields.append(SimpleNamespace(
                name=name, baseName=name, type=kind, length=255 if kind=='String' else 0,
                aliasName=name, isNullable=True, domain='', defaultValue=None,
                required=True, precision=0, scale=0))
        self.a = SimpleNamespace(
            GetInstallInfo=lambda: {'Version':'SIMULADA'},
            EnvManager=lambda **kwargs: nullcontext(),
            ListFields=Mock(side_effect=lambda path:list(self.fields)),
            ListIndexes=Mock(return_value=[]), TestSchemaLock=Mock(return_value=True),
            management=SimpleNamespace(
                GetCount=Mock(side_effect=lambda path:SimpleNamespace(getOutput=lambda n:str(self.records))),
                AlterField=Mock(side_effect=self.alter)))

    def field(self, name):
        return next(f for f in self.fields if f.baseName==name)

    def alter(self, path, name, *, field_type):
        self.assertEqual(path, self.path)
        self.assertEqual(field_type, 'DOUBLE')
        field = self.field(name)
        field.type = 'Double'
        field.length = 8

    def validate(self, a, args, model):
        c = model['clases'][0]
        tool.runner.engine.validate_fields(a, self.path, c['campos'])
        tool.runner.validate_existing_names(self.fields, c)
        extras=tool.runner.unexpected_fields(self.fields,SimpleNamespace(),c)
        if extras:
            raise ValueError('Campos extra: '+str(extras))
        return {'estructuras':self.path}, {}, 1, True

    @contextmanager
    def patched(self):
        with patch.object(tool.runner.engine,'inspect',return_value=({'estructuras':self.path},{})), \
                patch.object(tool.runner,'preflight',side_effect=self.validate) as preflight:
            yield preflight

    def run_tool(self, temp, apply=False):
        self.last_report_path = None
        def capture(message):
            if message.startswith('Resultado JSON: '):
                self.last_report_path = Path(message.removeprefix('Resultado JSON: '))
        return tool.run('fixture.gdb',apply=apply,reports=temp,arcpy_module=self.a,emit=capture)

    def latest_report(self, temp):
        path = getattr(self, 'last_report_path', None)
        self.assertIsNotNone(path, 'La ejecucion no emitio su Resultado JSON final.')
        self.assertTrue(path.is_relative_to(Path(temp)))
        return json.loads(path.read_text(encoding='utf-8'))

    def test_model_has_exactly_seven_double_and_fourteen_text_own_attributes(self):
        fields=[f for f in self.model['clases'][0]['campos'] if f.get('campo_fuente')]
        self.assertEqual({f['nombre'] for f in fields if f['tipo']=='DOUBLE'},set(tool.FIELDS))
        self.assertEqual(sum(f['tipo']=='TEXT' for f in fields),14)
        self.assertTrue(all(f['longitud']==4000 for f in fields if f['tipo']=='TEXT'))
        self.assertEqual(len(self.model['clases'][0]['campos']),32)

    def test_plan_supports_mixed_string_double_without_mutating_model(self):
        self.alter(self.path,'este',field_type='DOUBLE')
        before=copy.deepcopy(self.model)
        with self.patched():
            path, rows, lock=tool.plan(self.a,self.args,self.model)
        self.assertEqual(path,self.path)
        self.assertTrue(lock)
        self.assertEqual(next(r['accion'] for r in rows if r['campo']=='este'),'YA_DOUBLE')
        self.assertEqual(sum(r['accion']=='ALTERAR_TIPO' for r in rows),6)
        self.assertEqual(self.model,before)
        self.a.management.AlterField.assert_not_called()

    def test_validation_has_no_writes_and_records_actionable_plan(self):
        before=tool.snapshot(self.a,self.path)
        with tempfile.TemporaryDirectory() as temp, self.patched():
            _,report=self.run_tool(temp)
            self.assertEqual(report['estado'],'VALIDACION_OK_SIN_CAMBIOS')
            self.assertEqual(len(report['plan']),7)
            self.assertEqual(report['completadas'],[])
        self.assertEqual(tool.snapshot(self.a,self.path),before)
        self.a.management.AlterField.assert_not_called()

    def test_nonempty_class_blocks_before_first_write(self):
        self.records=1
        with tempfile.TemporaryDirectory() as temp, self.patched(), \
                self.assertRaisesRegex(ValueError,'contiene 1 registros'):
            self.run_tool(temp,apply=True)
        self.a.management.AlterField.assert_not_called()

    def test_unexpected_third_type_blocks_before_first_write(self):
        self.field('east').type='Integer'
        with self.patched(), self.assertRaisesRegex(ValueError,'solo se admite TEXT anterior o DOUBLE'):
            tool.plan(self.a,self.args,self.model)
        self.a.management.AlterField.assert_not_called()

    def test_required_domain_nullability_or_default_block_before_first_write(self):
        for prop,value in [('required',True),('domain','dom_externo'),('isNullable',False),('defaultValue','0')]:
            with self.subTest(prop=prop):
                field=self.field('este'); old=getattr(field,prop);setattr(field,prop,value)
                try:
                    with self.patched(), self.assertRaises(ValueError):
                        tool.plan(self.a,self.args,self.model)
                finally:
                    setattr(field,prop,old)
        self.a.management.AlterField.assert_not_called()

    def test_index_on_candidate_blocks_before_first_write(self):
        self.a.ListIndexes.return_value=[SimpleNamespace(name='ix_este',fields=[self.field('este')])]
        with self.patched(), self.assertRaisesRegex(ValueError,'Indice ix_este'):
            tool.plan(self.a,self.args,self.model)
        self.a.management.AlterField.assert_not_called()

    def test_apply_changes_only_authorized_types_and_preserves_other_properties(self):
        before=tool.snapshot(self.a,self.path)
        with tempfile.TemporaryDirectory() as temp, self.patched():
            _,report=self.run_tool(temp,apply=True)
        self.assertEqual(report['estado'],'TIPOS_VERIFICADOS')
        self.assertEqual(report['completadas'],list(tool.FIELDS))
        self.assertEqual([c.args[1] for c in self.a.management.AlterField.call_args_list],list(tool.FIELDS))
        after=tool.snapshot(self.a,self.path)
        for name,original in before.items():
            if name not in tool.FIELDS:
                self.assertEqual(original,after[name])
            else:
                self.assertEqual(after[name]['tipo'],'Double')
                for prop in ['nombre','alias','nullable','dominio','defecto','requerido']:
                    self.assertEqual(original[prop],after[name][prop])

    def test_partial_failure_records_progress_and_resume_does_not_repeat_double(self):
        def fail_second(path,name,*,field_type):
            if name=='norte':
                raise RuntimeError('Fallo GP simulado')
            self.alter(path,name,field_type=field_type)
        self.a.management.AlterField.side_effect=fail_second
        with tempfile.TemporaryDirectory() as temp, self.patched():
            with self.assertRaisesRegex(RuntimeError,'Fallo GP simulado'):
                self.run_tool(temp,apply=True)
            failed=self.latest_report(temp)
            self.assertEqual(failed['estado'],'ERROR_DETENIDO')
            self.assertEqual(failed['completadas'],['este'])
            self.assertEqual(failed['campo_en_curso'],'norte')
            self.assertEqual(failed['campos_observados_al_detener']['este']['tipo'],'Double')
            self.a.management.AlterField.reset_mock(side_effect=True)
            self.a.management.AlterField.side_effect=self.alter
            _,resumed=self.run_tool(temp,apply=True)
            self.assertEqual(resumed['estado'],'TIPOS_VERIFICADOS')
            self.assertNotIn('este',[c.args[1] for c in self.a.management.AlterField.call_args_list])
            self.assertEqual(self.a.management.AlterField.call_count,6)

    def test_error_after_real_change_is_reported_and_resume_recognizes_current_type(self):
        def mutate_then_raise(path,name,*,field_type):
            self.alter(path,name,field_type=field_type)
            raise RuntimeError('GP informo error despues de aplicar')
        self.a.management.AlterField.side_effect=mutate_then_raise
        with tempfile.TemporaryDirectory() as temp, self.patched():
            with self.assertRaises(RuntimeError):
                self.run_tool(temp,apply=True)
            failed=self.latest_report(temp)
            self.assertEqual(failed['completadas'],[])
            self.assertEqual(failed['campo_en_curso'],'este')
            self.assertEqual(failed['campos_observados_al_detener']['este']['tipo'],'Double')
            self.a.management.AlterField.reset_mock(side_effect=True)
            self.a.management.AlterField.side_effect=self.alter
            _,report=self.run_tool(temp,apply=True)
            self.assertEqual(report['estado'],'TIPOS_VERIFICADOS')
            self.assertNotIn('este',[c.args[1] for c in self.a.management.AlterField.call_args_list])

    def test_schema_lock_failure_blocks_writes_but_validation_reports_it(self):
        self.a.TestSchemaLock.return_value=False
        with tempfile.TemporaryDirectory() as temp, self.patched():
            _,report=self.run_tool(temp)
            self.assertFalse(report['bloqueo_disponible'])
            self.assertEqual(report['estado'],'VALIDACION_OK_SIN_CAMBIOS')
            with self.assertRaisesRegex(ValueError,'No hay bloqueo de esquema'):
                self.run_tool(temp,apply=True)
        self.a.management.AlterField.assert_not_called()

    def test_repeat_after_completion_performs_no_writes(self):
        for name in tool.FIELDS:
            self.alter(self.path,name,field_type='DOUBLE')
        self.a.TestSchemaLock.return_value=False
        with tempfile.TemporaryDirectory() as temp, self.patched():
            _,report=self.run_tool(temp,apply=True)
        self.assertEqual(report['estado'],'TIPOS_VERIFICADOS')
        self.assertEqual(report['completadas'],[])
        self.a.management.AlterField.assert_not_called()

    def test_unexpected_property_change_stops_and_is_not_marked_complete(self):
        def mutate_other_property(path,name,*,field_type):
            self.alter(path,name,field_type=field_type)
            self.field('codigo_enti').aliasName='Alias cambiado sin autorizacion'
        self.a.management.AlterField.side_effect=mutate_other_property
        with tempfile.TemporaryDirectory() as temp, self.patched():
            with self.assertRaisesRegex(ValueError,'codigo_enti: cambio inesperado'):
                self.run_tool(temp,apply=True)
            report=self.latest_report(temp)
            self.assertEqual(report['completadas'],[])
            self.assertEqual(report['campo_en_curso'],'este')
        self.assertEqual(self.a.management.AlterField.call_count,1)

    def test_successful_gp_without_double_is_not_accepted(self):
        self.a.management.AlterField.side_effect=lambda *args,**kwargs:None
        with tempfile.TemporaryDirectory() as temp, self.patched():
            with self.assertRaisesRegex(ValueError,'no confirma Double'):
                self.run_tool(temp,apply=True)
            report=self.latest_report(temp)
            self.assertEqual(report['completadas'],[])
            self.assertEqual(report['campo_en_curso'],'este')


if __name__=='__main__':
    unittest.main()
