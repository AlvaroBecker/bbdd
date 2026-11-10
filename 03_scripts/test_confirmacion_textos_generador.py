"""Pruebas de alcance e integridad para confirmar TEXT sin cambiar el esquema."""

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

import aplicar_confirmacion_textos as confirmation


class ConfirmationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.review = confirmation.load_verified_review(cls.root)
        cls.payloads = confirmation._read_baseline(cls.root)
        cls.base = cls.payloads['esquema.json']
        cls.target, cls.config = confirmation.apply_text_confirmation(cls.base, cls.review)
        cls.candidates = {(row['clase'], row['campo']) for row in cls.review['campos']
                          if row['grupo_revision'] == confirmation.TEXT_GROUP}

    @staticmethod
    def fields(model):
        return {(cls['nombre'], field['nombre']): field for cls in model['clases'] for field in cls['campos']}

    def test_exact_approved_keys_and_pending_count(self):
        before = self.fields(self.base)
        after = self.fields(self.target)
        changed = {key for key in before if before[key] != after[key]}
        configured = {(row['clase'], row['campo']) for row in self.config['campos']}
        self.assertEqual(changed, self.candidates)
        self.assertEqual(configured, self.candidates)
        self.assertEqual(len(self.config['campos']), 1356)
        self.assertEqual(sum('pendiente' in f.get('origen', '').lower() for f in after.values()), 730)
        self.assertEqual(len(self.target['clases']), 76)
        self.assertEqual(len(after), 3340)

    def test_only_two_field_metadata_keys_and_model_version_change(self):
        before = self.fields(self.base)
        after = self.fields(self.target)
        for key in self.candidates:
            original = copy.deepcopy(before[key])
            original['origen'] = confirmation.CONFIRMED_ORIGIN
            original['tipo_confirmado'] = True
            self.assertEqual(after[key], original, key)
        original_root = {key: value for key, value in self.base.items() if key not in ('version', 'clases')}
        target_root = {key: value for key, value in self.target.items() if key not in ('version', 'clases')}
        self.assertEqual(original_root, target_root)
        for original_class, target_class in zip(self.base['clases'], self.target['clases']):
            self.assertEqual({key: value for key, value in original_class.items() if key != 'campos'},
                             {key: value for key, value in target_class.items() if key != 'campos'})
        self.assertEqual((self.base['version'], self.target['version']), (10, 11))

    def test_original_inputs_remain_unchanged(self):
        original_model = copy.deepcopy(self.base)
        original_review = copy.deepcopy(self.review)
        result, config = confirmation.apply_text_confirmation(original_model, original_review)
        self.assertEqual(original_model, self.base)
        self.assertEqual(original_review, self.review)
        result['clases'][0]['campos'][0]['nombre'] = 'changed_only_in_result'
        config['kmz_verificados'][0]['sha256'] = 'changed_only_in_result'
        self.assertEqual(original_model, self.base)
        self.assertEqual(original_review, self.review)

    def test_deterministic_and_idempotent_generation(self):
        result, config = confirmation.apply_text_confirmation(copy.deepcopy(self.base), copy.deepcopy(self.review))
        again, same_config = confirmation.apply_text_confirmation(result, self.review)
        self.assertEqual(confirmation.model_bytes(result), confirmation.model_bytes(self.target))
        self.assertEqual(confirmation.model_bytes(again), confirmation.model_bytes(result))
        self.assertEqual(config, self.config)
        self.assertEqual(same_config, config)
        self.assertEqual(confirmation.model_sha256(result), config['modelo_objetivo_sha256'])
        self.assertEqual(config['modelo_origen_sha256'], confirmation.MODEL10_SHA256)
        self.assertEqual(config['revision_sha256'], confirmation.REVIEW_SHA256)

    def test_previous_99_approvals_and_office_mapping_unchanged(self):
        before, after = self.fields(self.base), self.fields(self.target)
        old_approvals = {(row['clase'], row['campo'])
                         for row in self.payloads['campos_aprobados_1_5.json']['cambios']}
        self.assertEqual(len(old_approvals), 99)
        self.assertFalse(old_approvals & self.candidates)
        for key in old_approvals:
            self.assertEqual(before[key], after[key], key)
        office_key = ('predios_inscritos_sunarp_recorte', 'oficina_registral')
        self.assertEqual(before[office_key], after[office_key])
        self.assertNotIn(office_key, self.candidates)
        self.assertNotIn(('predios_inscritos_sunarp_recorte', 'oficina_registral_2'), after)

    def test_all_non_text_groups_remain_pending(self):
        after = self.fields(self.target)
        for row in self.review['campos']:
            if row['grupo_revision'] != confirmation.TEXT_GROUP:
                field = after[(row['clase'], row['campo'])]
                self.assertIn('pendiente', field['origen'])
                self.assertNotIn('tipo_confirmado', field)
        self.assertEqual(sum(self.config['grupos_excluidos'].values()), 730)

    def test_config_preserves_evidence_and_authorization(self):
        self.assertEqual(self.config['aprobacion_usuario']['texto'], 'ok vamos con el siguiente paso')
        self.assertTrue(self.config['confirmacion_solo_metadatos'])
        self.assertFalse(self.config['cambios_fisicos'])
        self.assertFalse(self.config['carga_de_datos'])
        self.assertEqual(self.config['kmz_verificados'], self.review['kmz_verificados'])
        self.assertEqual(len(self.config['kmz_verificados']), 13)
        review_fields = {(row['clase'], row['campo']): row for row in self.review['campos']}
        for row in self.config['campos']:
            original = review_fields[(row['clase'], row['campo'])]
            self.assertEqual((row['tipo'], row['longitud']), ('TEXT', 4000))
            self.assertGreater(row['valores_utiles'], 0)
            for name in ('longitud_maxima_utf16', 'valores_utiles', 'cobertura', 'propuesta_historica'):
                self.assertEqual(row[name], original[name])

    def test_tampered_review_candidates_are_rejected(self):
        mutations = {
            'empty_useful_values': ('valores_utiles', 0),
            'blocked_mapping': ('bloqueos', 'CONFLICTO_DE_MAPEO'),
            'unknown_class': ('clase', 'clase_no_autorizada'),
            'unknown_field': ('campo', 'campo_no_autorizado'),
            'wrong_type': ('tipo_actual', 'DOUBLE'),
            'wrong_capacity': ('longitud_actual', 10000),
            'oversize_value': ('longitud_maxima_utf16', 4001),
            'unapproved_proposal': ('propuesta_historica', 'REVISAR_FECHA'),
            'partial_coverage': ('cobertura', 'PARCIAL'),
            'changed_approval': ('aprobado', True),
        }
        for label, (name, value) in mutations.items():
            with self.subTest(label=label):
                changed = copy.deepcopy(self.review)
                row = next(row for row in changed['campos'] if row['grupo_revision'] == confirmation.TEXT_GROUP)
                row[name] = value
                with self.assertRaisesRegex(ValueError, 'revision no coincide'):
                    confirmation.apply_text_confirmation(self.base, changed)

    def test_extra_or_removed_review_records_are_rejected(self):
        for operation in ('extra', 'missing', 'empty'):
            with self.subTest(operation=operation):
                changed = copy.deepcopy(self.review)
                if operation == 'extra':
                    changed['campos'].append(copy.deepcopy(changed['campos'][0]))
                elif operation == 'missing':
                    changed['campos'].pop()
                else:
                    changed['campos'] = []
                with self.assertRaises(ValueError):
                    confirmation.apply_text_confirmation(self.base, changed)

    def test_extra_approval_of_excluded_field_is_rejected(self):
        changed = copy.deepcopy(self.review)
        office = next(row for row in changed['campos'] if row['grupo_revision'] == 'CONFLICTO_DE_MAPEO')
        office['grupo_revision'] = confirmation.TEXT_GROUP
        office['bloqueos'] = ''
        with self.assertRaises(ValueError):
            confirmation.apply_text_confirmation(self.base, changed)

    def test_altered_physical_model_is_rejected(self):
        for name, value in (('tipo', 'DOUBLE'), ('longitud', 255), ('nullable', False),
                            ('alias', 'alias cambiado'), ('dominio', 'dominio_cambiado'), ('nombre', 'otro_nombre')):
            with self.subTest(property=name):
                changed = copy.deepcopy(self.base)
                self.fields(changed)[sorted(self.candidates)[0]][name] = value
                with self.assertRaises(ValueError):
                    confirmation.apply_text_confirmation(changed, self.review)

    def test_extra_class_or_field_is_rejected(self):
        changed = copy.deepcopy(self.base)
        changed['clases'].append(copy.deepcopy(changed['clases'][0]))
        with self.assertRaisesRegex(ValueError, '76 clases'):
            confirmation.apply_text_confirmation(changed, self.review)
        changed = copy.deepcopy(self.base)
        changed['clases'][0]['campos'].append(copy.deepcopy(changed['clases'][0]['campos'][0]))
        with self.assertRaisesRegex(ValueError, '3340 campos'):
            confirmation.apply_text_confirmation(changed, self.review)

    def test_wrong_model_version_is_rejected(self):
        changed = copy.deepcopy(self.base)
        changed['version'] = 12
        with self.assertRaisesRegex(ValueError, 'modelo 10 o el modelo 11'):
            confirmation.apply_text_confirmation(changed, self.review)

    def test_partial_model11_confirmation_is_rejected(self):
        changed = copy.deepcopy(self.target)
        first = self.fields(changed)[sorted(self.candidates)[0]]
        first['origen'] = confirmation.PENDING_ORIGIN
        with self.assertRaisesRegex(ValueError, 'Confirmacion incompleta'):
            confirmation.apply_text_confirmation(changed, self.review)

    def test_model11_with_extra_confirmation_is_rejected(self):
        changed = copy.deepcopy(self.target)
        field = self.fields(changed)[('predios_inscritos_sunarp_recorte', 'oficina_registral')]
        field['origen'] = confirmation.CONFIRMED_ORIGIN
        field['tipo_confirmado'] = True
        with self.assertRaisesRegex(ValueError, 'modelo de origen no coincide'):
            confirmation.apply_text_confirmation(changed, self.review)

    def test_load_rechecks_all_13_raw_kmz_hashes(self):
        with mock.patch.object(confirmation, 'sha_file', wraps=confirmation.sha_file) as hash_file:
            loaded = confirmation.load_verified_review(self.root)
        self.assertEqual(loaded, self.review)
        self.assertEqual(hash_file.call_count, 13)
        self.assertTrue(all(call.args[0].suffix == '.kmz' for call in hash_file.call_args_list))

    def test_changed_raw_kmz_hash_is_rejected(self):
        with mock.patch.object(confirmation, 'sha_file', return_value='0' * 64):
            with self.assertRaisesRegex(ValueError, 'SHA-256 no coincidente en KMZ'):
                confirmation.load_verified_review(self.root)

    def test_changed_review_file_is_rejected_before_using_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / confirmation.REVIEW_RELATIVE
            path.parent.mkdir(parents=True)
            path.write_bytes(b'{}')
            with self.assertRaisesRegex(ValueError, 'revision historica ha cambiado'):
                confirmation.load_verified_review(root)

    def test_changed_profile_csv_hash_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'perfil historico de 2185 campos ha cambiado'):
            confirmation._verify_profile(self.review, self.payloads, b'altered profile')

    def test_new_canonical_package_cannot_replace_baseline_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / '02_entregas/Datos_Proyecto_Controlado.zip'
            destination.parent.mkdir(parents=True)
            with zipfile.ZipFile(destination, 'w') as archive:
                archive.writestr('MANIFIESTO_DATOS_PROYECTO.json', json.dumps({'version': '1.7', 'version_modelo': 11}))
            with self.assertRaisesRegex(ValueError, 'referencia debe ser el paquete 1.6.2'):
                confirmation._read_baseline(root)

    def test_tampered_baseline_model_hash_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / confirmation.BASELINE_RELATIVE
            destination.parent.mkdir(parents=True)
            with zipfile.ZipFile(self.root / confirmation.BASELINE_RELATIVE) as original:
                with zipfile.ZipFile(destination, 'w') as archive:
                    archive.writestr('MANIFIESTO_DATOS_PROYECTO.json', original.read('MANIFIESTO_DATOS_PROYECTO.json'))
                    archive.writestr('esquema.json', b'{}')
            with self.assertRaisesRegex(ValueError, 'Integridad incorrecta en la referencia'):
                confirmation._read_baseline(root)


if __name__ == '__main__':
    unittest.main()
