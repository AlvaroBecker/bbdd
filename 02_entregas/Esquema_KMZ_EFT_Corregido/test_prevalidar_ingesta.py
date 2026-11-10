"""Integracion del plan 1.10: consulta de 76 clases, fuentes y reportes sin DDL."""
import copy
from contextlib import ExitStack, nullcontext
import csv
import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import prevalidar_ingesta as tool


class Cursor:
    def __init__(self, values):
        self.values = values

    def __enter__(self):
        return iter(self.values)

    def __exit__(self, *args):
        return False


class ReadFixture:
    """Modelo real y llamadas reales del inspector; todas las mutaciones fallan."""
    def __init__(self, root, model):
        self.workspace = os.path.abspath(str(root / 'fixture.gdb'))
        self.ds = os.path.join(self.workspace, 'Datos_Proyecto')
        self.parent = os.path.join(self.workspace, 'mline_tc_proyecto')
        self.paths = {c['nombre']: os.path.join(self.ds, c['nombre']) for c in model['clases']}
        self.calls, self.mutations, self.fields, self.counts = [], [], {}, {}
        self.descriptions = {self.workspace: SimpleNamespace(workspaceType='LocalDatabase'),
            self.ds: SimpleNamespace(dataType='FeatureDataset', spatialReference=SimpleNamespace(factoryCode=4326)),
            self.parent: SimpleNamespace(hasOID=True)}
        for c in model['clases']:
            path = self.paths[c['nombre']]
            self.fields[path] = [self.field(f['nombre'], tool.runner.engine.TYPE[f['tipo']],
                 f.get('longitud') or 0, f['nullable'], f.get('dominio') or '') for f in c['campos']]
            self.fields[path].extend([self.field('OBJECTID', 'OID'), self.field('Shape', 'Geometry'),
                                      self.field('GlobalID', 'GlobalID')])
            self.counts[path] = 0
            self.descriptions[path] = SimpleNamespace(dataType='FeatureClass', path=self.ds,
                shapeType=c['geometria'], spatialReference=SimpleNamespace(factoryCode=4326),
                hasZ=True, hasM=False, hasGlobalID=True, editorTrackingEnabled=True, isTimeInUTC=True,
                isVersioned=False, relationshipClassNames=[])
        self.fields[self.parent] = [self.field('co_proyecto', 'String', 12), self.field('no_proyecto', 'String', 128)]
        self.projects = [{'co_proyecto': 'PRY-00000005', 'no_proyecto': 'Chanchamayo'}]
        self.domains = [SimpleNamespace(name=name, type='Text', domainType='CodedValue',
            codedValues={v: v for v in spec['valores']}) for name, spec in model['dominios'].items()]
        self.da = SimpleNamespace(ListDomains=lambda _: self.domains, SearchCursor=self.SearchCursor,
                                  InsertCursor=self.deny, UpdateCursor=self.deny)
        self.management = SimpleNamespace(GetCount=self.GetCount, AlterField=self.deny,
            CreateFeatureclass=self.deny, AddField=self.deny, Delete=self.deny, Append=self.deny)

    @staticmethod
    def field(name, kind, length=0, nullable=True, domain=''):
        return SimpleNamespace(name=name, baseName=name, type=kind, length=length,
                               isNullable=nullable, domain=domain)

    def deny(self, *args, **kwargs):
        self.mutations.append((args, kwargs))
        raise AssertionError('Mutacion GIS prohibida en la prevalidacion')

    def GetInstallInfo(self):
        return {'Version': 'SIMULADA_SOLO_LECTURA'}

    def EnvManager(self, **kwargs):
        self.calls.append(('EnvManager', kwargs))
        return nullcontext()

    def Exists(self, path):
        return path in self.descriptions

    def Describe(self, path):
        return self.descriptions[path]

    def ListFields(self, path):
        self.calls.append(('ListFields', path))
        return self.fields[path]

    def ListDatasets(self, **kwargs):
        return ['Datos_Proyecto']

    def ListFeatureClasses(self, feature_dataset=''):
        return list(self.paths) if feature_dataset else []

    def ListTables(self):
        return ['mline_tc_proyecto']

    def ValidateTableName(self, name, workspace):
        return name

    def ValidateFieldName(self, name, workspace):
        return name

    def SearchCursor(self, path, fields):
        self.calls.append(('SearchCursor', path, fields))
        assert path == self.parent
        return Cursor([[r[f] for f in fields] for r in self.projects])

    def GetCount(self, path):
        self.calls.append(('GetCount', path))
        return SimpleNamespace(getOutput=lambda _: str(self.counts[path]))


class PrevalidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.package = Path(tool.__file__).parent
        cls.actual_model = json.loads((cls.package / 'esquema.json').read_text(encoding='utf-8-sig'))

    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.sources = self.root / 'fuentes'
        self.sources.mkdir()
        self.model = copy.deepcopy(self.actual_model)
        (self.root / 'esquema.json').write_text(json.dumps(self.model), encoding='utf-8')
        self.a = ReadFixture(self.root, self.model)
        self.profile = dict(fuentes=[], rutas=[], campos_destino=[], campos_fuente=[],
                            incidencias=[], rutas_no_inventariadas=[], conteos=dict(elementos_observados=13))
        catalog = []
        cls = next(c for c in self.model['clases'] if c['nombre'] == 'subestacion_poligono')
        for index in range(13):
            filename = ('Proyecto CHANCHAMAYO.kmz' if index == 0 else f'Fuente_{index:02d}.kmz')
            content = f'CONTENIDO_SINTETICO_{index}'.encode()
            (self.sources / filename).write_bytes(content)
            self.profile['fuentes'].append({'archivo': filename, 'sha256': hashlib.sha256(content).hexdigest()})
            route = dict(archivo=filename, ruta='Capa sintetica', geometria='Pol\u00edgono')
            destination = cls['nombre'] if index % 2 == 0 else ''
            self.profile['rutas'].append(dict(**route, clase=destination, esperados=1, observados=1, estado='COINCIDE'))
            catalog.append(dict(**route, clase_propuesta=destination, elementos=1))
        self.write_csv('mapeo_capas_revision.csv', catalog)
        self.write_csv('campos_por_ruta.csv', [], ['archivo', 'ruta', 'geometria', 'clase_destino', 'campo_destino'])
        self.messages = []

    def write_csv(self, name, rows, columns=None):
        path = self.root / name
        with path.open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=columns or list(rows[0]), delimiter=';')
            writer.writeheader()
            writer.writerows(rows)
        return path

    def mapping(self):
        return self.write_csv('proyectos.csv', [dict(archivo_kmz=s['archivo'], co_proyecto='PRY-00000005',
                                                     confirmado='si') for s in self.profile['fuentes']])

    def patches(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        # Exact reference/schema lineage is tested elsewhere. These fixtures only
        # replace the archive envelope while exercising source/plan/project APIs.
        stack.enter_context(patch.object(tool, 'reference_hashes', return_value={'referencia': 'fija'}))
        stack.enter_context(patch.object(tool.validation, 'validated_model', side_effect=lambda _, m: m))
        stack.enter_context(patch.object(tool.validation, 'read_profile_snapshot',
            side_effect=lambda _: ({'perfil': copy.deepcopy(self.profile), 'generado_utc': 'ENSAYO'}, 'hash_archivado')))
        return stack

    def run_tool(self, **kwargs):
        with self.patches():
            return tool.run(self.a.workspace, self.sources, reports=self.root, model_dir=self.root,
                            arcpy_module=self.a, emit=self.messages.append, **kwargs)

    def latest(self):
        files = list(self.root.glob('Preingesta_*/resultado.json'))
        self.assertEqual(len(files), 1)
        return json.loads(files[0].read_text(encoding='utf-8'))

    def test_complete_sources_and_3340_fields_still_not_ready_for_ingestion(self):
        before = copy.deepcopy(self.a.fields)
        _, report = self.run_tool()
        self.assertEqual(report['estado'], 'PLAN_INGESTA_CON_PENDIENTES')
        self.assertEqual(report['destino']['campos_verificados'], 3340)
        self.assertEqual(len(report['destino']['recuentos']), 76)
        self.assertTrue(report['fuentes']['verificado'])
        self.assertFalse(report['ingesta_autorizada'])
        self.assertFalse(report['cambios_en_sde'])
        self.assertEqual(report['registros_insertados'], 0)
        self.assertEqual(report['proyectos']['confirmados'], 0)
        self.assertTrue(all(not r['cargable'] and not r['autorizada_para_carga'] for r in report['plan']['rutas']))
        self.assertEqual(self.a.fields, before)
        self.assertEqual(self.a.mutations, [])

    def test_readonly_facade_hides_all_mutation_entrypoints(self):
        a = tool.ReadOnlyArcPy(self.a)
        for obj, name in [(a.management, 'AlterField'), (a.management, 'CreateFeatureclass'),
                          (a.management, 'Delete'), (a.management, 'Append'),
                          (a.da, 'InsertCursor'), (a.da, 'UpdateCursor'), (a, 'CopyFeatures_management')]:
            with self.subTest(name=name), self.assertRaises(AttributeError):
                getattr(obj, name)
        self.assertEqual(self.a.mutations, [])

    def test_nine_sources_does_not_certify_archived_values_as_current(self):
        for s in self.profile['fuentes'][9:]:
            (self.sources / s['archivo']).unlink()
        _, report = self.run_tool()
        self.assertEqual(report['estado'], 'PREVALIDACION_INGESTA_INCOMPLETA')
        self.assertEqual(len(report['fuentes']['ausentes']), 4)
        self.assertFalse(report['evidencia_valores_actuales'])
        self.assertTrue(all(not r['evidencia_actual_verificada'] for r in report['plan']['rutas']))
        self.assertEqual(len(report['plan']['rutas']), 13)

    def test_inventory_changed_midrun_writes_failure_report(self):
        original = tool.fuentes_ingesta.discover_sources
        calls = []

        def changing(*args, **kwargs):
            calls.append(1)
            if len(calls) == 2:
                (self.sources / 'nuevo.kmz').write_bytes(b'OTRO_CONTENIDO')
            return original(*args, **kwargs)

        with patch.object(tool.fuentes_ingesta, 'discover_sources', side_effect=changing):
            with self.assertRaisesRegex(ValueError, 'inventario cambiaron'):
                self.run_tool()
        report = self.latest()
        self.assertEqual(report['estado'], 'ERROR_DETENIDO')
        self.assertFalse(report['ingesta_autorizada'])
        self.assertIn('inventario cambiaron', report['error'])

    def test_mapping_changed_midrun_writes_failure_report(self):
        path = self.mapping()
        original = tool.proyectos_ingesta.plan_projects

        def changing(*args, **kwargs):
            result = original(*args, **kwargs)
            path.write_text(path.read_text(encoding='utf-8-sig') + '\n', encoding='utf-8-sig')
            return result

        with patch.object(tool.proyectos_ingesta, 'plan_projects', side_effect=changing):
            with self.assertRaisesRegex(ValueError, 'CSV de proyectos'):
                self.run_tool(project_csv=path)
        self.assertEqual(self.latest()['estado'], 'ERROR_DETENIDO')

    def test_confirmation_routes_only_receive_explicit_existing_keys(self):
        _, report = self.run_tool(project_csv=self.mapping())
        self.assertTrue(report['proyectos']['verificado'])
        self.assertTrue(report['correspondencias_proyecto_verificadas'])
        self.assertTrue(all(r['co_proyecto'] == 'PRY-00000005' for r in report['plan']['rutas']))
        self.assertTrue(all(r['proyecto_confirmado'] for r in report['plan']['rutas']))
        self.assertTrue(all(not r['autorizada_para_carga'] for r in report['plan']['rutas']))
        with Path(report['archivos_csv']['confirmar_proyectos.csv']).open(encoding='utf-8-sig', newline='') as stream:
            rows = list(csv.DictReader(stream, delimiter=';'))
        self.assertEqual(len(rows), 13)
        self.assertEqual(set(rows[0]), {'archivo_kmz', 'co_proyecto', 'confirmado'})
        self.assertTrue(all(r['confirmado'] == 'si' for r in rows))

    def test_unconfirmed_name_candidates_leave_keys_empty_in_routes_and_template(self):
        _, report = self.run_tool()
        self.assertEqual(report['proyectos']['asociaciones'][0]['candidatos'][0]['co_proyecto'], 'PRY-00000005')
        self.assertTrue(all(not r['co_proyecto'] for r in report['plan']['rutas']))
        with Path(report['archivos_csv']['confirmar_proyectos.csv']).open(encoding='utf-8-sig', newline='') as stream:
            rows = list(csv.DictReader(stream, delimiter=';'))
        self.assertTrue(all(not r['co_proyecto'] and r['confirmado'] == 'no' for r in rows))

    def test_destination_field_difference_does_not_claim_complete(self):
        cls = self.model['clases'][0]['nombre']
        self.a.fields[self.a.paths[cls]][0].type = 'INCORRECTO'
        _, report = self.run_tool()
        self.assertEqual(report['estado'], 'PREVALIDACION_INGESTA_INCOMPLETA')
        self.assertFalse(report['destino']['verificado'])
        self.assertEqual(report['destino']['campos_verificados'], 3339)

    def test_changed_source_bytes_do_not_reuse_archived_values_as_current(self):
        source = self.profile['fuentes'][0]
        (self.sources / source['archivo']).write_bytes(b'CONTENIDO_CAMBIADO')
        _, report = self.run_tool()
        self.assertEqual(report['estado'], 'PREVALIDACION_INGESTA_INCOMPLETA')
        self.assertFalse(report['evidencia_valores_actuales'])
        self.assertEqual(len(report['fuentes']['conflictos_nombre']), 1)
        self.assertEqual(len(report['fuentes']['ausentes']), 1)

    def test_parent_key_integrity_blocks_complete_prevalidation(self):
        self.a.projects.append(dict(self.a.projects[0]))
        _, report = self.run_tool()
        self.assertFalse(report['catalogo_proyectos']['verificado'])
        self.assertEqual(report['estado'], 'PREVALIDACION_INGESTA_INCOMPLETA')
        self.assertEqual(report['proyectos']['confirmados'], 0)

    def test_extra_destination_field_is_structural_incident(self):
        path = next(iter(self.a.paths.values()))
        self.a.fields[path].append(self.a.field('campo_ajeno', 'String', 20))
        _, report = self.run_tool()
        self.assertEqual(report['estado'], 'PREVALIDACION_INGESTA_INCOMPLETA')
        self.assertEqual(report['destino']['incidencias_preingesta'][0]['motivo'], 'CAMPOS_FUERA_MODELO')
        self.assertEqual(self.a.mutations, [])

    def test_destination_missing_raises_after_writing_report(self):
        del self.a.descriptions[self.a.workspace]
        with self.assertRaisesRegex(ValueError, 'no se encuentra'):
            self.run_tool()
        report = self.latest()
        self.assertEqual(report['estado'], 'ERROR_DETENIDO')
        self.assertIsNone(report['destino'])
        self.assertTrue(Path(report['archivo_informe']).is_file())

    def test_nonempty_destination_is_retained_as_incident(self):
        self.a.counts[next(iter(self.a.counts))] = 12
        _, report = self.run_tool()
        self.assertEqual(report['destino']['registros_existentes'], 12)
        self.assertEqual(report['destino']['incidencias_preingesta'][0]['motivo'], 'DESTINO_CON_REGISTROS')
        self.assertFalse(report['ingesta_autorizada'])
        self.assertEqual(self.a.mutations, [])


if __name__ == '__main__':
    unittest.main()
