"""Pruebas de seleccion de fuentes inmutables y preservacion del CSV de trabajo."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import warnings
import zipfile

import fuentes_inventario_verificadas as sources


class VerifiedInventoryTests(unittest.TestCase):
    NAME = 'inventario_kmz_matriz_campos.csv'

    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        with zipfile.ZipFile(cls.root / 'inventario_kmz_resumen.zip') as archive:
            cls.original = archive.read(cls.NAME)

    def fixture(self, directory, current=b'custom working file', member=None, raw=None):
        root = Path(directory)
        path = root / 'inventario_kmz_resumen' / self.NAME
        path.parent.mkdir(parents=True)
        if current is not None:
            path.write_bytes(current)
        if member is not None:
            with zipfile.ZipFile(root / 'inventario_kmz_resumen.zip', 'w') as archive:
                archive.writestr(member, self.original if raw is None else raw)
        return root, path

    def test_constants_equal_approved_baseline_validation(self):
        with zipfile.ZipFile(self.root / '02_entregas/Datos_Proyecto_Controlado_v1_6_2.zip') as archive:
            validation = json.loads(archive.read('VALIDACION_NORMALIZACION.json'))
        self.assertEqual(sources.EXPECTED_SHA256,
                         {name: row['sha256'] for name, row in validation['fuentes'].items()})

    def test_all_four_real_sources_match_approved_hashes(self):
        for name, digest in sources.EXPECTED_SHA256.items():
            with self.subTest(name=name):
                raw = sources.read_inventory_bytes(self.root, name)
                self.assertEqual(hashlib.sha256(raw).hexdigest(), digest)

    def test_matching_current_csv_is_used_without_zip(self):
        with tempfile.TemporaryDirectory() as directory:
            root, path = self.fixture(directory, current=self.original)
            self.assertEqual(sources.read_inventory_bytes(root, self.NAME), self.original)
            metadata = sources.source_metadata(root, self.NAME)
            self.assertEqual(metadata['origen'], 'CSV_ACTUAL_VERIFICADO')
            self.assertIsNone(metadata['miembro_zip'])
            self.assertFalse(metadata['archivo_actual_modificado'])
            self.assertEqual(path.read_bytes(), self.original)

    def test_changed_current_csv_is_preserved_when_zip_is_used(self):
        with tempfile.TemporaryDirectory() as directory:
            current = b'user modifications must remain'
            root, path = self.fixture(directory, current=current, member=self.NAME)
            before = path.stat().st_mtime_ns
            self.assertEqual(sources.read_inventory_bytes(root, self.NAME), self.original)
            metadata = sources.source_metadata(root, self.NAME)
            self.assertEqual(metadata['origen'], 'ZIP_ORIGINAL_VERIFICADO')
            self.assertEqual(metadata['miembro_zip'], self.NAME)
            self.assertEqual(metadata['sha256_actual'], hashlib.sha256(current).hexdigest())
            self.assertEqual(metadata['sha256'], sources.EXPECTED_SHA256[self.NAME])
            self.assertEqual(path.read_bytes(), current)
            self.assertEqual(path.stat().st_mtime_ns, before)

    def test_missing_current_csv_does_not_get_recreated(self):
        with tempfile.TemporaryDirectory() as directory:
            root, path = self.fixture(directory, current=None, member=self.NAME)
            self.assertEqual(sources.read_inventory_bytes(root, self.NAME), self.original)
            self.assertIsNone(sources.source_metadata(root, self.NAME)['sha256_actual'])
            self.assertFalse(path.exists())

    def test_unique_basename_inside_archive_folder_is_allowed(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self.fixture(directory, member='archived/' + self.NAME)
            self.assertEqual(sources.read_inventory_bytes(root, self.NAME), self.original)
            self.assertEqual(sources.source_metadata(root, self.NAME)['miembro_zip'], 'archived/' + self.NAME)

    def test_wrong_archive_hash_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root, path = self.fixture(directory, member=self.NAME, raw=b'wrong CSV')
            with self.assertRaisesRegex(ValueError, 'SHA-256 del miembro del ZIP no coincide'):
                sources.read_inventory_bytes(root, self.NAME)
            self.assertEqual(path.read_bytes(), b'custom working file')

    def test_missing_archive_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self.fixture(directory)
            with self.assertRaisesRegex(ValueError, 'falta el ZIP original'):
                sources.read_inventory_bytes(root, self.NAME)

    def test_duplicate_archive_basenames_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self.fixture(directory, member=self.NAME)
            with zipfile.ZipFile(root / 'inventario_kmz_resumen.zip', 'a') as archive:
                archive.writestr('other/' + self.NAME, self.original)
            with self.assertRaisesRegex(ValueError, 'unico miembro'):
                sources.read_inventory_bytes(root, self.NAME)

    def test_duplicate_exact_archive_names_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self.fixture(directory, member=self.NAME)
            with warnings.catch_warnings():
                warnings.simplefilter('ignore', UserWarning)
                with zipfile.ZipFile(root / 'inventario_kmz_resumen.zip', 'a') as archive:
                    archive.writestr(self.NAME, self.original)
            with self.assertRaisesRegex(ValueError, 'unico miembro'):
                sources.read_inventory_bytes(root, self.NAME)

    def test_missing_archive_member_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self.fixture(directory, member='unrelated.csv')
            with self.assertRaisesRegex(ValueError, 'encontrados 0'):
                sources.read_inventory_bytes(root, self.NAME)

    def test_arbitrary_sources_and_paths_are_rejected(self):
        for name in ('other.csv', '../' + self.NAME, 'subfolder/' + self.NAME,
                     'C:\\sources\\' + self.NAME, 'INVENTARIO_KMZ_MATRIZ_CAMPOS.CSV'):
            with self.subTest(name=name):
                with self.assertRaisesRegex(ValueError, 'no autorizada'):
                    sources.read_inventory_bytes(self.root, name)


if __name__ == '__main__':
    unittest.main()
