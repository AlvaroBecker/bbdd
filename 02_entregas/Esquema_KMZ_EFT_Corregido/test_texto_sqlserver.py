from types import SimpleNamespace
from unittest.mock import Mock
import unittest
import validacion_texto_sqlserver as t


class SqlTextTests(unittest.TestCase):
    def api(self,result):
        self.execute=Mock(return_value=result)
        return SimpleNamespace(ArcSDESQLExecute=Mock(return_value=SimpleNamespace(execute=self.execute)))

    def test_local_gdb_performs_no_sql(self):
        a=self.api([])
        self.assertIsNone(t.verify(a,'fixture.gdb','gis',True))
        a.ArcSDESQLExecute.assert_not_called()

    def test_only_select_metadata_query_and_unicode_old_column(self):
        a=self.api([['nvarchar',8000]])
        result=t.verify(a,'fixture.sde','gis')
        self.assertTrue(result['unicode'])
        self.assertFalse(result['es_max'])
        sql=self.execute.call_args.args[0]
        self.assertTrue(sql.startswith('SELECT '))
        self.assertNotIn(';',sql)
        self.assertIn('sys.columns',sql)

    def test_non_unicode_column_blocks(self):
        with self.assertRaisesRegex(ValueError,'preservar Unicode'):
            t.verify(self.api([['varchar',4000]]),'fixture.sde','gis')

    def test_after_requires_max_and_exact_column(self):
        self.assertTrue(t.verify(self.api([['nvarchar',-1]]),'fixture.sde','GIS',True)['es_max'])
        for result in [[['nvarchar',8000]],[],[['nvarchar',-1],['nvarchar',-1]]]:
            with self.subTest(result=result),self.assertRaises(ValueError):
                t.verify(self.api(result),'fixture.sde','gis',True)

    def test_owner_cannot_change_sql_structure(self):
        a=self.api([['nvarchar',-1]])
        with self.assertRaises(ValueError):t.verify(a,'fixture.sde',"gis'; DROP TABLE t;--")
        a.ArcSDESQLExecute.assert_not_called()

    def test_repair_fields_only_and_injection_rejected(self):
        for name in t.ALLOWED_FIELDS:
            a=self.api([['nvarchar',-1]])
            self.assertTrue(t.verify(a,'fixture.sde','gis',True,field_name=name)['es_max'])
            self.assertIn(f"LOWER(col.name)=N'{name}'",self.execute.call_args.args[0])
        for name in ('otro_campo', "x'; DELETE FROM t;--"):
            a=self.api([['nvarchar',-1]])
            with self.assertRaises(ValueError):
                t.verify(a,'fixture.sde','gis',True,field_name=name)
            a.ArcSDESQLExecute.assert_not_called()

    def test_only_approved_old_and_new_table_names_are_queried(self):
        for name in t.ALLOWED_TABLES:
            a=self.api([['nvarchar',-1]])
            self.assertTrue(t.verify(a,'fixture.sde','gis',True,table_name=name)['es_max'])
            self.assertIn(f"LOWER(tab.name)=N'{name}'",self.execute.call_args.args[0])
        a=self.api([['nvarchar',-1]])
        with self.assertRaises(ValueError):
            t.verify(a,'fixture.sde','gis',table_name="otra_tabla';DROP TABLE x;--")
        a.ArcSDESQLExecute.assert_not_called()


if __name__=='__main__':unittest.main()
