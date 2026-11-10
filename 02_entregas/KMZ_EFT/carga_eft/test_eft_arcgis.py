import os
import tempfile
import unittest

try:
    import arcpy
except ImportError:
    arcpy = None

import eft_modelo


@unittest.skipIf(arcpy is None, "Requiere el entorno Python de ArcGIS Pro.")
class EstructuraArcPyTests(unittest.TestCase):
    def test_create_structure_is_idempotent_and_adds_eft_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            gdb = arcpy.management.CreateFileGDB(tmp, "eft_test.gdb").getOutput(0)
            try:
                table = arcpy.management.CreateTable(gdb, eft_modelo.TABLA_PROYECTO).getOutput(0)
                arcpy.management.AddField(table, eft_modelo.CLAVE_PROYECTO, "TEXT", field_length=20)
                specs = eft_modelo.specs_de_destinos([
                    ("Estructuras", eft_modelo.PUNTO),
                    ("Rios_Recorte", eft_modelo.LINEA),
                    ("Subestacion", eft_modelo.POLIGONO),
                    ("Subestacion", eft_modelo.PUNTO),
                ])

                primera = eft_modelo.crear_estructura(gdb, specs)
                segunda = eft_modelo.crear_estructura(gdb, specs)
                self.assertEqual(primera, segunda)

                relacion = eft_modelo.crear_relaciones(gdb, specs)
                self.assertEqual(relacion["motivo"], "")
                self.assertEqual(len(relacion["creadas"]), 4)

                for spec in specs:
                    ruta = primera[spec.fisico.lower()]
                    descripcion = arcpy.Describe(ruta)
                    self.assertEqual(descripcion.spatialReference.factoryCode, eft_modelo.WKID)
                    self.assertTrue(descripcion.hasZ)
                    self.assertTrue(descripcion.hasGlobalID)
                    self.assertTrue(descripcion.editorTrackingEnabled)
                    nombres = {campo.name.lower() for campo in arcpy.ListFields(ruta)}
                    self.assertTrue(set(x.lower() for x in eft_modelo.nombres_campos(spec)).issubset(nombres))

                dominios = {d.name for d in arcpy.da.ListDomains(gdb)}
                self.assertEqual(dominios, set(eft_modelo.DOMINIOS))
            finally:
                arcpy.management.ClearWorkspaceCache(gdb)

    def test_relationship_creation_skips_when_project_table_is_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            gdb = arcpy.management.CreateFileGDB(tmp, "eft_no_project.gdb").getOutput(0)
            try:
                spec = eft_modelo.spec_de("Estructuras", eft_modelo.PUNTO)
                eft_modelo.crear_estructura(gdb, [spec])
                resultado = eft_modelo.crear_relaciones(gdb, [spec])
                self.assertEqual(resultado["creadas"], [])
                self.assertIn(eft_modelo.TABLA_PROYECTO, resultado["motivo"])
            finally:
                arcpy.management.ClearWorkspaceCache(gdb)


if __name__ == "__main__":
    unittest.main()
