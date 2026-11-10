"""Contrato de la toolbox integrada y su ruta de diagnostico de solo lectura."""
import hashlib
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch


HERE = Path(__file__).resolve().parent
BASELINE = HERE / 'validacion_fixture_toolbox_1_6.txt'
BASELINE_SHA = '43de2ec1b9babf969c1a7e64d9409cbff2d8177c12a5575915f031e657cf7915'


class Parameter:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
        self.multiValue = kwargs.get('multiValue', False)
        self.value = None
        self.filter = SimpleNamespace(type=None, list=[])

    @property
    def valueAsText(self):
        return None if self.value is None else str(self.value)


def load_toolbox(source, name, arcpy):
    module = ModuleType(name)
    module.__file__ = str(HERE / 'Datos_Proyecto.pyt')
    with patch.dict(sys.modules, {'arcpy': arcpy}):
        exec(compile(source, module.__file__, 'exec'), module.__dict__)
    return module


def parameter_contract(parameters):
    return [dict(name=p.name, label=p.displayName, datatype=p.datatype,
        required=p.parameterType, direction=p.direction, multi=p.multiValue,
        value=p.value, filter_type=p.filter.type, filter_values=p.filter.list)
        for p in parameters]


class IntegratedDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.a = SimpleNamespace(Parameter=Parameter, AddMessage=Mock(), AddWarning=Mock(), AddError=Mock())
        self.module = load_toolbox((HERE / 'Datos_Proyecto.pyt').read_text(encoding='utf-8-sig'),
                                   'toolbox_integrated_test', self.a)
        previous_raw = BASELINE.read_bytes()
        self.assertEqual(hashlib.sha256(previous_raw).hexdigest(), BASELINE_SHA)
        self.previous = load_toolbox(previous_raw.decode('utf-8-sig'),
                                     'toolbox_previous_test', self.a)

    def test_catalog_adds_diagnostic_after_the_five_existing_tools(self):
        old_names = [tool.__name__ for tool in self.previous.Toolbox().tools]
        new_names = [tool.__name__ for tool in self.module.Toolbox().tools]
        self.assertEqual(new_names, old_names + ['DiagnosticarRenombrado', 'ValidarTextosConfirmados', 'ValidarTodosTiposKMZ', 'CerrarTiposKMZ', 'PrevalidarIngesta', 'RegistrarProyectosFaltantes', 'ConfigurarCatalogoProyectos', 'PrepararCargaInicialKMZ'])
        self.assertIn('1.13', self.module.Toolbox().label)

    def test_ingestion_plan_requires_current_sources_and_has_no_apply_action(self):
        params = self.module.PrevalidarIngesta().getParameterInfo()
        self.assertEqual([p.name for p in params], ['workspace', 'kmz_dir', 'project_csv',
            'database', 'owner', 'reports', 'report'])
        self.assertEqual(params[1].parameterType, 'Required')
        self.assertEqual(params[2].parameterType, 'Optional')
        self.assertEqual(params[2].filter.list, ['csv'])
        params[0].value, params[1].value = 'C:/destino.sde', 'C:/fuentes'
        params[5].value = 'C:/informes'
        verifier = SimpleNamespace(run=Mock(return_value=(Path('C:/informes'),
            {'estado': 'PLAN_INGESTA_CON_PENDIENTES', 'archivo_resultado': 'C:/informes/resultado.json'})))
        with patch.object(self.module, 'load_runner', Mock()):
            with patch.dict(sys.modules, {'prevalidar_ingesta': verifier}):
                self.module.PrevalidarIngesta().execute(params, None)
        verifier.run.assert_called_once_with('C:/destino.sde', kmz_dir='C:/fuentes',
            project_csv=None, database='ArcGisAWS', owner='gis', reports='C:/informes',
            arcpy_module=self.a, emit=self.a.AddMessage)
        self.assertEqual(params[6].value, 'C:/informes/resultado.json')

    def test_existing_tool_parameters_and_validation_defaults_are_preserved(self):
        for old_class in self.previous.Toolbox().tools:
            with self.subTest(tool=old_class.__name__):
                before = parameter_contract(old_class().getParameterInfo())
                after = parameter_contract(getattr(self.module, old_class.__name__)().getParameterInfo())
                if old_class.__name__ == 'RenombrarClases':
                    self.assertEqual(after[:6], before[:6])
                    self.assertEqual(after[-1], before[-1])
                    self.assertEqual(after[6]['name'], 'previous_report')
                    self.assertEqual(after[6]['required'], 'Optional')
                else:
                    self.assertEqual(after, before)
                self.assertEqual(after[1]['value'], 'Validar (sin cambios)')

    def test_resume_uses_original_report_with_the_same_selected_classes(self):
        params = self.module.RenombrarClases().getParameterInfo()
        params[0].value = 'C:/destino.sde'
        params[1].value = 'Aplicar nombres aprobados'
        params[2].values = ['accesos']
        params[5].value = 'C:/informes'
        params[6].value = 'C:/informe_original.json'
        renamer = SimpleNamespace(run=Mock(return_value=(Path('C:/informes'),
            {'estado': 'NOMBRES_VERIFICADOS', 'archivo_resultado': 'C:/informes/resultado.json'})))
        with patch.object(self.module, 'load_runner', Mock()):
            with patch.dict(sys.modules, {'renombrar_clases': renamer}):
                self.module.RenombrarClases().execute(params, None)
        renamer.run.assert_called_once_with('C:/destino.sde', apply=True, names=['accesos'],
            database='ArcGisAWS', owner='gis', reports='C:/informes', arcpy_module=self.a,
            emit=self.a.AddMessage, previous_report_path='C:/informe_original.json')
        self.assertEqual(params[7].value, 'C:/informes/resultado.json')

    def test_diagnostic_has_no_apply_option_and_does_not_reuse_old_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'resultado_origen.json').write_text('{}', encoding='utf-8')
            with patch.object(self.module, 'HERE', root):
                params = self.module.DiagnosticarRenombrado().getParameterInfo()
            self.assertEqual([p.name for p in params],
                ['workspace', 'previous_report', 'database', 'owner', 'reports', 'report'])
            self.assertFalse(any(p.name in ('mode', 'apply') for p in params))
            self.assertIsNone(params[1].value)
            self.assertEqual(params[1].filter.list, ['json'])
            self.assertEqual(params[-1].parameterType, 'Derived')
            self.assertEqual(params[-1].direction, 'Output')
            self.assertEqual(params[2].value, 'ArcGisAWS')
            self.assertEqual(params[3].value, 'gis')

    def test_text_tool_has_no_apply_or_class_selector_and_returns_readonly_report(self):
        params = self.module.ValidarTextosConfirmados().getParameterInfo()
        self.assertEqual([p.name for p in params], ['workspace', 'database', 'owner', 'reports', 'report'])
        self.assertEqual(params[-1].parameterType, 'Derived')
        params[0].value = 'C:/destino.sde'
        params[3].value = 'C:/informes'
        verifier = SimpleNamespace(run=Mock(return_value=(Path('C:/informes'),
            {'estado': 'TEXTOS_CONFIRMADOS_VERIFICADOS', 'archivo_resultado': 'C:/informes/resultado.json'})))
        with patch.object(self.module, 'load_runner', Mock()):
            with patch.dict(sys.modules, {'verificar_textos_confirmados': verifier}):
                self.module.ValidarTextosConfirmados().execute(params, None)
        verifier.run.assert_called_once_with('C:/destino.sde', database='ArcGisAWS', owner='gis',
            reports='C:/informes', arcpy_module=self.a, emit=self.a.AddMessage)
        self.assertEqual(params[4].value, 'C:/informes/resultado.json')

    def test_closure_defaults_to_readonly_and_applies_only_explicit_action(self):
        for apply in (False, True):
            with self.subTest(apply=apply):
                params = self.module.CerrarTiposKMZ().getParameterInfo()
                self.assertEqual([p.name for p in params], ['workspace','accion','database','owner','reports','report'])
                self.assertEqual(params[1].value, 'Validar cierre (sin cambios)')
                self.assertEqual(params[1].filter.list, ['Validar cierre (sin cambios)', 'Aplicar cierre de tipos'])
                params[0].value = 'C:/destino.sde'
                params[4].value = 'C:/informes'
                if apply:
                    params[1].value = 'Aplicar cierre de tipos'
                closer = SimpleNamespace(run=Mock(return_value=(Path('C:/informes'),
                    {'archivo_resultado':'C:/informes/resultado.json','cierre_verificado':apply})))
                with patch.object(self.module,'load_runner',Mock()), patch.dict(sys.modules,{'cerrar_tipos_kmz':closer}):
                    self.module.CerrarTiposKMZ().execute(params,None)
                closer.run.assert_called_once_with('C:/destino.sde',apply=apply,database='ArcGisAWS',
                    owner='gis',reports='C:/informes',arcpy_module=self.a,emit=self.a.AddMessage)
                self.assertEqual(params[-1].value,'C:/informes/resultado.json')

    def test_closure_rejects_unknown_action_and_preserves_failure(self):
        params = self.module.CerrarTiposKMZ().getParameterInfo()
        params[1].value = 'Crear y cargar'
        closer = SimpleNamespace(run=Mock())
        with patch.object(self.module,'load_runner',Mock()), patch.dict(sys.modules,{'cerrar_tipos_kmz':closer}):
            with self.assertRaisesRegex(ValueError,'Accion'):
                self.module.CerrarTiposKMZ().execute(params,None)
        closer.run.assert_not_called()
        params[1].value = 'Aplicar cierre de tipos'
        closer.run.side_effect = ValueError('Clase contiene registros')
        with patch.object(self.module,'load_runner',Mock()), patch.dict(sys.modules,{'cerrar_tipos_kmz':closer}):
            with self.assertRaisesRegex(ValueError,'registros'):
                self.module.CerrarTiposKMZ().execute(params,None)
        self.assertIsNone(params[-1].value)

    def make_parameters(self):
        params = self.module.DiagnosticarRenombrado().getParameterInfo()
        for index, value in enumerate(('C:/destino.sde', 'C:/informe_original.json',
                                       'ArcGisAWS', 'gis', 'C:/informes')):
            params[index].value = value
        return params

    def test_full_kmz_tool_uses_optional_sources_and_returns_complete_report(self):
        params = self.module.ValidarTodosTiposKMZ().getParameterInfo()
        self.assertEqual([p.name for p in params], ['workspace','kmz_dir','database','owner','reports','report'])
        self.assertEqual(params[1].parameterType, 'Optional')
        self.assertIsNone(params[1].value)
        self.assertFalse(any(p.name in ('apply','mode','classes') for p in params))
        params[0].value = 'C:/destino.sde'
        params[4].value = 'C:/informes'
        validator = SimpleNamespace(run=Mock(return_value=(Path('C:/informes'),
            {'estado':'VALIDACION_TIPOS_COMPLETA_CON_PENDIENTES','archivo_resultado':'C:/informes/resultado.json'})))
        with patch.object(self.module, 'load_runner', Mock()):
            with patch.dict(sys.modules, {'validar_tipos_kmz':validator}):
                self.module.ValidarTodosTiposKMZ().execute(params, None)
        validator.run.assert_called_once_with('C:/destino.sde',kmz_dir=None,database='ArcGisAWS',
            owner='gis',reports='C:/informes',arcpy_module=self.a,emit=self.a.AddMessage)
        self.assertEqual(params[-1].value, 'C:/informes/resultado.json')
        self.a.AddWarning.assert_called_once()

    def test_full_kmz_tool_preserves_failures(self):
        params = self.module.ValidarTodosTiposKMZ().getParameterInfo()
        validator = SimpleNamespace(run=Mock(side_effect=ValueError('Perfil incluido no coincide con el modelo')))
        with patch.object(self.module, 'load_runner', Mock()):
            with patch.dict(sys.modules, {'validar_tipos_kmz':validator}):
                with self.assertRaisesRegex(ValueError,'no coincide'):
                    self.module.ValidarTodosTiposKMZ().execute(params,None)
        self.a.AddError.assert_called_once()
        self.assertIsNone(params[-1].value)

    def test_execute_routes_only_to_read_diagnostic_and_returns_report(self):
        params = self.make_parameters()
        diagnostic = SimpleNamespace(run=Mock(return_value=(Path('C:/informes'),
            {'estado': 'DIFERENCIAS_DETECTADAS', 'archivo_resultado': 'C:/informes/resultado.json'})))
        with patch.object(self.module, 'load_runner', Mock()) as loader:
            with patch.dict(sys.modules, {'diagnostico_renombrado': diagnostic}):
                self.module.DiagnosticarRenombrado().execute(params, None)
        loader.assert_called_once_with()
        diagnostic.run.assert_called_once_with('C:/destino.sde', 'C:/informe_original.json',
            database='ArcGisAWS', owner='gis', reports='C:/informes',
            arcpy_module=self.a, emit=self.a.AddMessage)
        self.assertEqual(params[5].value, 'C:/informes/resultado.json')
        self.a.AddWarning.assert_called_once()
        self.a.AddError.assert_not_called()

    def test_incomplete_diagnostic_warns_but_keeps_output_and_no_difference_is_not_resume(self):
        for state in ('DIAGNOSTICO_INCOMPLETO', 'SIN_DIFERENCIAS_ACTUALES'):
            with self.subTest(state=state):
                self.a.AddWarning.reset_mock()
                self.a.AddMessage.reset_mock()
                params = self.make_parameters()
                diagnostic = SimpleNamespace(run=Mock(return_value=(Path('C:/informes'),
                    {'estado': state, 'archivo_resultado': 'C:/informes/resultado.json'})))
                with patch.object(self.module, 'load_runner', Mock()):
                    with patch.dict(sys.modules, {'diagnostico_renombrado': diagnostic}):
                        self.module.DiagnosticarRenombrado().execute(params, None)
                self.assertEqual(params[5].value, 'C:/informes/resultado.json')
                if state == 'DIAGNOSTICO_INCOMPLETO':
                    self.a.AddWarning.assert_called_once()
                else:
                    self.a.AddWarning.assert_not_called()
                    self.a.AddMessage.assert_called_once()
                    self.assertIn('no explica', self.a.AddMessage.call_args.args[0])

    def test_reference_rejection_is_reported_and_does_not_produce_success_output(self):
        params = self.make_parameters()
        diagnostic = SimpleNamespace(run=Mock(side_effect=ValueError('El workspace no coincide')))
        with patch.object(self.module, 'load_runner', Mock()):
            with patch.dict(sys.modules, {'diagnostico_renombrado': diagnostic}):
                with self.assertRaisesRegex(ValueError, 'workspace no coincide'):
                    self.module.DiagnosticarRenombrado().execute(params, None)
        self.a.AddError.assert_called_once_with('El workspace no coincide')
        self.assertIsNone(params[5].value)


if __name__ == '__main__':
    unittest.main()
