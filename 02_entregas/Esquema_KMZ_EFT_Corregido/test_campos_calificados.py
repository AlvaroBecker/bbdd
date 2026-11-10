"""Regresiones de lectura de campos SDE; no requiere una conexion real."""
from types import SimpleNamespace
from unittest.mock import Mock
import unittest
import datos_proyecto as runner


class QualifiedFieldTests(unittest.TestCase):
    def field(self, name='ArcGisAWS.GIS.centros_poblados_inei_recorte.area', base='area', **kw):
        values=dict(name=name,baseName=base,type='String',length=4000,isNullable=True,domain='')
        values.update(kw)
        return SimpleNamespace(**values)

    def spec(self, **kw):
        values=dict(nombre='area',tipo='TEXT',longitud=4000,nullable=True,dominio='')
        values.update(kw)
        return values

    def test_qualified_field_passes_all_name_and_type_checks(self):
        fields=[self.field()]
        a=SimpleNamespace(ListFields=Mock(return_value=fields))
        c=dict(nombre='centros_poblados_inei_recorte',campos=[self.spec()])
        runner.engine.validate_fields(a,'fixture.sde/centros',[self.spec()])
        runner.validate_existing_names(fields,c)
        self.assertEqual(runner.unexpected_fields(fields,SimpleNamespace(),c),[])

    def test_real_missing_field_is_not_replaced_by_shape_area(self):
        a=SimpleNamespace(ListFields=Mock(return_value=[self.field(name='Shape_Area',base='Shape_Area',type='Double')]))
        with self.assertRaisesRegex(ValueError,'faltan campos: area') as error:
            runner.engine.validate_fields(a,'fixture',[self.spec()])
        self.assertIn('Shape_Area -> Shape_Area',str(error.exception))

    def test_qualified_uppercase_still_fails_snake_case(self):
        with self.assertRaisesRegex(ValueError,'sin normalizar'):
            runner.validate_existing_names([self.field(base='AREA')],dict(nombre='centros',campos=[self.spec()]))

    def test_qualified_field_type_length_nullability_and_domain_still_checked(self):
        for values,spec,message in [({'type':'Double'}, {}, 'tipo'),
                ({'length':10},{},'longitud'), ({},{'nullable':False},'NOT NULL'),
                ({},{'dominio':'dom_prueba'},'dominio')]:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError,message):
                a=SimpleNamespace(ListFields=lambda p:self.fields)
                self.fields=[self.field(**values)]
                runner.engine.validate_fields(a,'fixture',[self.spec(**spec)])

    def test_duplicate_basename_is_ambiguous(self):
        with self.assertRaisesRegex(ValueError,'ambiguo'):
            runner.engine.field_index([self.field(),self.field(name='otra_tabla.area')])

    def test_qualified_extra_column_is_still_reported(self):
        f=self.field(name='GIS.centros.extra',base='extra')
        self.assertEqual(runner.unexpected_fields([f],SimpleNamespace(),dict(campos=[self.spec()])),[f.name])

    def test_field_without_basename_has_compatible_fallback(self):
        self.assertEqual(runner.engine.field_base_name(SimpleNamespace(name='GIS.centros.area')),'area')
        self.assertEqual(runner.engine.field_base_name(SimpleNamespace(name='area')),'area')


if __name__=='__main__':
    unittest.main()
