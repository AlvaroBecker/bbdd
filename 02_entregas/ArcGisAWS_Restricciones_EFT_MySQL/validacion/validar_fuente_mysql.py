"""Contrastar el alcance SQL con el DDL original sin conectarse a ninguna BD.

Solo analiza CREATE TABLE; no exporta filas ni datos personales. Escribe un
resultado JSON local. No importa ArcPy ni ejecuta SQL.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re


def validate(source: Path, manifest: Path):
    raw = source.read_bytes()
    source_sha = hashlib.sha256(raw).hexdigest()
    model = json.loads(manifest.read_text(encoding="utf-8-sig"))
    if source_sha != model["source_sha256"]:
        raise AssertionError("El hash del respaldo difiere del registrado en el modelo.")
    # La normalizacion solo afecta el texto analizado. El hash usa bytes originales.
    text = raw.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    names = {table["name"] for table in model["tables"]}
    ddls = [match for match in re.finditer(r"^CREATE TABLE `([^`]+)` \([\s\S]*?^\) ENGINE=.*;$", text, re.M)
            if match[1] in names]
    assert len(names) == 8 and len(ddls) == 8, "Se esperaban ocho tablas del origen."
    auto_increment = sum(len(re.findall(r"\bAUTO_INCREMENT\b", table[0], re.I)) for table in ddls)
    assert auto_increment == 0, "No se debe inventar ni omitir AUTO_INCREMENT del origen."
    pks = {match[1]: re.findall(r"`([^`]+)`", re.search(r"PRIMARY KEY \(([^\n]+)\)", match[0])[1])
           for match in ddls}
    assert pks == {table["name"]: table["primary_key"] for table in model["tables"]}
    indexes, foreign = [], []
    source_actions = {}
    for table in ddls:
        indexes.extend((table[1], name, tuple(re.findall(r"`([^`]+)`", columns)))
                       for name, columns in re.findall(r"^  KEY `([^`]+)` \(([^\n]+)\)", table[0], re.M))
        for line in table[0].splitlines():
            fk = re.search(r"CONSTRAINT `([^`]+)` FOREIGN KEY \(`([^`]+)`\) REFERENCES `([^`]+)` \(`([^`]+)`\)(.*)", line)
            if not fk:
                continue
            name, child_key, parent, parent_key, tail = fk.groups()
            foreign.append((name, parent, table[1], parent_key, child_key))
            actions = {}
            for operation in ("DELETE", "UPDATE"):
                found = re.search(r"ON " + operation + r" (CASCADE|SET NULL|NO ACTION|RESTRICT|SET DEFAULT)", tail)
                actions["on_" + operation.lower()] = found[1].replace(" ", "_") if found else "NO_ACTION"
            source_actions[name] = actions
    assert len(indexes) == 27
    assert sorted(indexes) == sorted((index["table"], index["name"], tuple(index["columns"]))
                                     for index in model["original_indexes"])
    assert len(foreign) == 27
    assert sorted(foreign) == sorted((rel["name"], rel["parent"], rel["child"], rel["parent_key"], rel["child_key"])
                                     for rel in model["relations"])
    assert all(actions == {"on_delete": "NO_ACTION", "on_update": "NO_ACTION"}
               for actions in source_actions.values()), "La semantica de acciones debe coincidir con el DDL."

    spatial = {"mline_td_proyecto_ltransmision", "mline_td_proyecto_cgeneracion", "mline_td_proyecto_area_interes",
               "mline_td_proyecto_envelope", "mline_td_proyecto_celda", "mline_td_proyecto_infraestructura"}
    groups = {"active_sql": [], "obsolete_no_fk": [], "pending_spatial": [], "pending_parameter_domain": [], "pending_portal": []}
    for rel in model["relations"]:
        if rel.get("obsolete"):
            group = "obsolete_no_fk"
        elif rel["parent"] in names:
            group = "active_sql"
        elif rel["parent"] in spatial:
            group = "pending_spatial"
        elif rel["parent"] == "mline_tp_parametro":
            group = "pending_parameter_domain"
        elif rel["parent"] in ("mline_tm_capa", "mline_tm_capa_propiedad"):
            group = "pending_portal"
        else:
            raise AssertionError("Relacion fuera de la clasificacion documentada: " + rel["name"])
        groups[group].append(rel["name"])
    expected = {"active_sql": 11, "obsolete_no_fk": 3, "pending_spatial": 3, "pending_parameter_domain": 8, "pending_portal": 2}
    assert {key: len(value) for key, value in groups.items()} == expected
    recursive = [rel for rel in model["relations"] if rel["name"] in groups["active_sql"] and rel["parent"] == rel["child"]]
    assert len(recursive) == 2
    for rel in recursive:
        assert source_actions[rel["name"]] == {"on_delete": "NO_ACTION", "on_update": "NO_ACTION"}
    return {"source_file": source.name, "source_sha256": source_sha, "tables": 8, "primary_keys": 8,
            "foreign_keys": 27, "original_secondary_indexes": 27, "auto_increment_columns": auto_increment,
            "pk_matches_dump": True, "fk_matches_dump": True, "indexes_match_dump": True,
            "sql_active_foreign_keys": 11, "recursive_no_action_foreign_keys": 2,
            "classification_counts": expected, "classification_names": groups,
            "manifest_treatments": dict(Counter(rel.get("treatment", "") for rel in model["relations"])),
            "new_inferred_business_rules": 0, "sql_server_execution_tested": False, "arcgis_execution_tested": False}


def main():
    here = Path(__file__).resolve()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=here.parents[3] / "01_fuentes" / "Mapline_20261030.sql")
    parser.add_argument("--manifest", type=Path, default=here.parents[1] / "modelo_restricciones.json")
    parser.add_argument("--report", type=Path, default=here.with_name("resultado_indices_fuente.json"))
    args = parser.parse_args()
    result = validate(args.source, args.manifest)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("DDL original coincide: 8 PK, 27 FK, 11 FK SQL activas y 27 indices secundarios.")


if __name__ == "__main__":
    main()
