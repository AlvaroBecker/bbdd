"""Inventario de KMZ y matriz de revision del EFT, sin ArcPy ni carga a SQL.

Lee los ZIP/XML originales por streaming, sin extraerlos ni modificarlos.
Las clases candidatas son sugerencias identificables por nombres del EFT;
ninguna fila queda aprobada automaticamente para cargar.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import datetime as dt
import hashlib
from html.parser import HTMLParser
import io
import json
from pathlib import Path
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[2]
GEOMETRIES = {"Point": "PUNTO", "LineString": "LINEA", "Polygon": "POLIGONO",
              "Model": "MODELO_3D", "Track": "TRAZA_GX"}
OTHER_FEATURES = {"GroundOverlay", "ScreenOverlay", "PhotoOverlay", "NetworkLink"}


def local(tag):
    return tag.rsplit("}", 1)[-1]


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def normal(value):
    return re.sub(r"[^a-z0-9]+", " ", "".join(c for c in unicodedata.normalize("NFKD", value.lower())
                                                  if not unicodedata.combining(c))).strip()


class NamespaceStream:
    """Declara xsi en la copia de lectura si una exportacion antigua lo omite."""
    def __init__(self, source):
        self.source = source
        prefix = source.read(65536)
        root = re.search(rb"<(?:[A-Za-z_][\w.-]*:)?kml(?=[\s>])[^>]*>", prefix)
        self.repaired = bool(root and not re.search(rb"xmlns:xsi\s*=", root[0]))
        if self.repaired:
            start = re.match(rb"<(?:[A-Za-z_][\w.-]*:)?kml", root[0]).group()
            replacement = start + b' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"' + root[0][len(start):]
            prefix = prefix[:root.start()] + replacement + prefix[root.end():]
        self.prefix = io.BytesIO(prefix)

    def read(self, size=-1):
        if size < 0:
            return self.prefix.read() + self.source.read()
        first = self.prefix.read(size)
        return first + self.source.read(size - len(first)) if len(first) < size else first


class PopupFields(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self.row_stack = []
        self.cell_stack = []

    def finish_cell(self):
        cell = self.cell_stack.pop()
        cell["owner"].append(" ".join("".join(cell["parts"]).split()))

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row_stack.append([])
        elif tag in ("td", "th") and self.row_stack:
            # HTML permite omitir </td> antes de abrir la siguiente celda.
            if self.cell_stack and self.cell_stack[-1]["owner"] is self.row_stack[-1]:
                self.finish_cell()
            self.cell_stack.append({"owner": self.row_stack[-1], "parts": []})

    def handle_data(self, data):
        if self.cell_stack:
            self.cell_stack[-1]["parts"].append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell_stack:
            self.finish_cell()
        elif tag == "tr" and self.row_stack:
            row = self.row_stack.pop()
            # Algunas descripciones omiten cierres de celdas; conservar las de esta fila.
            while self.cell_stack and self.cell_stack[-1]["owner"] is row:
                self.finish_cell()
            if len(row) >= 2:
                name = row[0].strip().rstrip(":")
                if name and len(name) <= 160 and normal(name) not in {"campo", "field", "field name", "atributo", "nombre del campo"}:
                    self.rows.append(name)


def candidate(folder_name, geometry):
    """Candidatos de temas expresos del EFT, siempre pendientes de revision."""
    text = normal(folder_name)
    if geometry in {"MODELO_3D", "TRAZA_GX", "SIN_GEOMETRIA"}:
        return "", "Revisar tratamiento; no convertir automaticamente en una clase del modelo."
    rules = [
        ("area de estudio de campo", "POLIGONO", "AreaEstudioCampo"),
        ("franja", "POLIGONO", "FranjaServidumbre"),
        ("calicata", "PUNTO", "Calicatas"),
        ("muestreo", "PUNTO", "Muestreo"),
        ("acceso", "LINEA", "Accesos"),
        ("subestacion", "PUNTO", "Subestacion"),
        ("subestacion", "POLIGONO", "Subestacion"),
        ("estructura", "PUNTO", "Estructuras"),
        ("torre", "PUNTO", "Estructuras"),
        ("vano", "LINEA", "Vanos"),
        ("area de estudio", "POLIGONO", "mline_td_proyecto_area_interes"),
    ]
    for token, geom, name in rules:
        if token in text and geometry == geom:
            reason = "Coincidencia de nombre y geometria; confirmar contenido, proyecto y claves."
            if name in {"Estructuras", "Vanos"}:
                reason = "Confirmar fuente PLS-CADD y revisar copias CAD antes de aprobar."
            if name == "FranjaServidumbre":
                reason = "Confirmar que la franja corresponde a servidumbre; el nombre solo es una pista."
            if name == "Subestacion":
                reason = "Tema del EFT; definir nombres fisicos distintos para punto y poligono."
            return name, reason
    return "", "Asignar tema con contexto de carpetas y atributos; no se infiere solo por geometria."


def scan_kml(stream, source_id, member):
    folders = {}
    groups = {}
    containers = []
    stack = []
    stats = Counter()
    objects = []
    next_id = 0
    pm_depth = 0
    reader = NamespaceStream(stream)
    for event, elem in ET.iterparse(reader, events=("start", "end")):
        tag = local(elem.tag)
        if event == "start":
            stack.append(elem)
            if tag in {"Folder", "Document"}:
                next_id += 1
                frame = {"id": next_id, "parent": containers[-1]["id"] if containers else None,
                         "kind": tag, "name": "", "placemarks_directos": 0, "objetos_directos": 0}
                folders[next_id] = frame
                containers.append(frame)
                stats[tag] += 1
            elif tag == "Placemark":
                pm_depth += 1
            elif tag in {"Style", "StyleMap"}:
                stats[tag] += 1
            continue
        parent = stack[-2] if len(stack) > 1 else None
        if tag == "name" and parent is not None and local(parent.tag) in {"Folder", "Document"}:
            containers[-1]["name"] = (elem.text or "").strip()
        if tag == "Placemark":
            stats["Placemark"] += 1
            owner = containers[-1]["id"] if containers else 0
            if owner:
                folders[owner]["placemarks_directos"] += 1
            parts = Counter()
            fields = set()
            html_fields = set()
            description = ""
            extra_html = []
            multi = False
            for node in elem.iter():
                kind = local(node.tag)
                if kind in GEOMETRIES:
                    parts[GEOMETRIES[kind]] += 1
                elif kind == "MultiGeometry":
                    multi = True
                elif kind in {"Data", "SimpleData"} and node.get("name"):
                    fields.add(node.get("name"))
                    value = node.text if kind == "SimpleData" else next((n.text for n in node if local(n.tag) == "value"), "")
                    if value and re.search(r"<table\b", value, re.I):
                        extra_html.append(value)
                elif kind == "description" and node.text:
                    description = node.text
            if description:
                stats["Placemark_con_description"] += 1
                if re.search(r"<table\b", description, re.I):
                    stats["Placemark_con_tabla_HTML"] += 1
                    popup = PopupFields()
                    popup.feed(description)
                    html_fields.update(popup.rows)
            if extra_html:
                stats["Placemark_con_HTML_en_ExtendedData"] += 1
                for html in extra_html:
                    popup = PopupFields()
                    popup.feed(html)
                    html_fields.update(popup.rows)
            if fields:
                stats["Placemark_con_ExtendedData"] += 1
            if multi:
                stats["Placemark_MultiGeometry"] += 1
            if len(parts) > 1:
                stats["Placemark_geometria_mixta"] += 1
            if not parts:
                parts["SIN_GEOMETRIA"] = 0
            stats["Asignaciones_geometria"] += len(parts)
            for geom, amount in parts.items():
                stats["partes_" + geom] += amount
                key = (owner, geom)
                group = groups.setdefault(key, {"container": owner, "geometry": geom, "placemarks": 0,
                                               "partes": 0, "multi": 0, "mixtos": 0,
                                               "fields": set(), "html_fields": set()})
                group["placemarks"] += 1
                group["partes"] += amount
                group["multi"] += int(multi)
                group["mixtos"] += int(len(parts) > 1)
                group["fields"].update(fields)
                group["html_fields"].update(html_fields)
            pm_depth -= 1
            if parent is not None:
                parent.remove(elem)
            elem.clear()
        elif tag in OTHER_FEATURES and not pm_depth:
            stats[tag] += 1
            owner = containers[-1]["id"] if containers else 0
            if owner:
                folders[owner]["objetos_directos"] += 1
            objects.append({"container": owner, "tipo": tag,
                            "nombre": next(((n.text or "").strip() for n in elem if local(n.tag) == "name"), "")})
            if parent is not None:
                parent.remove(elem)
            elem.clear()
        elif tag in {"Document", "Folder"}:
            containers.pop()
            if parent is not None:
                parent.remove(elem)
            elem.clear()
        elif tag in {"Style", "StyleMap", "Schema"} and not pm_depth:
            if parent is not None:
                parent.remove(elem)
            elem.clear()
        stack.pop()
    def route(uid):
        if not uid:
            return "(raiz)"
        frame = folders[uid]
        if "path" not in frame:
            label = frame["name"] or "{} sin nombre [{}]".format(frame["kind"], uid)
            if frame["parent"]:
                route(frame["parent"])
            frame["path_parts"] = (folders[frame["parent"]]["path_parts"] if frame["parent"] else []) + [label]
            frame["path"] = " / ".join(frame["path_parts"])
        return frame["path"]
    for frame in folders.values():
        route(frame["id"])
        frame["ruta_componentes_json"] = json.dumps(frame["path_parts"], ensure_ascii=False)
        frame.update(source_id=source_id, kml=member)
    for group in groups.values():
        group["path"] = route(group["container"])
        group["folder_name"] = folders[group["container"]]["name"] if group["container"] else ""
        group["path_parts"] = folders[group["container"]]["path_parts"] if group["container"] else []
        group.update(source_id=source_id, kml=member)
    for obj in objects:
        obj.update(source_id=source_id, kml=member, ruta_kml=route(obj["container"]))
    assert sum(g["placemarks"] for g in groups.values()) == stats["Asignaciones_geometria"]
    assert sum(f["placemarks_directos"] for f in folders.values()) + sum(
        g["placemarks"] for g in groups.values() if g["container"] == 0 and g["geometry"] == "SIN_GEOMETRIA"
    ) <= stats["Asignaciones_geometria"]
    return list(folders.values()), list(groups.values()), objects, dict(stats), reader.repaired


def write_csv(path, rows, columns):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, delimiter=";", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def run(inputs, output):
    paths = []
    for root in inputs:
        if not root.is_dir():
            raise ValueError("No existe la carpeta de entrada: " + str(root))
        paths.extend(p.resolve() for p in root.rglob("*") if p.is_file() and p.suffix.casefold() == ".kmz")
    paths = list(dict.fromkeys(paths))
    if not paths:
        raise ValueError("No se encontraron KMZ.")
    if output.exists():
        raise FileExistsError("El destino ya existe; use otra carpeta para conservar revisiones: " + str(output))
    if any(p.resolve() == output.resolve() or p.resolve() in output.resolve().parents for p in inputs):
        raise ValueError("El destino debe estar fuera de las carpetas de entrada.")
    files, duplicates, by_hash = [], [], {}
    for path in paths:
        h = digest(path)
        if h in by_hash:
            duplicates.append({"copia": str(path), "original_inventariado": str(by_hash[h]), "sha256": h})
        else:
            by_hash[h] = path
    folders, mappings, objects = [], [], []
    totals = Counter()
    errors = []
    for index, (h, path) in enumerate(by_hash.items(), 1):
        print("[{}/{}] {}".format(index, len(by_hash), path.name), flush=True)
        record = {"archivo": path.name, "ruta": str(path), "sha256": h, "bytes": path.stat().st_size,
                  "estado": "OK", "estadisticas": {}, "kml_members": [], "declaracion_xsi_agregada_solo_lectura": False}
        files.append(record)
        file_folders, file_groups, file_objects = [], [], []
        try:
            with zipfile.ZipFile(path) as archive:
                members = [i for i in archive.infolist() if not i.is_dir() and i.filename.lower().endswith(".kml")]
                if not members:
                    raise ValueError("ZIP sin archivos KML.")
                record["recursos"] = dict(Counter(Path(i.filename).suffix.lower() or "(sin extension)"
                                                  for i in archive.infolist() if not i.is_dir() and not i.filename.lower().endswith(".kml")))
                for member in members:
                    with archive.open(member) as stream:
                        fs, gs, os, stats, repaired = scan_kml(stream, h, member.filename)
                    file_folders.extend(fs)
                    file_groups.extend(gs)
                    file_objects.extend(os)
                    record["declaracion_xsi_agregada_solo_lectura"] |= repaired
                    record["kml_members"].append({"nombre": member.filename, "bytes": member.file_size})
                    record["estadisticas"] = dict(Counter(record["estadisticas"]) + Counter(stats))
            for key in ["Placemark", "Folder", "Document", "Placemark_MultiGeometry", "Placemark_geometria_mixta",
                        "Placemark_con_description", "Placemark_con_tabla_HTML", "Placemark_con_ExtendedData",
                        "Placemark_con_HTML_en_ExtendedData", "GroundOverlay", "ScreenOverlay", "PhotoOverlay", "NetworkLink"]:
                record["estadisticas"].setdefault(key, 0)
            folders.extend(file_folders)
            objects.extend(file_objects)
            for group in file_groups:
                proposed, reason = candidate(group["folder_name"], group["geometry"])
                row = {"source_id": h, "archivo_origen": path.name, "kml": group["kml"],
                       "carpeta_id": group["container"], "ruta_kml": group["path"],
                       "ruta_componentes_json": json.dumps(group["path_parts"], ensure_ascii=False),
                       "geometria": group["geometry"], "placemarks": group["placemarks"], "partes_geometricas": group["partes"],
                       "placemarks_multigeometria": group["multi"], "placemarks_mixtos": group["mixtos"],
                       "campos_ExtendedData": " | ".join(sorted(group["fields"])),
                       "etiquetas_HTML_candidatas": " | ".join(sorted(group["html_fields"])),
                       "proyecto_etiqueta_origen": re.sub(r"^Proyecto\s+", "", path.stem, flags=re.I),
                       "dataset_candidato": "Datos_Proyecto", "clase_candidata": proposed, "motivo_candidato": reason,
                       "incluir_aprobado": "", "dataset_aprobado": "", "clase_aprobada": "", "co_proyecto_validado": "",
                       "id_componente_validado": "", "id_alternativa_validado": "", "id_analisis_validado": "",
                       "estado_revision": "PENDIENTE", "observaciones_revision": ""}
                mappings.append(row)
            totals.update(record["estadisticas"])
            print("  {} Placemarks; {} carpetas; {} grupos carpeta/geometria".format(
                record["estadisticas"].get("Placemark", 0), record["estadisticas"].get("Folder", 0), len(file_groups)), flush=True)
        except Exception as exc:
            record["estado"] = "ERROR"
            record["error"] = str(exc)
            errors.append({"archivo": str(path), "error": str(exc)})
            print("  ERROR: " + str(exc), flush=True)
    output.mkdir(parents=True)
    control = {"fecha_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "version_inventario": 2,
               "entradas": [str(p.resolve()) for p in inputs], "archivos_fisicos": len(paths), "fuentes_unicas": len(files),
               "copias_identicas": duplicates, "archivos": files, "totales": dict(totals), "grupos_mapeo": len(mappings),
               "filas_aprobadas_para_carga": 0, "errores": errors,
               "diferencia_placemarks_vs_279623_eft": totals.get("Placemark", 0) - 279623,
               "advertencias": ["No se valida geometria GIS ni se cargan datos; el inventario es XML.",
                                 "Un Placemark mixto aparece en varias filas de geometria; no sumar esas filas como entidades unicas.",
                                 "Las etiquetas HTML son heuristicas y pueden incluir titulos/valores de presentacion: no son un diccionario canonico de campos.",
                                 "ruta_componentes_json conserva la jerarquia real; no separar ruta_kml por barras, que pueden ser parte del nombre original.",
                                 "Dataset y clase candidatos no son asignaciones aprobadas; revisar excepciones del EFT para Datos_Internos.",
                                 "No se asignan codigos de proyecto, componentes, alternativas ni analisis automaticamente.",
                                 "NetworkLinks y referencias externas se inventarian sin descargar su contenido.",
                                 "La deduplicacion es exclusivamente de archivos KMZ con SHA256 identico, no de entidades entre proyectos."]}
    (output / "control_inventario.json").write_text(json.dumps(control, ensure_ascii=False, indent=2), encoding="utf-8")
    file_rows = [{"archivo": f["archivo"], "ruta": f["ruta"], "sha256": f["sha256"], "bytes": f["bytes"],
                  "estado": f["estado"], **f["estadisticas"]} for f in files]
    file_cols = ["archivo", "ruta", "sha256", "bytes", "estado"] + sorted(set().union(*(set(f["estadisticas"]) for f in files)))
    write_csv(output / "01_archivos.csv", file_rows, file_cols)
    write_csv(output / "02_carpetas.csv", folders, ["source_id", "kml", "id", "parent", "kind", "name", "path", "ruta_componentes_json", "placemarks_directos", "objetos_directos"])
    mapping_cols = list(mappings[0]) if mappings else ["source_id", "archivo_origen", "ruta_kml", "geometria", "estado_revision"]
    write_csv(output / "03_matriz_mapeo_EFT.csv", mappings, mapping_cols)
    write_csv(output / "04_objetos_no_placemark.csv", objects, ["source_id", "kml", "container", "ruta_kml", "tipo", "nombre"])
    themes = {}
    for row in mappings:
        key = (row["clase_candidata"] or "POR_CLASIFICAR", row["geometria"])
        summary = themes.setdefault(key, {"clase_candidata": key[0], "geometria": key[1], "grupos": 0,
                                          "placemarks": 0, "partes_geometricas": 0, "archivos": set()})
        summary["grupos"] += 1
        summary["placemarks"] += row["placemarks"]
        summary["partes_geometricas"] += row["partes_geometricas"]
        summary["archivos"].add(row["archivo_origen"])
    theme_rows = [dict(row, archivos=len(row["archivos"])) for _, row in sorted(themes.items())]
    write_csv(output / "05_resumen_candidatos.csv", theme_rows,
              ["clase_candidata", "geometria", "grupos", "placemarks", "partes_geometricas", "archivos"])
    print(json.dumps({"output": str(output.resolve()), "fuentes_unicas": len(files), "copias_identicas": len(duplicates),
                      "placemarks": totals.get("Placemark", 0), "carpetas": totals.get("Folder", 0),
                      "grupos_mapeo": len(mappings), "errores": len(errors)}, ensure_ascii=False), flush=True)
    return 1 if errors else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, action="append", dest="inputs", help="Carpeta de entrada; se puede repetir")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent / "inventario_inicial")
    args = parser.parse_args()
    inputs = args.inputs or [ROOT / "01_fuentes" / "kmz", ROOT.parent / "InformaciónMapline"]
    return run(inputs, args.output)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
