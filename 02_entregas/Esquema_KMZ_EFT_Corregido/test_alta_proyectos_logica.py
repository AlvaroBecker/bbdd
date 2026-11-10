"""Regresiones del planificador puro; ejecutar con unittest, sin ArcGIS."""

import copy
import datetime
import json
import unittest

import alta_proyectos_logica as logic


def row(identifier, name=None, description=None, state="1", **extra):
    result = {"id_proyecto": identifier, "co_proyecto": "PRY-%08d" % identifier,
              "no_proyecto": name or "Proyecto ajeno %d" % identifier,
              "de_proyecto": description, "es_registro": state}
    result.update(extra)
    return result


class PlanningTests(unittest.TestCase):
    def blocked(self, rows, expected):
        with self.assertRaises(logic.PlanError) as caught:
            logic.plan_projects(rows)
        self.assertIn(expected, {item["codigo"] for item in caught.exception.incidencias})
        json.dumps(caught.exception.incidencias)

    def test_next_two_after_all_rows_including_inactive_and_no_mutation(self):
        catalog = [row(40, state="0", us_creacion="historico", fe_eliminacion=datetime.datetime(2020, 1, 1)), row(2)]
        before = copy.deepcopy(catalog)
        plan = logic.plan_projects(catalog)
        self.assertEqual([item["valores"]["co_proyecto"] for item in plan["altas"]], ["PRY-00000041", "PRY-00000042"])
        self.assertEqual(catalog, before)
        self.assertFalse(plan["codigos_reservados"])
        self.assertEqual(plan["max_id_proyecto"], 40)
        for item in plan["altas"]:
            self.assertEqual(set(item["valores"]), set(logic.INSERT_FIELDS))
            self.assertEqual(item["valores"]["id_tipo_proyecto"], 8)
            self.assertEqual(item["valores"]["id_estado_proyecto"], 3)
            self.assertEqual(item["valores"]["es_registro"], "1")
        json.dumps(plan)

    def test_empty_catalog_starts_at_one(self):
        self.assertEqual([item["valores"]["id_proyecto"] for item in logic.plan_projects([])["altas"]], [1, 2])

    def test_reuses_both_exact_and_canonical_variations(self):
        catalog = [row(5, "proyecto-JAÉN_NORTE.kmz", "LT 220kV CÁCLIC — Jaén Norte"),
                   row(8, " Poroma ", "LT 220 kV Ica-Poroma")]
        plan = logic.plan_projects(catalog)
        self.assertEqual(plan["altas"], [])
        self.assertEqual(plan["estado"], "PROYECTOS_YA_EXISTEN")
        self.assertEqual([item["id_proyecto"] for item in plan["existentes"]], [5, 8])

    def test_reuses_inactive_without_reactivation(self):
        plan = logic.plan_projects([row(12, "Jaennorte", state="0"), row(20)])
        self.assertTrue(plan["existentes"][0]["inactivo"])
        self.assertTrue(plan["existentes"][0]["sin_modificar"])
        self.assertEqual(plan["altas"][0]["proyecto"], "POROMA")
        self.assertEqual(plan["altas"][0]["valores"]["id_proyecto"], 21)

    def test_deletion_date_marks_inactive_and_output_stays_json(self):
        plan = logic.plan_projects([row(2, "Poroma", fe_eliminacion=datetime.datetime(2020, 1, 1))])
        self.assertTrue(plan["existentes"][0]["inactivo"])
        json.dumps(plan)

    def test_root_label_can_be_the_name_or_only_description(self):
        catalog = [row(3, "LT 220 kV Caclic-Jaen Norte"), row(7, "Poroma")]
        catalog[1]["no_proyecto"] = None
        catalog[1]["de_proyecto"] = "LT 220 kV Ica-Poroma"
        self.assertEqual(len(logic.plan_projects(catalog)["existentes"]), 2)

    def test_duplicate_target_names_block_even_with_distinct_codes(self):
        self.blocked([row(1, "JAEN NORTE"), row(2, "Proyecto JAENNORTE")], "PROYECTO_DUPLICADO")

    def test_fuzzy_mentions_block_instead_of_creating_or_reusing(self):
        for name in ("LT 138 kV Jaen Norte", "Ampliacion Poroma", "G1 LT 220 kV Ica-Poroma", "Poroma II"):
            with self.subTest(name=name):
                self.blocked([row(1, name)], "COINCIDENCIA_AMBIGUA")
        self.blocked([row(1, "Poroma", "Ampliacion Poroma")], "COINCIDENCIA_AMBIGUA")

    def test_contradictory_names_block(self):
        self.blocked([row(1, "JAENNORTE", "LT 220 kV Ica-Poroma")], "PROYECTOS_CRUZADOS")
        self.blocked([row(1, "FELAM", "LT 220 kV Caclic-Jaen Norte")], "IDENTIDAD_CONTRADICTORIA")

    def test_duplicate_business_ids_and_codes_block(self):
        self.blocked([row(1), row(1)], "ID_DUPLICADO")
        self.blocked([row(1), row(2, co_proyecto="PRY-00000001")], "CODIGO_DUPLICADO")

    def test_id_must_be_actual_positive_bounded_integer(self):
        for value in (None, True, 1.0, "1", 0, -1, 100000000):
            candidate = row(1)
            candidate["id_proyecto"] = value
            with self.subTest(value=value):
                self.blocked([candidate], "ID_INVALIDO")

    def test_bad_codes_and_divergence_block(self):
        for value in (None, "", "pry-00000001", "PRY-1", " PRY-00000001", "PRY-00000001\n", "PRY-０００００００１"):
            with self.subTest(value=value):
                self.blocked([row(1, co_proyecto=value)], "CODIGO_INVALIDO")
        self.blocked([row(1, co_proyecto="PRY-00000002")], "SECUENCIA_CONTRADICTORIA")

    def test_nchar_padding_is_accepted(self):
        plan = logic.plan_projects([row(1, "POROMA", co_proyecto="PRY-00000001  ")])
        self.assertEqual(plan["existentes"][0]["co_proyecto"], "PRY-00000001")

    def test_full_catalog_required_not_only_active_or_incomplete_export(self):
        candidate = row(1)
        del candidate["id_proyecto"]
        self.blocked([candidate], "CAMPOS_AUSENTES")
        self.blocked([row(1, description=12)], "TEXTO_INVALIDO")
        self.blocked(None, "CATALOGO_INVALIDO")
        self.blocked({}, "CATALOGO_INVALIDO")
        self.blocked([None], "FILA_INVALIDA")

    def test_exhaustion_blocks_entire_batch_but_idempotent_reuse_still_works(self):
        self.blocked([row(99999998)], "SECUENCIA_AGOTADA")
        self.blocked([row(99999999)], "SECUENCIA_AGOTADA")
        plan = logic.plan_projects([row(99999998, "JAENNORTE"), row(99999999, "POROMA")])
        self.assertFalse(plan["altas"])

    def test_last_available_code_is_allowed_for_one_missing_project(self):
        plan = logic.plan_projects([row(99999998, "POROMA")])
        self.assertEqual(plan["altas"][0]["valores"]["co_proyecto"], "PRY-99999999")

    def test_second_run_reuses_created_projects_with_no_new_codes(self):
        catalog = [row(40)]
        first = logic.plan_projects(catalog)
        second = logic.plan_projects(catalog + [item["valores"] for item in first["altas"]])
        self.assertEqual(second["altas"], [])
        self.assertEqual([item["co_proyecto"] for item in second["existentes"]], ["PRY-00000041", "PRY-00000042"])

    def test_other_projects_are_not_candidates_or_modified(self):
        plan = logic.plan_projects([row(7, "Proyecto HUARAZ", "LT 138 kV Huaraz-Huaylas")])
        self.assertEqual(len(plan["altas"]), 2)
        self.assertEqual(plan["existentes"], [])


if __name__ == "__main__":
    unittest.main()
