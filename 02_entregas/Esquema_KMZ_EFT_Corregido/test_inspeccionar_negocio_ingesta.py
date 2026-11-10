"""Identidad real, integridad y limites de una inspeccion exclusivamente de lectura."""
from contextlib import nullcontext
from datetime import datetime, timezone
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import inspeccionar_negocio_ingesta as business


PROJECT = 'mline_tc_proyecto'
COMPONENT = 'mline_td_proyecto_componente'
ALTERNATIVE = 'mline_td_proyecto_alternativa'
AREA = 'mline_td_proyecto_area_interes'
INFRA = 'mline_td_proyecto_infraestructura'
LINE = 'mline_td_proyecto_ltransmision'


class Cursor:
    def __init__(self, rows):
        self.rows = rows

    def __enter__(self):
        return iter(self.rows)

    def __exit__(self, *args):
        return False


def sample():
    common = dict(proyecto='PRY-00000001', id_analisis='Carga inicial KMZ')
    return {
        PROJECT: [dict(id_proyecto=1, co_proyecto='PRY-00000001', no_proyecto='Uno')],
        COMPONENT: [dict(id_proyecto_componente=10, id_proyecto=1, no_componente='LT Uno')],
        ALTERNATIVE: [dict(id_proyecto_alternativa=20, id_proyecto_componente=10, co_alternativa='ALT-01')],
        AREA: [dict(common, id_proyecto_area_interes=30, id_proyecto_componente=10)],
        INFRA: [dict(common, id_proyecto_infraestructura=40, id_proyecto_alternativa=20, co_infraestructura='TRAZO-1')],
        LINE: [dict(common, id_proyecto_ltransmision=50, id_proyecto_componente=10)],
        'vertices': [dict(common, id_proyecto_infraestructura=40, cod_vertice='V01')],
    }


class ReadOnlyArcPy:
    """No management, InsertCursor ni UpdateCursor: cualquier escritura fallaria."""
    def __init__(self, rows=None):
        self.rows = sample() if rows is None else rows
        self.calls = []
        self.fields = {}
        for name, pk, required, labels in business.SPECS:
            cols = ([pk] if pk else []) + list(required)
            cols += [k for row in self.rows.get(name, []) for k in row if k not in cols]
            self.fields[name] = [SimpleNamespace(name=k, baseName=k,
                type='Integer' if k.startswith('id_') and k != 'id_analisis' else (
                    'Date' if k == 'fe_eliminacion' else 'String'), length=255)
                for k in dict.fromkeys(cols)]
        self.da = SimpleNamespace(SearchCursor=self.SearchCursor)

    @staticmethod
    def base(path):
        return str(path).replace('\\', '/').rsplit('/', 1)[-1].rsplit('.', 1)[-1]

    def EnvManager(self, **kwargs):
        self.calls.append(('EnvManager', kwargs))
        return nullcontext()

    def ListDatasets(self, **kwargs):
        return ['Datos_Proyecto']

    def ListFeatureClasses(self, feature_dataset=''):
        return [name for name in self.rows if name not in {PROJECT, COMPONENT, ALTERNATIVE}] if feature_dataset else []

    def ListTables(self):
        return [name for name in self.rows if name in {PROJECT, COMPONENT, ALTERNATIVE}]

    def Exists(self, path):
        return True

    def Describe(self, path):
        return SimpleNamespace(dataType='FeatureClass' if self.base(path) not in
            {PROJECT, COMPONENT, ALTERNATIVE} else 'Table', hasOID=True, isVersioned=False,
            relationshipClassNames=[], connectionProperties=SimpleNamespace(database='db', user='gis'))

    def ListFields(self, path):
        return self.fields[self.base(path)]

    def SearchCursor(self, path, names):
        self.calls.append(('SearchCursor', self.base(path), names))
        return Cursor([[row.get(n.rsplit('.', 1)[-1]) for n in names]
                       for row in self.rows[self.base(path)]])


