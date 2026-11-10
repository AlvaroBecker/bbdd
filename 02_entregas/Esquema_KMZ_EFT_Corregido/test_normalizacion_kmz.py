import csv
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import datos_proyecto as runner
from normalizacion_kmz import destination, merge_values, normalize_record, snake_case, spelling_index, SQLSERVER_RESERVED

HERE = Path(__file__).resolve().parent


class NormalizationTests(unittest.TestCase):
    def test_count_rejected_by_real_sde_preserves_attribute_and_mapping(self):
        for original in ['COUNT', 'count', 'Count']:
            row=dict(campo=original, campo_normalizado='COUNT')
            name,rule,_=destination(row, {}, 'zonas_vida_holdridge_recorte', {}, {})
            self.assertEqual(name, 'src_count')
            self.assertEqual(rule, 'NOMBRE_RECHAZADO_ARCGIS_SDE')
        model=json.loads((HERE/'esquema.json').read_text(encoding='utf-8'))
        self.assertFalse(any(f['nombre']=='count' for c in model['clases'] for f in c['campos']))
        cls=next(c for c in model['clases'] if c['nombre']=='zonas_vida_holdridge_recorte')
        field=next(f for f in cls['campos'] if f['nombre']=='src_count')
        self.assertEqual(field['campo_fuente'],'COUNT')

    def test_reserved_sql_names_keep_source_attribute_under_safe_name(self):
        for word in SQLSERVER_RESERVED:
            row = dict(campo=word.lower(), campo_normalizado=word)
            name, rule, _ = destination(row, {}, 'example', {}, {})
            self.assertEqual(name, 'src_' + word.lower())
            self.assertEqual(rule, 'PALABRA_RESERVADA_SQLSERVER')

    def test_reserved_word_as_substring_does_not_rename_valid_field(self):
        row = dict(campo='beginDate', campo_normalizado='BEGINDATE')
        self.assertEqual(destination(row, {}, 'example', {}, {})[0], 'begin_date')

    def test_all_generated_names_avoid_current_sql_reserved_keywords(self):
        model=json.loads((HERE/'esquema.json').read_text(encoding='utf-8'))
        self.assertFalse({c['nombre'].upper() for c in model['clases']} & SQLSERVER_RESERVED)
        self.assertFalse({f['nombre'].upper() for c in model['clases'] for f in c['campos']} & SQLSERVER_RESERVED)
        c=next(c for c in model['clases'] if c['nombre']=='mline_td_proyecto_infraestructura')
        self.assertTrue({'src_begin','src_end'} <= {f['nombre'] for f in c['campos']})
        self.assertEqual(next(f for f in c['campos'] if f['nombre']=='src_begin')['campo_fuente'],'BEGIN')

    def test_destination_validation_reports_all_bad_names_without_writing(self):
        a=SimpleNamespace(ValidateFieldName=Mock(side_effect=lambda n,w: n+'_' if n in {'begin','end'} else n),
                          ValidateTableName=Mock(side_effect=lambda n,w: n))
        classes=[{'nombre':n,'campos':[{'nombre':f} for f in ['begin','end','proyecto']]} for n in ['uno','dos']]
        with self.assertRaises(ValueError) as error:
            runner.engine.validate_names(a, 'fixture.sde', classes)
        for expected in ['uno.begin','uno.end','dos.begin','dos.end']:
            self.assertIn(expected,str(error.exception))
        self.assertEqual(a.ValidateFieldName.call_count,3)

    def test_snake_case_preserves_words_and_removes_accents(self):
        for original, expected in [('CodigoEnti','codigo_enti'),('CodVertice','cod_vertice'),
                ('ÁREA inscrita (ha)','area_inscrita_ha'),('Lat,\u00a0Lon','lat_lon'),
                ('OBSERVACIONES','observaciones'),('___A__B','a_b')]:
            self.assertEqual(snake_case(original), expected)
        self.assertTrue(snake_case('123').startswith('atrib_'))
        self.assertLessEqual(len(snake_case('campo_'*30)),55)
        self.assertNotEqual(snake_case('campo_'*30+'uno'),snake_case('campo_'*30+'dos'))

    def test_spelling_uses_original_camel_case_and_is_order_independent(self):
        rows=[dict(campo_normalizado='CODVERTICE',campo=n) for n in ['CODVERTICE','CodVertice']]
        self.assertEqual(spelling_index(rows)['CODVERTICE'],'cod_vertice')
        self.assertEqual(spelling_index(rows),spelling_index(list(reversed(rows))))

    def test_partial_name_match_does_not_merge(self):
        row=dict(campo='Nombre',campo_normalizado='NOMBRE',es_campo_del_nombre='sí')
        core={'nombre':{'origen':'EFT 5.8.7'}}
        self.assertEqual(destination(row,{'nombre_viene_del_campo':'Nombre (16%)'},'estructuras',core,{'NOMBRE':'nombre'})[0],'src_nombre')
        self.assertEqual(destination(row,{'nombre_viene_del_campo':'Nombre (100%)'},'estructuras',core,{'NOMBRE':'nombre'})[0],'nombre')
        self.assertEqual(destination(row,{'nombre_viene_del_campo':'CodVertice (100%)'},'estructuras',core,{'NOMBRE':'nombre'})[0],'src_nombre')

    def test_equivalences_use_eft_targets_and_ddl(self):
        for source,target in [('ALTERNATIV','alternativa'),('ALTERNATIVA','alternativa'),('OBSERVACIO','observaciones'),('TENSION_NO','tension_nominal_kv'),('CODIGOU','id_origen')]:
            row=dict(campo=source,campo_normalizado=source)
            core={n:{'origen':'EFT 5.8.7'} for n in ['alternativa','id_origen']}
            self.assertEqual(destination(row,{},'ejemplo_recorte',core,{})[0],target)
        row=dict(campo='TENSION_NO',campo_normalizado='TENSION_NO')
        self.assertEqual(destination(row,{},'mline_td_proyecto_ltransmision',{},{} )[0],'me_nivel_tension')

    def test_conflicting_values_stop_without_mutating_input(self):
        initial={'nombre':'Punto 1'}
        with self.assertRaisesRegex(ValueError,'Valores diferentes'):
            merge_values([('nombre','Nombre de linea')],initial)
        self.assertEqual(initial,{'nombre':'Punto 1'})
        with self.assertRaises(ValueError):merge_values([('x',0),('x','0')])
        self.assertEqual(merge_values([('x',None),('x',0),('x','')]),{'x':0})
        self.assertEqual(merge_values([('x','<Null>')]),{'x':'<Null>'})

    def test_record_mapping_rejects_unknown_fields_and_different_routes(self):
        mappings=[dict(archivo='a',ruta='ruta',campo_original=n,campo_destino='alternativa',estado='MAPEADO') for n in ['Alternativ','Alternativa']]
        self.assertEqual(normalize_record([('Alternativ','A1'),('Alternativa','A1')],mappings),{'alternativa':'A1'})
        with self.assertRaises(ValueError):normalize_record([('Alternativ','A1'),('Alternativa','A2')],mappings)
        with self.assertRaises(ValueError):normalize_record([('Campo no previsto','x')],mappings)
        mappings[1]['ruta']='otra'
        with self.assertRaisesRegex(ValueError,'una sola ruta'):normalize_record([],mappings)

    def test_all_inventory_rows_and_structures_evidence(self):
        with (HERE/'campos_por_ruta.csv').open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f,delimiter=';'))
        self.assertEqual(len(rows),9934)
        structures=[r for r in rows if r['clase_destino']=='estructuras']
        self.assertTrue(all(r['campo_destino']=='alternativa' for r in structures if r['campo_fuente'] in ['ALTERNATIV','ALTERNATIVA']))
        palian=[r for r in structures if 'PALIAN' in r['archivo'] and r['campo_fuente']=='NOMBRE']
        self.assertTrue(palian)
        self.assertTrue(all(r['campo_destino']=='src_nombre' for r in palian))
        torre=[r for r in structures if r['campo_fuente']=='TORRE']
        self.assertTrue(torre)
        self.assertTrue(all(r['campo_destino']=='torre' and '(16%)' in r['evidencia_nombre'] for r in torre))

    def test_existing_uppercase_column_is_not_silently_accepted(self):
        model=json.loads((HERE/'esquema.json').read_text(encoding='utf-8'))
        c=next(c for c in model['clases'] if c['nombre']=='estructuras')
        fields=[SimpleNamespace(name=f['nombre']) for f in c['campos']]
        next(f for f in fields if f.name=='tipo').name='TIPO'
        with self.assertRaisesRegex(ValueError,'sin normalizar'):runner.validate_existing_names(fields,c)


if __name__=='__main__':unittest.main()
