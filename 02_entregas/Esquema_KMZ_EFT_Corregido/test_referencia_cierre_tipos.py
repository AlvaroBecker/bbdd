"""Pruebas de integridad del cierre autorizado sobre la evidencia real 1.8."""
from collections import Counter
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import referencia_cierre_tipos as reference


HERE = Path(__file__).resolve().parent
FILES = ('esquema_anterior_1_8.json', 'esquema.json', 'cierre_tipos_1_9.json',
         'PERFIL_COMPLETO_KMZ_1_8.json')


def fields(model):
    return {(cls['nombre'], field['nombre']):field
            for cls in model['clases'] for field in cls['campos']}


class ClosureReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.originals = {name:(HERE / name).read_bytes() for name in FILES}

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name, raw in self.originals.items():
            (self.root / name).write_bytes(raw)
        self.base = json.loads(self.originals['esquema_anterior_1_8.json'])
        self.target = json.loads(self.originals['esquema.json'])
        self.config = json.loads(self.originals['cierre_tipos_1_9.json'])

    def save_config(self):
        (self.root / 'cierre_tipos_1_9.json').write_text(
            json.dumps(self.config, ensure_ascii=False), encoding='utf-8')

    def save_target_with_matching_config_hash(self):
        """El rechazo no debe depender solo de encontrar un hash desactualizado."""
        raw = json.dumps(self.target, ensure_ascii=False).encode('utf-8')
        (self.root / 'esquema.json').write_bytes(raw)
        self.config['modelo_objetivo_sha256'] = hashlib.sha256(raw).hexdigest()
        self.save_config()

    def test_real_approval_confirms_730_and_changes_only_eight_physical_definitions(self):
        before = {name:hashlib.sha256((self.root / name).read_bytes()).hexdigest() for name in FILES}
        base, target, config = reference.read_reference(self.root)
        original, current = fields(base), fields(target)
        pending = {key for key, field in original.items()
                   if 'pendiente' in field.get('origen', '').lower()}
        self.assertEqual((base['version'], target['version']), (11, 12))
        self.assertEqual(len(pending), 730)
        self.assertEqual(set(original), set(current))
        self.assertEqual(len(current), 3340)
        self.assertFalse(any('pendiente' in field.get('origen', '').lower()
                             for field in current.values()))
        self.assertTrue(all(current[key]['tipo_confirmado'] for key in pending))
        actual_changes = []
        for key, old in original.items():
            new = current[key]
            if key not in pending:
                self.assertEqual(old, new, key)
            if (old['tipo'], old.get('longitud')) != (new['tipo'], new.get('longitud')):
                actual_changes.append((key, new['tipo']))
            old_other = {k:v for k,v in old.items() if k not in {'origen', 'tipo_confirmado', 'tipo', 'longitud'}}
            new_other = {k:v for k,v in new.items() if k not in {'origen', 'tipo_confirmado', 'tipo', 'longitud'}}
            self.assertEqual(old_other, new_other, key)
        self.assertEqual(len(actual_changes), 8)
        self.assertEqual(Counter(typ for _,typ in actual_changes), {'LONG':6, 'DOUBLE':2})
        self.assertEqual({key[0] for key,_ in actual_changes}, {
            'sitios_arqueologicos_poligono_recorte', 'sitios_arqueologicos_punto_recorte', 'suelos_recorte'})
        self.assertEqual(Counter(current[key]['tipo'] for key in pending), {'TEXT':722, 'LONG':6, 'DOUBLE':2})
        self.assertEqual(len(config['campos']), 730)
        self.assertEqual(len(config['cambios_fisicos']), 8)
        self.assertEqual(before, {name:hashlib.sha256((self.root / name).read_bytes()).hexdigest() for name in FILES})

    def test_unrelated_geometry_or_property_change_rejected_even_with_new_target_hash(self):
        original = copy.deepcopy(self.target)
        for property_name, value in (('geometria', 'POLYLINE'), ('alias', 'otro_alias')):
            with self.subTest(propiedad=property_name):
                self.target = copy.deepcopy(original)
                cls = next(c for c in self.target['clases'] if c['nombre']=='estructuras')
                cls[property_name] = value
                self.save_target_with_matching_config_hash()
                with self.assertRaisesRegex(ValueError, 'diferencias ajenas'):
                    reference.read_reference(self.root)

    def test_extra_physical_change_to_previously_approved_field_rejected(self):
        item = fields(self.target)['estructuras', 'este']
        self.assertEqual(item['tipo'], 'DOUBLE')
        item['tipo'] = 'LONG'
        self.save_target_with_matching_config_hash()
        with self.assertRaisesRegex(ValueError, 'diferencias ajenas'):
            reference.read_reference(self.root)

    def test_missing_field_cannot_be_hidden_by_updating_target_hash(self):
        self.target['clases'][0]['campos'].pop()
        self.save_target_with_matching_config_hash()
        with self.assertRaisesRegex(ValueError, 'diferencias ajenas'):
            reference.read_reference(self.root)

    def test_numeric_candidate_cannot_be_changed_to_another_type(self):
        fields(self.target)['suelos_recorte', 'p_aui_suel']['tipo'] = 'DOUBLE'
        self.save_target_with_matching_config_hash()
        with self.assertRaisesRegex(ValueError, 'diferencias ajenas'):
            reference.read_reference(self.root)

    def test_global_or_field_approval_false_is_rejected(self):
        original = copy.deepcopy(self.config)
        self.config['aprobado'] = False
        self.save_config()
        with self.assertRaisesRegex(ValueError, 'decision autorizada'):
            reference.read_reference(self.root)
        self.config = original
        self.config['campos'][0]['aprobado'] = False
        self.save_config()
        with self.assertRaisesRegex(ValueError, 'Decision incompatible'):
            reference.read_reference(self.root)

    def test_incomplete_duplicate_or_extra_approval_rows_are_rejected(self):
        original = copy.deepcopy(self.config)
        for change in ('missing', 'duplicate', 'extra'):
            with self.subTest(cambio=change):
                self.config = copy.deepcopy(original)
                if change == 'missing':
                    self.config['campos'].pop()
                elif change == 'duplicate':
                    self.config['campos'][1] = copy.deepcopy(self.config['campos'][0])
                else:
                    self.config['campos'].append(dict(self.config['campos'][0], campo='extension_no_autorizada'))
                self.save_config()
                with self.assertRaisesRegex(ValueError, 'exactamente los 730'):
                    reference.read_reference(self.root)

    def test_changed_target_type_in_decision_or_extra_ddl_is_rejected(self):
        original = copy.deepcopy(self.config)
        self.config['campos'][0]['tipo_objetivo'] = 'DATE'
        self.save_config()
        with self.assertRaisesRegex(ValueError, 'Decision incompatible'):
            reference.read_reference(self.root)
        self.config = original
        self.config['cambios_fisicos'].append(dict(self.config['cambios_fisicos'][0], campo='otro'))
        self.save_config()
        with self.assertRaisesRegex(ValueError, 'ocho cambios'):
            reference.read_reference(self.root)

    def test_source_profile_hash_or_bytes_changed_reject_closure(self):
        original = copy.deepcopy(self.config)
        self.config['perfil_origen_sha256'] = '0' * 64
        self.save_config()
        with self.assertRaisesRegex(ValueError, 'perfil original 1.8'):
            reference.read_reference(self.root)
        self.config = original
        self.save_config()
        profile = self.root / 'PERFIL_COMPLETO_KMZ_1_8.json'
        profile.write_bytes(profile.read_bytes() + b' ')
        with self.assertRaisesRegex(ValueError, 'perfil original 1.8'):
            reference.read_reference(self.root)

    def test_historical_model_is_immutable_even_if_semantically_equal_json(self):
        base = self.root / 'esquema_anterior_1_8.json'
        base.write_bytes(base.read_bytes() + b' ')
        with self.assertRaisesRegex(ValueError, 'modelo 11 de referencia fue modificado'):
            reference.read_reference(self.root)

    def test_office_text_confirmation_keeps_mapping_block_open(self):
        base, target, config = reference.read_reference(self.root)
        key = 'predios_inscritos_sunarp_recorte', 'oficina_registral'
        old, new = fields(base)[key], fields(target)[key]
        self.assertIn('pendiente', old['origen'])
        self.assertEqual((old['tipo'], old['longitud']), ('TEXT', 4000))
        self.assertEqual((new['tipo'], new['longitud'], new['tipo_confirmado']), ('TEXT', 4000, True))
        block = next(row for row in config['bloqueos_ingesta'] if row['codigo']=='OFICINA_REGISTRAL')
        self.assertIs(block['resuelto'], False)
        self.assertIs(config['ingesta_autorizada'], False)
        next(row for row in self.config['bloqueos_ingesta'] if row['codigo']=='OFICINA_REGISTRAL')['resuelto'] = True
        self.save_config()
        with self.assertRaisesRegex(ValueError, 'ocultar ni resolver'):
            reference.read_reference(self.root)

    def test_no_ingesta_authorization_or_hidden_block_after_type_closure(self):
        original = copy.deepcopy(self.config)
        self.config['ingesta_autorizada'] = True
        self.save_config()
        with self.assertRaisesRegex(ValueError, 'ocultar ni resolver'):
            reference.read_reference(self.root)
        self.config = original
        self.config['bloqueos_ingesta'] = [b for b in self.config['bloqueos_ingesta']
                                          if b['codigo']!='G1_SIN_COMPROBAR_EN_CT6788']
        self.save_config()
        with self.assertRaisesRegex(ValueError, 'ocultar ni resolver'):
            reference.read_reference(self.root)


if __name__ == '__main__':
    unittest.main()