class BusinessTests(unittest.TestCase):
    def inspect(self, a=None):
        return business.inspect_business(a or ReadOnlyArcPy(),
            SimpleNamespace(workspace='test.gdb', database='db', owner='gis'),
            {'tabla_proyecto': PROJECT, 'clases': []})

    def codes(self, report):
        return {x['codigo'] for x in report['incidencias']}

    def obj(self, report, name):
        return next(o for o in report['objetos'] if o['nombre'] == name)

    def test_preserves_business_ids_and_chain_without_authorizing_ingestion(self):
        a = ReadOnlyArcPy()
        r = self.inspect(a)
        self.assertTrue(r['lectura_completa'])
        self.assertTrue(r['integridad_observada_sin_incidencias'])
        self.assertTrue(all(x['verificada'] for x in r['relaciones']))
        vertex = next(x for x in r['correspondencias_destino'] if x['objeto'] == 'vertices')
        self.assertEqual(vertex['id_proyecto_infraestructura'], 40)
        self.assertEqual(vertex['co_proyecto_por_cadena_fk'], 'PRY-00000001')
        self.assertFalse(r['ingesta_autorizada'])
        self.assertFalse(r['cambios_en_sde'])
        self.assertEqual(r['ids_asignados'], [])
        self.assertEqual(r['candidatos_cruce_kmz'], [])
        self.assertEqual(r['preservacion_ids_origen']['estado'], 'NO_VERIFICABLE_SOLO_DESTINO')
        self.assertEqual(r['id_analisis_carga_inicial']['valor'], 'Carga inicial KMZ')
        self.assertNotIn('OBJECTID', [f for call in a.calls if call[0] == 'SearchCursor' for f in call[2]])
        self.assertNotIn('SHAPE@', [f for call in a.calls if call[0] == 'SearchCursor' for f in call[2]])
        json.dumps(r, allow_nan=False)

    def test_missing_parent_is_not_created_or_assumed(self):
        rows = sample()
        del rows[COMPONENT]
        r = self.inspect(ReadOnlyArcPy(rows))
        self.assertFalse(r['lectura_completa'])
        self.assertIn('OBJETO_AUSENTE', self.codes(r))
        self.assertEqual(r['objetos_creados'], [])
        self.assertEqual(r['correspondencias_destino'], [])
        self.assertFalse(any(x['verificada'] for x in r['relaciones'] if x['padre'] == COMPONENT))

    def test_empty_objects_do_not_verify_relationships(self):
        rows = {key: [] for key in sample()}
        r = self.inspect(ReadOnlyArcPy(rows))
        self.assertTrue(r['lectura_completa'])
        self.assertFalse(r['integridad_observada_sin_incidencias'])
        self.assertIn('OBJETO_VACIO_SIN_EVIDENCIA', self.codes(r))
        self.assertTrue(all(x['estado'] == 'SIN_FILAS_HIJAS_NO_VERIFICADA' for x in r['relaciones']))

    def test_empty_parent_with_children_is_orphan(self):
        rows = sample()
        rows[ALTERNATIVE] = []
        r = self.inspect(ReadOnlyArcPy(rows))
        self.assertIn('FK_HUERFANA', self.codes(r))
        self.assertFalse(r['integridad_observada_sin_incidencias'])

    def test_duplicate_numeric_key_and_code_are_not_resolved_by_order(self):
        rows = sample()
        rows[PROJECT].append(dict(id_proyecto=1, co_proyecto='pry-00000001   ', no_proyecto='Duplicado'))
        r = self.inspect(ReadOnlyArcPy(rows))
        self.assertIn('CLAVE_DUPLICADA', self.codes(r))
        self.assertIn('FK_AMBIGUA', self.codes(r))
        self.assertFalse(r['integridad_observada_sin_incidencias'])
        self.assertTrue(all(x['co_proyecto_por_cadena_fk'] is None for x in r['correspondencias_destino']))

    def test_orphan_vertex_and_null_component_are_reported(self):
        rows = sample()
        rows['vertices'][0]['id_proyecto_infraestructura'] = 999
        rows[LINE][0]['id_proyecto_componente'] = None
        r = self.inspect(ReadOnlyArcPy(rows))
        self.assertTrue({'FK_HUERFANA', 'FK_SIN_VALOR'} <= self.codes(r))
        self.assertFalse(r['integridad_observada_sin_incidencias'])

    def test_inactive_parent_is_disclosed_not_filtered(self):
        rows = sample()
        rows[COMPONENT][0].update(es_registro='0', fe_eliminacion=datetime(2025, 1, 1, tzinfo=timezone.utc))
        r = self.inspect(ReadOnlyArcPy(rows))
        self.assertEqual(self.obj(r, COMPONENT)['registros_leidos'], 1)
        self.assertIn('FK_A_REGISTRO_INACTIVO', self.codes(r))
        self.assertIn('REGISTROS_INACTIVOS_CONSERVADOS', self.codes(r))
        self.assertEqual(self.obj(r, COMPONENT)['registros'][0]['fe_eliminacion'], '2025-01-01T00:00:00+00:00')
        json.dumps(r, allow_nan=False)

    def test_missing_fk_field_and_incompatible_type_stop_that_cursor(self):
        for mode in ('missing', 'type'):
            a = ReadOnlyArcPy()
            if mode == 'missing':
                a.fields[AREA] = [f for f in a.fields[AREA] if f.name != 'id_proyecto_componente']
            else:
                next(f for f in a.fields[AREA] if f.name == 'id_proyecto_area_interes').type = 'String'
            r = self.inspect(a)
            self.assertFalse(self.obj(r, AREA)['lectura_completa'])
            self.assertFalse(any(c[0] == 'SearchCursor' and c[1] == AREA for c in a.calls))

    def test_qualified_fields_use_actual_names(self):
        a = ReadOnlyArcPy()
        for f in a.fields[PROJECT]:
            f.name = 'GIS.' + PROJECT + '.' + f.name
        r = self.inspect(a)
        self.assertTrue(r['lectura_completa'])
        self.assertTrue(all(n.startswith('GIS.') for n in self.obj(r, PROJECT)['campos_consultados']))

    def test_disagreeing_project_chain_is_not_confirmed(self):
        rows = sample()
        rows[PROJECT].append(dict(id_proyecto=2, co_proyecto='PRY-00000002', no_proyecto='Dos'))
        rows[INFRA][0]['proyecto'] = 'PRY-00000002'
        r = self.inspect(ReadOnlyArcPy(rows))
        self.assertIn('PROYECTO_DISCREPA_CADENA_FK', self.codes(r))

    def test_report_cap_does_not_hide_integrity_errors(self):
        rows = sample()
        rows['vertices'].append(dict(rows['vertices'][0], id_proyecto_infraestructura=999))
        with patch.object(business, 'MAX_REPORT_ROWS', 1):
            r = self.inspect(ReadOnlyArcPy(rows))
        self.assertTrue(self.obj(r, 'vertices')['registros_informe_truncados'])
        self.assertEqual(self.obj(r, 'vertices')['registros_leidos'], 2)
        self.assertIn('FK_HUERFANA', self.codes(r))
        self.assertIn('CATALOGO_INFORME_INCOMPLETO', self.codes(r))
        self.assertFalse(r['lectura_completa'])
        self.assertTrue(r['lectura_datos_completa'])
        self.assertEqual(r['correspondencias_destino'], [])

    def test_reordered_cursors_produce_identical_report(self):
        rows = sample()
        rows[PROJECT].append(dict(id_proyecto=2, co_proyecto='PRY-00000002', no_proyecto='Dos'))
        rows['vertices'].append(dict(rows['vertices'][0], cod_vertice='V02'))
        a = self.inspect(ReadOnlyArcPy(rows))
        b = self.inspect(ReadOnlyArcPy({name: list(reversed(data)) for name, data in rows.items()}))
        self.assertEqual(a, b)

    def test_full_value_hash_detects_change_beyond_display_limit(self):
        rows = sample()
        rows[PROJECT][0]['de_proyecto'] = 'x' * 600 + 'A'
        a = self.inspect(ReadOnlyArcPy(rows))
        rows[PROJECT][0]['de_proyecto'] = 'x' * 600 + 'B'
        b = self.inspect(ReadOnlyArcPy(rows))
        self.assertEqual(self.obj(a, PROJECT)['registros'], self.obj(b, PROJECT)['registros'])
        self.assertNotEqual(self.obj(a, PROJECT)['huella_datos_leidos_sha256'],
                            self.obj(b, PROJECT)['huella_datos_leidos_sha256'])

    def test_empty_analysis_is_explicit_pending_data(self):
        rows = sample()
        rows[AREA][0]['id_analisis'] = ' '
        r = self.inspect(ReadOnlyArcPy(rows))
        self.assertIn('ID_ANALISIS_SIN_VALOR', self.codes(r))
        self.assertFalse(r['integridad_observada_sin_incidencias'])

    def test_scan_cap_prevents_partial_crosswalk_and_certification(self):
        rows = sample()
        rows[PROJECT].append(dict(id_proyecto=2, co_proyecto='PRY-00000002'))
        with patch.object(business, 'MAX_SCAN_ROWS', 1):
            r = self.inspect(ReadOnlyArcPy(rows))
        self.assertFalse(r['lectura_completa'])
        self.assertIn('LIMITE_LECTURA', self.codes(r))
        self.assertEqual(r['correspondencias_destino'], [])

    def test_maximum_never_allocates_new_identifier(self):
        r = self.inspect()
        stats = self.obj(r, INFRA)['claves']['id_proyecto_infraestructura']
        self.assertEqual(stats['maximo_observado'], 40)
        self.assertFalse(stats['maximo_autoriza_asignacion'])
        self.assertEqual(r['ids_asignados'], [])

    def test_wrong_database_stops_before_inventory(self):
        a = ReadOnlyArcPy()
        r = business.inspect_business(a, SimpleNamespace(workspace='dest.sde', database='otro', owner='gis'), {})
        self.assertIn('DESTINO_NO_INSPECCIONABLE', self.codes(r))
        self.assertFalse(any(c[0] == 'SearchCursor' for c in a.calls))


if __name__ == '__main__':
    unittest.main()
