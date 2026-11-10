"""Pruebas de tipos y modo de lectura completo 1.8, sin ArcPy real."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import inspeccion_kmz as collector
import validar_tipos_kmz as validation


HERE = Path(__file__).resolve().parent


def stats(values, declared=None, untyped=0, conflicts=0):
    result = collector.fresh()
    for index, value in enumerate(values):
        result['registros'] += 1
        collector.observe(result, value, declared if index >= untyped else None,
                          'fixture' if declared else None, validation.observe_validation)
    result = collector.finished(result)
    result.update(cobertura='COMPLETA_RUTAS_DEL_CAMPO', conflictos=conflicts, rutas=[])
    return result


def field(typ='TEXT', pending=True, length=4000, nullable=True, own=True):
    value = dict(nombre='dato', tipo=typ, longitud=length if typ == 'TEXT' else None,
                 nullable=nullable, dominio=None, origen='Atributo KMZ; pendiente' if pending else 'EFT 5.8.7')
    if own:
        value['campo_fuente'] = 'DATO'
    return value


class TypeEvidenceTests(unittest.TestCase):
    def test_unicode_capacity_counts_utf16_not_display_characters(self):
        result = validation.evaluate_field(field(length=4), stats(['abc\U0001f600']))
        self.assertIn('LONGITUD_INSUFICIENTE', result['incidencias'])
        self.assertEqual(result['tipo_destino_recomendado'], 'TEXT')
        self.assertEqual(result['longitud_destino_recomendada'], 5)
        self.assertFalse(result['aprobado'])

    def test_declared_int_everywhere_and_range_yields_candidate_not_approval(self):
        result = validation.evaluate_field(field(), stats(['0','2','5'], 'int'))
        self.assertEqual(result['propuesta'], 'CANDIDATO_LONG_DECLARADO')
        self.assertEqual(result['tipo_destino_recomendado'], 'LONG')
        self.assertIsNone(result['longitud_destino_recomendada'])
        self.assertTrue(result['requiere_decision'])
        self.assertFalse(result['aprobado'])

    def test_partial_schema_does_not_apply_to_untyped_sources(self):
        result = validation.evaluate_field(field(), stats(['1','2','3'], 'int', untyped=2))
        self.assertEqual(result['propuesta'], 'CONSERVAR_TEXT_TIPO_ORIGEN_INCOMPLETO')
        self.assertIn('parcial', result['tipo_origen'])
        self.assertFalse(result['declaracion_completa'])

    def test_incomplete_field_coverage_blocks_otherwise_fully_declared_candidate(self):
        values=stats(['0','2','5'],'int')
        values['cobertura']='INCOMPLETA'
        result=validation.evaluate_field(field(),values)
        self.assertEqual(result['tipo_destino_recomendado'],'TEXT')
        self.assertEqual(result['propuesta'],'RESOLVER_INCIDENCIAS_ANTES_DE_TIPIFICAR')
        self.assertIn('COBERTURA_INCOMPLETA',result['bloqueos_mapeo'])

    def test_numeric_strings_remain_text_when_declared_string(self):
        result = validation.evaluate_field(field(), stats(['12','20'], 'string'))
        self.assertEqual(result['propuesta'], 'CANDIDATO_CONFIRMAR_TEXT_DECLARADO')
        self.assertEqual(result['tipo_destino_recomendado'], 'TEXT')

    def test_nonstandard_long_is_not_equated_to_arcgis_long(self):
        for value in ('1', '2147483648'):
            result = validation.evaluate_field(field(), stats([value], 'long'))
            self.assertEqual(result['propuesta'], 'CONSERVAR_TEXT_TIPO_KML_NO_ESTANDAR')
            self.assertEqual(result['tipo_destino_recomendado'], 'TEXT')

    def test_unsigned_int_outside_long_is_not_silently_narrowed(self):
        result = validation.evaluate_field(field(), stats(['4294967295'], 'uint'))
        self.assertEqual(result['propuesta'], 'CONSERVAR_TEXT_DECLARACION_INCOMPATIBLE')

    def test_mixed_declarations_are_not_unified(self):
        values = stats(['1','2'], 'int')
        values['tipos_declarados'] = {'int':1,'string':1}
        values['validacion_valores_por_tipo'] = {'int':{'utiles':1,'numericos':1,'enteros_lexicos':1},'string':{'utiles':1,'numericos':1,'enteros_lexicos':1}}
        result = validation.evaluate_field(field(), values)
        self.assertEqual(result['propuesta'], 'CONSERVAR_TEXT_DECLARACIONES_DISTINTAS')

    def test_zero_and_negative_conventions_are_not_nullified(self):
        values = stats(['0','-1','-99'], 'int')
        self.assertEqual(values['validacion_valores']['utiles'],3)
        self.assertEqual(values['validacion_valores'].get('marcadores',0),0)
        result = validation.evaluate_field(field(), values)
        self.assertEqual(result['tipo_destino_recomendado'],'LONG')

    def test_leading_zeros_are_preserved(self):
        result = validation.evaluate_field(field(), stats(['001','002'], 'int'))
        self.assertEqual(result['tipo_destino_recomendado'],'TEXT')
        result = validation.evaluate_field(field('LONG',pending=False), stats(['001']))
        self.assertIn('CEROS_INICIALES_SE_PERDERIAN',result['incidencias'])

    def test_float_roundtrip_and_precision_are_separate(self):
        okay = validation.evaluate_field(field('DOUBLE',pending=False), stats(['0.1','3.14']))
        self.assertEqual(okay['incidencias'],[])
        lossy = validation.evaluate_field(field('DOUBLE',pending=False),stats(['9007199254740993']))
        self.assertIn('DOUBLE_CAMBIA_VALOR_DECIMAL',lossy['incidencias'])
        self.assertIn('PRECISION_MAYOR_15_DIGITOS',lossy['incidencias'])

    def test_nonfinite_and_fractional_integer_are_rejected(self):
        cases = [('DOUBLE','1e999','DOUBLE_NO_FINITO'),
                 ('DOUBLE','Infinity','VALORES_NO_NUMERICOS'),
                 ('LONG','1.5','FRACCIONES_EN_ENTERO'),
                 ('LONG','2147483648','FUERA_RANGO_LONG'),
                 ('SHORT','32768','FUERA_RANGO_SHORT')]
        for typ,value,code in cases:
            with self.subTest(typ=typ,value=value):
                self.assertIn(code,validation.evaluate_field(field(typ,pending=False),stats([value]))['incidencias'])

    def test_date_iso_invalid_ambiguous_timezone_and_subseconds(self):
        good = validation.evaluate_field(field('DATE',pending=False),stats(['2024-02-29']))
        self.assertEqual(good['incidencias'],[])
        for value in ('2023-02-29','01/02/2024','Perpetuo','05/12/208'):
            self.assertIn('FECHA_FORMATO_NO_UNIVOCO_O_INVALIDO',
                validation.evaluate_field(field('DATE',pending=False),stats([value]))['incidencias'])
        special = validation.evaluate_field(field('DATE',pending=False),stats(['2024-01-01T12:00:00.123Z']))
        self.assertIn('FECHA_ZONA_HORARIA_REQUIERE_REGLA',special['incidencias'])
        self.assertIn('FECHA_SUBSEGUNDOS_REQUIERE_PRECISION',special['incidencias'])
        for value in ('2026-01-01T00:00:00.0000001','2026-01-01T00:00:00.1234567'):
            result=validation.evaluate_field(field('DATE',pending=False),stats([value]))
            self.assertIn('FECHA_SUBSEGUNDOS_REQUIERE_PRECISION',result['incidencias'])

    def test_text_dates_do_not_become_date_implicitly(self):
        result=validation.evaluate_field(field(),stats(['2024-01-01']))
        self.assertEqual(result['tipo_destino_recomendado'],'TEXT')

    def test_empty_or_only_markers_get_explicit_conservative_proposal(self):
        for values in ([''],['<Null>','NULL','n/a']):
            result=validation.evaluate_field(field(),stats(values))
            self.assertEqual(result['propuesta'],'CONSERVAR_TEXT_SIN_VALORES_UTILES')
            self.assertTrue(result['requiere_decision'])
        result=validation.evaluate_field(field('LONG',pending=False),stats(['1','<Null>']))
        self.assertIn('MARCADORES_REQUIEREN_REGLA_NULL',result['incidencias'])

    def test_office_mapping_conflict_does_not_change_text_type(self):
        result=validation.evaluate_field(field(),stats(['LIMA','JUNIN'],conflicts=1))
        self.assertEqual(result['tipo_destino_recomendado'],'TEXT')
        self.assertEqual(result['compatibilidad_tipo'],'COMPATIBLE_VALORES_OBSERVADOS')
        self.assertEqual(result['bloqueos_mapeo'],['CONFLICTO_MAPEO_VALORES'])

    def test_common_or_ddl_absent_source_is_not_called_empty_kmz(self):
        result=validation.evaluate_field(field('DATE',pending=False,own=False),None)
        self.assertEqual(result['compatibilidad'],'NO_APLICA_TIPO_ORIGEN')
        self.assertEqual(result['tipo_origen'],'NO_APLICA_TIPO_ORIGEN')
        self.assertFalse(result['requiere_decision'])

    def test_boolean_values_do_not_get_implicit_integer_mapping(self):
        result=validation.evaluate_field(field(),stats(['true','false','0','1'],'bool'))
        self.assertEqual(result['propuesta'],'CONSERVAR_TEXT_BOOLEANO_REQUIERE_MAPEO')

    def test_missing_exhaustive_counts_cannot_be_replaced_with_examples(self):
        values=stats(['1','2'])
        values.pop('validacion_valores')
        with self.assertRaisesRegex(ValueError,'exhaustiva'):
            validation.evaluate_field(field(),values)

    def test_source_declared_subset_is_not_contaminated_by_untyped_values(self):
        values=stats(['not an integer','7'],'int',untyped=1)
        result=validation.evaluate_source_declaration(values)
        self.assertEqual(result['validacion_tipo_origen'],'DECLARACION_PARCIAL')
        self.assertEqual(result['incidencias_tipo_origen'],[])
        self.assertEqual(result['detalle_tipos_origen'][0]['valores'],1)

    def test_source_bool_lexemes_and_unsigned_ranges_are_checked(self):
        for kind,raw,expected in (
            ('bool','TRUE','DECLARACION_BOOL_LEXEMA_INVALIDO'),
            ('bool','2','DECLARACION_BOOL_LEXEMA_INVALIDO'),
            ('ushort','-1','DECLARACION_ENTERA_FUERA_RANGO'),
            ('ushort','65536','DECLARACION_ENTERA_FUERA_RANGO'),
            ('uint','4294967296','DECLARACION_ENTERA_FUERA_RANGO'),
            ('int','1e2','DECLARACION_ENTERA_LEXEMA_INVALIDO'),
            ('int','1.0','DECLARACION_ENTERA_LEXEMA_INVALIDO')):
            with self.subTest(kind=kind,raw=raw):
                value=stats([raw],kind)
                self.assertIn(expected,validation.evaluate_source_declaration(value)['incidencias_tipo_origen'])
                self.assertEqual(validation.evaluate_field(field(),value)['tipo_destino_recomendado'],'TEXT')
        good=validation.evaluate_source_declaration(stats(['true','false','0','1'],'bool'))
        self.assertEqual(good['validacion_tipo_origen'],'DECLARACION_VERIFICADA')

    def test_source_numeric_empty_marker_rule_does_not_replace_values(self):
        values=stats(['','<Null>','0'],'int')
        original=copy.deepcopy(values)
        result=validation.evaluate_source_declaration(values)
        self.assertIn('DECLARACION_NO_TEXTUAL_REQUIERE_REGLA_NULL',result['incidencias_tipo_origen'])
        self.assertEqual(values,original)
        self.assertEqual(validation.evaluate_field(field(),values)['tipo_destino_recomendado'],'TEXT')

    def test_declared_float_uses_32_bit_range_independent_of_double_destination(self):
        for raw,code in (
            ('1e39','DECLARACION_FLOAT_FUERA_RANGO_32_BITS'),
            ('-1e39','DECLARACION_FLOAT_FUERA_RANGO_32_BITS'),
            ('1e-46','DECLARACION_FLOAT_REQUIERE_REGLA_SUBDESBORDAMIENTO')):
            with self.subTest(raw=raw):
                value=stats([raw],'float')
                self.assertIn(code,validation.evaluate_source_declaration(value)['incidencias_tipo_origen'])
                self.assertEqual(validation.evaluate_field(field(),value)['tipo_destino_recomendado'],'TEXT')
                double=validation.evaluate_source_declaration(stats([raw],'double'))
                self.assertEqual(double['incidencias_tipo_origen'],[])
        self.assertEqual(validation.evaluate_source_declaration(stats(['0','0.1','-3.14','3.4e38','1.5e-45'],'float'))['incidencias_tipo_origen'],[])

    def test_confirmed_destination_capacity_does_not_resolve_source_contradiction(self):
        result=validation.evaluate_field(field('TEXT',pending=False),stats(['-1'],'ushort'))
        self.assertEqual(result['compatibilidad_tipo'],'COMPATIBLE_VALORES_OBSERVADOS')
        self.assertEqual(result['validacion_declaracion_origen'],'DECLARACION_CON_INCIDENCIAS')
        self.assertEqual(result['propuesta'],'REVISAR_DECLARACION_ORIGEN_MODELO_CONFIRMADO')
        self.assertTrue(result['requiere_decision'])
        self.assertEqual(result['tipo_destino_recomendado'],'TEXT')

    def test_unmapped_source_type_can_be_checked_without_a_model_field(self):
        result=validation.evaluate_source_declaration(stats(['no-number'],'double'))
        self.assertIn('DECLARACION_FLOTANTE_VALOR_NO_NUMERICO',result['incidencias_tipo_origen'])
        self.assertEqual(validation.evaluate_source_declaration(stats(['anything']))['validacion_tipo_origen'],'SIN_TIPO_DECLARADO')

    def test_own_source_declared_counters_are_required(self):
        values=stats(['1'],'int')
        values.pop('validacion_valores_por_tipo')
        with self.assertRaisesRegex(ValueError,'por tipo declarado'):
            validation.evaluate_source_declaration(values)


class FakeContext:
    def __enter__(self): return self
    def __exit__(self,*args): return False


class FakeArcPy:
    def __init__(self,model):
        self.model=model
        self.da=SimpleNamespace(ListDomains=lambda workspace:[])
        self.mutations=[]
        self.fields={c['nombre']:[SimpleNamespace(name=f['nombre'],baseName=f['nombre'],
            type=validation.runner.engine.TYPE[f['tipo']],length=f.get('longitud') or 0,
            isNullable=f['nullable'],domain=f.get('dominio') or '') for f in c['campos']] for c in model['clases']}
    def EnvManager(self,**kwargs): return FakeContext()
    def GetInstallInfo(self): return {'Version':'fake'}
    def Exists(self,path): return True
    def Describe(self,path):
        p=Path(path)
        if p.suffix=='.gdb':return SimpleNamespace(workspaceType='LocalDatabase')
        if p.name=='Datos_Proyecto':return SimpleNamespace(dataType='FeatureDataset',spatialReference=SimpleNamespace(factoryCode=4326))
        c=next(c for c in self.model['clases'] if c['nombre']==p.name)
        return SimpleNamespace(dataType='FeatureClass',path=str(p.parent),shapeType=c['geometria'],
            spatialReference=SimpleNamespace(factoryCode=4326),hasZ=True,hasM=False,
            hasGlobalID=True,editorTrackingEnabled=True,isTimeInUTC=True)
    def ListDatasets(self,**kwargs):return ['Datos_Proyecto']
    def ListFeatureClasses(self,feature_dataset=''):
        return list(self.fields) if feature_dataset else []
    def ListTables(self):return []
    def ListFields(self,path):return self.fields[Path(path).name]
    def ValidateTableName(self,name,workspace):return name
    def ValidateFieldName(self,name,workspace):return name
    @property
    def management(self):
        self.mutations.append('management')
        raise AssertionError('No DDL')


class DestinationTests(unittest.TestCase):
    def model(self):
        f=field(pending=False)
        return dict(datasets=['Datos_Proyecto'],dominios={},clases=[dict(nombre='accesos',geometria='POLYLINE',campos=[f])])
    def test_readonly_facade_blocks_management_sql_and_record_cursors(self):
        fake=FakeArcPy(self.model())
        facade=validation.ReadOnlyArcPy(fake)
        for name in ('management','ArcSDESQLExecute','Delete_management'):
            with self.assertRaises(AttributeError):getattr(facade,name)
        self.assertFalse(hasattr(facade.da,'SearchCursor'))
        self.assertEqual(fake.mutations,[])
    def test_checks_fields_without_writes_and_accumulates_differences(self):
        model=self.model(); fake=FakeArcPy(model)
        okay=validation.inspect_destination(fake,'fixture.gdb','ArcGisAWS','gis',model)
        self.assertTrue(okay['verificado']);self.assertEqual(okay['campos_verificados'],1)
        fake.fields['accesos'][0].length=3
        fake.fields['accesos'][0].isNullable=False
        bad=validation.inspect_destination(fake,'fixture.gdb','ArcGisAWS','gis',model)
        self.assertFalse(bad['verificado']);self.assertEqual(len(bad['incidencias']),2)
        self.assertEqual(fake.mutations,[])


class SnapshotAndRunTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        for name in validation.REFERENCES:
            source = HERE/name
            if name == 'esquema.json' and json.loads(source.read_text(encoding='utf-8-sig'))['version'] == 12:
                source = HERE/'esquema_anterior_1_8.json'
            shutil.copyfile(source,self.root/name)
        self.profile=dict(estado='LECTURA_COMPLETA',fuentes=[{'archivo':'fixture.kmz','sha256':'a'*64}],
            rutas=[dict(archivo='fixture.kmz',ruta='Root',geometria='Punto',clase='',esperados=1,observados=1,estado='COINCIDE')],
            campos_destino=[],campos_fuente=[],incidencias=[],conteos={'elementos_esperados':1,'elementos_observados':1})
        self.envelope=dict(version_paquete='1.8',version_modelo=11,referencias_sha256=validation.input_hashes(self.root),
            generado_utc='fixture',perfil=self.profile)
    def tearDown(self):self.temp.cleanup()
    def write(self):validation.write_profile_snapshot(self.envelope,self.root)
    def test_snapshot_integrity_and_code_mapping_binding(self):
        self.write()
        value,sha=validation.read_profile_snapshot(self.root)
        self.assertEqual(value,self.envelope);self.assertEqual(len(sha),64)
        with self.assertRaisesRegex(ValueError,'no se sobrescribe'):
            self.write()
        (self.root/'campos_por_ruta.csv').write_text('cambiado',encoding='utf8')
        with self.assertRaisesRegex(ValueError,'no corresponde'):
            validation.read_profile_snapshot(self.root)
    def test_corrupted_snapshot_rejected(self):
        self.write()
        with (self.root/validation.SNAPSHOT).open('ab') as stream:stream.write(b' ')
        with self.assertRaisesRegex(ValueError,'modificado'):
            validation.read_profile_snapshot(self.root)
    def test_archived_profile_offline_does_not_claim_fresh_kmz_or_approval(self):
        self.write()
        before=(self.root/'esquema.json').read_bytes()
        _,report=validation.run(None,reports=self.root,model_dir=self.root,emit=lambda message:None)
        self.assertEqual(report['origen_evidencia'],'PERFIL_INCLUIDO_VERIFICADO')
        self.assertEqual(report['campos_revisados'],3340)
        self.assertEqual(report['campos_tipo_pendiente'],730)
        self.assertEqual(report['estado'],'VALIDACION_TIPOS_COMPLETA_CON_PENDIENTES')
        self.assertEqual(sum(report['tipos_recomendados_pendientes'].values()),730)
        self.assertFalse(report['ingesta_autorizada'])
        self.assertEqual(before,(self.root/'esquema.json').read_bytes())
        self.assertTrue(Path(report['archivo_campos']).is_file())
    def test_failure_writes_new_report_without_mutating_snapshot(self):
        self.write()
        (self.root/validation.SNAPSHOT_SHA).write_text('bad',encoding='ascii')
        emitted=[]
        with self.assertRaisesRegex(ValueError,'Huella'):
            validation.run(None,reports=self.root,model_dir=self.root,emit=emitted.append)
        path=Path(next(message.removeprefix('Resultado JSON: ') for message in emitted if message.startswith('Resultado JSON: ')))
        report=json.loads(path.read_text(encoding='utf8'))
        self.assertEqual(report['estado'],'ERROR_DETENIDO')
        self.assertFalse(report['cambios_en_sde'])

    def close_fixture(self):
        """El wrapper delega la aprobacion al helper, ensayado por su propio modulo."""
        original=(self.root/'esquema.json').read_bytes()
        base=json.loads(original)
        target=copy.deepcopy(base)
        target['version']=12
        for cls in target['clases']:
            for field in cls['campos']:
                if validation.runner.provisional(field):
                    field['origen']='Atributo KMZ; almacenamiento TEXT confirmado por decision 1.9'
                    field['tipo_confirmado']=True
        (self.root/'esquema.json').write_text(json.dumps(target),encoding='utf-8')
        (self.root/'esquema_anterior_1_8.json').write_bytes(original)
        (self.root/'cierre_tipos_1_9.json').write_text('{}',encoding='utf-8')
        (self.root/'referencia_cierre_tipos.py').write_text('# fixture de referencia',encoding='utf-8')
        self.envelope.update(version_paquete='1.9',version_modelo=12,
                             referencias_sha256=validation.input_hashes(self.root))
        return base,target

    def test_model12_reads_separate_snapshot_and_reports_zero_provisional_not_ingesta(self):
        base,target=self.close_fixture()
        with patch.dict(sys.modules,{'referencia_cierre_tipos':SimpleNamespace(
                read_reference=lambda model_dir:(base,target,{}))}):
            self.write()
            self.assertTrue((self.root/validation.SNAPSHOT_1_9).is_file())
            self.assertFalse((self.root/validation.SNAPSHOT).exists())
            original=(self.root/'esquema.json').read_bytes()
            _,report=validation.run(None,model_dir=self.root,reports=self.root,emit=lambda _:None)
            self.assertEqual((report['version_paquete'],report['version_modelo']),('1.9',12))
            self.assertEqual(report['campos_tipo_pendiente'],0)
            self.assertEqual(report['campos_revisados'],3340)
            self.assertEqual(report['estado'],'VALIDACION_TIPOS_COMPLETA_CON_PENDIENTES')
            self.assertEqual(report['tipos_recomendados_pendientes'],{})
            self.assertFalse(report['ingesta_autorizada'])
            self.assertEqual((self.root/'esquema.json').read_bytes(),original)

    def test_model12_requires_closure_and_failure_json_keeps_model_version(self):
        self.close_fixture()
        def rejected(_):raise ValueError('Linaje de cierre rechazado')
        emitted=[]
        with patch.dict(sys.modules,{'referencia_cierre_tipos':SimpleNamespace(read_reference=rejected)}), \
                patch.object(validation,'inspect_destination') as destination:
            with self.assertRaisesRegex(ValueError,'Linaje'):
                validation.run('fixture.gdb',model_dir=self.root,reports=self.root,emit=emitted.append)
            destination.assert_not_called()
        path=Path(next(message.removeprefix('Resultado JSON: ') for message in emitted if message.startswith('Resultado JSON: ')))
        report=json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual((report['version_paquete'],report['version_modelo'],report['estado']),('1.9',12,'ERROR_DETENIDO'))

    def test_model12_binds_all_closure_references_and_rejects_legacy_fallback(self):
        self.write()
        base,target=self.close_fixture()
        with patch.dict(sys.modules,{'referencia_cierre_tipos':SimpleNamespace(
                read_reference=lambda model_dir:(base,target,{}))}):
            with self.assertRaises(FileNotFoundError):validation.read_profile_snapshot(self.root)
            self.write()
            (self.root/'cierre_tipos_1_9.json').write_text('{"cambio":true}',encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'no corresponde'):
                validation.read_profile_snapshot(self.root)

    def test_model12_current_kmz_profile_keeps_version_and_unchanged_source_semantics(self):
        base,target=self.close_fixture()
        with patch.dict(sys.modules,{'referencia_cierre_tipos':SimpleNamespace(
                read_reference=lambda model_dir:(base,target,{}))}), \
                patch.object(collector,'collect',return_value=copy.deepcopy(self.profile)) as collect:
            envelope=validation.build_profile('fuentes',model_dir=self.root,emit=lambda _:None)
        collect.assert_called_once()
        self.assertEqual((envelope['version_paquete'],envelope['version_modelo']),('1.9',12))
        self.assertEqual(envelope['perfil'],self.profile)
        self.assertFalse(envelope['cambios_en_modelo'])

    def test_model12_rejects_returned_target_different_or_provisional(self):
        base,target=self.close_fixture()
        wrong=copy.deepcopy(target);wrong['version']=11
        with patch.dict(sys.modules,{'referencia_cierre_tipos':SimpleNamespace(
                read_reference=lambda model_dir:(base,wrong,{}))}):
            with self.assertRaisesRegex(ValueError,'no coincide'):
                validation.validated_model(self.root,target)
        target['clases'][0]['campos'][-1]['origen']='Atributo KMZ pendiente'
        with patch.dict(sys.modules,{'referencia_cierre_tipos':SimpleNamespace(
                read_reference=lambda model_dir:(base,target,{}))}):
            with self.assertRaisesRegex(ValueError,'cero tipos'):
                validation.validated_model(self.root,target)


if __name__=='__main__':
    unittest.main(verbosity=2)
