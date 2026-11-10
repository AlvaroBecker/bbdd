"""Preparar la propuesta de mapeo desde el inventario recibido y las fuentes.

No aprueba filas ni escribe en SQL/ArcGIS. Conserva los valores recibidos y
agrega propuestas trazables para revision.
"""
from collections import Counter
import csv
import hashlib
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
ROOT = BASE.parents[1]
INVENTORY = ROOT.parent / "01_fuentes" / "inventario_ArcGIS_20261103_114443"
SOURCE = ROOT / "KMZ_EFT/inventario"
OUT = BASE / "datos"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream, delimiter=";"))


def write_csv(path, rows, columns):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, delimiter=";", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main():
    control = json.loads((INVENTORY / "control_inventario.json").read_text(encoding="utf-8"))
    previous = json.loads((SOURCE / "control_inventario.json").read_text(encoding="utf-8"))
    assert not control["errores"] and control["fuentes_unicas"] == 13
    assert control["totales"]["Placemark"] == 279623
    hashes = {(x["archivo"], x["sha256"]) for x in control["archivos"]}
    assert hashes == {(x["archivo"], x["sha256"]) for x in previous["archivos"]}
    raw = read_csv(INVENTORY / "03_matriz_mapeo_EFT.csv")
    original_columns = list(raw[0])
    assert len(raw) == 3655 and sum(int(r["placemarks"]) for r in raw) == 279623
    assert len({(r["source_id"], r["kml"], r["carpeta_id"], r["geometria"]) for r in raw}) == len(raw)
    classifier_spec = importlib.util.spec_from_file_location("clasificar_contexto", HERE / "clasificar_contexto.py")
    classifier = importlib.util.module_from_spec(classifier_spec)
    classifier_spec.loader.exec_module(classifier)
    mysql = json.loads((HERE / "proyectos_mysql.json").read_text(encoding="utf-8"))
    assert len(mysql["proyectos"]) == 40 and len(mysql["componentes"]) == 120 and len(mysql["projectCandidates"]) == 13
    project_by_file = {row["archivo"]: row for row in mysql["projectCandidates"]}
    known_codes = {row["co"] for row in mysql["proyectos"]}
    assert set(project_by_file) == {row["archivo_origen"] for row in raw}
    approved_fields = ["incluir_aprobado", "dataset_aprobado", "clase_aprobada", "co_proyecto_validado",
                       "id_componente_validado", "id_alternativa_validado", "id_analisis_validado"]
    # No reemplazar decisiones introducidas por el usuario en el archivo recibido.
    approved_received = sum(any(row[field] for field in approved_fields) for row in raw)
    if approved_received:
        raise ValueError("El inventario ya contiene decisiones: deben integrarse individualmente antes de reagruparlo.")
    groups = {}
    detailed = []
    for row in raw:
        proposal = classifier.classify(row)
        if isinstance(proposal["opciones_destino"], (list, tuple)):
            proposal["opciones_destino"] = "; ".join(proposal["opciones_destino"])
        group_key = (row["archivo_origen"], row["geometria"], proposal["familia"], proposal["clase_propuesta"],
                     proposal["opciones_destino"], proposal["contexto_agrupacion"])
        group_id = "G_" + hashlib.sha256(json.dumps(group_key, ensure_ascii=False).encode("utf-8")).hexdigest()[:12]
        group = groups.setdefault(group_id, {"grupo_revision": group_id, "archivo": row["archivo_origen"],
            "familia": proposal["familia"], "geometria": row["geometria"], "grupos_origen": 0, "placemarks": 0,
            "partes_geometricas": 0, "clase_propuesta": proposal["clase_propuesta"], "opciones_destino": proposal["opciones_destino"],
            "contexto": proposal["contexto_agrupacion"], "motivo": proposal["motivo"],
            "pendiente": proposal["pendiente_especifico"], "referencia_eft": proposal["referencia_eft"],
            "clase_confirmada": "", "incluir": "Pendiente", "comentario_revision": ""})
        group["grupos_origen"] += 1
        group["placemarks"] += int(row["placemarks"])
        group["partes_geometricas"] += int(row["partes_geometricas"])
        detailed.append(dict(row, grupo_revision=group_id, familia_propuesta=proposal["familia"],
                             clase_propuesta_v1=proposal["clase_propuesta"], opciones_destino=proposal["opciones_destino"],
                             contexto_agrupacion_v1=proposal["contexto_agrupacion"], motivo_contexto_v1=proposal["motivo"],
                             pendiente_especifico=proposal["pendiente_especifico"], referencia_eft_v1=proposal["referencia_eft"]))
    group_rows = sorted(groups.values(), key=lambda r: (r["archivo"], r["familia"], r["geometria"], r["contexto"]))
    assert sum(r["placemarks"] for r in group_rows) == 279623
    assert sum(r["grupos_origen"] for r in group_rows) == 3655
    assert len(groups) == len({row["grupo_revision"] for row in group_rows})
    for raw_row, new_row in zip(raw, detailed):
        assert all(raw_row[key] == new_row[key] for key in original_columns)
    project_rows = []
    for filename in sorted(project_by_file):
        source = project_by_file[filename]
        assert set(source["codigos_candidatos"]).issubset(known_codes)
        evidence = " ".join(source["evidencia"])
        project_rows.append({"archivo": filename, "codigos_candidatos": "; ".join(source["codigos_candidatos"]),
                             "evidencia": evidence,
                             "pendiente": "Confirmar alta/correspondencia en BD; no crear codigo automaticamente." if not source["codigos_candidatos"]
                             else "Resolver candidatos antes de elegir." if len(source["codigos_candidatos"]) > 1
                             else "Confirmar proyecto y la correspondencia con componente/alternativa.",
                             "co_proyecto_confirmado": "", "id_analisis_confirmado": "", "comentario_revision": ""})
    out = {"fuente_recibida": str(INVENTORY), "fuentes": {"inventario": "03_matriz_mapeo_EFT.csv recibido de ArcGIS Pro",
            "eft": "EFT - ENGIE Mapline ArcGIS Enterprise y ArcGIS Pro_v2.4.docx, 5.8.5 a 5.8.11",
            "mysql": "Mapline_20261030.sql", "mysql_sha256": mysql["fuente_mysql"]["sha256"]},
           "conteos": {"archivos": 13, "placemarks": 279623, "grupos_origen": 3655, "grupos_revision": len(group_rows),
                       "grupos_con_clase_propuesta": sum(bool(r["clase_propuesta"]) for r in group_rows),
                       "filas_con_clase_propuesta": sum(bool(r["clase_propuesta_v1"]) for r in detailed),
                       "decisiones_recibidas": approved_received, "nuevas_aprobaciones": 0},
           "grupos": group_rows, "detalle": detailed, "proyectos": project_rows,
           "mysql_proyectos": mysql["proyectos"], "mysql_componentes": mysql["componentes"],
           "archivos": [{"archivo": x["archivo"], "sha256": x["sha256"], "placemarks": x["estadisticas"]["Placemark"]}
                        for x in control["archivos"]],
           "hashes_entrada": {p.name: sha(p) for p in INVENTORY.iterdir() if p.is_file()},
           "hash_clasificador": sha(HERE / "clasificar_contexto.py")}
    OUT.mkdir(parents=True, exist_ok=True)
    (HERE / "datos_workbook.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(OUT / "01_mapeo_detallado_propuesto.csv", detailed, list(detailed[0]))
    write_csv(OUT / "02_grupos_revision.csv", group_rows, list(group_rows[0]))
    write_csv(OUT / "03_proyectos_candidatos.csv", project_rows, list(project_rows[0]))
    print(json.dumps(out["conteos"], ensure_ascii=False))


if __name__ == "__main__":
    main()
