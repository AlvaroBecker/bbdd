import copy
import json
from pathlib import Path
import unittest

import plan_ingesta as plan


def fixture():
    route = dict(archivo='a.kmz', ruta='Proyecto / Capa', geometria='Polígono')
    other = dict(archivo='a.kmz', ruta='Proyecto / Sin destino', geometria='Punto')
    spec = dict(nombre='src_area_ha', tipo='DOUBLE', nullable=True, longitud=None,
                tipo_confirmado=True, campo_fuente='AREA_HA', origen='Confirmado')
    model = dict(clases=[dict(nombre='subestacion_poligono', geometria='POLYGON',
        dataset='Datos_Proyecto', campos=[spec,
            dict(nombre='proyecto', tipo='TEXT', nullable=False, longitud=12, origen='EFT'),
            dict(nombre='id_analisis', tipo='TEXT', nullable=False, longitud=100, origen='EFT')])])
    catalog = [dict(**route, clase_propuesta='subestacion_poligono', elementos='2'),
               dict(**other, clase_propuesta='', elementos='3')]
    maps = [dict(**route, clase_destino='subestacion_poligono', campo_destino='src_area_ha',
                 campo_original='AREA_HA', estado='MAPEADO')]
    stats = dict(clase='subestacion_poligono', campo='src_area_ha', registros=2,
        valores_utiles=0, vacios=0, marcadores={'<Null>': 2}, max_utf16=6,
        max_significant=0, conflictos=0, tipos_declarados={}, valores_sin_tipo=2,
        validacion_valores={'marcadores': 2}, cobertura='COMPLETA_RUTAS_DEL_CAMPO',
        rutas=[route])
    profile = dict(rutas=[dict(**route, clase='subestacion_poligono', esperados=2,
                               observados=2, estado='COINCIDE'),
                         dict(**other, clase='', esperados=3, observados=3, estado='COINCIDE')],
        campos_destino=[stats], campos_fuente=[], incidencias=[], rutas_no_inventariadas=[],
        conteos=dict(elementos_observados=5))
    return profile, model, catalog, maps


def build(data):
    profile, model, catalog, mappings = data
    return plan.build_plan(profile, model, catalog=catalog, field_mappings=mappings)


