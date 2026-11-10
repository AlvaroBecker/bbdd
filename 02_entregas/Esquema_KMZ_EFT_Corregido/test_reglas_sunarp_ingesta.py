"""Pruebas del contrato SUNARP; no usan ArcPy ni modifican fuentes/modelo.

Los 18 pares ponderados de casos_control proceden de los 288 registros reales
de FELAM/PARINAS. Se preservan por separado los 253 pares distintos y 35 iguales.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

import reglas_sunarp_ingesta as sunarp


BASE = Path(__file__).parent


class SunarpRulesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rules = sunarp.load_rules()
        cls.model = json.loads((BASE / 'esquema.json').read_text(encoding='utf-8-sig'))

    def source(self, row):
        sha = next(item['sha256'] for item in self.rules['fuentes']
                   if item['archivo'] == row['archivo'])
        return dict(archivo=row['archivo'], miembro='doc.kml', ruta=row['ruta'],
                    geometria=row['geometria'], sha256=sha)

    def route_rows(self, row):
        return [item for item in self.rules['equivalencias']
                if all(item[key] == row[key] for key in ('archivo', 'ruta', 'geometria'))]

    def attributes(self, rows, values=None):
        values = values or {}
        items = [('name', 'Marcador', None, None, 'XML'),
                 ('description', '<table>...</table>', None, None, 'XML')]
        for row in rows:
            items += [(label, 'contexto', None, None, 'HTML') for label in row['contexto_anterior']]
            value = values.get((row['etiqueta_original'], row['ocurrencia']), 'Valor original')
            items.append((row['etiqueta_original'], value, None, None, 'HTML'))
            items += [(label, 'contexto', None, None, 'HTML') for label in row['contexto_posterior']]
        return items

    def duplicated_route(self):
        row = next(item for item in self.rules['equivalencias'] if item['cambio_de_mapeo'])
        return row, self.route_rows(row)

    def error(self, code, function, *args, **kwargs):
        with self.assertRaises(sunarp.SunarpRuleError) as raised:
            function(*args, **kwargs)
        self.assertEqual(raised.exception.code, code)

    def test_packaged_references_and_schema(self):
        result = sunarp.validate_references(self.rules)
        self.assertEqual(result['estado'], 'REFERENCIAS_SUNARP_VERIFICADAS')
        self.assertEqual(len(result['referencias']), 4)
        self.assertFalse(result['carga_ejecutada'])

    def test_actual_253_different_and_35_equal_pairs_keep_both_roles(self):
        equal = different = total = 0
        compound_preserved = False
        for case in self.rules['casos_control']:
            row = next(item for item in self.rules['equivalencias']
                       if item['archivo'] == case['archivo'] and item['ruta'] == case['ruta'])
            rows = self.route_rows(row)
            for pair in case['pares']:
                values = {('OFICINA REGISTRAL', 1): pair['inmueble'],
                          ('OFICINA REGISTRAL', 2): pair['persona_juridica']}
                for _ in range(pair['registros']):
                    result = sunarp.resolve_record(self.rules, self.source(row), self.attributes(rows, values))
                    self.assertEqual(result['asignaciones'], {
                        'oficina_registral': pair['inmueble'], 'oficina_1': pair['persona_juridica']})
                    self.assertEqual(result['roles'], {'oficina_inmueble': 'oficina_registral',
                                                      'oficina_persona_juridica': 'oficina_1'})
                    self.assertEqual(len(result['indices_consumidos']), 2)
                    self.assertEqual(len(result['trazabilidad']), 2)
                    total += 1
                    if pair['inmueble'] == pair['persona_juridica']:
                        equal += 1
                    else:
                        different += 1
                compound_preserved |= ' / ' in pair['persona_juridica']
        self.assertEqual((total, different, equal), (288, 253, 35))
        self.assertTrue(compound_preserved)

    def test_all_14_unchanged_equivalences_still_use_existing_destination(self):
        checked = 0
        for row in self.rules['equivalencias']:
            if row['cambio_de_mapeo']:
                continue
            result = sunarp.resolve_record(self.rules, self.source(row), self.attributes(self.route_rows(row)))
            trace = next(item for item in result['trazabilidad']
                         if item['etiqueta_original'] == row['etiqueta_original']
                         and item['ocurrencia'] == row['ocurrencia'])
            self.assertEqual(trace['campo_destino'], row['campo_destino_anterior'])
            checked += 1
        self.assertEqual(checked, 14)

    def test_inputs_untouched_and_consumed_indices_allow_other_fields(self):
        row, rows = self.duplicated_route()
        attrs = self.attributes(rows)
        attrs.append(('OTRO_ATRIBUTO', 'Sin cambiar', None, None, 'HTML'))
        old = copy.deepcopy(attrs)
        previous = {'otro_destino': 'Existente'}
        result = sunarp.resolve_record(self.rules, self.source(row), attrs, previous)
        self.assertEqual(attrs, old)
        self.assertEqual(previous, {'otro_destino': 'Existente'})
        self.assertEqual([attrs[i][0] for i in result['indices_consumidos']],
                         ['OFICINA REGISTRAL', 'OFICINA REGISTRAL'])
        self.assertNotIn('otro_destino', result['asignaciones'])

    def test_dictionary_items_and_raw_whitespace_markers_are_preserved(self):
        row, rows = self.duplicated_route()
        values = {('OFICINA REGISTRAL', 1): '  Piura / Lima  ', ('OFICINA REGISTRAL', 2): 'No aplica'}
        attrs = [{'etiqueta': a[0], 'valor': a[1], 'canal': a[4]} for a in self.attributes(rows, values)]
        result = sunarp.resolve_record(self.rules, self.source(row), attrs)
        self.assertEqual(result['asignaciones']['oficina_registral'], '  Piura / Lima  ')
        self.assertEqual(result['asignaciones']['oficina_1'], 'No aplica')

    def test_missing_or_wrong_identity_blocks(self):
        row, rows = self.duplicated_route()
        for key in ('archivo', 'miembro', 'ruta', 'geometria', 'sha256'):
            with self.subTest(key=key):
                source = self.source(row)
                del source[key]
                self.error('IDENTIDAD_INVALIDA', sunarp.resolve_record,
                           self.rules, source, self.attributes(rows))
        for key in ('archivo', 'miembro', 'ruta', 'geometria'):
            with self.subTest(wrong_key=key):
                source = self.source(row)
                source[key] += ' alterado'
                self.error('IDENTIDAD_NO_VERIFICADA', sunarp.resolve_record,
                           self.rules, source, self.attributes(rows))

    def test_source_hash_change_blocks(self):
        row, rows = self.duplicated_route()
        source = self.source(row)
        source['sha256'] = '0' * 64
        self.error('FUENTE_CAMBIO', sunarp.resolve_record, self.rules, source, self.attributes(rows))

    def test_context_change_blocks(self):
        row, rows = self.duplicated_route()
        for offset in (-1, 1):
            attrs = self.attributes(rows)
            index = next(i for i, item in enumerate(attrs) if item[0] == 'OFICINA REGISTRAL')
            item = attrs[index + offset]
            attrs[index + offset] = ('CONTEXTO DISTINTO',) + item[1:]
            self.error('CONTEXTO_CAMBIO', sunarp.resolve_record, self.rules, self.source(row), attrs)

    def test_third_or_missing_occurrence_blocks(self):
        row, rows = self.duplicated_route()
        attrs = self.attributes(rows)
        attrs.append(('OFICINA REGISTRAL', 'Tercero', None, None, 'HTML'))
        self.error('OCURRENCIAS_INVALIDAS', sunarp.resolve_record, self.rules, self.source(row), attrs)
        attrs = self.attributes(rows)
        index = next(i for i, item in enumerate(attrs) if item[0] == 'OFICINA REGISTRAL')
        del attrs[index]
        self.error('OCURRENCIAS_INVALIDAS', sunarp.resolve_record, self.rules, self.source(row), attrs)

    def test_wrong_channel_or_new_office_label_blocks(self):
        row, rows = self.duplicated_route()
        attrs = self.attributes(rows)
        index = next(i for i, item in enumerate(attrs) if item[0] == 'OFICINA REGISTRAL')
        attrs[index] = attrs[index][:-1] + ('Data',)
        self.error('OFICINA_NO_VERIFICADA', sunarp.resolve_record, self.rules, self.source(row), attrs)
        attrs = self.attributes(rows) + [('OFICINA__2', 'Nueva', None, None, 'HTML')]
        self.error('OFICINA_NO_VERIFICADA', sunarp.resolve_record, self.rules, self.source(row), attrs)

    def test_collision_blocks_even_for_equal_or_null_previous_value(self):
        row, rows = self.duplicated_route()
        for previous in ('Valor original', 'Otro valor', None):
            with self.subTest(previous=previous):
                self.error('DESTINO_OCUPADO', sunarp.resolve_record, self.rules, self.source(row),
                           self.attributes(rows), {'oficina_1': previous})

    def test_no_truncation_and_utf16_capacity(self):
        row, rows = self.duplicated_route()
        values = {('OFICINA REGISTRAL', 2): '\U0001f30e' * 2000}
        result = sunarp.resolve_record(self.rules, self.source(row), self.attributes(rows, values))
        self.assertEqual(result['asignaciones']['oficina_1'], values[('OFICINA REGISTRAL', 2)])
        values[('OFICINA REGISTRAL', 2)] += 'a'
        self.error('LONGITUD_EXCEDIDA', sunarp.resolve_record, self.rules, self.source(row),
                   self.attributes(rows, values))

    def test_numeric_values_and_collapsed_attribute_dictionary_block(self):
        row, rows = self.duplicated_route()
        self.error('VALOR_INVALIDO', sunarp.resolve_record, self.rules, self.source(row),
                   self.attributes(rows, {('OFICINA REGISTRAL', 1): 100}))
        self.error('ATRIBUTOS_INVALIDOS', sunarp.resolve_record, self.rules, self.source(row),
                   {'OFICINA REGISTRAL': 'Valor ya colapsado'})

    def test_schema_missing_field_or_changed_type_blocks(self):
        for change in ('delete', 'type', 'length', 'confirmed'):
            model = copy.deepcopy(self.model)
            cls = next(c for c in model['clases'] if c['nombre'] == sunarp.CLASS)
            field = next(f for f in cls['campos'] if f['nombre'] == 'oficina_1')
            if change == 'delete':
                cls['campos'].remove(field)
            elif change == 'type':
                field['tipo'] = 'LONG'
            elif change == 'length':
                field['longitud'] = 29
            else:
                field['tipo_confirmado'] = False
            self.error('ESQUEMA_INVALIDO', sunarp.validate_schema, self.rules, model)

    def test_changed_or_missing_packaged_reference_blocks(self):
        with tempfile.TemporaryDirectory() as folder:
            self.error('REFERENCIA_ILEGIBLE', sunarp.validate_references, self.rules, folder)
            first = self.rules['referencias'][0]['archivo']
            (Path(folder) / first).write_text('alterado', encoding='utf-8')
            self.error('REFERENCIA_CAMBIO', sunarp.validate_references, self.rules, folder)

    def test_changed_mapping_or_duplicate_rule_blocks(self):
        for duplicate in (False, True):
            rules = copy.deepcopy(self.rules)
            if duplicate:
                rules['equivalencias'][1] = copy.deepcopy(rules['equivalencias'][0])
            else:
                rules['equivalencias'][0]['campo_destino_existente'] = 'oficina_1'
            self.error('CONFIG_INVALIDA', sunarp.validate_schema, rules, self.model)

    def test_malformed_configuration_and_model_fail_with_controlled_error(self):
        for key in ('campos_existentes', 'fuentes', 'equivalencias'):
            rules = copy.deepcopy(self.rules)
            rules[key] = None
            self.error('CONFIG_INVALIDA', sunarp.validate_schema, rules, self.model)
        self.error('ESQUEMA_INVALIDO', sunarp.validate_schema, self.rules, {'clases': None})


if __name__ == '__main__':
    unittest.main()
