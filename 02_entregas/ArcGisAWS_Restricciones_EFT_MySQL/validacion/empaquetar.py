"""Empaquetar solo la entrega SQL actual y el verificador ArcGIS de solo lectura."""
from pathlib import Path
import datetime as dt
import hashlib
import json
import zipfile

BASE = Path(__file__).resolve().parents[1]
source = json.loads((BASE / "validacion/resultado_indices_fuente.json").read_text(encoding="utf-8"))
sql = json.loads((BASE / "validacion/resultado_03_pk_fk.json").read_text(encoding="utf-8"))
helper = json.loads((BASE / "validacion/resultado_helper_00.json").read_text(encoding="utf-8"))

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

assert sql["script_sha256"] == sha(BASE / "03_agregar_PK_FK_SQLServer.sql")
assert all(sql["static_checks"].values())
assert source["auto_increment_columns"] == 0
summary = {
    "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
    "scope": "Ocho PK fisicas y once FK fisicas; indices secundarios originales en archivo separado.",
    "destination": {"database": "ArcGisAWS", "schema": "gis", "tables": 8},
    "required_state": "Registradas con geodatabase; sin versionado tradicional/branch ni archivado.",
    "branch_conflict": "Las PK impiden activar branch mientras existan; no se resuelve esa transicion en este paquete.",
    "source_ddl": source,
    "sql_static_review": sql,
    "readonly_helper_mock_tests": helper,
    "sql_server_parse_tested": False,
    "sql_server_execution_tested": False,
    "arcgis_real_execution_tested": False,
    "changes_applied_to_destination": False,
    "delivery": "No incluye las propuestas de dominios/reglas ni los generadores o tests locales.",
}
(BASE / "05_verificacion_local.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
files = ["LEEME.md", "00_verificar_estado_arcgis.py", "01_diagnostico_sql.sql",
         "02_restaurar_indices_no_unicos.sql", "03_agregar_PK_FK_SQLServer.sql",
         "04_correspondencia_EFT_MySQL.md", "modelo_restricciones.json", "05_verificacion_local.json"]
hashes = {name: sha(BASE / name) for name in files}
(BASE / "SHA256.json").write_text(json.dumps(hashes, ensure_ascii=False, indent=2), encoding="utf-8")
files.append("SHA256.json")
target = BASE.parent / "Mapline_PK_FK_SQLServer_EFT.zip"
assert target.resolve().parent == BASE.parent.resolve()
with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
    for name in files:
        z.write(BASE / name, BASE.name + "/" + name)
with zipfile.ZipFile(target) as z:
    assert z.testzip() is None
    assert len(z.infolist()) == 9
    for name in files:
        assert z.read(BASE.name + "/" + name) == (BASE / name).read_bytes()
print(json.dumps({"zip": str(target), "files": len(files), "bytes": target.stat().st_size,
                  "zip_sha256": sha(target), "crc_ok": True}, ensure_ascii=False))
