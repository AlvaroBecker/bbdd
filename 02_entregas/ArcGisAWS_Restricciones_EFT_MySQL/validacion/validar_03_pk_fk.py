"""QA local del script PK/FK: mapa literal contra MySQL y revision estatica.

No se conecta a SQL Server ni ArcGIS y no modifica el script de carga.
Los indicadores de control se revisan como texto; no equivalen a una prueba
de compilacion o ejecucion del motor SQL Server.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re


def validate(sql_file, model_file, source_report):
    text = sql_file.read_text(encoding="utf-8-sig")
    model = json.loads(model_file.read_text(encoding="utf-8-sig"))
    source = json.loads(source_report.read_text(encoding="utf-8-sig"))
    assert source["pk_matches_dump"] and source["fk_matches_dump"] and source["indexes_match_dump"]
    assert source["source_sha256"] == model["source_sha256"]
    pk_section = text.split("INSERT INTO @PK VALUES", 1)[1].split("DECLARE @FK TABLE", 1)[0]
    fk_section = text.split("INSERT INTO @FK VALUES", 1)[1].split("-- Validaciones globales", 1)[0]
    pks = re.findall(r"\(N'([^']+)', N'([^']+)', N'([^']+)'\)", pk_section)
    fks = re.findall(r"\(N'([^']+)', N'([^']+)', N'([^']+)', N'([^']+)', N'([^']+)'\)", fk_section)
    names = {table["name"] for table in model["tables"]}
    expected_pk = {(table["name"], table["primary_key"][0]) for table in model["tables"]}
    assert len(pks) == 8 and {(table, column) for table, column, _ in pks} == expected_pk
    expected_fk = {(rel["name"], rel["child"], rel["child_key"], rel["parent"], rel["parent_key"])
                   for rel in model["relations"] if not rel.get("obsolete") and rel["parent"] in names}
    assert len(fks) == 11 and set(fks) == expected_fk
    recursive = [fk[0] for fk in fks if fk[1] == fk[3]]
    assert len(recursive) == 2
    assert set(fk[0] for fk in fks) == set(source["classification_names"]["active_sql"])
    for group in ("obsolete_no_fk", "pending_spatial", "pending_parameter_domain", "pending_portal"):
        assert not set(fk[0] for fk in fks).intersection(source["classification_names"][group])
    checks = {
        "same_existing_database": "USE [ArcGisAWS];" in text and "DECLARE @Esquema sysname = N'gis';" in text,
        "no_prior_transaction": "IF @@TRANCOUNT <> 0" in text and "SET IMPLICIT_TRANSACTIONS OFF;" in text,
        "base_script_requires_arcgis_verification": "DECLARE @EstadoArcGISVerificado bit = 0;" in text
            and "@EstadoArcGISVerificado <> 1" in text and "@ServidorVerificado <> CONVERT" in text,
        "all_tables_preflight": "Falta alguna tabla gis" in text,
        "all_pk_int_not_null_preflight": "c.system_type_id=56 AND c.is_nullable=0 AND c.is_computed=0" in text,
        "existing_objectid_pk_not_replaced": "Una tabla admite una sola PK" in text
            and "k.type='PK'" in text and "PK existente diferente o deshabilitada" in text
            and "c.name=p.columna" in text and "IF EXISTS (SELECT 1 FROM @Conflictos)" in text,
        "pk_name_index_collision_preflight": "OR EXISTS (SELECT 1 FROM sys.indexes i" in text and "i.name=p.nombre" in text,
        "pk_nonclustered": "PRIMARY KEY NONCLUSTERED" in text,
        "fk_with_check": "WITH CHECK ADD CONSTRAINT" in text,
        "fk_no_action": "ON DELETE NO ACTION ON UPDATE NO ACTION" in text,
        "fk_equivalence_simple_enabled_trusted": "constraint_object_id=k.object_id)=1" in text
            and "k.is_disabled=0 AND k.is_not_trusted=0" in text,
        "fk_equivalence_no_action": "k.delete_referential_action=0 AND k.update_referential_action=0" in text,
        "fk_equivalence_not_for_replication_false": text.count("k.is_not_for_replication=0") >= 3
            and "k.is_not_for_replication=1" in text,
        "arcgis_verification_recent_15_minutes": "NOT BETWEEN -1 AND 15" in text,
        "all_data_preflight": "@Datos WHERE nulos>0 OR duplicados>0 OR huerfanos>0" in text,
        "idempotent_equivalent_plan": "CONSERVAR_EQUIVALENTE" in text and "WHERE accion=N'CREAR'" in text,
        "nullable_existing_plan": "existente sysname NULL" in text,
        "single_transaction_and_rollback": "BEGIN TRY\n    BEGIN TRANSACTION;" in text
            and "IF XACT_STATE()<>0 ROLLBACK TRANSACTION;" in text and "COMMIT TRANSACTION;" in text,
        "post_checks_before_commit": text.index("No se confirmaron las ocho PK") < text.index("COMMIT TRANSACTION;")
            and text.index("No se confirmaron las once FK") < text.index("COMMIT TRANSACTION;"),
        "no_drop_or_row_changes": not re.search(r"(?im)^\s*(DROP\b|UPDATE\s+(?!@)|DELETE\s|TRUNCATE\s|CREATE\s+(TABLE|DATABASE|SCHEMA)\b)", text),
        "no_sqlcmd": ":ON ERROR" not in text and not re.search(r"(?im)^\s*:r\b", text),
    }
    assert all(checks.values()), {key: value for key, value in checks.items() if not value}
    return {
        "review_mode": "static SQL text and literal PK/FK map compared with independently verified MySQL DDL",
        "script_file": sql_file.name,
        "script_sha256": hashlib.sha256(sql_file.read_bytes()).hexdigest(),
        "source_sha256": source["source_sha256"],
        "pk_count": len(pks), "active_fk_count": len(fks), "self_fk_count": len(recursive),
        "original_secondary_indexes_verified": source["original_secondary_indexes"],
        "pk_matches_source": True, "active_fk_matches_source": True,
        "excluded_classes": {key: len(source["classification_names"][key]) for key in
                             ("obsolete_no_fk", "pending_spatial", "pending_parameter_domain", "pending_portal")},
        "static_checks": checks,
        "sql_server_parse_tested": False, "sql_server_execution_tested": False,
        "arcgis_execution_tested": False,
        "limitations": ["Static idempotence and rollback review is not an engine execution test.",
                        "Fresh ArcGIS registration/versioning state is required in the destination environment."]}


def main():
    here = Path(__file__).resolve()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sql", type=Path, default=here.parents[1] / "03_agregar_PK_FK_SQLServer.sql")
    parser.add_argument("--manifest", type=Path, default=here.parents[1] / "modelo_restricciones.json")
    parser.add_argument("--source-report", type=Path, default=here.with_name("resultado_indices_fuente.json"))
    parser.add_argument("--report", type=Path, default=here.with_name("resultado_03_pk_fk.json"))
    args = parser.parse_args()
    result = validate(args.sql, args.manifest, args.source_report)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("QA estatica correcta: 8 PK, 11 FK activas, 2 autorreferencias NO ACTION; sin ejecucion de BD.")


if __name__ == "__main__":
    main()
