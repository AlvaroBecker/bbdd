"""Pruebas de identidad de fuentes para la prevalidación de ingesta."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import fuentes_ingesta as sources


class SourcesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.expected = [dict(archivo=('G1 ' if i < 4 else 'Proyecto ') + str(i) + '.kmz',
                              sha256=hashlib.sha256(str(i).encode()).hexdigest())
                         for i in range(13)]

    def create(self, start=0, end=13):
        for i in range(start, end):
            path = self.root / ('subcarpeta' if i >= 4 else '') / self.expected[i]['archivo']
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(str(i).encode())

    def run_discovery(self):
        report = sources.discover_sources(self.root, self.expected, emit=None)
        json.dumps(report)
        return report

    def test_all_thirteen_recursively_without_changing_files(self):
        self.create()
        before = {str(path): path.read_bytes() for path in self.root.rglob('*.kmz')}
        report = self.run_discovery()
        self.assertTrue(report['completo'])
        self.assertTrue(report['verificado'])
        self.assertEqual(report['conteos']['referencias_cubiertas'], 13)
        self.assertEqual(len(report['archivos_por_referencia']), 13)
        self.assertFalse(report['ingesta_autorizada'])
        self.assertEqual(before, {str(path): path.read_bytes() for path in self.root.rglob('*.kmz')})

    def test_nine_project_files_report_four_g1_missing(self):
        self.create(4)
        report = self.run_discovery()
        self.assertFalse(report['completo'])
        self.assertFalse(report['verificado'])
        self.assertEqual(len(report['ausentes']), 4)
        self.assertTrue(all(row['archivo'].startswith('G1 ') for row in report['ausentes']))

    def test_renamed_source_with_different_accents_and_dashes_uses_exact_content(self):
        self.create()
        (self.root / self.expected[0]['archivo']).rename(self.root / 'G1 Palián – copia.KMZ')
        report = self.run_discovery()
        self.assertTrue(report['verificado'])
        self.assertTrue(report['archivos_por_referencia'][self.expected[0]['archivo']].endswith('copia.KMZ'))
        renamed = [row for row in report['inventario'] if row['nombre'].endswith('copia.KMZ')][0]
        self.assertEqual(renamed['estado'], 'IDENTICO_CONTENIDO_NOMBRE_DISTINTO')

    def test_identical_copies_are_inventoried_but_not_selected_for_loading(self):
        self.create()
        (self.root / 'copia.kmz').write_bytes(b'0')
        report = self.run_discovery()
        self.assertTrue(report['completo'])
        self.assertFalse(report['verificado'])
        self.assertEqual(len(report['duplicados']), 1)
        self.assertNotIn(self.expected[0]['archivo'], report['archivos_por_referencia'])
        row = next(row for row in report['fuentes'] if row['archivo'] == self.expected[0]['archivo'])
        self.assertEqual(Path(row['ruta_elegida']).name, self.expected[0]['archivo'])

    def test_unexpected_content_does_not_remove_complete_reference_coverage(self):
        self.create()
        (self.root / 'nuevo.kmz').write_bytes(b'nuevo')
        report = self.run_discovery()
        self.assertTrue(report['completo'])
        self.assertFalse(report['verificado'])
        self.assertEqual(len(report['inesperados']), 1)

    def test_same_name_with_changed_content_does_not_pass(self):
        self.create()
        (self.root / self.expected[0]['archivo']).write_bytes(b'changed')
        report = self.run_discovery()
        self.assertFalse(report['completo'])
        self.assertEqual(len(report['conflictos_nombre']), 1)
        self.assertEqual(len(report['ausentes']), 1)
        self.assertEqual(len(report['inesperados']), 1)

    def test_hashes_still_recognized_when_two_names_are_swapped(self):
        self.create()
        (self.root / self.expected[0]['archivo']).write_bytes(b'1')
        (self.root / self.expected[1]['archivo']).write_bytes(b'0')
        report = self.run_discovery()
        self.assertTrue(report['completo'])
        self.assertFalse(report['verificado'])
        self.assertEqual(len(report['conflictos_nombre']), 2)

    def test_read_failure_keeps_inventory_and_prevents_complete_status(self):
        self.create()
        real = sources.digest
        def denied(path):
            if path.name == self.expected[0]['archivo']:
                raise PermissionError('Acceso denegado de prueba')
            return real(path)
        with patch.object(sources, 'digest', side_effect=denied):
            report = self.run_discovery()
        self.assertFalse(report['completo'])
        self.assertEqual(len(report['inventario']), 13)
        self.assertEqual(len(report['errores']), 1)

    def test_nonexistent_root_returns_actionable_report(self):
        report = sources.discover_sources(self.root / 'no_existe', self.expected, emit=None)
        self.assertFalse(report['completo'])
        self.assertEqual(len(report['errores']), 1)
        self.assertEqual(len(report['ausentes']), 13)

    def test_file_is_not_accepted_as_directory(self):
        path = self.root / 'archivo'
        path.write_text('x')
        report = sources.discover_sources(path, self.expected, emit=None)
        self.assertFalse(report['completo'])
        self.assertEqual(len(report['errores']), 1)

    def test_reference_requires_valid_unique_names_and_hashes(self):
        bad = [[], [dict(archivo='x.kmz', sha256='bad')],
               [dict(archivo='../x.kmz', sha256='a' * 64)],
               [self.expected[0], self.expected[0]],
               [self.expected[0], dict(archivo='otro.kmz', sha256=self.expected[0]['sha256'])]]
        for reference in bad:
            with self.subTest(reference=reference), self.assertRaises(ValueError):
                sources.discover_sources(self.root, reference, emit=None)

    def test_non_kmz_files_are_not_treated_as_sources(self):
        self.create()
        (self.root / 'readme.txt').write_text('x')
        report = self.run_discovery()
        self.assertTrue(report['verificado'])
        self.assertEqual(report['conteos']['encontrados'], 13)

    def test_subfolder_link_is_reported_without_traversal(self):
        self.create()
        real = sources._is_link
        with patch.object(sources, '_is_link', side_effect=lambda path: path.name == 'subcarpeta' or real(path)):
            report = self.run_discovery()
        self.assertFalse(report['completo'])
        self.assertEqual(report['conteos']['encontrados'], 4)
        self.assertEqual(len(report['errores']), 1)

    def test_file_link_is_reported_without_hashing(self):
        self.create()
        real = sources._is_link
        with patch.object(sources, '_is_link', side_effect=lambda path: path.name == self.expected[0]['archivo'] or real(path)):
            report = self.run_discovery()
        self.assertFalse(report['completo'])
        self.assertEqual(len(report['errores']), 1)
        self.assertIsNone(report['inventario'][0]['sha256'])


if __name__ == '__main__':
    unittest.main()
