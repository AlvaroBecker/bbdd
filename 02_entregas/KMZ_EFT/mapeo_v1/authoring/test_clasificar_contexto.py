"""Regresiones sintéticas de propuestas de contexto; sin GIS, SQL ni aprobaciones."""
import copy
import json
import unittest

from clasificar_contexto import classify


def row(parts, geometry="PUNTO", file="Proyecto EJEMPLO.kmz"):
    return {"archivo_origen": file, "ruta_componentes_json": json.dumps(parts, ensure_ascii=False),
            "geometria": geometry, "source_id": "hash_fuente", "co_proyecto_validado": "", "incluir_aprobado": ""}


class ContextTests(unittest.TestCase):
    def test_is_pure_and_never_emits_approval_or_business_ids(self):
        source = row(["Proyecto", "Calicatas", "LT 60kV"])
        original = copy.deepcopy(source)
        result = classify(source)
        self.assertEqual(source, original)
        self.assertEqual(set(result), {"familia", "clase_propuesta", "opciones_destino", "contexto_agrupacion", "motivo", "pendiente_especifico", "referencia_eft"})
        self.assertFalse(any("aprobado" in key or key.startswith("id_") or key.startswith("co_proyecto") for key in result))

    def test_pls_sections_group_by_root_geometry_and_role_not_section_number(self):
        base = ["Proyecto", "LT 220kV", "PLS-CADD Model"]
        first = classify(row(base + ["Section #1, 220kV, from Str. #T01 to #T02"], "LINEA"))
        second = classify(row(base + ["Section #99, 220kV, from Str. #T99 to #T100"], "LINEA"))
        self.assertEqual(first["familia"], "PLS-CADD")
        self.assertEqual(first["contexto_agrupacion"], second["contexto_agrupacion"])
        self.assertEqual(first["clase_propuesta"], "")
        self.assertEqual(first["opciones_destino"], ["Estructuras", "Vanos"])
        polygon = classify(row(base + ["Section #1"], "POLIGONO"))
        self.assertEqual(polygon["clase_propuesta"], "")
        self.assertNotEqual(first["contexto_agrupacion"], polygon["contexto_agrupacion"])

    def test_structure_locations_points_proposed_without_classifying_wireframes(self):
        point = classify(row(["Proyecto", "PLSCADD", "Structure locations"]))
        line = classify(row(["Proyecto", "PLSCADD", "Structure 'T1'"], "LINEA"))
        self.assertEqual(point["clase_propuesta"], "Estructuras")
        self.assertEqual(line["clase_propuesta"], "")

    def test_html_href_not_used_as_pls_evidence_and_literal_slash_preserved(self):
        name = '<a href="file:///D:/PLSCADD/Modelo.xyz">Modelo / inspección</a>'
        result = classify(row(["Proyecto", name, "Point Features"]))
        context = json.loads(result["contexto_agrupacion"])
        self.assertEqual(result["familia"], "Entidades CAD por interpretar")
        self.assertEqual(context["ruta"], ["Proyecto", name])
        self.assertEqual(result["clase_propuesta"], "")

    def test_calicatas_ancestor_overrides_substation_and_lt_leaf(self):
        for leaf in ["Subestación Jaén", "LT 60kV", "Vértices"]:
            with self.subTest(leaf=leaf):
                result = classify(row(["Proyecto", "Calicatas", leaf]))
                self.assertEqual(result["clase_propuesta"], "Calicatas")
        auxiliary = classify(row(["Proyecto", "Calicatas", "Subestación Jaén"], "LINEA"))
        self.assertEqual(auxiliary["clase_propuesta"], "")

    def test_field_area_uses_station_context_but_not_every_station_polygon(self):
        for station in ("EBI01A", "EBI01B", "F01", "SOC02", "EBI01A/B"):
            with self.subTest(station=station):
                result = classify(row(["Proyecto", "Ambiental", station, "ÁREA DE ESTUDIO"], "POLIGONO"))
                self.assertEqual(result["clase_propuesta"], "AreaEstudioCampo")
        other = classify(row(["Proyecto", "Ambiental", "SOC01", "COMUNIDAD CAMPESINA"], "POLIGONO"))
        self.assertNotEqual(other["clase_propuesta"], "AreaEstudioCampo")
        self.assertEqual(classify(row(["Proyecto", "ÁREA DE ESTUDIO DE CAMPO"], "POLIGONO"))["clase_propuesta"], "AreaEstudioCampo")

    def test_ambiguous_general_area_not_automatically_aoi(self):
        result = classify(row(["Proyecto", "Ambiental", "Prefinal", "Area de estudio"], "POLIGONO"))
        self.assertEqual(result["clase_propuesta"], "")
        self.assertIn("mline_td_proyecto_area_interes", result["opciones_destino"])

    def test_public_aliases_are_recortes_with_geometry_checked(self):
        tests = [(["Proyecto", "ANA", "RiosSecc_LT2"], "LINEA", "Rios_Recorte"),
                 (["Proyecto", "ANA", "FAJ_MARG_LT2"], "PUNTO", "FajasMarginales_Recorte"),
                 (["Proyecto", "SERNANP", "ANP_LT2"], "POLIGONO", "ANPNacional_Recorte"),
                 (["Proyecto", "SUNARP", "Predios SUNARP"], "POLIGONO", "PredioSUNARP_Recorte"),
                 (["Proyecto", "LY_SIMP_Mineras_17S"], "POLIGONO", "CatastroMinero_Recorte"),
                 (["Proyecto", "LY_SIMP_Red_Vial_Departamental"], "LINEA", "ViasRegional_Recorte")]
        for parts, geometry, expected in tests:
            with self.subTest(parts=parts):
                self.assertEqual(classify(row(parts, geometry))["clase_propuesta"], expected)
        wrong = classify(row(["Proyecto", "ANA", "FAJ_MARG_LT2"], "POLIGONO"))
        self.assertEqual(wrong["clase_propuesta"], "")

    def test_more_specific_public_child_beats_parent_anp(self):
        result = classify(row(["Proyecto", "SERNANP", "ANP Nacional", "Zonas de amortiguamiento"], "POLIGONO"))
        self.assertEqual(result["clase_propuesta"], "ZonaAmortiguamiento_Recorte")

    def test_substation_point_polygon_share_theme_pending_distinct_physical_names(self):
        for geometry in ("PUNTO", "POLIGONO"):
            result = classify(row(["Proyecto", "SUBESTACIÓN ELÉCTRICA"], geometry))
            self.assertEqual(result["clase_propuesta"], "Subestacion")
            self.assertIn("nombres físicos distintos", result["pendiente_especifico"])

    def test_transmission_trace_cannot_choose_component_or_alternative(self):
        for name in ("LT500kV", "Eje de Línea de Transmisión - Opción 1", "Alternativa 2"):
            result = classify(row(["Proyecto", name], "LINEA"))
            self.assertEqual(result["clase_propuesta"], "")
            self.assertEqual(result["opciones_destino"], ["mline_td_proyecto_ltransmision", "mline_td_proyecto_infraestructura"])

    def test_torres_copies_are_retained_as_proposals(self):
        a = classify(row(["Pariñas", "Ingeniería", "TORRES"], file="Proyecto PARIÑAS.kmz"))
        b = classify(row(["Pariñas", "Ambiental", "F01", "TORRES"], file="Proyecto PARIÑAS.kmz"))
        self.assertEqual(a["clase_propuesta"], "Estructuras")
        self.assertEqual(b["clase_propuesta"], "Estructuras")
        self.assertNotEqual(a["contexto_agrupacion"], b["contexto_agrupacion"])

    def test_unknowns_group_by_ancestor_not_only_geometry(self):
        a = classify(row(["Proyecto", "Diseño A", "Point Features"]))
        b = classify(row(["Proyecto", "Diseño B", "Point Features"]))
        self.assertEqual(a["clase_propuesta"], "")
        self.assertNotEqual(a["contexto_agrupacion"], b["contexto_agrupacion"])
        for geometry in ("MODELO_3D", "SIN_GEOMETRIA", "TRAZA_GX", "DESCONOCIDA"):
            self.assertEqual(classify(row(["Proyecto", "TORRES"], geometry))["clase_propuesta"], "")

    def test_does_not_invent_classes_for_unlisted_themes_or_bad_json(self):
        unlisted = classify(row(["Proyecto", "LY_SIMP_Concesiones_Forestales"], "POLIGONO"))
        self.assertEqual(unlisted["clase_propuesta"], "")
        malformed = classify({"ruta_componentes_json": "not-json / LT", "geometria": "LINEA"})
        self.assertEqual(malformed["clase_propuesta"], "")
        self.assertEqual(malformed["opciones_destino"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
