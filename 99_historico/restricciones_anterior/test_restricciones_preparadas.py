from pathlib import Path
import ast
import importlib.util
import json
import re
import sys
import types
import unittest

BASE = Path(__file__).resolve().parent / 'ArcGisAWS_Restricciones'
SPEC = importlib.util.spec_from_file_location('mapline_restricciones', BASE / '03_configurar_reglas_arcgis.py')
M = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = M
SPEC.loader.exec_module(M)
INDEX_SPEC = importlib.util.spec_from_file_location('mapline_indices', BASE / '02b_restaurar_indices_arcgis.py')
I = importlib.util.module_from_spec(INDEX_SPEC)
INDEX_SPEC.loader.exec_module(I)
MANIFEST = json.loads((BASE / 'modelo_restricciones.json').read_text(encoding='utf-8'))

class PreparedScripts(unittest.TestCase):
    def setUp(self):
        self.rules = M.build_rule_plan(MANIFEST, {t['name']: 'GlobalID' for t in MANIFEST['tables']})

    def test_scope_and_complete_original_inventory(self):
        self.assertEqual({t['name'] for t in MANIFEST['tables']}, M.EXPECTED_TABLES)
        self.assertEqual(len(MANIFEST['original_indexes']), 27)
        self.assertEqual(len(MANIFEST['relations']), 27)
        self.assertEqual(len(MANIFEST['deferred_incoming_relations']), 4)
        self.assertEqual(sum(len(x) for x in MANIFEST['domain_codes'].values()), 28)

    def test_rule_coverage(self):
        self.assertEqual(len(self.rules), 44)
        counts = {kind: sum(r.kind == kind for r in self.rules) for kind in ('pk', 'fk', 'ref', 'dom', 'old')}
        self.assertEqual(counts, {'pk': 8, 'fk': 11, 'ref': 11, 'dom': 10, 'old': 4})
        self.assertEqual(len({(r.table, r.name) for r in self.rules}), 44)
        for r in self.rules:
            self.assertLessEqual(len(r.name), 64)
            self.assertLessEqual(len(r.message), 256)
            self.assertLessEqual(len(r.description), 256)
            self.assertTrue(set(r.events).issubset({'INSERT', 'UPDATE', 'DELETE'}))

    def test_no_extra_relations_or_cascades(self):
        for r in self.rules:
            self.assertNotIn('NextSequenceValue', r.expression)
            self.assertNotIn('"edit"', r.expression)
            if r.kind in ('fk', 'dom'):
                self.assertIn('IsEmpty', r.expression)
                self.assertIn('return true;', r.expression)
            if r.kind == 'ref':
                self.assertEqual(set(r.events), {'UPDATE', 'DELETE'})
                self.assertIn('$originalFeature', r.expression)

    def test_rule_conflicts_are_not_silently_overwritten(self):
        r = self.rules[0]
        existing = types.SimpleNamespace(type='esriARTConstraint', scriptExpression=r.expression,
            triggeringEvents=';'.join(r.events), isEnabled=True, excludeFromClientEvaluation=True,
            batch=False, triggeringFields=[], subtypeCodes=[], subtypeCode=-1,
            errorNumber=r.error_number, errorMessage=r.message, description=r.description)
        self.assertEqual(M.rules_equivalent(existing, r), [])
        existing.scriptExpression = 'return true;'
        self.assertIn('expression', M.rules_equivalent(existing, r))
        existing.scriptExpression = r.expression
        existing.isEnabled = False
        self.assertIn('enabled', M.rules_equivalent(existing, r))

    def test_no_data_writes_or_versioning_calls(self):
        tree = ast.parse((BASE / '03_configurar_reglas_arcgis.py').read_text(encoding='utf-8'))
        called = {n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        forbidden = {'UpdateCursor', 'InsertCursor', 'DeleteRows', 'CalculateField', 'Delete',
                     'DeleteAttributeRule', 'DeleteDomain', 'RegisterAsVersioned', 'UnregisterAsVersioned'}
        self.assertFalse(called & forbidden)
        self.assertTrue({'AddGlobalIDs', 'CreateDomain', 'AddAttributeRule'}.issubset(called))

    def test_sql_index_plan_has_all_original_names_and_no_destructive_ddl(self):
        s = (BASE / '02_restaurar_indices_no_unicos.sql').read_text(encoding='utf-8-sig')
        for idx in MANIFEST['original_indexes']:
            self.assertIn("N'" + idx['name'] + "'", s)
        self.assertIn('DECLARE @Aplicar bit = 0;', s)
        self.assertIn('IF @@TRANCOUNT <> 0', s)
        self.assertIn('SET IMPLICIT_TRANSACTIONS OFF;', s)
        self.assertIn('CREATE NONCLUSTERED INDEX', s)
        self.assertNotRegex(s, r'(?im)^\s*(?:DROP|DELETE|TRUNCATE|ALTER TABLE|CREATE SCHEMA|CREATE DATABASE)\b')

    def test_schema_lock_failure_prevents_first_mutation(self):
        api = types.SimpleNamespace(TestSchemaLock=lambda path: False)
        report = {'globalids_to_add': ['mline_tc_proyecto']}
        runner = M.Configurator(api, 'connection.sde', MANIFEST, report)
        with self.assertRaisesRegex(RuntimeError, 'bloqueos de esquema'):
            runner.apply()
        self.assertNotIn('mutations_attempted', report)

    def index(self, **changes):
        item = {'name': 'otro_indice', 'id': 3, 'type': 2, 'unique': False,
                'disabled': False, 'hypothetical': False, 'filtered': False,
                'columns': ['id_proyecto'], 'descending': [False], 'included': []}
        item.update(changes)
        return item

    def test_equivalent_index_is_preserved(self):
        e = {'table': 'mline_tc_proyecto', 'name': 'indice_original', 'columns': ['id_proyecto']}
        self.assertEqual(I.plan_index(e, [self.index()])['action'], 'skip_existing_index')
        self.assertEqual(I.plan_index(e, [self.index(unique=True)])['action'], 'skip_existing_unique_review_branch')

    def test_filtered_index_does_not_replace_full_index(self):
        e = {'table': 'mline_tc_proyecto', 'name': 'indice_original', 'columns': ['id_proyecto']}
        self.assertEqual(I.plan_index(e, [self.index(filtered=True)])['action'], 'create_non_unique')

    def test_index_name_conflict_is_rejected(self):
        e = {'table': 'mline_tc_proyecto', 'name': 'indice_original', 'columns': ['id_proyecto']}
        with self.assertRaisesRegex(RuntimeError, 'Conflicto'):
            I.plan_index(e, [self.index(name='indice_original', columns=['id_tipo_proyecto'])])

if __name__ == '__main__':
    unittest.main()
