import csv
import tempfile
import unittest
from pathlib import Path

import eft_atributos
import eft_mapeo
import eft_modelo
import eft_reglas


class ReglasTests(unittest.TestCase):
    def test_normaliza_y_id_estable(self):
        self.assertEqual(eft_reglas.norm("Líneas de Transmisión"), "lineas de transmision")
        ruta = ("Doc", "Proyecto", "Ingeniería", "Vértices", "LT 220 kV")
        self.assertEqual(eft_reglas.grupo_id("Proyecto A.kmz", ruta, "PUNTO"),
                         eft_reglas.grupo_id("Proyecto A.kmz", ruta, "PUNTO"))
        self.assertNotEqual(eft_reglas.grupo_id("Proyecto A.kmz", ruta, "PUNTO"),
                            eft_reglas.grupo_id("Proyecto A.kmz", ruta, "LINEA"))

    def test_hoja_geometrica_y_componente(self):
        decision = eft_reglas.clasificar(
            "Proyecto CHANCHAMAYO.kmz",
            ("CHANCHAMAYO Final", "CHANCHAMAYO", "1. Líneas de Transmisión", "1. Vértices", "LT 220 kV"),
            eft_modelo.PUNTO,
        )
        self.assertEqual(decision.estado, eft_reglas.CARGAR)
        self.assertEqual(decision.destino, "Vertices")
        self.assertEqual(decision.componente, "LT 220 kV")
        self.assertEqual(decision.proyecto, "PRY-00000005")

    def test_regla_pls_cadd_por_geometria(self):
        ruta = ("Proyecto", "CHANCHAMAYO", "1. Ingeniería", "PLS-CADD Model", "Section 1", "Line Features")
        decision = eft_reglas.clasificar("Proyecto CHANCHAMAYO.kmz", ruta, eft_modelo.LINEA)
        self.assertEqual(decision.destino, "Vanos")
        self.assertEqual(decision.estado, eft_reglas.CARGAR)
        self.assertIn("Q-04", decision.preguntas)

    def test_recorte_publico_y_condicion(self):
        decision = eft_reglas.clasificar(
            "Proyecto CHANCHAMAYO.kmz",
            ("Proyecto", "CHANCHAMAYO", "4. Consultor Predial", "OSINERGMIN-LT",
             "LT_EN_OPERACION", "SUBESTACIONES EN OPERACIÓN", "Point Features"),
            eft_modelo.PUNTO,
        )
        self.assertEqual(decision.destino, "SE_Existente_Recorte")
        self.assertEqual(decision.estado, eft_reglas.CARGAR)
        self.assertEqual(decision.condicion, "Existente")
        self.assertEqual(decision.fuente, "OSINERGMIN")

    def test_area_estudio_estacion(self):
        decision = eft_reglas.clasificar(
            "Proyecto CHANCHAMAYO.kmz",
            ("Proyecto", "CHANCHAMAYO", "5. Consultor Ambiental", "Biológico", "PL01",
             "ÁREA DE ESTUDIO DE CAMPO", "Polygon Features"),
            eft_modelo.POLIGONO,
        )
        self.assertEqual(decision.destino, "AreaEstudioCampo")
        self.assertEqual(decision.estado, eft_reglas.CARGAR)
        self.assertIn("S-16", decision.supuestos)

    def test_fringe_over_60m_is_pending(self):
        decision = eft_reglas.clasificar(
            "Proyecto CHANCHAMAYO.kmz",
            ("Proyecto", "CHANCHAMAYO", "1. Ingeniería", "Área de estudio", "Franja_400m"),
            eft_modelo.POLIGONO,
        )
        self.assertEqual(decision.destino, "FranjaServidumbre")
        self.assertEqual(decision.estado, eft_reglas.PENDIENTE)
        self.assertIn("Q-13", decision.preguntas)

    def test_provisional_project_blocks_auto_load(self):
        decision = eft_reglas.clasificar(
            "Proyecto JAENNORTE.kmz",
            ("Proyecto", "Jaén Norte", "1. Ingeniería", "Torres", "Point Features"),
            eft_modelo.PUNTO,
        )
        self.assertEqual(decision.destino, "Estructuras")
        self.assertEqual(decision.estado, eft_reglas.PENDIENTE)
        self.assertTrue(decision.proyecto.startswith("PROV-"))
        self.assertIn("Q-01", decision.preguntas)

    def test_special_geometry_and_invalid_pair(self):
        decision = eft_reglas.clasificar(
            "Proyecto JAENNORTE.kmz", ("Proyecto", "Jaén Norte", "PLS-CADD Model"), eft_reglas.MULTIPATCH
        )
        self.assertEqual(decision.estado, eft_reglas.PENDIENTE)
        self.assertIn("Q-07", decision.preguntas)
        self.assertFalse(eft_modelo.validar_destino("Vanos", eft_modelo.PUNTO)[0])


