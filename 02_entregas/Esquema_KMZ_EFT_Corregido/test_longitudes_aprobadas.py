import copy
import json
from pathlib import Path
import unittest
import datos_proyecto as runner


class ApprovedLengthTests(unittest.TestCase):
    def setUp(self):
        self.model=json.loads((Path(__file__).parent/'esquema.json').read_text(encoding='utf-8'))

    def field(self,model):
        cls=next(c for c in model['clases'] if c['nombre']=='predios_inscritos_sunarp_recorte')
        return next(f for f in cls['campos'] if f['nombre']=='cargas_y_gravamenes')

    def test_only_approved_field_and_legacy_length_are_accepted(self):
        self.assertEqual(self.field(self.model)['longitud'],10000)
        runner.scoped_model(self.model,['predios_inscritos_sunarp_recorte'])
        old=copy.deepcopy(self.model);self.field(old)['longitud']=4000
        runner.scoped_model(old,['predios_inscritos_sunarp_recorte'])

    def test_other_fields_cannot_increase_limit(self):
        c=next(c for c in self.model['clases'] if c['nombre']=='predios_inscritos_sunarp_recorte')
        f=next(f for f in c['campos'] if f['nombre']=='oficina_registral')
        f['longitud']=10000
        with self.assertRaisesRegex(ValueError,'Longitud de texto invalida'):
            runner.scoped_model(self.model,[c['nombre']])

    def test_approved_field_does_not_allow_arbitrary_or_boolean_length(self):
        for length in [10001,8000,True,'10000']:
            model=copy.deepcopy(self.model);self.field(model)['longitud']=length
            with self.subTest(length=length),self.assertRaisesRegex(ValueError,'Longitud de texto invalida'):
                runner.scoped_model(model,['predios_inscritos_sunarp_recorte'])


if __name__=='__main__':unittest.main()
