"""Protege la creacion frente a nombres antiguos y verifica la API de alias."""
import copy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import crear_esquema as engine
import datos_proyecto as runner
import test_actualizar_campos_aprobados as fixtures


class NamingIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.ApprovedFieldsTests(methodName='runTest')
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.args=SimpleNamespace(workspace=self.f.workspace,database='ArcGisAWS',owner='gis',aplicar=False)
        self.model=copy.deepcopy(self.f.source)
        self.model['datasets']=['Datos_Proyecto']
        for cls in self.model['clases']:
            if cls['nombre']=='predios_inscritos_en_sunarp_recorte':
                cls['nombre']='predios_inscritos_sunarp_recorte'

    def test_cli_engine_rejects_legacy_class_before_creation(self):
        with self.assertRaisesRegex(ValueError,'no se crea una clase duplicada'):
            engine.inspect(self.f.a,self.args,self.model,self.model['clases'])
        self.f.a.management.AlterField.assert_not_called()

    def test_toolbox_preflight_rejects_legacy_class_before_creation(self):
        with self.assertRaisesRegex(ValueError,'Normalizar nombres'):
            runner.preflight(self.f.a,self.args,self.model)
        self.f.a.management.AlterField.assert_not_called()

    def test_inventory_only_remains_available_for_renaming(self):
        inventory,_=engine.inspect(self.f.a,self.args,self.model,[])
        self.assertIn('predios_inscritos_en_sunarp_recorte',inventory)
        self.assertNotIn('predios_inscritos_sunarp_recorte',inventory)

    def test_new_class_uses_documented_root_alias_function(self):
        cls=copy.deepcopy(self.f.source['clases'][0])
        cls.update(nombre='predios_inscritos_sunarp_recorte',alias='Predios inscritos en SUNARP - recorte')
        path=self.f.ds+'/predios_inscritos_sunarp_recorte'
        a=SimpleNamespace(Exists=lambda p: True,
            Describe=lambda p: SimpleNamespace(isVersioned=False),
            SpatialReference=lambda code: code,
            AlterAliasName=Mock(),
            management=SimpleNamespace(
                CreateFeatureclass=Mock(return_value=SimpleNamespace(getOutput=lambda i: path)),
                AddFields=Mock(),AddField=Mock(),AddGlobalIDs=Mock(),EnableEditorTracking=Mock()))
        engine.create(a,self.args,{'dominios':{},'datasets':['Datos_Proyecto']},
                      [cls],{'datos_proyecto':self.f.ds},{})
        a.AlterAliasName.assert_called_once_with(path,cls['alias'])
        self.assertFalse(hasattr(a.management,'AlterAliasName'))


if __name__=='__main__':
    unittest.main()