class PlanTests(unittest.TestCase):
    def test_route_counts_not_attribute_counts(self):
        data = fixture()
        # Two source labels target one field; they must not double two features.
        data[3].append(dict(data[3][0], campo_original='AREA COPIA'))
        result = build(data)
        self.assertEqual(result['resumen']['elementos'], 5)
        self.assertEqual(result['resumen']['elementos_con_destino'], 2)
        self.assertEqual(result['resumen']['elementos_sin_destino'], 3)
        self.assertEqual(result['resumen_clases'][0]['elementos'], 2)
        self.assertFalse(result['ingesta_autorizada'])

    def test_only_exact_marker_and_whitelisted_double(self):
        spec = fixture()[1]['clases'][0]['campos'][0]
        self.assertEqual(plan.convert_planned_null('subestacion_poligono', 'src_area_ha', '<Null>', spec),
                         (None, plan.NULL_RULE))
        for value in ('0', 0, '', 'null', '<null>', ' <Null> ', None):
            self.assertEqual(plan.convert_planned_null('subestacion_poligono', 'src_area_ha', value, spec),
                             (value, None))
        self.assertEqual(plan.convert_planned_null('another', 'src_area_ha', '<Null>', spec), ('<Null>', None))
        for bad in (dict(spec, nullable=False), dict(spec, tipo='TEXT')):
            with self.assertRaises(ValueError):
                plan.convert_planned_null('subestacion_poligono', 'src_area_ha', '<Null>', bad)

    def test_rule_accounts_occurrences_but_does_not_modify_input(self):
        data = fixture()
        before = copy.deepcopy(data)
        result = build(data)
        self.assertEqual(data, before)
        self.assertEqual(result['resumen']['ocurrencias_null_con_regla'], 2)
        self.assertEqual(result['incidencias_campos'], [])
        self.assertFalse(result['reglas_null'][0]['aplicada'])
        self.assertEqual(result['campos_verificados'][0]['incidencias_resueltas_por_regla_del_plan'],
                         ['MARCADORES_REQUIEREN_REGLA_NULL'])

    def test_additional_marker_retains_incident(self):
        data = fixture()
        stats = data[0]['campos_destino'][0]
        stats['marcadores'] = {'<Null>': 1, '<null>': 1}
        result = build(data)
        self.assertEqual(result['reglas_null'][0]['estado'], 'REGLA_NO_APLICABLE')
        self.assertIn('MARCADORES_REQUIEREN_REGLA_NULL', result['incidencias_campos'][0]['incidencias'])

    def test_conflicting_values_not_resolved_by_null_rule(self):
        data = fixture()
        data[0]['campos_destino'][0]['conflictos'] = 1
        result = build(data)
        self.assertEqual(result['reglas_null'][0]['estado'], 'REGLA_NO_APLICABLE')
        self.assertIn('CONFLICTO_MAPEO_VALORES', result['incidencias_campos'][0]['incidencias'])

    def test_missing_mandatory_fields_remain_explicit(self):
        result = build(fixture())
        self.assertEqual({r['campo'] for r in result['pendientes_campos_comunes']}, {'proyecto', 'id_analisis'})
        mapped = next(r for r in result['rutas'] if r['clase_destino'])
        self.assertEqual(mapped['campos_obligatorios_por_definir'], ['id_analisis', 'proyecto'])
        self.assertFalse(mapped['autorizada_para_carga'])

    def test_unmapped_route_not_silently_discarded(self):
        result = build(fixture())
        row = next(r for r in result['rutas'] if not r['clase_destino'])
        self.assertEqual(row['elementos'], 3)
        self.assertEqual(row['estado_plan'], 'DESTINO_PENDIENTE')
        self.assertIn('RUTA_SIN_DESTINO', row['incidencias'])

    def test_matching_unmapped_route_is_not_incomplete_coverage(self):
        data = fixture()
        data[0]['rutas'][1]['estado'] = 'SIN_DESTINO_COINCIDE'
        result = build(data)
        row = next(r for r in result['rutas'] if not r['clase_destino'])
        self.assertNotIn('COBERTURA_RUTA_INCOMPLETA', row['incidencias'])
        self.assertIn('RUTA_SIN_DESTINO', row['incidencias'])
        data[0]['rutas'][1]['observados'] = 2
        data[0]['conteos']['elementos_observados'] = 4
        result = build(data)
        row = next(r for r in result['rutas'] if not r['clase_destino'])
        self.assertIn('COBERTURA_RUTA_INCOMPLETA', row['incidencias'])

    def test_duplicate_route_rejected(self):
        for index in (0, 2):
            data = fixture()
            target = data[0]['rutas'] if index == 0 else data[2]
            target.append(copy.deepcopy(target[0]))
            with self.assertRaisesRegex(ValueError, 'duplicad'):
                build(data)

    def test_wrong_destination_and_total_rejected(self):
        data = fixture()
        data[0]['rutas'][0]['clase'] = 'different'
        with self.assertRaisesRegex(ValueError, 'destino'):
            build(data)
        data = fixture()
        data[0]['conteos']['elementos_observados'] = 9
        with self.assertRaisesRegex(ValueError, 'total'):
            build(data)

    def test_geometry_mismatch_blocks_route(self):
        data = fixture()
        data[1]['clases'][0]['geometria'] = 'POINT'
        result = build(data)
        self.assertIn('GEOMETRIA_INCOMPATIBLE', result['rutas'][0]['incidencias'])

    def test_wrappers_are_observations_plain_description_remains_pending(self):
        data = fixture()
        route = data[0]['campos_destino'][0]['rutas'][0]
        data[0]['incidencias'] = [dict(codigo='CONTENEDOR_XML_SIN_DESTINO', ruta=route, ocurrencias=2),
                                 dict(codigo='ATRIBUTO_SIN_MAPEO', ruta=route, detalle='description', ocurrencias=1)]
        result = build(data)
        self.assertFalse(result['incidencias_fuente'][0]['requiere_decision'])
        self.assertTrue(result['incidencias_fuente'][1]['requiere_decision'])
        self.assertIn('ATRIBUTO_SIN_MAPEO', result['rutas'][0]['incidencias'])
        self.assertNotIn('CONTENEDOR_XML_SIN_DESTINO', result['rutas'][0]['incidencias'])

    def test_extra_route_counted_once(self):
        data = fixture()
        data[0]['rutas_no_inventariadas'] = [dict(archivo='a.kmz', ruta='Extra', geometria='Punto', observados=4)]
        data[0]['conteos']['elementos_observados'] = 9
        result = build(data)
        self.assertEqual(result['resumen']['elementos'], 9)
        self.assertEqual(result['resumen']['elementos_sin_destino'], 7)

    def test_full_reference_counts_office_and_nulls(self):
        here = Path(__file__).resolve().parent
        profile = json.loads((here / 'PERFIL_COMPLETO_KMZ_1_9.json').read_text(encoding='utf-8'))['perfil']
        model = json.loads((here / 'esquema.json').read_text(encoding='utf-8'))
        result = plan.build_plan(profile, model, here)
        self.assertEqual(result['resumen']['rutas'], 3638)
        self.assertEqual(result['resumen']['rutas_sin_destino'], 2601)
        self.assertEqual(result['resumen']['elementos'], 279623)
        self.assertEqual(result['resumen']['elementos_sin_destino'], 140319)
        self.assertEqual(result['resumen']['elementos_con_destino'], 139304)
        self.assertEqual(result['resumen']['reglas_null_definidas'], 3)
        self.assertEqual(result['resumen']['ocurrencias_null_con_regla'], 23)
        self.assertEqual(len(result['incidencias_campos']), 1)
        office = result['incidencias_campos'][0]
        self.assertEqual((office['clase'], office['campo']), ('predios_inscritos_sunarp_recorte', 'oficina_registral'))
        self.assertEqual(office['registros_perfilados'], 288)
        self.assertEqual(office['registros_conflictivos'], 253)
        self.assertEqual(len(result['resumen_clases']), 76)
        self.assertTrue(all(not row['autorizada_para_carga'] for row in result['rutas']))

    def test_office_proposal_preserves_two_attributes_without_deciding_ddl(self):
        here = Path(__file__).resolve().parent
        profile = json.loads((here / 'PERFIL_COMPLETO_KMZ_1_9.json').read_text(encoding='utf-8'))['perfil']
        model = json.loads((here / 'esquema.json').read_text(encoding='utf-8'))
        before = copy.deepcopy(model)
        result = plan.build_plan(profile, model, here)
        self.assertEqual(model, before)
        proposal = result['ajustes_esquema_propuestos'][0]
        self.assertEqual(proposal['operacion'], 'RECONCILIAR_ATRIBUTOS_OFICINA')
        self.assertFalse(proposal['aprobado_ddl'])
        self.assertFalse(proposal['aplicado'])
        self.assertEqual(proposal['tipos_pendientes_nuevos'], 0)
        self.assertEqual({x['nombre'] for x in proposal['campos_actuales_a_reconciliar']},
                         {'oficina', 'oficina_re', 'oficina_1', 'oficina_registral'})
        proposed = proposal['campos_semanticos_propuestos']
        self.assertEqual({x['nombre_propuesto'] for x in proposed},
                         {'oficina_registral_inmueble', 'oficina_registral_persona_juridica'})
        self.assertEqual({x['ocurrencia'] for x in proposed}, {1, 2})
        self.assertTrue(all(x['tipo'] == 'TEXT' and x['longitud'] == 4000 for x in proposed))
        self.assertTrue(all(x['operacion_fisica'] == 'POR_DEFINIR_TRAS_RECONCILIAR_CAMPOS_EXISTENTES' for x in proposed))
        # The conflict remains until the correspondence is actually reconciled.
        self.assertEqual(result['incidencias_campos'][0]['registros_conflictivos'], 253)


if __name__ == '__main__':
    unittest.main()
