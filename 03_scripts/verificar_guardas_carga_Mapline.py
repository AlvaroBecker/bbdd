import importlib.util, sqlite3, types, unittest
from pathlib import Path
p=Path(__file__).resolve().parent.parent/'02_entregas'/'ArcGisAWS_Carga_Mapline'/'02_cargar_modelo_arcgis.py'
spec=importlib.util.spec_from_file_location('loader',p); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
class Guards(unittest.TestCase):
 def make(self, bad=False, duplicate=False):
  self.data={'mline_tc_proyecto':[{'id_proyecto':1,'co_proyecto':'PRY-00000001'},{'id_proyecto':2,'co_proyecto':'PRY-00000002'}], 'mline_td_proyecto_componente':[{'id_proyecto_componente':10,'id_proyecto':1},{'id_proyecto_componente':11,'id_proyecto':2}], 'mline_td_proyecto_alternativa':[{'id_proyecto_alternativa':100,'id_proyecto_componente':10,'id_alternativa_origen':None},{'id_proyecto_alternativa':101,'id_proyecto_componente':11 if bad else 10,'id_alternativa_origen':100}]}
  if duplicate:self.data['mline_tc_proyecto'][1]['id_proyecto']=1
  tables=[]
  for name, rows in self.data.items():tables.append({'name':name,'primary_key':[next(iter(rows[0]))],'fields':[{'name':f}for f in rows[0]],'rows':len(rows)})
  model={'tables':tables,'relations':[{'name':'alt_parent','parent':'mline_td_proyecto_alternativa','child':'mline_td_proyecto_alternativa','parent_key':'id_proyecto_alternativa','child_key':'id_alternativa_origen'}]}
  api=types.SimpleNamespace(ListFields=lambda path:[types.SimpleNamespace(name=f) for f in self.data[path.split('.')[-1]][0]])
  loader=m.Loader(api,model,{},sqlite3.connect(':memory:'))
  loader.rows=lambda name,fields: iter(tuple(row.get(f) for f in fields) for row in self.data[name])
  return loader
 def test_missing_config_stops_before_connection(self):
  with self.assertRaisesRegex(RuntimeError,'Complete source_sde'): self.make().verify_connections()
 def test_valid_keys_and_same_project(self):self.make().verify_stage()
 def test_duplicate_key_rejected(self):
  with self.assertRaisesRegex(RuntimeError,'repetida'):self.make(duplicate=True).verify_stage()
 def test_cross_project_reference_rejected(self):
  with self.assertRaisesRegex(RuntimeError,'proyectos distintos'):self.make(bad=True).verify_stage()
if __name__=='__main__': unittest.main()
