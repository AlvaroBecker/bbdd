"""Casos de procedencia y cobertura del lector KMZ, sin ArcGIS."""
import csv
from pathlib import Path
import tempfile
import unittest
import zipfile

import inspeccion_kmz as subject


def kml(body, name='D'):
    return f'<kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>{name}</name>{body}</Document></kml>'


def pm(body='', geom='<Point><coordinates>0,0</coordinates></Point>'):
    return '<Placemark>' + body + geom + '</Placemark>'


def schema(typ='double', name='x', sid='s'):
    return f'<Schema id="{sid}"><SimpleField name="{name}" type="{typ}"/></Schema>'


def simple(value, name='x', url='#s'):
    return f'<ExtendedData><SchemaData schemaUrl="{url}"><SimpleData name="{name}">{value}</SimpleData></SchemaData></ExtendedData>'


def html(*pairs):
    return '<description><![CDATA[<table>' + ''.join(f'<tr><td>{name}</td><td>{value}</td></tr>' for name, value in pairs) + '</table>]]></description>'


# Fragmento real de G1 LT 220 kV Muyurina - Mollepata, doc.kml.
# Solo se abrevia el espacio entre etiquetas: el JS ya era texto plano,
# no un nodo script. El titulo no sustituye al contenido completo de la celda.
REAL_NESTED_POPUP = """<html><body><table border="1">
<tr><th>Field Name</th><th>Field Value</th></tr>
<tr><td>description</td><td>
<table style='font-family:Arial,Verdana,Times;font-size:12px;text-align:left;width:100%;border-collapse:collapse;padding:3px 3px 3px 3px'>
<tr style='text-align:center;font-weight:bold;background:#9CBCE2'><td>Electro Centro</td></tr>
<tr><td><table style='font-family:Arial,Verdana,Times;font-size:12px;text-align:left;width:100%;border-spacing:0px; padding:3px 3px 3px 3px'>
<tr><td>EMPRESA</td><td>Electro Centro</td></tr>
<tr><td>CODIGO</td><td>9277972</td></tr>
<tr><td>ETIQUETA SED</td><td>E401233</td></tr>
<tr><td>FECHA DE PUESTA EN SERVICIO</td><td>10/02/2005</td></tr>
<tr><td>CÓDIGO DE SISTEMA ELÉCTRICO</td><td>SE0060</td></tr>
<tr><td>NOMBRE SISTEMA ELÉCTRICO</td><td>Ayacucho</td></tr>
<tr><td>SHAPE</td><td>Point</td></tr>
</table></td></tr></table>
function changeImage(attElement, nameElement) {
document.getElementById('imageAttachment').src = attElement;
document.getElementById('imageName').innerHTML = nameElement;}
</td></tr></table></body></html>"""


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sources = self.root/'sources'
        self.model = self.root/'model'
        self.sources.mkdir()
        self.model.mkdir()

    def source(self, content, filename='source.kmz', members=None):
        path = self.sources/filename
        path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, 'w') as archive:
            for name, text in (members or {'doc.kml':content}).items():
                archive.writestr(name, text)
        return path

    def inventory(self, routes=None, fields=None):
        routes = routes if routes is not None else [('D','Punto',1,'target')]
        with (self.model/'mapeo_capas_revision.csv').open('w',encoding='utf-8',newline='') as stream:
            writer = csv.DictWriter(stream, ['archivo','ruta','geometria','elementos','clase_propuesta'], delimiter=';')
            writer.writeheader()
            for route, geom, count, dest in routes:
                writer.writerow(dict(archivo='source.kmz',ruta=route,geometria=geom,elementos=count,clase_propuesta=dest))
        fields = fields if fields is not None else [('D','Punto','x','target','x','NOMBRE_NORMALIZADO')]
        with (self.model/'campos_por_ruta.csv').open('w',encoding='utf-8',newline='') as stream:
            writer = csv.DictWriter(stream, ['archivo','ruta','geometria','campo_original','clase_destino','campo_destino','regla'], delimiter=';')
            writer.writeheader()
            for route, geom, original, dest, field, rule in fields:
                writer.writerow(dict(archivo='source.kmz',ruta=route,geometria=geom,campo_original=original,clase_destino=dest,campo_destino=field,regla=rule))

    def run_collect(self, **kwargs):
        return subject.collect(self.sources, self.model, emit=lambda _:None, **kwargs)

    def test_schema_after_feature_resolves_without_changing_source(self):
        path = self.source(kml(pm(simple('1.5'))+schema()))
        raw, stamp = path.read_bytes(), path.stat().st_mtime_ns
        self.inventory()
        report = self.run_collect()
        field = report['campos_destino'][0]
        self.assertEqual(report['estado'],'LECTURA_COMPLETA')
        self.assertEqual(field['tipos_declarados'],{'double':1})
        self.assertEqual(field['minimo'],'1.5')
        self.assertEqual(field['valores_sin_tipo'],0)
        self.assertEqual((path.read_bytes(),path.stat().st_mtime_ns),(raw,stamp))

    def test_html_does_not_inherit_schema_by_equal_name(self):
        self.source(kml(schema()+pm(html(('x','8')))))
        self.inventory()
        field = self.run_collect()['campos_destino'][0]
        self.assertEqual(field['tipos_declarados'],{})
        self.assertEqual(field['valores_sin_tipo'],1)

    def test_equal_html_copy_preserves_typed_value_and_provenance(self):
        self.source(kml(schema()+pm(simple('8')+html(('x','8')))))
        self.inventory()
        report = self.run_collect()
        field = report['campos_destino'][0]
        self.assertEqual(field['tipos_declarados'],{'double':1})
        self.assertEqual(field['copias_sin_tipo'],1)
        self.assertEqual(field['conflictos'],0)
        self.assertEqual(len([x for x in report['campos_fuente'] if x['campo_original']=='x']),2)

    def test_different_repeated_html_values_are_preserved_and_conflicting(self):
        self.source(kml(pm(html(('office','A'),('office','B')))))
        self.inventory(fields=[('D','Punto','office','target','office','NOMBRE_NORMALIZADO')])
        report = self.run_collect()
        field = report['campos_destino'][0]
        self.assertEqual(field['conflictos'],1)
        self.assertEqual(field['otros_textos'],2)
        self.assertEqual([x['ocurrencia'] for x in report['campos_fuente'] if x['campo_original']=='office'],[1,2])

    def test_schema_ids_are_scoped_to_kml_member(self):
        self.source('',members={'a.kml':kml(schema('int')+pm(simple('5')),'A'),
                                'b.kml':kml(pm(simple('5')),'B')})
        self.inventory(routes=[('A','Punto',1,'target'),('B','Punto',1,'target')],
            fields=[('A','Punto','x','target','x','NOMBRE_NORMALIZADO'),('B','Punto','x','target','x','NOMBRE_NORMALIZADO')])
        report = self.run_collect()
        field = report['campos_destino'][0]
        self.assertEqual(field['tipos_declarados'],{'int':1})
        self.assertEqual(field['valores_sin_tipo'],1)
        self.assertIn('SCHEMA_NO_RESUELTO',{x['codigo'] for x in report['incidencias']})

    def test_explicit_internal_member_ref_resolves_but_external_url_does_not(self):
        self.source('',members={'schemas.kml':kml(schema('int')),
            'doc.kml':kml(pm(simple('5',url='schemas.kml#s'))+pm(simple('7',url='https://invalid.example/s#s')))})
        self.inventory(routes=[('D','Punto',2,'target')])
        field = self.run_collect()['campos_destino'][0]
        self.assertEqual(field['tipos_declarados'],{'int':1})
        self.assertEqual(field['valores_sin_tipo'],1)

    def test_duplicate_schema_id_is_not_chosen(self):
        self.source(kml(schema('int')+schema('string')+pm(simple('1'))))
        self.inventory()
        report = self.run_collect()
        self.assertEqual(report['campos_destino'][0]['tipos_declarados'],{})
        self.assertIn('SCHEMA_ID_DUPLICADO',{x['codigo'] for x in report['incidencias']})

    def test_duplicate_kmz_filename_rejected(self):
        self.source(kml(pm(simple('1'))))
        self.source(kml(pm(simple('1'))),'other/source.kmz')
        self.inventory()
        with self.assertRaisesRegex(ValueError,'ambiguas'):
            self.run_collect()

    def test_missing_kmz_reports_incomplete_not_zero_success(self):
        self.inventory()
        report = self.run_collect()
        self.assertEqual(report['estado'],'LECTURA_INCOMPLETA')
        self.assertEqual(report['fuentes_ausentes'],['source.kmz'])
        self.assertEqual(report['campos_destino'][0]['cobertura'],'INCOMPLETA')

    def test_all_geometry_groups_and_unmapped_attributes_are_profiled(self):
        fixtures = [('Punto','<Point/>'),('Línea','<LineString/>'),('Polígono','<Polygon/>'),
                    ('Modelo3D','<Model/>'),('Mixta','<MultiGeometry><Point/><LineString/></MultiGeometry>'),
                    ('Sin geometría','')]
        self.source(kml(''.join(pm('<ExtendedData><Data name="x"><value>7</value></Data></ExtendedData>',geo) for _,geo in fixtures)))
        self.inventory(routes=[('D',label,1,'') for label,_ in fixtures],fields=[])
        report = self.run_collect()
        self.assertEqual(report['estado'],'LECTURA_COMPLETA')
        self.assertEqual(report['conteos']['elementos_observados'],6)
        self.assertEqual(len(report['campos_fuente']),6)
        self.assertEqual(report['campos_destino'],[])

    def test_standalone_ring_combined_with_point_or_line_is_mixed(self):
        for primary in ('<Point/>','<LineString/>'):
            self.assertEqual(subject.geometry(subject.ET.fromstring(pm(geom='<MultiGeometry>'+primary+'<LinearRing/></MultiGeometry>'))),'Mixta')
        self.assertEqual(subject.geometry(subject.ET.fromstring(pm(geom='<Polygon><outerBoundaryIs><LinearRing/></outerBoundaryIs></Polygon>'))),'Polígono')

    def test_html_container_name_uses_visible_label_without_following_link(self):
        label = '&lt;a href="file:///nonexistent/private/Conexion.xyz"&gt;Conexion 2218_2219&lt;/a&gt;'
        self.source(kml('<Folder><name>'+label+'</name>'+pm(simple('2'))+'</Folder>'+schema()))
        self.inventory(routes=[('D / Conexion 2218_2219','Punto',1,'target')],
            fields=[('D / Conexion 2218_2219','Punto','x','target','x','NOMBRE_NORMALIZADO')])
        report = self.run_collect()
        self.assertEqual(report['estado'],'LECTURA_COMPLETA')
        self.assertEqual(report['rutas'][0]['ruta'],'D / Conexion 2218_2219')

    def test_repeated_named_folders_aggregate_expected_route(self):
        self.source(kml('<Folder><name>F</name>'+pm(simple('1'))+'</Folder><Folder><name>F</name>'+pm(simple('2'))+'</Folder>'+schema()))
        self.inventory(routes=[('D / F','Punto',2,'target')],fields=[('D / F','Punto','x','target','x','NOMBRE_NORMALIZADO')])
        report = self.run_collect()
        self.assertEqual(report['estado'],'LECTURA_COMPLETA')
        self.assertEqual(report['campos_destino'][0]['registros'],2)

    def test_unknown_route_is_not_silently_ignored(self):
        self.source(kml(pm(simple('1'))+'<Folder><name>F</name>'+pm(simple('2'))+'</Folder>'+schema()))
        self.inventory()
        report = self.run_collect()
        self.assertEqual(report['estado'],'LECTURA_INCOMPLETA')
        self.assertEqual(report['conteos']['elementos_observados'],2)
        self.assertEqual(len(report['rutas_no_inventariadas']),1)

    def test_mapping_normalization_collision_rejected(self):
        self.source(kml(pm(html(('X','1')))))
        self.inventory(fields=[('D','Punto','X','target','x','NOMBRE_NORMALIZADO'),
                               ('D','Punto','x','target','other','NOMBRE_NORMALIZADO')])
        with self.assertRaisesRegex(ValueError,'ambiguo'):
            self.run_collect()

    def test_source_values_observed_callback_and_numbers_preserve_representation(self):
        self.source(kml(pm(html(('x','001'),('y','-99.000'),('z','')))))
        self.inventory()
        def callback(stats,value,declared=None):
            stats.setdefault('validacion_valores',{})['conteo'] = stats.get('validacion_valores',{}).get('conteo',0)+1
        report = self.run_collect(value_observer=callback)
        field = report['campos_destino'][0]
        self.assertEqual(field['leading_zeros'],1)
        self.assertEqual(field['ejemplos'],['001'])
        self.assertEqual(field['validacion_valores']['conteo'],1)
        y = next(x for x in report['campos_fuente'] if x['campo_original']=='y')
        self.assertEqual(y['minimo'],'-99.000')
        self.assertEqual(y['marcadores'],{})

    def test_observer_receives_only_declaration_of_its_own_value(self):
        self.source(kml(schema('int')+pm(simple('1')+html(('x','text')))))
        self.inventory()
        def callback(stats,value,declared=None):
            bucket = stats.setdefault('por_tipo',{}).setdefault(declared or 'SIN_TIPO',[])
            bucket.append(value)
        report = self.run_collect(value_observer=callback)
        field = report['campos_destino'][0]
        self.assertEqual(field['por_tipo'],{'int':['1'],'SIN_TIPO':['text']})
        typed = next(r for r in report['campos_fuente'] if r['campo_original']=='x' and r['canal']=='SimpleData')
        self.assertEqual(typed['por_tipo'],{'int':['1']})

    def test_html_wrapper_is_profiled_as_container_not_unmapped_user_field(self):
        self.source(kml(pm(html(('x','1')))))
        self.inventory()
        report = self.run_collect()
        container = next(r for r in report['campos_fuente'] if r['campo_original']=='description')
        self.assertEqual(container['contenedores_presentacion'],1)
        self.assertTrue(any(r['codigo']=='CONTENEDOR_XML_SIN_DESTINO' and r['detalle']=='description' for r in report['incidencias']))
        self.assertFalse(any(r['codigo']=='ATRIBUTO_SIN_MAPEO' and r['detalle']=='description' for r in report['incidencias']))

    def test_real_nested_popup_keeps_inner_text_and_literal_javascript(self):
        parser = subject.Pairs()
        parser.feed(REAL_NESTED_POPUP)
        parser.close()
        pairs = dict(parser.pairs)
        self.assertEqual(pairs['EMPRESA'], 'Electro Centro')
        self.assertEqual(pairs['CODIGO'], '9277972')
        self.assertEqual(pairs['FECHA DE PUESTA EN SERVICIO'], '10/02/2005')
        value = pairs['description']
        for token in ('Electro Centro', 'EMPRESA', '9277972', 'Ayacucho', 'function changeImage'):
            self.assertIn(token, value)
        self.assertNotEqual(value, 'Electro Centro')
        self.assertNotIn('<table', value)
        self.source(kml(pm('<description><![CDATA[' + REAL_NESTED_POPUP + ']]></description>')))
        self.inventory(fields=[('D','Punto','description','target','description','NOMBRE_NORMALIZADO')])
        report = self.run_collect()
        field = report['campos_destino'][0]
        self.assertEqual(report['estado'], 'LECTURA_COMPLETA')
        self.assertEqual(field['conflictos'], 0)
        self.assertEqual(field['valores_utiles'], 1)
        self.assertEqual(field['max_utf16'], len(value.encode('utf-16-le')) // 2)
        wrapper = next(x for x in report['campos_fuente'] if x['canal']=='description')
        self.assertEqual(wrapper['campo_destino'], '')
        self.assertEqual(wrapper['registros_mapeados'], 0)
        self.assertEqual(wrapper['registros_solo_evidencia'], 1)
        self.assertEqual(wrapper['max_utf16'], len(REAL_NESTED_POPUP.encode('utf-16-le')) // 2)

    def test_html_ignores_only_real_script_style_and_keeps_inline_text(self):
        parser = subject.Pairs()
        parser.feed('<table><tr><td><b>x</b></td><td><style>.a {color:red}</style>'
                    '<script>function hidden() {}</script><b>Visible</b><br>'
                    '<a href="https://invalid.example">link</a> function literal() {}</td></tr></table>')
        parser.close()
        self.assertEqual(parser.pairs, [('x','Visible\nlink function literal() {}')])

    def test_html_omitted_cell_and_row_closures_do_not_drop_repeated_values(self):
        parser = subject.Pairs()
        parser.feed('<table><tr><td>x<td>one<tr><td>x<td>two</table>')
        parser.close()
        self.assertEqual(parser.pairs, [('x','one'), ('x','two')])

    def test_explicit_named_xml_html_field_still_maps_its_original_value(self):
        value = '<table><tr><td>x</td><td>1</td></tr></table>'
        self.source(kml(pm('<ExtendedData><Data name="popup"><value><![CDATA['+value+']]></value></Data></ExtendedData>')))
        self.inventory(fields=[('D','Punto','popup','target','popup','NOMBRE_NORMALIZADO')])
        report = self.run_collect()
        field = report['campos_destino'][0]
        self.assertEqual(field['ejemplos'], [value])
        raw = next(x for x in report['campos_fuente'] if x['campo_original']=='popup')
        self.assertEqual(raw['campo_destino'], 'popup')
        self.assertEqual(raw['registros_mapeados'], 1)

    def test_mixed_native_descriptions_count_only_plain_values_as_mapped(self):
        self.source(kml(pm('<description>Plain</description>')+pm(html(('description','Inner')))))
        self.inventory(routes=[('D','Punto',2,'target')],
            fields=[('D','Punto','description','target','description','NOMBRE_NORMALIZADO')])
        report = self.run_collect()
        field = report['campos_destino'][0]
        self.assertEqual(field['ejemplos'], ['Plain','Inner'])
        self.assertEqual(field['conflictos'], 0)
        raw = next(x for x in report['campos_fuente'] if x['canal']=='description')
        self.assertEqual(raw['registros'], 2)
        self.assertEqual(raw['registros_mapeados'], 1)
        self.assertEqual(raw['registros_solo_evidencia'], 1)
        self.assertEqual(raw['campo_destino'], 'description')

    def test_native_wrapper_does_not_satisfy_missing_business_description(self):
        self.source(kml(pm(html(('x','1')))))
        self.inventory(fields=[('D','Punto','description','target','description','NOMBRE_NORMALIZADO')])
        report = self.run_collect()
        self.assertEqual(report['estado'], 'LECTURA_INCOMPLETA')
        self.assertEqual(report['conteos']['vinculos_campos_sin_observar'], 1)
        self.assertEqual(report['campos_destino'][0]['registros'], 0)

    def test_progress_emits_source_start_and_completion(self):
        self.source(kml(pm(simple('1'))+schema()))
        self.inventory()
        lines = []
        subject.collect(self.sources,self.model,emit=lines.append)
        self.assertTrue(lines[0].startswith('LEYENDO KMZ: source.kmz'))
        self.assertTrue(lines[-1].startswith('KMZ LEIDO: source.kmz'))

    def test_native_name_fallback_requires_approved_mapping_rule(self):
        self.source(kml(pm('<name>Native</name>')))
        self.inventory(fields=[('D','Punto','Nombre','target','nombre','NOMBRE_KML_100')])
        field = self.run_collect()['campos_destino'][0]
        self.assertEqual(field['ejemplos'],['Native'])
        self.assertEqual(field['tipos_declarados'],{'string':1})

    def test_two_schema_fields_to_one_destination_keep_conflicting_values(self):
        self.source(kml(schema('int','x','s')+schema('string','y','t')+pm(simple('1')+simple('2','y','#t'))))
        self.inventory(fields=[('D','Punto','x','target','x','ALIAS'),('D','Punto','y','target','x','ALIAS')])
        field = self.run_collect()['campos_destino'][0]
        self.assertEqual(field['tipos_declarados'],{'int':1,'string':1})
        self.assertEqual(field['conflictos'],1)

    def test_missing_attribute_in_one_route_cannot_inherit_type_from_another(self):
        self.source(kml(schema('int')+'<Folder><name>A</name>'+pm(simple('1'))+'</Folder>'
            +'<Folder><name>B</name>'+pm('')+'</Folder>'))
        self.inventory(routes=[('D / A','Punto',1,'target'),('D / B','Punto',1,'target')],
            fields=[('D / A','Punto','x','target','x','NOMBRE_NORMALIZADO'),
                    ('D / B','Punto','x','target','x','NOMBRE_NORMALIZADO')])
        report = self.run_collect()
        self.assertEqual(report['conteos']['rutas_coincidentes'],2)
        self.assertEqual(report['conteos']['vinculos_campos_sin_observar'],1)
        self.assertEqual(report['estado'],'LECTURA_INCOMPLETA')
        field = report['campos_destino'][0]
        self.assertEqual(field['cobertura'],'INCOMPLETA')
        self.assertEqual(field['vinculos_sin_observar'][0]['ruta'],'D / B')
        self.assertIn('ATRIBUTO_ESPERADO_NO_OBSERVADO',{row['codigo'] for row in report['incidencias']})

    def test_observed_empty_attribute_is_not_missing_and_not_required_on_every_feature(self):
        self.source(kml(pm(simple(''))+pm('')+schema('int')))
        self.inventory(routes=[('D','Punto',2,'target')])
        report = self.run_collect()
        self.assertEqual(report['estado'],'LECTURA_COMPLETA')
        self.assertEqual(report['conteos']['vinculos_campos_sin_observar'],0)
        field = report['campos_destino'][0]
        self.assertEqual(field['registros'],1)
        self.assertEqual(field['vacios'],1)
        self.assertEqual(field['cobertura'],'COMPLETA_RUTAS_DEL_CAMPO')


if __name__ == '__main__':
    unittest.main()
