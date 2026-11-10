"""Contrato de la preparacion del catalogo: validar primero y aprobar auditoria aparte."""
import ast
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from test_diagnostico_integrado import Parameter, load_toolbox


HERE = Path(__file__).resolve().parent


class ProjectConfigurationToolboxTests(unittest.TestCase):
    def setUp(self):
        self.a = SimpleNamespace(Parameter=Parameter, AddMessage=Mock(), AddWarning=Mock(), AddError=Mock())
        self.source = (HERE / 'Datos_Proyecto.pyt').read_text(encoding='utf-8-sig')
        self.module = load_toolbox(self.source, 'toolbox_project_configuration_test', self.a)

    def test_validation_default_does_not_preapprove_new_fields(self):
        tool = self.module.ConfigurarCatalogoProyectos()
        params = tool.getParameterInfo()
        self.assertFalse(tool.canRunInBackground)
        self.assertEqual([p.name for p in params], ['workspace', 'mode', 'approve_native_audit',
            'database', 'owner', 'reports', 'report'])
        self.assertEqual(params[1].value, 'Validar configuracion (sin cambios)')
        self.assertEqual(params[1].filter.list,
            ['Validar configuracion (sin cambios)', 'Aplicar configuracion aprobada'])
        self.assertEqual(params[2].datatype, 'GPBoolean')
        self.assertIs(params[2].value, False)
        self.assertIn('cuatro campos', params[2].displayName)
        self.assertEqual(params[3].value, 'ArcGisAWS')
        self.assertEqual(params[4].value, 'gis')
        self.assertEqual(params[-1].parameterType, 'Derived')
        self.assertEqual(params[-1].direction, 'Output')

    def test_action_and_approval_are_independent_runtime_arguments(self):
        for apply in (False, True):
            for approved in (False, True):
                with self.subTest(apply=apply, approved=approved):
                    params = self.module.ConfigurarCatalogoProyectos().getParameterInfo()
                    params[0].value = 'C:/destino.sde'
                    params[1].value = params[1].filter.list[int(apply)]
                    params[2].value = approved
                    params[5].value = 'C:/informes'
                    runtime = SimpleNamespace(run=Mock(return_value=(Path('C:/informes'),
                        {'estado': 'PRUEBA', 'archivo_resultado': 'C:/informes/resultado.json'})))
                    with patch.object(self.module, 'load_runner', Mock()):
                        with patch.dict(sys.modules, {'configurar_proyecto': runtime}):
                            self.module.ConfigurarCatalogoProyectos().execute(params, None)
                    runtime.run.assert_called_once_with('C:/destino.sde', apply=apply,
                        approve_native_audit=approved, database='ArcGisAWS', owner='gis',
                        reports='C:/informes', arcpy_module=self.a, emit=self.a.AddMessage)
                    self.assertEqual(params[-1].value, 'C:/informes/resultado.json')

    def test_string_false_is_not_an_approval(self):
        params = self.module.ConfigurarCatalogoProyectos().getParameterInfo()
        params[2].value = 'false'
        runtime = SimpleNamespace(run=Mock(return_value=(HERE, {'archivo_resultado': 'resultado.json'})))
        with patch.object(self.module, 'load_runner', Mock()):
            with patch.dict(sys.modules, {'configurar_proyecto': runtime}):
                self.module.ConfigurarCatalogoProyectos().execute(params, None)
        self.assertFalse(runtime.run.call_args.kwargs['approve_native_audit'])
        self.assertFalse(runtime.run.call_args.kwargs['apply'])

    def test_unknown_action_never_calls_runtime(self):
        params = self.module.ConfigurarCatalogoProyectos().getParameterInfo()
        params[1].value = 'Aplicar sin revisar'
        runtime = SimpleNamespace(run=Mock())
        with patch.object(self.module, 'load_runner', Mock()):
            with patch.dict(sys.modules, {'configurar_proyecto': runtime}):
                with self.assertRaisesRegex(ValueError, 'Accion'):
                    self.module.ConfigurarCatalogoProyectos().execute(params, None)
        runtime.run.assert_not_called()
        self.assertIsNone(params[-1].value)

    def test_runtime_blocker_is_not_reported_as_success(self):
        params = self.module.ConfigurarCatalogoProyectos().getParameterInfo()
        runtime = SimpleNamespace(run=Mock(side_effect=ValueError('Auditoria nativa sin aprobacion')))
        with patch.object(self.module, 'load_runner', Mock()):
            with patch.dict(sys.modules, {'configurar_proyecto': runtime}):
                with self.assertRaisesRegex(ValueError, 'sin aprobacion'):
                    self.module.ConfigurarCatalogoProyectos().execute(params, None)
        self.a.AddError.assert_called_once_with('Auditoria nativa sin aprobacion')
        self.assertIsNone(params[-1].value)

    def test_pending_audit_approval_is_visible_with_the_report(self):
        params = self.module.ConfigurarCatalogoProyectos().getParameterInfo()
        runtime = SimpleNamespace(run=Mock(return_value=(HERE, {
            'estado': 'CONFIGURACION_PENDIENTE_APROBACION_AUDITORIA',
            'archivo_resultado': 'C:/informes/resultado.json'})))
        with patch.object(self.module, 'load_runner', Mock()):
            with patch.dict(sys.modules, {'configurar_proyecto': runtime}):
                self.module.ConfigurarCatalogoProyectos().execute(params, None)
        self.a.AddWarning.assert_called_once()
        message = self.a.AddWarning.call_args.args[0]
        for field in ('created_user', 'created_date', 'last_edited_user', 'last_edited_date'):
            self.assertIn(field, message)
        self.assertIn('no autoriza', message)
        self.assertEqual(params[-1].value, 'C:/informes/resultado.json')

    def test_runtime_loads_after_its_parent_dependencies(self):
        tree = ast.parse(self.source)
        loader = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'load_runner')
        loop = next(n for n in loader.body if isinstance(n, ast.For))
        names = ast.literal_eval(loop.iter)
        self.assertEqual(names[names.index('alta_proyectos'):names.index('configurar_proyecto') + 1],
                         ('alta_proyectos', 'configurar_proyecto'))
        self.assertLess(names.index('crear_esquema'), names.index('configurar_proyecto'))


if __name__ == '__main__':
    unittest.main()
