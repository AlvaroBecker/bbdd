from collections import Counter
import json
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET
import perfilar_tipos_datos_proyecto as p


class ProfileAllTests(unittest.TestCase):
    def stat(self,*values):
        s=p.fresh()
        for value in values:p.observe(s,value)
        return s

    def test_numeric_identifiers_preserve_leading_zero_text(self):
        for name in ['ubigeo','partida','codigo','ruc','id','zona_utm']:
            proposal,_=p.recommend(name,self.stat('050101','50101'))
            self.assertEqual(proposal,'MANTENER_TEXT_IDENTIFICADOR_O_ETIQUETA')

    def test_magnitude_and_code_like_area_are_not_conflated(self):
        self.assertEqual(p.recommend('area_ha',self.stat('0.125','12.5'))[0],'CANDIDATO_DOUBLE')
        self.assertEqual(p.recommend('area',self.stat('1','2'))[0],'REVISAR_NUMERICO_SIN_SEMANTICA')
        self.assertEqual(p.recommend('este',self.stat('543596.43'))[0],'CANDIDATO_DOUBLE')
        self.assertEqual(p.recommend('car_hid_y',self.stat('0','56'))[0],'REVISAR_NUMERICO_SIN_SEMANTICA')
        self.assertEqual(p.recommend('near_y',self.stat('543596.43'))[0],'CANDIDATO_DOUBLE')

    def test_html_header_is_not_an_attribute_but_mapped_field_is_preserved(self):
        elem=ET.fromstring('<Placemark><description>&lt;table&gt;&lt;tr&gt;&lt;td&gt;Field Name&lt;/td&gt;&lt;td&gt;Field Value&lt;/td&gt;&lt;/tr&gt;&lt;/table&gt;</description></Placemark>')
        self.assertEqual(p.raw_attributes(elem,{}),[])
        self.assertEqual(p.raw_attributes(elem,{'field_name':'field_name'}),[('Field Name','Field Value')])

    def test_mixed_dates_are_not_converted_automatically(self):
        self.assertEqual(p.recommend('fecleg',self.stat('10/23/2020','23/10/2020'))[0],'REVISAR_FECHA')
        self.assertEqual(p.recommend('acp_fecad',self.stat('2020-01-02','Perpetuo'))[0],'REVISAR_FECHA')

    def test_numeric_limits_do_not_force_unsafe_types(self):
        self.assertEqual(p.recommend('poblacion',self.stat('0','2000'))[0],'CANDIDATO_LONG')
        self.assertNotEqual(p.recommend('poblacion',self.stat('2147483648'))[0],'CANDIDATO_LONG')
        self.assertNotEqual(p.recommend('este',self.stat('1234567890123456'))[0],'CANDIDATO_DOUBLE')
        self.assertNotEqual(p.recommend('este',self.stat('1,234'))[0],'CANDIDATO_DOUBLE')

    def test_wrapping_html_is_not_lost_when_mapped(self):
        elem=ET.fromstring('<Placemark><ExtendedData><Data name="PopupInfo"><value>'
            '&lt;table&gt;&lt;tr&gt;&lt;td&gt;Este&lt;/td&gt;&lt;td&gt;1&lt;/td&gt;&lt;/tr&gt;&lt;/table&gt;'
            '</value></Data></ExtendedData></Placemark>')
        pairs=p.raw_attributes(elem,{'popup_info':'popup_info','este':'este'})
        self.assertIn(('Este','1'),pairs)
        self.assertEqual(next(v for k,v in pairs if k=='PopupInfo'),'<table><tr><td>Este</td><td>1</td></tr></table>')

    def test_lengths_measure_full_values_and_utf16(self):
        s=self.stat('A'*5000+'\U0001f600')
        self.assertEqual(s['max_length'],5001)
        self.assertEqual(s['max_utf16'],5002)
        self.assertLessEqual(len(s['samples'][0]),250)

    def test_real_outputs_balance_scope_without_changes(self):
        report=json.loads((p.ROOT/'02_entregas/Revision_Tipos_Datos_Proyecto/resultado.json').read_text(encoding='utf-8'))
        self.assertEqual(report['definiciones_perfiladas'],2185)
        self.assertEqual(sum(report['propuestas'].values()),2185)
        self.assertFalse(report['cambios_en_sde'])
        self.assertFalse(report['cambios_en_modelo'])
        self.assertEqual(report['rutas_con_diferencias'],0)
        self.assertEqual(report['fuentes_ausentes'],[])
        self.assertEqual(len(report['fuentes']),13)
        for source in report['fuentes']:
            self.assertEqual(source['sha256'],p.digest(Path(source['ruta_lectura'])))


if __name__=='__main__':
    unittest.main()
