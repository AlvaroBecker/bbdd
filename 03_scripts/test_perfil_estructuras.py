from collections import Counter
from decimal import Decimal
import json
import unittest
import xml.etree.ElementTree as ET
import perfilar_estructuras_kmz as profiler


class ProfileTests(unittest.TestCase):
    def test_null_markers_are_not_silently_converted_to_zero(self):
        for value in ['<Null>', '<NULL>', 'null']:
            self.assertEqual(profiler.value_kind(value), ('MARCADOR_LITERAL', None))
        self.assertEqual(profiler.value_kind('0'), ('NUMERICO_DECIMAL', Decimal(0)))
        self.assertEqual(profiler.value_kind(' '), ('VACIO', None))

    def test_numeric_conversion_is_conservative_and_does_not_guess_locale(self):
        self.assertEqual(profiler.value_kind('-1.25e2'), ('NUMERICO_DECIMAL', Decimal('-125')))
        for value in ['1,234', '18L', '12 m', '\u221212.5']:
            self.assertEqual(profiler.value_kind(value), ('TEXTO', None))

    def test_nested_html_preserves_empty_fields_and_literal_null(self):
        p=profiler.Pairs()
        p.feed('<table><tr><td><table><tr><td>Fuente</td><td>&lt;Null&gt;</td></tr>'
               '<tr><td>Vertice</td><td></td></tr></table></td></tr></table>')
        self.assertEqual(p.pairs,[('Fuente','<Null>'),('Vertice','')])

    def test_extended_fields_and_popup_are_preserved_without_value_truncation(self):
        long='A'*5001
        pm=ET.fromstring('<Placemark><ExtendedData><Data name="Name"><value>'+long+'</value></Data>'
            '<SchemaData><SimpleData name="Vano">0</SimpleData></SchemaData></ExtendedData>'
            '<description>&lt;table&gt;&lt;tr&gt;&lt;td&gt;Vano&lt;/td&gt;&lt;td&gt;2.5&lt;/td&gt;&lt;/tr&gt;&lt;/table&gt;</description></Placemark>')
        self.assertEqual(profiler.attributes(pm),[('Name',long),('Vano','0'),('Vano','2.5')])

    def test_identifiers_are_kept_text_even_when_all_values_are_numeric(self):
        kinds=Counter(NUMERICO_DECIMAL=100)
        self.assertEqual(profiler.recommendation('name',kinds),'TEXT_CONSERVAR')
        self.assertEqual(profiler.recommendation('codigo_enti',kinds),'TEXT_CONSERVAR')
        self.assertEqual(profiler.recommendation('este',kinds),'DOUBLE_CANDIDATO')
        self.assertEqual(profiler.recommendation('este',Counter(NUMERICO_DECIMAL=100,TEXTO=1)),'TEXT_CONSERVAR')

    def test_real_profile_reconciles_all_current_structures_routes(self):
        r=json.loads((profiler.OUT/'resultado.json').read_text(encoding='utf-8'))
        self.assertEqual(r['registros_observados'],r['registros_esperados'])
        self.assertEqual(r['rutas_con_diferencias'],0)
        self.assertEqual(r['incidencias'],0)
        self.assertEqual(r['campos_revisados'],21)
        self.assertFalse(r['cambios_en_sde'])
        config=json.loads((profiler.ROOT/'03_scripts/tipos_estructuras_aprobados.json').read_text(encoding='utf-8'))
        self.assertEqual(r['esquema_sha256'],config['modelo_base_sha256'])
        self.assertEqual(config['perfil_sha256'],profiler.sha(profiler.OUT/'resultado.json'))
        for source in r['fuentes']:
            self.assertEqual(source['sha256'],profiler.sha(profiler.ROOT/'01_fuentes/kmz'/source['archivo']))


if __name__=='__main__':
    unittest.main()
