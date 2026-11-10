"""Pruebas de renombrado con inventario y ArcPy simulados; nunca abre SDE."""
import copy
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import test_actualizar_campos_aprobados as fixture_module
import renombrar_clases as tool


class RenameTests(unittest.TestCase):
    def setUp(self):
        f=fixture_module.ApprovedFieldsTests(methodName='runTest')
        f.setUp();self.addCleanup(f.doCleanups)
        self.f=f
        self.old='zonas_de_vida_holdridge_recorte'
        self.new='zonas_vida_holdridge_recorte'
        self.source=copy.deepcopy(f.source)
        # La otra clase no cambia de nombre en esta fixture; ambas reciben alias.
        for c in self.source['clases']:
            c['nombre']=self.new if c['nombre']==self.old else c['nombre']
            c['alias']='Descripcion '+c['nombre']
        self.config=copy.deepcopy(f.config)
        for c in self.config['cambios']:
            if c['clase']==self.old:c['clase']=self.new
        self.mapping=dict(version_paquete='1.6',clases=[dict(
            nombre_anterior=self.old if c['nombre']==self.new else c['nombre'],
            nombre_nuevo=c['nombre'],alias=c['alias'],rol=c['rol'],geometria=c['geometria'],
            renombrar=c['nombre']==self.new,motivo='Convencion aprobada')
            for c in self.source['clases']])
        self.model_path=f.root/'renombrar_modelo.json'
        self.mapping_path=f.root/'nombres.json'
        self.config_path=f.root/'tipos.json'
        self.write_inputs()
        for name,path in f.paths.items():
            f.descriptions[path].aliasName='Alias anterior '+name
        f.a.da.ListSubtypes=Mock(return_value={0:dict(SubtypeField='')})
        f.a.management.Rename=Mock(side_effect=self.rename)
        f.a.AlterAliasName=Mock(side_effect=self.alias)
        # No necesitamos ampliar texto para comprobar renombrado; conserva 4000.
        self.calls=[]

    def write_inputs(self):
        self.model_path.write_text(json.dumps(self.source),encoding='utf-8')
        self.mapping_path.write_text(json.dumps(self.mapping),encoding='utf-8')
        self.config_path.write_text(json.dumps(self.config),encoding='utf-8')

    def rename(self,path,destination,data_type):
        f=self.f
        self.assertEqual(data_type,'FeatureClass')
        old=tool.runner.engine.simple(os.path.basename(path))
        new=tool.runner.engine.simple(os.path.basename(destination))
        self.assertNotIn(destination,f.descriptions)
        for attribute in ('fields','records','indices','descriptions'):
            values=getattr(f,attribute);values[destination]=values.pop(path)
        if path in f.locks:f.locks[destination]=f.locks.pop(path)
        f.paths.pop(old);f.paths[new]=destination
        f.descriptions[destination].aliasName=new # Rename de Esri tambien cambia el alias.
        self.calls.append(('Rename',old,new))

    def alias(self,path,name):
        self.f.descriptions[path].aliasName=name
        self.calls.append(('Alias',tool.runner.engine.simple(os.path.basename(path)),name))

    def run_tool(self,apply=False,names=None):
        self.last_report_path = None
        def capture(message):
            if message.startswith('Resultado JSON: '):
                self.last_report_path = Path(message.removeprefix('Resultado JSON: '))
        return tool.run(self.f.workspace,apply=apply,reports=self.f.root,
            arcpy_module=self.f.a,emit=capture,model_path=self.model_path,
            mapping_path=self.mapping_path,config_path=self.config_path,names=names)

    def report(self):
        path = getattr(self, 'last_report_path', None)
        self.assertIsNotNone(path, 'La ejecucion no emitio su Resultado JSON final.')
        self.assertTrue(path.is_relative_to(self.f.root))
        return json.loads(path.read_text(encoding='utf-8'))

    def test_validation_all_classes_without_writes_preserves_inputs(self):
        paths=dict(self.f.paths)
        _,r=self.run_tool()
        self.assertEqual(r['estado'],'VALIDACION_OK_SIN_CAMBIOS')
        self.assertEqual(sum(x['renombrar'] for x in r['plan']),1)
        self.assertEqual(paths,self.f.paths)
        self.assertEqual(self.calls,[])
        self.f.a.management.AlterField.assert_not_called()

    def test_rename_alias_and_repeat_preserve_numeric_types_fields_and_indexes(self):
        path=self.f.paths[self.old]
        self.f.field(self.old,'medida').type='Double'
        self.f.field(self.old,'medida').length=8
        self.f.indices[path]=[SimpleNamespace(name='ix_medida',fields=[self.f.field(self.old,'medida')],isUnique=False,isAscending=True)]
        before=tool.snapshot(self.f.a,path)
        _,r=self.run_tool(True)
        self.assertEqual(r['estado'],'NOMBRES_VERIFICADOS')
        self.assertNotIn(self.old,self.f.paths)
        self.assertEqual(tool.snapshot(self.f.a,self.f.paths[self.new]),before)
        self.assertEqual(self.f.a.management.Rename.call_count,1)
        self.assertEqual(self.f.a.AlterAliasName.call_count,2)
        self.assertEqual(self.f.field(self.new,'medida').type,'Double')
        self.f.a.management.AlterField.assert_not_called()
        self.calls.clear()
        self.f.locks.update({p:False for p in self.f.paths.values()})
        _,r=self.run_tool(True)
        self.assertEqual(r['estado'],'NOMBRES_VERIFICADOS')
        self.assertEqual(self.calls,[])

    def test_both_names_missing_and_destination_collisions_block_whole_batch(self):
        old_path=self.f.paths[self.old]
        target=os.path.join(self.f.ds,'GIS.'+self.new)
        for attribute in ('fields','records','indices','descriptions'):
            getattr(self.f,attribute)[target]=copy.deepcopy(getattr(self.f,attribute)[old_path])
        self.f.paths[self.new]=target
        with self.assertRaisesRegex(ValueError,'Existen ambos nombres'):
            self.run_tool(True)
        self.assertEqual(self.calls,[])
        del self.f.paths[self.new];del self.f.paths[self.old]
        with self.assertRaisesRegex(ValueError,'No existe'):
            self.run_tool(True)
        self.assertEqual(self.calls,[])

    def test_registered_destination_not_in_inventory_is_also_blocked(self):
        target=os.path.join(self.f.ds,'GIS.'+self.new)
        self.f.descriptions[target]=SimpleNamespace(dataType='Table')
        with self.assertRaisesRegex(ValueError,'destino ya existe'):
            self.run_tool(True)
        self.assertEqual(self.calls,[])

    def test_wrong_dataset_nonempty_and_schema_lock_prevent_every_write(self):
        path=self.f.paths[self.old]
        self.f.records[path]=1
        with self.assertRaisesRegex(ValueError,'contiene 1 registros'):self.run_tool(True)
        self.f.records[path]=0
        self.f.descriptions[path].path=os.path.join(self.f.workspace,'otro_dataset')
        with self.assertRaisesRegex(ValueError,'fuera de Datos_Proyecto'):self.run_tool(True)
        self.f.descriptions[path].path=self.f.ds
        self.f.locks[path]=False
        with self.assertRaisesRegex(ValueError,'bloqueo de esquema'):self.run_tool(True)
        self.assertEqual(self.calls,[])

    def test_connections_owner_and_invalid_new_name_block_before_writes(self):
        self.f.use_sde()
        self.f.connection.user='otro'
        with self.assertRaisesRegex(ValueError,'conexion del propietario'):self.run_tool(True)
        self.f.connection.user='gis'
        self.f.a.ValidateTableName=lambda n,w:n+'_'
        with self.assertRaisesRegex(ValueError,'Nombre objetivo no valido'):self.run_tool(True)
        self.assertEqual(self.calls,[])

    def test_dependencies_are_not_silently_broken(self):
        description=self.f.descriptions[self.f.paths[self.old]]
        for attr,value in [('relationshipClassNames',['rel_otra']),('attributeRules',[{}]),
                           ('isArchived',True),('isReplicated',True),('subtypeFieldName','tipo')]:
            with self.subTest(attr=attr):
                setattr(description,attr,value)
                with self.assertRaisesRegex(ValueError,'dependencias'):self.run_tool(True)
                setattr(description,attr,None)
        self.f.a.da.ListSubtypes.return_value={1:dict(SubtypeField='tipo')}
        with self.assertRaisesRegex(ValueError,'subtipos'):self.run_tool(True)
        self.assertEqual(self.calls,[])

    def test_partial_rename_and_alias_failure_before_and_after_effect_resume(self):
        # Instancias independientes para cada frontera de falla.
        for operation in ('Rename','AlterAliasName'):
            for after in (False,True):
                with self.subTest(operation=operation,after=after):
                    case=RenameTests(methodName='runTest');case.setUp()
                    try:
                        method=case.f.a.management.Rename if operation=='Rename' else case.f.a.AlterAliasName
                        real=case.rename if operation=='Rename' else case.alias
                        def fail(*args):
                            if after:real(*args)
                            raise RuntimeError('Fallo simulado')
                        method.side_effect=fail
                        with self.assertRaisesRegex(RuntimeError,'Fallo simulado'):
                            case.run_tool(True,names=[case.new])
                        error=case.report()
                        self.assertEqual(error['estado'],'ERROR_DETENIDO')
                        self.assertEqual(error['clase_en_curso'],case.new)
                        self.assertIn(case.new,error['nombres_observados_al_detener'])
                        method.side_effect=real;case.calls.clear()
                        _,done=case.run_tool(True,names=[case.new])
                        self.assertEqual(done['estado'],'NOMBRES_VERIFICADOS')
                        if after and operation=='Rename':
                            self.assertFalse(any(c[0]=='Rename' for c in case.calls))
                        if after and operation=='AlterAliasName':
                            self.assertEqual(case.calls,[])
                    finally:case.doCleanups()

    def test_unrelated_field_or_index_changes_after_rename_stop(self):
        real=self.rename
        def alter(*args):
            real(*args)
            self.f.field(self.new,'medida').aliasName='Modificado externo'
        self.f.a.management.Rename.side_effect=alter
        with self.assertRaisesRegex(ValueError,'modificaron campos'):self.run_tool(True,names=[self.new])
        self.f.a.AlterAliasName.assert_not_called()

    def test_gp_succeeds_without_actual_rename_is_not_success(self):
        self.f.a.management.Rename.side_effect=lambda *args:None
        with self.assertRaisesRegex(ValueError,'no confirma el nombre'):
            self.run_tool(True,names=[self.new])
        self.assertEqual(self.report()['estado'],'ERROR_DETENIDO')

    def test_wrong_alias_after_gp_is_not_success(self):
        self.f.a.AlterAliasName.side_effect=lambda *args:None
        with self.assertRaisesRegex(ValueError,'no confirma el alias'):
            self.run_tool(True,names=[self.new])

    def test_subselection_uses_new_names_and_changes_only_that_class(self):
        other='predios_inscritos_en_sunarp_recorte'
        path=self.f.paths[other];alias=self.f.descriptions[path].aliasName
        _,r=self.run_tool(True,names=[self.new])
        self.assertEqual([c['nombre'] for c in r['clases']],[self.new])
        self.assertEqual(self.f.descriptions[path].aliasName,alias)
        for names in ([],[self.old],['desconocida'],self.new):
            with self.subTest(names=names),self.assertRaises(ValueError):self.run_tool(True,names=names)

    def test_mapping_duplicates_incomplete_geometry_or_alias_rejected(self):
        for change in ('duplicated','incomplete','geometry','alias','flag'):
            value=copy.deepcopy(self.mapping)
            if change=='duplicated':value['clases'].append(copy.deepcopy(value['clases'][0]))
            if change=='incomplete':value['clases'].pop()
            if change=='geometry':value['clases'][0]['geometria']='POLYGON'
            if change=='alias':value['clases'][0]['alias']='No aprobado'
            if change=='flag':value['clases'][0]['renombrar']=True
            with self.subTest(change=change),self.assertRaises(ValueError):
                tool.selected_mapping(self.source,value,self.config)

    def test_recovery_does_not_require_type_changes_or_text_expansion(self):
        other='predios_inscritos_en_sunarp_recorte'
        before=tool.snapshot(self.f.a,self.f.paths[other])
        self.run_tool(True)
        self.assertEqual(tool.snapshot(self.f.a,self.f.paths[other]),before)
        self.assertEqual(self.f.field(other,'cargas_y_gravamenes').length,4000)
        self.assertEqual(self.f.field(other,'numerico').type,'String')

    def test_migrated_names_and_aliases_cannot_be_changed(self):
        model=copy.deepcopy(self.source);mapping=copy.deepcopy(self.mapping)
        target=self.new
        next(c for c in model['clases'] if c['nombre']==target)['rol']='migrada'
        row=next(r for r in mapping['clases'] if r['nombre_nuevo']==target)
        row['rol']='migrada'
        with self.assertRaisesRegex(ValueError,'migrados se conservan'):
            tool.selected_mapping(model,mapping,self.config)
        row.update(nombre_anterior=target,renombrar=False)
        with self.assertRaisesRegex(ValueError,'migrados se conservan'):
            tool.selected_mapping(model,mapping,self.config)
        row['alias']=None
        rows,_=tool.selected_mapping(model,mapping,self.config)
        self.assertIsNone(next(r for r in rows if r['nombre_nuevo']==target)['alias'])

    def test_model_hash_mismatch_blocks_before_any_arcpy_write(self):
        self.mapping['modelo_objetivo_sha256']='0'*64
        self.write_inputs()
        with self.assertRaisesRegex(ValueError,'hash aprobado'):
            self.run_tool(True)
        self.assertEqual(self.calls,[])

    def test_nonapproved_type_or_extra_fields_block_before_any_write(self):
        value=self.f.field(self.old,'medida')
        value.type='Integer'
        with self.assertRaisesRegex(ValueError,'tipo/longitud'):self.run_tool(True)
        value.type='String'
        self.f.fields[self.f.paths[self.old]].append(self.f.make_field('intruso','String',20,True))
        with self.assertRaisesRegex(ValueError,'fuera del esquema'):self.run_tool(True)
        self.assertEqual(self.calls,[])

    def prepare_sde_predios(self):
        self.f.use_sde()
        old='predios_inscritos_en_sunarp_recorte';new='predios_inscritos_sunarp_recorte'
        cls=next(c for c in self.source['clases'] if c['nombre']==old)
        cls['nombre']=new
        row=next(r for r in self.mapping['clases'] if r['nombre_anterior']==old)
        row.update(nombre_nuevo=new,renombrar=True)
        for change in self.config['cambios']:
            if change['clase']==old:change['clase']=new
        self.write_inputs()
        self.sql_queries=[]
        def sql_result(query):
            self.sql_queries.append(query)
            name=new if f"LOWER(tab.name)=N'{new}'" in query else old
            length=self.f.field(name,'cargas_y_gravamenes').length
            sql_length=self.f.sql_length_override
            if sql_length is None:sql_length=-1 if length>=10000 else 8000
            return [[self.f.sql_type,sql_length]]
        self.f.a.ArcSDESQLExecute.return_value.execute.side_effect=sql_result
        return old,new

    def test_sde_uses_real_old_then_new_table_metadata_without_type_writes(self):
        old,new=self.prepare_sde_predios()
        _,r=self.run_tool(True,names=[new])
        self.assertEqual(r['estado'],'NOMBRES_VERIFICADOS')
        self.assertIn(new,self.f.paths)
        self.assertEqual(self.f.field(new,'cargas_y_gravamenes').length,4000)
        self.assertTrue(any(f"LOWER(tab.name)=N'{old}'" in q for q in self.sql_queries))
        self.assertTrue(any(f"LOWER(tab.name)=N'{new}'" in q for q in self.sql_queries))
        self.assertTrue(all(q.startswith('SELECT ') for q in self.sql_queries))
        self.f.a.management.AlterField.assert_not_called()

    def test_sde_already_long_text_requires_real_max_before_rename(self):
        old,new=self.prepare_sde_predios()
        self.f.field(old,'cargas_y_gravamenes').length=10000
        self.f.sql_length_override=8000
        with self.assertRaisesRegex(ValueError,'no se confirma como NVARCHAR'):
            self.run_tool(True,names=[new])
        self.assertEqual(self.calls,[])
        self.f.sql_length_override=None
        _,r=self.run_tool(True,names=[new])
        self.assertEqual(r['estado'],'NOMBRES_VERIFICADOS')
        self.assertEqual(self.f.field(new,'cargas_y_gravamenes').length,10000)

    def test_casefold_match_cannot_confirm_non_snake_physical_name(self):
        # Simula catalogo que expone el nombre fisico en MAYUSCULAS.
        path=self.f.paths[self.old]
        upper=os.path.join(self.f.ds,'GIS.'+self.old.upper())
        for attribute in ('fields','records','indices','descriptions'):
            values=getattr(self.f,attribute);values[upper]=values.pop(path)
        self.f.paths.pop(self.old);self.f.paths[self.old.upper()]=upper
        with self.assertRaisesRegex(ValueError,'escritura del nombre incompatible'):
            self.run_tool(True)
        self.assertEqual(self.calls,[])


if __name__=='__main__':unittest.main()
