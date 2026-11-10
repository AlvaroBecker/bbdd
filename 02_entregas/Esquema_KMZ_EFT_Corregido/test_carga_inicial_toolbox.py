import ast
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from test_diagnostico_integrado import Parameter,load_toolbox

HERE=Path(__file__).resolve().parent


class InitialLoadToolboxTests(unittest.TestCase):
    def setUp(self):
        self.a=SimpleNamespace(Parameter=Parameter,AddMessage=Mock(),AddWarning=Mock(),AddError=Mock())
        self.source=(HERE/'Datos_Proyecto.pyt').read_text(encoding='utf-8-sig')
        self.module=load_toolbox(self.source,'initial_load_test',self.a)

    def test_single_tool_requires_sources_and_defaults_to_confirmed_csv(self):
        tool=self.module.PrepararCargaInicialKMZ()
        params=tool.getParameterInfo()
        self.assertEqual(len(self.module.Toolbox().tools),13)
        self.assertFalse(tool.canRunInBackground)
        self.assertEqual([p.name for p in params],['workspace','kmz_dir','project_csv','database','owner','reports','report'])
        self.assertEqual(params[1].parameterType,'Required')
        self.assertEqual(Path(params[2].value).name,'confirmar_proyectos_13_confirmados.csv')
        self.assertEqual(params[3].value,'ArcGisAWS')
        self.assertEqual(params[4].value,'gis')
        self.assertFalse(any(p.name in {'apply','mode'} for p in params))

    def test_executes_local_runtime_and_exposes_result(self):
        params=self.module.PrepararCargaInicialKMZ().getParameterInfo()
        params[0].value='destino.sde';params[1].value='fuentes'
        fake=SimpleNamespace(run=Mock(return_value=(HERE,dict(archivo_resultado='resultado.json'))))
        with patch.object(self.module,'load_runner',Mock()),patch.dict(sys.modules,{'preparar_carga_inicial':fake}):
            self.module.PrepararCargaInicialKMZ().execute(params,None)
        fake.run.assert_called_once_with('destino.sde',kmz_dir='fuentes',project_csv=params[2].value,
            database='ArcGisAWS',owner='gis',reports=str(HERE),arcpy_module=self.a,emit=self.a.AddMessage)
        self.assertEqual(params[6].value,'resultado.json')
        self.a.AddWarning.assert_called_once()

    def test_errors_are_not_reported_as_completed_preparation(self):
        params=self.module.PrepararCargaInicialKMZ().getParameterInfo()
        fake=SimpleNamespace(run=Mock(side_effect=ValueError('Referencia alterada')))
        with patch.object(self.module,'load_runner',Mock()),patch.dict(sys.modules,{'preparar_carga_inicial':fake}):
            with self.assertRaisesRegex(ValueError,'alterada'):
                self.module.PrepararCargaInicialKMZ().execute(params,None)
        self.a.AddError.assert_called_once()
        self.a.AddWarning.assert_not_called()
        self.assertIsNone(params[6].value)

    def test_loader_resolves_new_dependencies_before_controller(self):
        tree=ast.parse(self.source)
        loader=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='load_runner')
        names=ast.literal_eval(next(n for n in loader.body if isinstance(n,ast.For)).iter)
        self.assertEqual(names[-1],'preparar_carga_inicial')
        for name in ['reglas_sunarp_ingesta','cobertura_ingesta','inspeccionar_negocio_ingesta','descripciones_ingesta']:
            self.assertLess(names.index(name),names.index('preparar_carga_inicial'))


if __name__=='__main__':unittest.main()