class AtributosTests(unittest.TestCase):
    def test_station_code_includes_pl_and_m(self):
        self.assertEqual(eft_atributos.codigo_estacion(["Proyecto", "PL01"]), "PL01")
        self.assertEqual(eft_atributos.codigo_estacion(["Proyecto", "M10"]), "M10")

    def test_description_html_table_is_parsed(self):
        payload = {"attribute_xml": [
            "<description>&lt;table&gt;&lt;tr&gt;&lt;td&gt;Punto&lt;/td&gt;"
            "&lt;td&gt;A&lt;/td&gt;&lt;/tr&gt;&lt;/table&gt;</description>"
        ]}
        self.assertEqual(eft_atributos.atributos_de(payload), {"Punto": "A"})

    def test_field_system_ids_are_not_duplicated(self):
        payload = {"attribute_xml": [
            "<ExtendedData><Data name=\"OBJECTID\"><value>2</value></Data>"
            "<Data name=\"CODRUTA\"><value>R-15</value></Data></ExtendedData>"
        ]}
        valores = eft_atributos.atributos_de(payload)
        self.assertEqual(valores, {"CODRUTA": "R-15"})
        self.assertEqual(eft_atributos.id_origen(valores), "R-15")


class MapeoTests(unittest.TestCase):
    def _grupo(self):
        return eft_reglas.Grupo(
            eft_reglas.grupo_id("Proyecto CHANCHAMAYO.kmz",
                                ("Proyecto", "CHANCHAMAYO", "1. Ingeniería", "Torres", "Point Features"),
                                eft_modelo.PUNTO),
            "Proyecto CHANCHAMAYO.kmz",
            ("Proyecto", "CHANCHAMAYO", "1. Ingeniería", "Torres", "Point Features"),
            eft_modelo.PUNTO, 1, 1,
        )

    def test_proposal_and_explicit_review_preservation(self):
        grupo = self._grupo()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mapeo_eft.csv"
            filas = eft_mapeo.proponer([grupo], path)
            filas[0]["comentario_revision"] = "Validado manualmente"
            eft_mapeo.escribir(path, filas)
            filas = eft_mapeo.proponer([grupo], path)
            self.assertEqual(filas[0]["comentario_revision"], "Validado manualmente")
            self.assertEqual(filas[0]["clase_destino"], "Estructuras")
            self.assertEqual(filas[0]["incluir"], "SI")

    def test_regenerate_keeps_comments_but_refreshes_proposal(self):
        grupo = self._grupo()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mapeo_eft.csv"
            filas = eft_mapeo.proponer([grupo], path)
            filas[0]["comentario_revision"] = "Conservar nota"
            filas[0]["clase_destino"] = "OtraClase"
            eft_mapeo.escribir(path, filas)
            filas = eft_mapeo.proponer([grupo], path, regenerar=True)
            self.assertEqual(filas[0]["comentario_revision"], "Conservar nota")
            self.assertEqual(filas[0]["clase_destino"], "Estructuras")
            self.assertTrue(list(Path(tmp).glob("*.bak_*.csv")))

    def test_invalid_load_cannot_be_effective(self):
        fila = {
            "incluir": "SI", "estado": "CARGAR", "clase_destino": "Vanos",
            "geometria": eft_modelo.PUNTO, "proyecto": "PRY-00000005",
        }
        estado, motivo = eft_mapeo.estado_efectivo(fila)
        self.assertEqual(estado, eft_reglas.PENDIENTE)
        self.assertIn("admite", motivo)


if __name__ == "__main__":
    unittest.main()
