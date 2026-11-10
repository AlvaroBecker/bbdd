"""Pruebas de cobertura, evidencia, limites semanticos y ausencia de carga."""
import copy
import csv
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import cobertura_ingesta as coverage


BASE = Path(__file__).resolve().parent


class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.rules = json.loads((BASE / coverage.RULES_FILE).read_text(encoding="utf-8"))
        self.row = {"fila_capas": "1", "archivo": r"inventario\Proyecto A.kmz",
                    "ruta": "Proyecto A / Alternativa 1", "descripcion": "Trazo / alternativas de ruta de la LT",
                    "geometria": "Punto", "elementos": "2", "clase_propuesta": "",
                    "dataset_propuesto": "", "motivo": "Pendiente", "incluir": "",
                    "clase_confirmada": "", "maestro_dataset": ""}
        self.profile = {"estado": "LECTURA_COMPLETA", "fuentes": [
            {"archivo": "Proyecto A.kmz", "sha256": "a" * 64}],
            "rutas": [{"archivo": "Proyecto A.kmz", "ruta": self.row["ruta"],
                       "geometria": "Punto", "clase": "", "esperados": 2,
                       "observados": 2, "estado": "COINCIDE"}], "campos_fuente": []}
        self.model = {"clases": [{"nombre": "vertices", "dataset": "Datos_Proyecto", "geometria": "POINT", "campos": []},
                                 {"nombre": "estructuras", "dataset": "Datos_Proyecto", "geometria": "POINT", "campos": []}]}
        self.fields = []

    def prepare(self, **kwargs):
        args = dict(rutas=[self.row], campos_por_ruta=self.fields, perfil=self.profile,
                    modelo=self.model, referencias={"verificados": True, "archivos_sha256": {}}, reglas=self.rules)
        args.update(kwargs)
        return coverage.preparar_cobertura(**args)

    def add_vertex(self):
        self.fields = [dict(self.row, campo_fuente="VERTICE", ejemplo_valor="V01")]
        self.profile["campos_fuente"] = [dict(self.profile["rutas"][0], campo_original="VÉRTICE",
                                             canal="Data", ocurrencia=1, registros=2,
                                             valores_utiles=2, max_utf16=3, ejemplos=["V01", "V02"])]

    def test_description_geometry_alone_does_not_map_to_substation(self):
        self.model["clases"].append({"nombre": "subestacion_punto", "dataset": "Datos_Proyecto",
                                     "geometria": "POINT", "descripciones": [self.row["descripcion"]]})
        result = self.prepare()["rutas"][0]
        self.assertEqual(result["estado"], "REVISION")
        self.assertEqual(result["clase_propuesta"], "")

    def test_explicit_vertex_requires_useful_profile_values(self):
        self.add_vertex()
        result = self.prepare()["rutas"][0]
        self.assertEqual(result["clase_propuesta"], "vertices")
        self.assertFalse(result["cargable"])
        self.assertEqual(len(result["evidencia"]["atributos_discriminantes"][0]["perfil_campo_sha256"]), 64)
        self.profile["campos_fuente"][0]["valores_utiles"] = 0
        self.assertEqual(self.prepare()["rutas"][0]["clase_propuesta"], "")

    def test_profile_count_mismatch_blocks_proposal(self):
        self.add_vertex()
        self.profile["rutas"][0]["observados"] = 1
        row = self.prepare()["rutas"][0]
        self.assertEqual(row["estado"], "REVISION")
        self.assertEqual(row["clase_propuesta"], "")
        self.assertIn("CONTEO_O_RUTA_NO_VERIFICADOS_EN_PERFIL", row["incidencias"])

    def test_unverified_references_block_proposal(self):
        self.add_vertex()
        row = self.prepare(referencias={"verificados": False})["rutas"][0]
        self.assertEqual(row["estado"], "REVISION")
        self.assertEqual(row["clase_propuesta"], "")

    def test_wrong_target_geometry_or_dataset_blocks_proposal(self):
        self.add_vertex()
        self.model["clases"][0]["geometria"] = "POLYGON"
        self.assertEqual(self.prepare()["rutas"][0]["estado"], "REVISION")
        self.model["clases"][0]["geometria"] = "POINT"
        self.model["clases"][0]["dataset"] = "Datos_Internos"
        self.assertEqual(self.prepare()["rutas"][0]["estado"], "REVISION")

    def test_duplicate_route_rejected_but_distinct_geometry_preserved(self):
        with self.assertRaisesRegex(ValueError, "duplicada"):
            self.prepare(rutas=[self.row, copy.deepcopy(self.row)])
        second = dict(self.row, fila_capas="2", geometria="Línea", elementos="3")
        self.profile["rutas"].append(dict(self.profile["rutas"][0], geometria="Línea", esperados=3, observados=3))
        result = self.prepare(rutas=[self.row, second])
        self.assertEqual(result["resumen"]["inventario"], {"rutas": 2, "elementos": 5})
        self.assertEqual(len(result["rutas"]), 2)

    def test_duplicate_basename_source_and_extra_profile_route_rejected(self):
        self.profile["fuentes"].append({"archivo": r"otra\Proyecto A.kmz", "sha256": "b" * 64})
        with self.assertRaisesRegex(ValueError, "ambigua"):
            self.prepare()
        self.profile["fuentes"].pop()
        self.profile["rutas"].append(dict(self.profile["rutas"][0], ruta="otra"))
        with self.assertRaisesRegex(ValueError, "no presentes"):
            self.prepare()

    def test_existing_mapping_is_not_loading_approval(self):
        self.row.update(clase_propuesta="vertices", dataset_propuesto="Datos_Proyecto")
        self.profile["rutas"][0]["clase"] = "vertices"
        row = self.prepare()["rutas"][0]
        self.assertEqual(row["estado"], "MAPEO_ACTUAL")
        self.assertEqual(row["clase_destino_actual"], "vertices")
        self.assertFalse(row["cargable"])

    def test_section_parser_keeps_strings_and_does_not_count_spans(self):
        text = ("Section #10, 60kV, '240mm2_aaac_NTP', from Str. #T01 Set 2 'Fase A CTO 1' "
                "to Str. #T05 Set 2 'Fase A CTO 1', Section at Temperatura máxima 60 kV 'Creep RS'")
        parsed = coverage.extraer_conectividad(text)
        self.assertEqual(parsed["estructura_origen"], "T01")
        self.assertEqual(parsed["estructura_destino"], "T05")
        self.assertEqual(parsed["circuito"], "1")
        self.assertEqual(parsed["tension_kv"], 60.0)
        self.assertEqual(parsed["nombre_original"], text)
        self.assertIsNone(parsed["numero_vanos_final"])
        absent = coverage.extraer_conectividad(text.replace("Fase A CTO 1", "Cable de Guarda 1"))
        self.assertIsNone(absent["circuito"])
        mismatch = coverage.extraer_conectividad(text.replace("to Str. #T05 Set 2 'Fase A CTO 1'", "to Str. #T05 Set 2 'Fase A CTO 2'"))
        self.assertIsNone(mismatch["circuito"])
        self.assertEqual(coverage.extraer_conectividad("Section desconocida")["estado"], "NOMBRE_NO_INTERPRETADO")

    def test_cad_and_models_are_not_automatically_discarded(self):
        self.row["descripcion"] = "Textos / anotaciones del plano"
        row = self.prepare()["rutas"][0]
        self.assertEqual(row["estado"], "DESCARTE_POR_APROBAR")
        self.assertEqual(row["disposicion_final"], "PENDIENTE")
        self.assertIn("REVISION_MANUAL", row["opciones_disposicion"])

    def test_pure_function_preserves_inputs(self):
        self.add_vertex()
        before = copy.deepcopy((self.row, self.profile, self.fields, self.model, self.rules))
        self.prepare()
        self.assertEqual(before, (self.row, self.profile, self.fields, self.model, self.rules))

    def fixture_package(self, root):
        rules = copy.deepcopy(self.rules)
        routes = io.StringIO()
        writer = csv.DictWriter(routes, fieldnames=list(self.row), delimiter=";")
        writer.writeheader()
        writer.writerow(self.row)
        payloads = {"esquema.json": json.dumps(self.model).encode(),
                    "mapeo_capas_revision.csv": routes.getvalue().encode(),
                    "campos_por_ruta.csv": b"archivo;ruta;geometria;campo_fuente\n"}
        refs = {name: hashlib.sha256(data).hexdigest() for name, data in payloads.items()}
        payloads[coverage.PROFILE_FILE] = json.dumps({"perfil": self.profile, "referencias_sha256": refs}).encode()
        rules["archivos_sha256"] = {name: hashlib.sha256(data).hexdigest() for name, data in payloads.items()}
        rules["esperados"] = {"rutas": 1, "elementos": 2, "fuentes": 1, "clases_actuales": 2}
        for name, data in payloads.items():
            (root / name).write_bytes(data)
        (root / coverage.RULES_FILE).write_text(json.dumps(rules), encoding="utf-8")

    def test_package_integrity_and_output_never_overwrites(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture_package(root)
            originals = {p.name: p.read_bytes() for p in root.iterdir()}
            result = coverage.generar_plan(root)
            self.assertEqual(result["resumen"]["inventario"]["rutas"], 1)
            self.assertEqual(originals, {p.name: p.read_bytes() for p in root.iterdir()})
            out = root / "plan.json"
            coverage.generar_plan(root, out)
            with self.assertRaises(FileExistsError):
                coverage.generar_plan(root, out)
            (root / "esquema.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Referencia alterada"):
                coverage.generar_plan(root)

    def test_actual_package_reconciles_all_routes_and_does_not_load(self):
        result = coverage.generar_plan(BASE)
        self.assertEqual(result["resumen"]["inventario"], {"rutas": 3638, "elementos": 279623})
        self.assertEqual(result["resumen"]["sin_destino_original"], {"rutas": 2601, "elementos": 140319})
        self.assertEqual(result["resumen"]["grupos_pendientes"], 65)
        self.assertEqual(result["resumen"]["propuestas_sustentadas"], {"rutas": 91, "elementos": 35823})
        self.assertEqual(result["resumen"]["incidencias"], 0)
        self.assertEqual(result["procesamiento_pls"]["secciones_rutas"], 1881)
        self.assertEqual(result["procesamiento_pls"]["secciones_parseadas"], 1881)
        self.assertIsNone(result["procesamiento_pls"]["numero_vanos_final"])
        self.assertTrue(all(r["cargable"] is False for r in result["rutas"]))
        self.assertFalse(result["ingesta_autorizada"])
        self.assertFalse(result["cambios_en_sde"])
        classes = {c["nombre"]: c for c in result["clases_propuestas"]}
        self.assertEqual(set(classes), {"vanos", "bofedales_inaigem_recorte"})
        self.assertEqual({f["nombre"] for f in classes["vanos"]["campos"]},
                         {"proyecto", "id_analisis", "estructura_origen", "estructura_destino", "circuito", "tension_kv", "conductor"})
        self.assertEqual(classes["bofedales_inaigem_recorte"]["campos"][-1]["longitud_observada_max"], 7)
        self.assertNotIn("archivo_origen", {f["nombre"] for c in classes.values() for f in c["campos"]})


if __name__ == "__main__":
    unittest.main()
