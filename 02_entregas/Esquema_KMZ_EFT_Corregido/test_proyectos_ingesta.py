"""Casos de integridad y confirmacion explicita de proyectos, sin escrituras GIS."""
import csv
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

import proyectos_ingesta as projects


class Cursor:
    def __init__(self, rows):
        self.rows = rows

    def __enter__(self):
        return iter(self.rows)

    def __exit__(self, *args):
        return False


def field(name, kind='String', length=128):
    return SimpleNamespace(name=name, type=kind, length=length, baseName=name.rsplit('.', 1)[-1])


class ArcPyReadOnly:
    def __init__(self, rows=None, fields=None, has_oid=True, exists=True):
        self.rows = rows if rows is not None else [
            {'co_proyecto': 'PRY-00000005', 'no_proyecto': 'Chanchamayo', 'de_proyecto': 'LT Chanchamayo'},
            {'co_proyecto': 'PRY-00000004', 'no_proyecto': 'Huaraz', 'de_proyecto': 'LT Huaraz'}]
        self.fields = fields or [field('co_proyecto', length=12), field('no_proyecto'), field('de_proyecto')]
        self.has_oid, self.exists = has_oid, exists
        self.calls = []
        self.da = SimpleNamespace(SearchCursor=self.SearchCursor)

    def Exists(self, path):
        self.calls.append(('Exists', path))
        return self.exists

    def Describe(self, path):
        self.calls.append(('Describe', path))
        return SimpleNamespace(hasOID=self.has_oid)

    def ListFields(self, path):
        self.calls.append(('ListFields', path))
        return self.fields

    def SearchCursor(self, path, names):
        self.calls.append(('SearchCursor', path, names))
        return Cursor([[row.get(name.rsplit('.', 1)[-1]) for name in names] for row in self.rows])


class ProjectsTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.arcpy = ArcPyReadOnly()
        self.catalog = projects.read_projects(self.arcpy, 'sde/GIS.mline_tc_proyecto')
        self.sources = ['Proyecto CHANCHAMAYO.kmz', 'Proyecto HUARAZ.kmz']

    def mapping(self, rows, delimiter=';'):
        path = self.root / 'proyectos.csv'
        with path.open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.writer(stream, delimiter=delimiter)
            writer.writerow(projects.CSV_COLUMNS)
            writer.writerows(rows)
        return path

    def codes(self, report):
        return {x['codigo'] for x in report['incidencias']}

    def test_reads_only_required_descriptions_and_key(self):
        self.assertTrue(self.catalog['verificado'])
        self.assertEqual(len(self.catalog['filas']), 2)
        self.assertFalse(self.catalog['cambios_en_sde'])
        self.assertEqual([c[0] for c in self.arcpy.calls], ['Exists', 'Describe', 'ListFields', 'SearchCursor'])

    def test_nchar_padding_removed_only_on_right(self):
        a = ArcPyReadOnly([{'co_proyecto': 'ABC         ', 'no_proyecto': 'Uno'}])
        r = projects.read_projects(a, 'parent')
        self.assertTrue(r['verificado'])
        self.assertEqual(r['filas'][0]['co_proyecto'], 'ABC')
        self.assertEqual(r['filas'][0]['co_proyecto_original'], 'ABC         ')

    def test_empty_null_long_and_control_keys_all_reported(self):
        rows = [{'co_proyecto': c, 'no_proyecto': 'Uno'} for c in [None, '', ' '*12, 'a'*13, '\tABC', 'ABC\n']]
        r = projects.read_projects(ArcPyReadOnly(rows), 'parent')
        self.assertFalse(r['verificado'])
        self.assertEqual(self.codes(r), {'CLAVE_VACIA', 'CLAVE_LARGA', 'CLAVE_ESPACIOS_INVALIDOS'})

    def test_case_insensitive_duplicate_and_padding_duplicate(self):
        rows = [{'co_proyecto': c, 'no_proyecto': 'Uno'} for c in ['AbC', 'abc  ']]
        r = projects.read_projects(ArcPyReadOnly(rows), 'parent')
        self.assertFalse(r['verificado'])
        self.assertIn('CLAVE_DUPLICADA', self.codes(r))

    def test_schema_missing_wrong_key_name_and_registration(self):
        for a, code in [
            (ArcPyReadOnly(exists=False), 'PADRE_AUSENTE'),
            (ArcPyReadOnly(has_oid=False), 'PADRE_NO_REGISTRADO'),
            (ArcPyReadOnly(fields=[field('co_proyecto', length=11), field('no_proyecto')]), 'CLAVE_INCOMPATIBLE'),
            (ArcPyReadOnly(fields=[field('co_proyecto', kind='Integer', length=12), field('no_proyecto')]), 'CLAVE_INCOMPATIBLE'),
            (ArcPyReadOnly(fields=[field('co_proyecto', length=12)]), 'NOMBRE_PROYECTO_AUSENTE')]:
            with self.subTest(code=code):
                r = projects.read_projects(a, 'parent')
                self.assertFalse(r['verificado'])
                self.assertIn(code, self.codes(r))
                self.assertNotIn('SearchCursor', [c[0] for c in a.calls])

    def test_empty_catalog_blocks(self):
        r = projects.read_projects(ArcPyReadOnly(rows=[]), 'parent')
        self.assertIn('PADRE_VACIO', self.codes(r))

    def test_qualified_fields_use_real_names_for_cursor(self):
        a = ArcPyReadOnly(fields=[field('GIS.parent.co_proyecto', length=12), field('GIS.parent.no_proyecto')])
        r = projects.read_projects(a, 'parent')
        self.assertTrue(r['verificado'])
        self.assertEqual(r['campos_consultados'], ['GIS.parent.co_proyecto', 'GIS.parent.no_proyecto'])

    def test_duplicate_base_field_stops_cursor(self):
        a = ArcPyReadOnly(fields=[field('co_proyecto', length=12), field('GIS.parent.co_proyecto', length=12), field('no_proyecto')])
        r = projects.read_projects(a, 'parent')
        self.assertIn('CAMPO_AMBIGUO', self.codes(r))
        self.assertNotIn('SearchCursor', [c[0] for c in a.calls])

    def test_deleted_state_is_disclosed_without_inventing_filter(self):
        a = ArcPyReadOnly(rows=[{'co_proyecto': 'PRY-00000005', 'no_proyecto': 'Chanchamayo',
                               'es_registro': '0', 'fe_eliminacion': object()}],
                         fields=[field('co_proyecto', length=12), field('no_proyecto'),
                                 field('es_registro', length=1), field('fe_eliminacion', kind='Date')])
        r = projects.read_projects(a, 'parent')
        self.assertTrue(r['verificado'])
        self.assertTrue(r['filas'][0]['tiene_fecha_eliminacion'])
        self.assertEqual(r['advertencias'][0]['codigo'], 'PROYECTO_CON_FECHA_ELIMINACION')

    def test_names_never_confirm_even_exact(self):
        r = projects.plan_projects(self.sources, self.catalog)
        self.assertEqual(r['confirmados'], 0)
        self.assertEqual(r['pendientes'], 2)
        self.assertFalse(r['verificado'])
        self.assertEqual(r['asociaciones'][0]['candidatos'][0]['co_proyecto'], 'PRY-00000005')
        self.assertIsNone(r['asociaciones'][0]['co_proyecto'])
        self.assertTrue(all(x['co_proyecto'] == '' and x['confirmado'] == 'no' for x in r['plantilla_csv']))

    def test_accents_dashes_copy_suffix_and_slash_candidates(self):
        rows = [{'co_proyecto': 'PRY-00000027', 'no_proyecto': 'G1 LT 220 kV Felam - Tierras Nuevas - Salitral'},
                {'co_proyecto': 'PRY-00000010', 'no_proyecto': 'G1 Enlaces 220 kV Felam - Tierras Nuevas - Salitral'},
                {'co_proyecto': 'PRY-00000026', 'no_proyecto': 'G1 Nueva SE Pali\u00e1n 220/60 kV y LT'}]
        cs = projects.candidates('G1 LT 220 kV Felam \u2013 Tierras Nuevas \u2013 Salitral (1).kmz', rows)
        self.assertEqual({c['co_proyecto'] for c in cs}, {'PRY-00000027', 'PRY-00000010'})
        cs = projects.candidates('G1 Nueva SE Pali\u00e1n 22060 kV y LT.kmz', rows)
        self.assertEqual(cs[0]['co_proyecto'], 'PRY-00000026')
        self.assertTrue(cs[0]['coincidencia_exacta_normalizada'])

    def test_explicit_csv_confirms_exact_existing_keys(self):
        path = self.mapping([(self.sources[0], 'PRY-00000005', 'si'), (self.sources[1], 'PRY-00000004', 'si')])
        r = projects.plan_projects([{'archivo': name} for name in self.sources], self.catalog, path)
        self.assertTrue(r['verificado'])
        self.assertEqual(r['confirmados'], 2)
        self.assertEqual(len(r['mapping_sha256']), 64)
        self.assertTrue(all(e['estado'] == 'CONFIRMADO_CSV' for e in r['asociaciones']))

    def test_many_sources_can_share_project_if_explicit(self):
        path = self.mapping([(name, 'PRY-00000005', 'si') for name in self.sources], ',')
        r = projects.plan_projects(self.sources, self.catalog, path)
        self.assertTrue(r['verificado'])

    def test_unconfirmed_code_does_not_authorize(self):
        path = self.mapping([(self.sources[0], 'PRY-00000005', 'no')])
        r = projects.plan_projects(self.sources, self.catalog, path)
        self.assertEqual(r['confirmados'], 0)
        self.assertFalse(r['verificado'])

    def test_nonexistent_and_nonexact_keys_rejected(self):
        for code in ['PRY-00000999', 'pry-00000005', 'PRY-00000005 ', '']:
            with self.subTest(code=code):
                path = self.mapping([(self.sources[0], code, 'si')])
                r = projects.plan_projects(self.sources, self.catalog, path)
                self.assertEqual(r['confirmados'], 0)
                self.assertIn('CSV_CODIGO_NO_EXISTE', self.codes(r))

    def test_csv_duplicate_and_unknown_files_block(self):
        path = self.mapping([(self.sources[0], 'PRY-00000005', 'si'),
                             (self.sources[0], 'PRY-00000004', 'si'),
                             ('otro.kmz', 'PRY-00000004', 'si')])
        r = projects.plan_projects(self.sources, self.catalog, path)
        self.assertFalse(r['verificado'])
        self.assertTrue({'CSV_ARCHIVO_DUPLICADO', 'CSV_ARCHIVO_DESCONOCIDO'} <= self.codes(r))

    def test_csv_invalid_flags_and_columns_block(self):
        path = self.mapping([(self.sources[0], 'PRY-00000005', 'quiza')])
        r = projects.plan_projects(self.sources, self.catalog, path)
        self.assertIn('CSV_CONFIRMACION_INVALIDA', self.codes(r))
        for content in ['', 'archivo_kmz;co_proyecto\na;b\n',
                        'archivo_kmz;co_proyecto;confirmado;confirmado\na;b;c;d\n',
                        'archivo_kmz;co_proyecto;confirmado\n"sin cerrar']:
            path.write_text(content, encoding='utf-8')
            r = projects.plan_projects(self.sources, self.catalog, path)
            self.assertFalse(r['verificado'])
            self.assertIn('CSV_NO_VALIDO', self.codes(r))

    def test_bad_catalog_blocks_even_confirmed_csv(self):
        bad = dict(self.catalog, verificado=False)
        path = self.mapping([(name, 'PRY-00000005', 'si') for name in self.sources])
        r = projects.plan_projects(self.sources, bad, path)
        self.assertEqual(r['confirmados'], 0)
        self.assertFalse(r['verificado'])

    def test_no_source_candidate_does_not_create_project(self):
        r = projects.plan_projects(['Proyecto POROMA.kmz'], self.catalog)
        self.assertEqual(r['asociaciones'][0]['estado'], 'SIN_CANDIDATO')
        self.assertIsNone(r['asociaciones'][0]['co_proyecto'])
        self.assertFalse(r['cambios_en_sde'])

    def test_empty_or_duplicate_source_list_rejected(self):
        for sources in [[], ['a.kmz', 'a.kmz']]:
            with self.assertRaises(ValueError):
                projects.plan_projects(sources, self.catalog)


if __name__ == '__main__':
    unittest.main()
