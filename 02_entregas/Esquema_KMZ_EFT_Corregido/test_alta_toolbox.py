"""Contrato publico de la herramienta de altas: parametros y delegacion acotada."""
import ast
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from test_diagnostico_integrado import Parameter, load_toolbox


HERE = Path(__file__).resolve().parent


class ProjectToolboxTests(unittest.TestCase):
    def setUp(self):
        self.a = SimpleNamespace(Parameter=Parameter, AddMessage=Mock(), AddWarning=Mock(), AddError=Mock())
        self.source = (HERE / 'Datos_Proyecto.pyt').read_text(encoding='utf-8-sig')
        self.module = load_toolbox(self.source, 'toolbox_project_insert_test', self.a)

    def test_default_is_validation_without_exclusive_claim(self):
        tool = self.module.RegistrarProyectosFaltantes()
        params = tool.getParameterInfo()
        self.assertFalse(tool.canRunInBackground)
        self.assertEqual([p.name for p in params], ['workspace', 'mode', 'exclusive', 'project_csv',
            'database', 'owner', 'reports', 'report'])
        self.assertEqual(params[1].value, 'Validar altas (sin cambios)')
        self.assertEqual(params[1].filter.list, ['Validar altas (sin cambios)', 'Crear proyectos faltantes'])
        self.assertEqual(params[2].datatype, 'GPBoolean')
        self.assertIs(params[2].value, False)
        self.assertEqual(params[3].parameterType, 'Optional')
        self.assertEqual(params[3].filter.list, ['csv'])
        self.assertEqual(params[4].value, 'ArcGisAWS')
        self.assertEqual(params[5].value, 'gis')
        self.assertEqual(params[-1].parameterType, 'Derived')
        self.assertEqual(params[-1].direction, 'Output')

    def test_runtime_receives_exact_apply_flag_and_operator_declaration(self):
        for apply in (False, True):
            for exclusive in (False, True):
                with self.subTest(apply=apply, exclusive=exclusive):
                    params = self.module.RegistrarProyectosFaltantes().getParameterInfo()
                    params[0].value = 'C:/destino.sde'
                    params[1].value = params[1].filter.list[int(apply)]
                    params[2].value = exclusive
                    params[3].value = 'C:/proyectos.csv'
                    params[6].value = 'C:/informes'
                    runtime = SimpleNamespace(run=Mock(return_value=(Path('C:/informes'),
                        {'estado': 'PRUEBA', 'archivo_resultado': 'C:/informes/resultado.json'})))
                    with patch.object(self.module, 'load_runner', Mock()):
                        with patch.dict(sys.modules, {'alta_proyectos': runtime}):
                            self.module.RegistrarProyectosFaltantes().execute(params, None)
                    runtime.run.assert_called_once_with('C:/destino.sde', apply=apply, exclusive=exclusive,
                        project_csv='C:/proyectos.csv', database='ArcGisAWS', owner='gis',
                        reports='C:/informes', arcpy_module=self.a, emit=self.a.AddMessage)
                    self.assertEqual(params[-1].value, 'C:/informes/resultado.json')

    def test_no_csv_stays_none_and_false_text_is_false(self):
        params = self.module.RegistrarProyectosFaltantes().getParameterInfo()
        params[2].value = 'false'
        runtime = SimpleNamespace(run=Mock(return_value=(HERE, {'archivo_resultado': 'resultado.json'})))
        with patch.object(self.module, 'load_runner', Mock()):
            with patch.dict(sys.modules, {'alta_proyectos': runtime}):
                self.module.RegistrarProyectosFaltantes().execute(params, None)
        self.assertFalse(runtime.run.call_args.kwargs['exclusive'])
        self.assertIsNone(runtime.run.call_args.kwargs['project_csv'])
        self.assertFalse(runtime.run.call_args.kwargs['apply'])

    def test_unknown_action_does_not_reach_runtime(self):
        params = self.module.RegistrarProyectosFaltantes().getParameterInfo()
        params[1].value = 'Insertar todos'
        runtime = SimpleNamespace(run=Mock())
        with patch.object(self.module, 'load_runner', Mock()):
            with patch.dict(sys.modules, {'alta_proyectos': runtime}):
                with self.assertRaisesRegex(ValueError, 'Accion'):
                    self.module.RegistrarProyectosFaltantes().execute(params, None)
        runtime.run.assert_not_called()
        self.assertIsNone(params[-1].value)

    def test_runtime_failure_is_not_reported_as_success(self):
        params = self.module.RegistrarProyectosFaltantes().getParameterInfo()
        runtime = SimpleNamespace(run=Mock(side_effect=ValueError('Proyecto ambiguo')))
        with patch.object(self.module, 'load_runner', Mock()):
            with patch.dict(sys.modules, {'alta_proyectos': runtime}):
                with self.assertRaisesRegex(ValueError, 'ambiguo'):
                    self.module.RegistrarProyectosFaltantes().execute(params, None)
        self.a.AddError.assert_called_once_with('Proyecto ambiguo')
        self.assertIsNone(params[-1].value)

    def test_module_loader_places_logic_before_runtime(self):
        tree = ast.parse(self.source)
        loader = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'load_runner')
        loop = next(n for n in loader.body if isinstance(n, ast.For))
        names = ast.literal_eval(loop.iter)
        start = names.index('prevalidar_ingesta')
        self.assertEqual(names[start:start + 3], ('prevalidar_ingesta', 'alta_proyectos_logica', 'alta_proyectos'))


if __name__ == '__main__':
    unittest.main()
