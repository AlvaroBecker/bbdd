"""Invariantes de nomenclatura 1.6 frente al paquete 1.5.1 distribuido."""
import copy
import csv
from collections import Counter
import hashlib
import io
import json
from pathlib import Path
import re
import unittest
from unittest.mock import patch
import zipfile

import nombres_clases_kmz as policy
import aplicar_nombres_clases as migration
from aplicar_confirmacion_textos import apply_text_confirmation
from fuentes_inventario_verificadas import read_inventory_bytes

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '02_entregas/Esquema_KMZ_EFT_Corregido'
BASE_ZIP = ROOT / '02_entregas/Datos_Proyecto_Controlado_v1_5_1.zip'


def decode_rows(raw):
    return list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig')), delimiter=';'))


def row_counter(rows):
    return Counter(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows)


class NamingPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with zipfile.ZipFile(BASE_ZIP) as archive:
            cls.baseline_raw = archive.read('esquema.json')
            cls.baseline = json.loads(cls.baseline_raw)
            cls.old_config = json.loads(archive.read('campos_aprobados_1_5.json'))
            cls.old_audit = json.loads(archive.read('VALIDACION_NORMALIZACION.json'))
            cls.old_csvs = {name: decode_rows(archive.read(name)) for name in (
                'catalogo_clases.csv', 'campos_por_ruta.csv', 'campos_matriz_a_esquema.csv',
                'revision_tipos.csv', 'equivalencias_nombres.csv', 'revision_equivalencias.csv',
                'plan_actualizacion_1_5.csv', 'PROPUESTA_MAPEO_OFICINAS.csv')}
        cls.actual = json.loads((OUT/'esquema.json').read_text(encoding='utf-8'))
        cls.mapping = json.loads((OUT/'nombres_clases_1_6.json').read_text(encoding='utf-8'))
        cls.text_review = json.loads((ROOT/'02_entregas/Revision_Pendientes_2086/revision_pendientes_2086.json').read_text(encoding='utf-8'))
        cls.confirmed_text = {(r['clase'], r['campo']) for r in cls.text_review['campos']
                              if r['grupo_revision'] == 'CANDIDATO_A_CONFIRMAR_TEXT'}

    def test_all_76_names_bijective_without_hashes_or_prescindible_words(self):
        rows = policy.policy_rows(self.baseline)
        self.assertEqual(len(rows), 76)
        self.assertEqual(sum(row['renombrar'] for row in rows), 25)
        self.assertEqual(sum(not row['renombrar'] for row in rows), 51)
        self.assertEqual(len({row['nombre_nuevo'].casefold() for row in rows}), 76)
        self.assertEqual(sum(bool(re.search(r'_[0-9a-f]{8}(?:_|$)', row['nombre_anterior'])) for row in rows), 10)
        for row in rows:
            name = row['nombre_nuevo']
            self.assertRegex(name, r'^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$')
            self.assertNotRegex(name, r'_[0-9a-f]{8}(?:_|$)')
            self.assertLessEqual(len(name), 63)
            self.assertFalse(set(name.split('_')) & policy.OMITTED_WORDS)
            self.assertEqual(row['nombre_anterior'].endswith('_recorte'), name.endswith('_recorte'))

    def test_preserves_every_field_property_and_class_property_other_than_name_alias(self):
        transformed, _ = migration.apply_model_policy(self.baseline)
        actual = {c['nombre']: c for c in transformed['clases']}
        for source in self.baseline['clases']:
            target = copy.deepcopy(actual[policy.final_name(source['nombre'])])
            target['nombre'] = source['nombre']
            if 'alias' not in source:
                target.pop('alias', None)
            else:
                target['alias'] = source['alias']
            self.assertEqual(source, target)
        self.assertEqual(sum(len(c['campos']) for c in transformed['clases']), 3340)
        self.assertEqual(sum('pendiente' in f['origen'].lower() for c in transformed['clases']
                             for f in c['campos']), 2086)

    def test_datasets_domains_migrated_tables_project_keys_and_metadata_preserved(self):
        transformed, _ = migration.apply_model_policy(self.baseline)
        for key, value in self.baseline.items():
            if key not in {'version', 'politica_nombres', 'clases', 'relaciones', 'relaciones_negocio'}:
                self.assertEqual(transformed[key], value, key)
        for cls in transformed['clases']:
            if cls['rol'] == 'migrada':
                original = next(c for c in self.baseline['clases'] if c['nombre'] == cls['nombre'])
                self.assertEqual(cls, original)

    def test_relationships_are_named_without_hash_and_keep_keys_and_destinations(self):
        transformed, _ = migration.apply_model_policy(self.baseline)
        targets = {c['nombre'] for c in transformed['clases']}
        self.assertEqual(len(transformed['relaciones']), 76)
        for old, new in zip(self.baseline['relaciones'], transformed['relaciones']):
            self.assertEqual(new['destino'], policy.final_name(old['destino']))
            self.assertIn(new['destino'], targets)
            self.assertEqual(new['nombre'], 'rel_proy_' + new['destino'])
            self.assertLessEqual(len(new['nombre']), 64)
            for key in ('origen', 'clave_origen', 'clave_destino'):
                self.assertEqual(new[key], old[key])
        for old, new in zip(self.baseline['relaciones_negocio'], transformed['relaciones_negocio']):
            self.assertEqual(new['nombre'], old['nombre'])
            for key in ('clave_origen', 'clave_destino'):
                self.assertEqual(new[key], old[key])

    def test_transform_is_pure_idempotent_and_generated_model_matches(self):
        before = copy.deepcopy(self.baseline)
        transformed, rows = migration.apply_model_policy(self.baseline)
        self.assertEqual(self.baseline, before)
        again, same_rows = migration.apply_model_policy(transformed)
        self.assertEqual(again, transformed)
        self.assertEqual(same_rows, rows)
        confirmed, _ = apply_text_confirmation(transformed, self.text_review)
        self.assertEqual(self.actual, confirmed)
        self.assertEqual(self.mapping['clases'], rows)

    def test_duplicate_unknown_missing_and_partial_models_are_rejected(self):
        with self.assertRaises(ValueError):
            policy.final_name('clase_no_revisada')
        missing = copy.deepcopy(self.baseline)
        missing['clases'].pop()
        with self.assertRaises(ValueError):
            policy.policy_rows(missing)
        duplicate = copy.deepcopy(self.baseline)
        duplicate['clases'][0]['nombre'] = duplicate['clases'][1]['nombre']
        with self.assertRaises(ValueError):
            policy.policy_rows(duplicate)
        corrupt = dict(policy.NAMES)
        old = next(name for name in corrupt if name != 'accesos')
        corrupt[old] = 'accesos'
        with patch.object(policy, 'NAMES', corrupt), self.assertRaises(ValueError):
            policy.validate_policy()

    def test_source_csvs_and_type_approval_unchanged(self):
        for name, metadata in self.old_audit['fuentes'].items():
            raw = read_inventory_bytes(ROOT, name)
            self.assertEqual(hashlib.sha256(raw).hexdigest(), metadata['sha256'], name)
        source = json.loads((ROOT/'03_scripts/campos_aprobados_1_5.json').read_text(encoding='utf-8'))
        self.assertEqual(source, self.old_config)

    def test_99_approved_changes_keep_types_lengths_and_evidence(self):
        before = copy.deepcopy(self.old_config)
        result = migration.retarget_approval(self.old_config)
        self.assertEqual(self.old_config, before)
        self.assertEqual(result, migration.retarget_approval(result))
        self.assertEqual(result['version_paquete'], '1.5')
        self.assertEqual(result['version_modelo'], 10)
        self.assertEqual(result['normalizacion_nombres_version'], '1.6')
        self.assertEqual(len(result['cambios']), 99)
        for old, new in zip(self.old_config['cambios'], result['cambios']):
            equivalent = dict(new)
            self.assertEqual(equivalent.pop('clase_anterior'), old['clase'])
            self.assertEqual(equivalent.pop('clase'), policy.final_name(old['clase']))
            self.assertEqual(equivalent, {key: value for key, value in old.items() if key != 'clase'})
        for key, value in self.old_config.items():
            if key not in {'cambios', 'version_modelo'}:
                self.assertEqual(result[key], value, key)
        current = migration.retarget_approval(self.old_config, model_version=11)
        self.assertEqual(current, dict(result, version_modelo=11))
        self.assertEqual(current, json.loads((OUT/'campos_aprobados_1_5.json').read_text(encoding='utf-8')))
        duplicate = copy.deepcopy(self.old_config)
        duplicate['cambios'].append(copy.deepcopy(duplicate['cambios'][0]))
        with self.assertRaises(ValueError):
            migration.retarget_approval(duplicate)

    def test_generated_csvs_change_only_named_destination_columns(self):
        aliases = {row['nombre_nuevo']: row['alias'] or '' for row in self.mapping['clases']}
        for name, old in self.old_csvs.items():
            column = 'clase' if 'clase' in old[0] else 'clase_destino'
            expected = migration.retarget_rows(old, (column,))
            if name == 'catalogo_clases.csv':
                for row in expected:
                    row['alias'] = aliases[row['clase']]
            if name in ('campos_por_ruta.csv', 'campos_matriz_a_esquema.csv'):
                for row in expected:
                    if (row['clase_destino'], row['campo_destino']) in self.confirmed_text:
                        row['estado'] = 'MAPEADO_TIPO_CONFIRMADO'
            if name == 'revision_tipos.csv':
                for row in expected:
                    if (row['clase'], row['campo']) in self.confirmed_text:
                        row.update(estado='TIPO_CONFIRMADO_PERFIL', tipo_confirmado='TEXT',
                            longitud_confirmada='4000', observacion='Texto confirmado; ver textos_confirmados_1_7.json. Sin cambio fisico.')
            actual = decode_rows((OUT/name).read_bytes())
            self.assertEqual(len(actual), len(old), name)
            self.assertEqual(row_counter(actual), row_counter(expected), name)
            self.assertEqual(migration.retarget_rows(expected, (column,)), expected, name)

    def test_mapping_artifacts_have_exact_baseline_and_target_hashes(self):
        self.assertEqual((OUT/'esquema_anterior_1_5_1.json').read_bytes(), self.baseline_raw)
        self.assertEqual(self.mapping['modelo_anterior_sha256'], migration.BASELINE_SHA256)
        self.assertEqual(self.mapping['modelo_objetivo_sha256'],
                         hashlib.sha256((OUT/'esquema.json').read_bytes()).hexdigest())
        self.assertEqual(self.mapping['version_paquete'], '1.6')
        rows = decode_rows((OUT/'nombres_clases_1_6.csv').read_bytes())
        self.assertEqual(len(rows), 76)
        self.assertEqual({row['nombre_nuevo'] for row in rows}, set(policy.NAMES.values()))

    def test_no_orphan_destinations_and_source_route_counts_unchanged(self):
        targets = {c['nombre'] for c in self.actual['clases']}
        with (OUT/'mapeo_capas_revision.csv').open(encoding='utf-8-sig', newline='') as stream:
            routes = list(csv.DictReader(stream, delimiter=';'))
        self.assertEqual(len(routes), 3638)
        self.assertEqual(sum(int(row['elementos']) for row in routes), 279623)
        self.assertEqual(sum(int(row['elementos']) for row in routes if row['clase_propuesta']), 139304)
        self.assertTrue(all(not row['clase_propuesta'] or row['clase_propuesta'] in targets for row in routes))
        with (ROOT/'inventario_kmz_resumen/inventario_kmz_capas.csv').open(encoding='utf-8-sig', newline='') as stream:
            original = list(csv.DictReader(stream, delimiter=';'))
        keys = ('archivo', 'ruta', 'descripcion', 'geometria', 'elementos')
        self.assertEqual(Counter(tuple(row[key] for key in keys) for row in routes),
                         Counter(tuple(row[key] for key in keys) for row in original))
        for name, column in (('campos_por_ruta.csv', 'clase_destino'),
                             ('campos_matriz_a_esquema.csv', 'clase_destino'),
                             ('revision_tipos.csv', 'clase')):
            rows = decode_rows((OUT/name).read_bytes())
            self.assertTrue(all(not row[column] or row[column] in targets for row in rows), name)


if __name__ == '__main__':
    unittest.main(verbosity=2)
