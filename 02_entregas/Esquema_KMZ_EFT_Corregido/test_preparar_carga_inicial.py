"""Pruebas de cierre de reglas, ausencia de escrituras y protección de evidencia."""
import copy
import csv
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import preparar_carga_inicial as runtime
import descripciones_ingesta as descriptions

HERE = Path(__file__).resolve().parent


class PreparationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = json.loads((HERE/'esquema.json').read_text(encoding='utf-8-sig'))
        cls.envelope, cls.fingerprint = runtime.validation.read_profile_snapshot(HERE)
        cls.base = runtime.plan_ingesta.build_plan(cls.envelope['perfil'], cls.model, model_dir=HERE)
        with (HERE/'confirmar_proyectos_13_confirmados.csv').open(encoding='utf-8-sig', newline='') as stream:
            rows = list(csv.DictReader(stream, delimiter=';'))
        cls.projects = dict(verificado=True, asociaciones=[dict(archivo_kmz=r['archivo_kmz'],
            co_proyecto=r['co_proyecto'], confirmado=True) for r in rows])
        cls.rules = runtime.sunarp.load_rules()
        cls.desc = descriptions.load_plan(current_sources_verified=True)

    def test_actual_package_closes_152_rules_preserving_four_ids_and_inputs(self):
        before = copy.deepcopy(self.base)
        plan = runtime.common_rules(self.base, self.projects, self.model, True)
        self.assertEqual(len(plan['reglas_campos_comunes']), 152)
        self.assertEqual(len(plan['pendientes_campos_comunes']), 4)
        self.assertEqual(self.base, before)
        self.assertTrue(all(r['co_proyecto'] and r['id_analisis']=='Carga inicial KMZ' for r in plan['rutas']))
        self.assertTrue(all(not r['cargable'] and not r['autorizada_para_carga'] for r in plan['rutas']))

    def test_source_changes_do_not_confirm_projects_from_archive(self):
        plan = runtime.common_rules(self.base, self.projects, self.model, False)
        self.assertEqual(len(plan['reglas_campos_comunes']), 76)
        self.assertEqual(len(plan['pendientes_campos_comunes']), 80)
        self.assertTrue(all(not r['co_proyecto'] for r in plan['rutas']))
        self.assertTrue(all('FUENTES_ACTUALES_NO_VERIFICADAS' in r['incidencias'] for r in plan['rutas']))

    def test_unconfirmed_project_catalog_never_closes_project_rules(self):
        projects = copy.deepcopy(self.projects)
        projects['verificado'] = False
        plan = runtime.common_rules(self.base, projects, self.model, True)
        self.assertEqual(len(plan['pendientes_campos_comunes']), 80)

    def test_duplicated_association_and_wrong_analysis_type_are_rejected(self):
        projects = copy.deepcopy(self.projects)
        projects['asociaciones'].append(projects['asociaciones'][0])
        with self.assertRaisesRegex(ValueError, 'duplicadas'):
            runtime.common_rules(self.base, projects, self.model, True)
        model = copy.deepcopy(self.model)
        for f in model['clases'][0]['campos']:
            if f['nombre']=='id_analisis': f['tipo']='LONG'
        with self.assertRaisesRegex(ValueError, 'id_analisis'):
            runtime.common_rules(self.base, self.projects, model, True)

    def test_sunarp_and_23_html_routes_are_resolved_by_precise_rules_only(self):
        plan = copy.deepcopy(self.base)
        other = copy.deepcopy(next(r for r in plan['incidencias_fuente'] if r['codigo']=='VALORES_CONFLICTIVOS'))
        other['detalle'] = 'predios_inscritos_sunarp_recorte.otro_campo'
        plan['incidencias_fuente'].append(other)
        runtime.reconcile_plan_issues(plan, self.rules, self.desc, True)
        self.assertEqual(len(plan['resoluciones_incidencias']), 25)
        self.assertTrue(other['requiere_decision'])
        self.assertEqual(plan['incidencias_campos'], [])
        self.assertTrue(any('VALORES_CONFLICTIVOS' in r['incidencias'] for r in plan['rutas']))
        self.assertEqual(len([r for r in plan['incidencias_fuente'] if r.get('regla')]),25)

    def test_no_issue_resolved_against_unverified_or_changed_evidence(self):
        plan = copy.deepcopy(self.base)
        runtime.reconcile_plan_issues(plan, self.rules, self.desc, False)
        self.assertEqual(len(plan['incidencias_campos']),1)
        rules = copy.deepcopy(self.rules)
        rules['evidencia']['distintos'] += 1
        with self.assertRaisesRegex(ValueError,'evidencia'):
            runtime.reconcile_plan_issues(plan, rules, self.desc, True)

    def test_description_is_not_discarded_or_truncated(self):
        self.assertEqual(len(self.desc['rutas']),59)
        self.assertEqual(self.desc['resumen']['registros'],1403)
        self.assertEqual(sum(r['estado_efectivo']=='CONTENIDO_EN_ATRIBUTOS_MAS_REGLAS_SISTEMA'
                             for r in self.desc['rutas']),23)
        spec={'tipo':'TEXT','longitud':3}
        value='á😀'
        self.assertEqual(descriptions.preserve_plain_text(value,spec),value)
        with self.assertRaisesRegex(ValueError,'trunca'):
            descriptions.preserve_plain_text(value+'x',spec)
        with self.assertRaisesRegex(ValueError,'Colisión'):
            descriptions.preserve_plain_text(value,spec,existing='')
        self.assertEqual(descriptions.preserve_plain_text(value,spec,existing=value),value)

    def test_description_evidence_changes_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)
            (path/'descripciones_1_13.json').write_text(json.dumps({'referencias_sha256':{'esquema.json':'x'}}))
            (path/'esquema.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'modificada'):
                descriptions.load_plan(path)

    def test_reports_cannot_be_written_inside_geodatabase(self):
        with tempfile.TemporaryDirectory(suffix='.gdb') as tmp:
            with self.assertRaisesRegex(ValueError,'fuera'):
                runtime.run('x.sde',tmp,reports=tmp)
            self.assertEqual(list(Path(tmp).iterdir()),[])

    def test_error_report_does_not_claim_rules_were_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError,'conexion'):
                runtime.run(None,tmp,reports=tmp,emit=lambda _:None)
            report=json.loads(next(Path(tmp).rglob('resultado.json')).read_text(encoding='utf-8'))
            self.assertEqual(report['estado'],'ERROR_DETENIDO')
            self.assertFalse(report['cambios_en_sde'])
            self.assertIn('Reglas SUNARP verificadas en esta ejecucion: False',
                next(Path(tmp).rglob('informe.txt')).read_text(encoding='utf-8'))


if __name__=='__main__': unittest.main()
