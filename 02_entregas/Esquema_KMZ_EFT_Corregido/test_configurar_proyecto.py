"""Guardas y reanudacion de la configuracion; no sustituye un ensayo SDE."""
import copy
import datetime as dt
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

import configurar_proyecto as runtime
from test_alta_proyectos import FakeArcPy, field


class ConfigArcPy(FakeArcPy):
    def __init__(self, workspace):
        super().__init__(workspace)
        self.schema_calls = []
        self.lock_available = True
        self.fail_schema_at = None
        self.after_schema = None
        self.fields = [f for f in self.fields if f.name not in runtime.NATIVE]
        self.fields += [field('fe_creacion', 'Date'), field('fe_actualizacion', 'Date'),
                        field('us_actualizacion'), field('ip_creacion')]
        for f in self.fields:
            self.complete_field(f)
            f.domain = ''
        self.domains = {}
        self.table_description.editorTrackingEnabled = False
        for key in runtime.TRACKING:
            setattr(self.table_description, key, '')
        self.rows = []
        for identifier in range(1, 41):
            self.add_existing(identifier)
        for row in self.rows:
            for name in runtime.NATIVE:
                row.pop(name, None)
            row.update(fe_creacion=dt.datetime(2020, 1, 1, 13, 5, 23),
                       fe_actualizacion=dt.datetime(2021, 2, 3, 17, 2, 11),
                       us_actualizacion='editor legado', ip_creacion='IP_CONSERVADA')
        self.management = NS(CreateDomain=self.create_domain,
            AddCodedValueToDomain=self.add_code, AssignDomainToField=self.assign_domain,
            AddField=self.add_field, EnableEditorTracking=self.enable_tracking)

    @staticmethod
    def complete_field(f):
        f.precision = 0
        f.scale = 0
        f.aliasName = f.name
        f.required = f.type in ('OID', 'GlobalID')
        return f

    def ListFields(self, _):
        # Describe/ListFields son observaciones, no referencias vivas mutables.
        return copy.deepcopy(self.fields)

    def TestSchemaLock(self, _):
        return self.lock_available

    def begin_step(self, action, *args):
        self.schema_calls.append((action, *args))
        if len(self.schema_calls) == self.fail_schema_at:
            raise RuntimeError('fallo de esquema simulado')

    def end_step(self):
        if self.after_schema:
            self.after_schema(self)

    def create_domain(self, workspace, name, description, kind, domain_type, split, merge):
        self.begin_step('CreateDomain', name)
        if kind != 'LONG' or domain_type != 'CODED':
            raise AssertionError('Tipo de dominio no autorizado')
        self.domains[name] = NS(name=name, domainType='CodedValue', type='Long',
                               owner='gis', codedValues={})
        self.end_step()

    def add_code(self, workspace, name, code, label):
        self.begin_step('AddCodedValueToDomain', name, code)
        self.domains[name].codedValues[code] = label
        self.end_step()

    def assign_domain(self, path, name, domain):
        self.begin_step('AssignDomainToField', name, domain)
        next(f for f in self.fields if f.name == name).domain = domain
        self.end_step()

    def add_field(self, path, name, kind, **kwargs):
        self.begin_step('AddField', name, kind)
        if kwargs['field_is_nullable'] != 'NULLABLE' or kwargs['field_is_required'] != 'NON_REQUIRED':
            raise AssertionError('Los campos de auditoria deben admitir NULL historico')
        f = field(name, 'String' if kind == 'TEXT' else 'Date', kwargs.get('field_length', 0))
        self.fields.append(self.complete_field(f))
        for row in self.rows:
            row[name] = None
        self.end_step()

    def enable_tracking(self, path, creator, created, editor, edited, add_fields, time_standard):
        self.begin_step('EnableEditorTracking', creator, created, editor, edited, add_fields, time_standard)
        if add_fields != 'NO_ADD_FIELDS' or time_standard != 'UTC':
            raise AssertionError('Tracking debe usar cuatro campos ya verificados y UTC')
        self.table_description.editorTrackingEnabled = True
        self.table_description.isTimeInUTC = True
        for key, name in zip(runtime.TRACKING, (creator, created, editor, edited)):
            setattr(self.table_description, key, name)
        self.end_step()

    def native_field(self, name, *, nonempty=False, kind=None, length=None):
        expected_kind, expected_length = runtime.NATIVE[name]
        f = field(name, kind or ('String' if expected_kind == 'TEXT' else 'Date'),
                  length if length is not None else (expected_length or 0))
        self.fields.append(self.complete_field(f))
        for row in self.rows:
            row[name] = ('origen sin zona' if f.type == 'String' else dt.datetime(2020, 1, 1)) if nonempty else None
        return f

    def domain(self, name, codes, *, assigned_to=None, owner='gis'):
        self.domains[name] = NS(name=name, type='Long', domainType='CodedValue',
                               codedValues=dict(codes), owner=owner)
        if assigned_to:
            next(f for f in self.fields if f.name == assigned_to).domain = name
        return self.domains[name]


class ConfigureProjectTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='configurar_proyecto_')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.workspace = os.path.abspath(str(self.root / 'destino.sde'))
        self.api = ConfigArcPy(self.workspace)
        self.messages = []
        self.last_folder = None

    def run_tool(self, **kwargs):
        old = set(self.root.glob('Configuracion_Proyectos_*'))
        try:
            return runtime.run(self.workspace, reports=self.root, arcpy_module=self.api,
                               emit=self.messages.append, **kwargs)
        finally:
            new = set(self.root.glob('Configuracion_Proyectos_*')) - old
            if new:
                self.last_folder = new.pop()

    def report(self):
        return json.loads((self.last_folder / 'resultado.json').read_text(encoding='utf-8'))

    def original_values(self, names):
        return [{name: row[name] for name in names} for row in self.api.rows]

    def test_config_retains_complete_original_catalog(self):
        config, digest = runtime.read_config()
        self.assertEqual(len(digest), 64)
        self.assertEqual({d['campo']: {c['codigo'] for c in d['codigos']} for d in config['dominios']},
                         {'id_tipo_proyecto': {7, 8}, 'id_estado_proyecto': {3, 4, 5, 6}})
        modified = copy.deepcopy(config)
        modified['dominios'][0]['codigos'][0]['codigo'] = 99
        (self.root / 'configuracion_proyecto_1_12.json').write_text(json.dumps(modified), encoding='utf-8')
        with patch.object(runtime, 'HERE', self.root):
            with self.assertRaisesRegex(ValueError, 'Catalogo'):
                runtime.read_config()

    def test_validation_is_readonly_and_includes_all_codes(self):
        before_fields, before_rows = copy.deepcopy(self.api.fields), copy.deepcopy(self.api.rows)
        self.api.rows[0]['id_tipo_proyecto'] = 7
        self.api.rows[1]['id_estado_proyecto'] = 4
        self.api.rows[2]['id_estado_proyecto'] = 5
        self.api.rows[3]['id_estado_proyecto'] = 6
        before_rows = copy.deepcopy(self.api.rows)
        _, report = self.run_tool()
        self.assertEqual(report['estado'], 'CONFIGURACION_PENDIENTE_APROBACION_AUDITORIA')
        self.assertEqual(self.api.schema_calls, [])
        self.assertEqual(self.api.rows, before_rows)
        self.assertEqual([f.__dict__ for f in self.api.fields], [f.__dict__ for f in before_fields])
        added_codes = {step['codigo'] for step in report['plan']['operaciones'] if step['accion'] == 'AGREGAR_CODIGO'}
        self.assertEqual(added_codes, {3, 4, 5, 6, 7, 8})

    def test_apply_without_approval_stops_before_any_schema_write(self):
        with self.assertRaisesRegex(ValueError, 'Falta aprobar'):
            self.run_tool(apply=True)
        self.assertEqual(self.api.schema_calls, [])
        self.assertEqual(self.report()['estado'], 'ERROR_SIN_CAMBIOS')
        self.assertEqual(self.report()['cambios_intentados'], 0)

    def test_unavailable_schema_lock_stops_before_any_schema_write(self):
        self.api.lock_available = False
        with self.assertRaisesRegex(ValueError, 'bloqueo de esquema'):
            self.run_tool(apply=True, approve_native_audit=True)
        self.assertEqual(self.api.schema_calls, [])

    def test_apply_preserves_every_legacy_value_and_uses_native_utc(self):
        before = copy.deepcopy(self.api.rows)
        names = [f.name for f in self.api.fields]
        _, report = self.run_tool(apply=True, approve_native_audit=True)
        self.assertEqual(report['estado'], 'CONFIGURACION_PROYECTO_VERIFICADA')
        self.assertEqual(self.original_values(names), before)
        self.assertEqual({f.name for f in self.api.fields} - set(names), set(runtime.NATIVE))
        self.assertTrue(all(row[name] is None for row in self.api.rows for name in runtime.NATIVE))
        self.assertEqual(report['campos_nativos_creados'], 4)
        self.assertTrue(self.api.table_description.isTimeInUTC)
        self.assertEqual(self.api.editor_calls, 0)
        self.assertEqual(self.api.insert_calls, 0)
        self.assertEqual(self.report()['proyectos_insertados'], 0)

    def test_repeat_is_noop_and_does_not_require_new_approval(self):
        self.run_tool(apply=True, approve_native_audit=True)
        old_calls = list(self.api.schema_calls)
        old_rows = copy.deepcopy(self.api.rows)
        _, report = self.run_tool(apply=True)
        self.assertEqual(report['estado'], 'CONFIGURACION_PROYECTO_VERIFICADA')
        self.assertEqual(report['pasos_ejecutados'], [])
        self.assertEqual(self.api.schema_calls, old_calls)
        self.assertEqual(self.api.rows, old_rows)

    def test_invalid_historical_parameter_blocks_before_ddl(self):
        for name, value in [('id_tipo_proyecto', 9), ('id_estado_proyecto', 0)]:
            with self.subTest(name=name):
                original = self.api.rows[0][name]
                self.api.rows[0][name] = value
                with self.assertRaisesRegex(ValueError, 'fuera del catalogo'):
                    self.run_tool(apply=True, approve_native_audit=True)
                self.api.rows[0][name] = original
        self.assertEqual(self.api.schema_calls, [])

    def test_incompatible_domain_is_never_rewritten(self):
        domain = self.api.domain('mline_proyecto_tipo', {7: 'OTRO SIGNIFICADO', 8: 'Linea'} )
        original = copy.deepcopy(domain.codedValues)
        with self.assertRaisesRegex(ValueError, 'incompatibles'):
            self.run_tool(apply=True, approve_native_audit=True)
        self.assertEqual(self.api.schema_calls, [])
        self.assertEqual(domain.codedValues, original)

    def test_complete_equivalent_assigned_domains_are_reused(self):
        self.api.domain('otro_tipo', runtime.EXPECTED_DOMAINS['id_tipo_proyecto'], assigned_to='id_tipo_proyecto')
        self.api.domain('otro_estado', runtime.EXPECTED_DOMAINS['id_estado_proyecto'], assigned_to='id_estado_proyecto')
        _, report = self.run_tool()
        self.assertFalse(any('DOMINIO' in step['accion'] or step['accion'] == 'AGREGAR_CODIGO'
                             for step in report['plan']['operaciones']))

    def test_integer_alias_for_long_domains_is_also_supported(self):
        for name, target in [('tipo', 'id_tipo_proyecto'), ('estado', 'id_estado_proyecto')]:
            domain = self.api.domain(name, runtime.EXPECTED_DOMAINS[target], assigned_to=target)
            domain.type = 'Integer'
        _, report = self.run_tool()
        self.assertFalse(any('DOMINIO' in step['accion'] or step['accion'] == 'AGREGAR_CODIGO'
                             for step in report['plan']['operaciones']))

    def test_partial_domain_of_other_owner_is_not_extended(self):
        self.api.domain('mline_proyecto_tipo', {8: runtime.EXPECTED_DOMAINS['id_tipo_proyecto'][8]}, owner='otro')
        with self.assertRaisesRegex(ValueError, 'otro propietario'):
            self.run_tool(apply=True, approve_native_audit=True)
        self.assertEqual(self.api.schema_calls, [])

    def test_existing_audit_field_type_length_precision_and_content_are_guarded(self):
        checks = [('created_user', dict(kind='Integer'), 'incompatible'),
                  ('created_user', dict(length=10), 'incompatible'),
                  ('created_user', dict(nonempty=True), 'contiene valores'),
                  ('created_date', dict(nonempty=True), 'contiene valores')]
        for name, kwargs, text in checks:
            with self.subTest(name=name, kwargs=kwargs):
                self.api = ConfigArcPy(self.workspace)
                self.api.native_field(name, **kwargs)
                with self.assertRaisesRegex(ValueError, text):
                    self.run_tool(apply=True, approve_native_audit=True)
                self.assertEqual(self.api.schema_calls, [])
        self.api = ConfigArcPy(self.workspace)
        self.api.native_field('created_date').precision = 1
        with self.assertRaisesRegex(ValueError, 'precision baja'):
            self.run_tool(apply=True, approve_native_audit=True)
        self.assertEqual(self.api.schema_calls, [])

    def test_native_audit_field_must_allow_historical_nulls(self):
        self.api.native_field('created_user').isNullable = False
        with self.assertRaisesRegex(ValueError, 'NULL|nullable|obligatorio'):
            self.run_tool(apply=True, approve_native_audit=True)
        self.assertEqual(self.api.schema_calls, [])

    def test_compatible_empty_native_field_is_reused(self):
        self.api.native_field('created_user')
        _, report = self.run_tool(apply=True, approve_native_audit=True)
        self.assertEqual(report['campos_nativos_creados'], 3)
        self.assertFalse(any(c[0] == 'AddField' and c[1] == 'created_user' for c in self.api.schema_calls))

    def test_other_tracking_configuration_is_not_disabled(self):
        self.run_tool(apply=True, approve_native_audit=True)
        self.api.table_description.creatorFieldName = 'us_creacion'
        count = len(self.api.schema_calls)
        with self.assertRaisesRegex(ValueError, 'otra configuracion'):
            self.run_tool(apply=True, approve_native_audit=True)
        self.assertEqual(len(self.api.schema_calls), count)

    def test_partial_ddl_reports_no_rollback_and_retries_only_missing_steps(self):
        before = copy.deepcopy(self.api.rows)
        self.api.fail_schema_at = 6
        with self.assertRaisesRegex(RuntimeError, 'fallo de esquema'):
            self.run_tool(apply=True, approve_native_audit=True)
        report = self.report()
        self.assertEqual(report['estado'], 'CONFIGURACION_DETENIDA_CON_PASOS_A_REVISAR')
        self.assertFalse(report['rollback_automatico'])
        self.assertEqual(len(report['pasos_ejecutados']), 5)
        self.assertEqual(report['cambios_intentados'], 6)
        self.assertEqual(self.api.rows, before)
        created_domains = [c for c in self.api.schema_calls if c[0] == 'CreateDomain']
        self.api.fail_schema_at = None
        _, final = self.run_tool(apply=True, approve_native_audit=True)
        self.assertEqual(final['estado'], 'CONFIGURACION_PROYECTO_VERIFICADA')
        self.assertEqual([c for c in self.api.schema_calls if c[0] == 'CreateDomain'], created_domains)

    def test_unexpected_row_edit_stops_remaining_steps(self):
        self.api.after_schema = lambda api: api.rows[0].update(us_creacion='CAMBIO NO AUTORIZADO')
        with self.assertRaisesRegex(ValueError, 'filas historicas'):
            self.run_tool(apply=True, approve_native_audit=True)
        self.assertEqual(len(self.api.schema_calls), 1)
        self.assertFalse(self.report()['rollback_automatico'])

    def test_unexpected_field_edit_stops_remaining_steps(self):
        def mutate(api):
            next(f for f in api.fields if f.name == 'no_proyecto').length = 400
        self.api.after_schema = mutate
        with self.assertRaisesRegex(ValueError, 'campo preexistente'):
            self.run_tool(apply=True, approve_native_audit=True)
        self.assertEqual(len(self.api.schema_calls), 1)

    def test_unexpected_domain_edit_on_another_field_is_detected(self):
        def mutate(api):
            next(f for f in api.fields if f.name == 'es_registro').domain = 'NO_AUTORIZADO'
        self.api.after_schema = mutate
        with self.assertRaisesRegex(ValueError, 'dominio|Dominio'):
            self.run_tool(apply=True, approve_native_audit=True)
        self.assertEqual(len(self.api.schema_calls), 1)

    def test_retrospective_native_audit_fill_is_detected(self):
        def mutate(api):
            if api.schema_calls[-1][0] == 'EnableEditorTracking':
                api.rows[0]['created_date'] = dt.datetime(2026, 11, 9)
        self.api.after_schema = mutate
        with self.assertRaisesRegex(ValueError, 'retrospectiva'):
            self.run_tool(apply=True, approve_native_audit=True)
        self.assertEqual(self.report()['estado'], 'CONFIGURACION_DETENIDA_CON_PASOS_A_REVISAR')
        self.assertTrue(self.api.table_description.editorTrackingEnabled)
        self.assertFalse(self.report()['rollback_automatico'])


if __name__ == '__main__':
    unittest.main()
