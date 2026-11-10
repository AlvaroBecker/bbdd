"""Verificaciones de cobertura, colisiones y guardas sin una licencia ArcGIS."""
import csv
import json
from pathlib import Path
import unittest
from types import SimpleNamespace

import crear_esquema as runtime

HERE=Path(__file__).resolve().parent


class Cursor:
    def __init__(self,rows): self.rows=rows
    def __enter__(self): return iter(self.rows)
    def __exit__(self,*args): pass


class EsquemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model=json.loads((HERE/'esquema.json').read_text(encoding='utf-8'))

    def test_cobertura_y_balance(self):
        def read(name):
            with (HERE/name).open(encoding='utf-8-sig',newline='') as f:
                return list(csv.DictReader(f,delimiter=';'))
        fields=read('campos_matriz_a_esquema.csv')
        groups=read('mapeo_capas_revision.csv')
        self.assertEqual(len(fields),3507)
        self.assertEqual(len({(r['descripcion'],r['geometria']) for r in fields}),125)
        self.assertEqual(len(groups),3638)
        self.assertEqual(sum(int(r['elementos']) for r in groups),279623)
        self.assertTrue(all(not r['incluir'] and not r['co_proyecto'] for r in groups))
        counts=read('catalogo_clases.csv')
        self.assertEqual(sum(int(r['elementos_propuestos']) for r in counts),
                         sum(int(r['elementos']) for r in groups if r['clase_propuesta']))

    def test_campos_sin_colisiones_y_relaciones(self):
        classes=self.model['clases']
        self.assertEqual(len({c['nombre'].lower() for c in classes}),len(classes))
        rels={r['destino']:r for r in self.model['relaciones']}
        for c in classes:
            fields={f['nombre'].lower():f for f in c['campos']}
            self.assertEqual(len(fields),len(c['campos']))
            self.assertIn(c['geometria'],('POINT','POLYLINE','POLYGON'))
            if c['dataset']=='Datos_Proyecto':
                self.assertFalse(fields['proyecto']['nullable'])
                self.assertFalse(fields['id_analisis']['nullable'])
                self.assertEqual(fields['proyecto']['longitud'],12)
                self.assertEqual(rels[c['nombre']]['clave_origen'],'co_proyecto')
            else:
                self.assertNotIn('proyecto',fields)
                self.assertNotIn(c['nombre'],rels)

    def test_todo_campo_mapeado_existe(self):
        classes={c['nombre']:{f['nombre'] for f in c['campos']} for c in self.model['clases']}
        with (HERE/'campos_matriz_a_esquema.csv').open(encoding='utf-8-sig',newline='') as f:
            for row in csv.DictReader(f,delimiter=';'):
                if row['estado']=='CAMPO_TEXTUAL':
                    self.assertIn(row['campo_destino'],classes[row['clase_destino']])
                elif row['estado']=='PENDIENTE_DESTINO':
                    self.assertEqual(row['clase_destino'],'')

    def test_llave_padre_rechaza_vacios_y_duplicados(self):
        for rows in [[(None,)],[(' ',)],[('PRY-00000005',),('PRY-00000005 ',)], [('PRY-00000005',),('pry-00000005',)]]:
            fake=SimpleNamespace(ListFields=lambda _: [SimpleNamespace(name='co_proyecto',type='String',length=12)],
                                 da=SimpleNamespace(SearchCursor=lambda *args:Cursor(rows)))
            with self.assertRaises(ValueError):
                runtime.parent_keys(fake,'parent','co_proyecto')

    def test_llave_padre_preserva_codigo(self):
        fake=SimpleNamespace(ListFields=lambda _: [SimpleNamespace(name='co_proyecto',type='String',length=12)],
                             da=SimpleNamespace(SearchCursor=lambda *args:Cursor([('PRY-00000005 ',)])))
        _,keys=runtime.parent_keys(fake,'parent','co_proyecto')
        self.assertEqual(keys,{'PRY-00000005'})

    def test_objeto_existente_incompatible_no_se_acepta(self):
        expected=[dict(nombre='proyecto',tipo='TEXT',longitud=12,nullable=False,dominio=None)]
        for actual in [[],[SimpleNamespace(name='proyecto',type='Integer')],
                       [SimpleNamespace(name='proyecto',type='String',length=8)],
                       [SimpleNamespace(name='proyecto',type='String',length=12,isNullable=True)]]:
            fake=SimpleNamespace(ListFields=lambda _:actual)
            with self.assertRaises(ValueError):
                runtime.validate_fields(fake,'existing',expected)


if __name__=='__main__': unittest.main(verbosity=2)
