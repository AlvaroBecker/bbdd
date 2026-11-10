"""Transferencia conservadora de KMZ a objetos nuevos de ArcGIS, sin inferir negocio."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import datetime as dt
import hashlib
import io
import json
import logging
import math
import os
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import time
import traceback
import unicodedata
import xml.etree.ElementTree as ET
import xml.sax
from xml.sax.saxutils import XMLGenerator
import zipfile


HERE = Path(__file__).resolve().parent
DEFAULT_SDE = (
    r"C:\Users\CT6788\Documents\ArcGIS\Projects\MyProject"
    r"\SQLServer-EEPAWSDBP01-ArcGisAWS(gis).sde"
)
GEOMETRIES = {"Point", "LineString", "Polygon", "MultiGeometry", "Model", "Track", "MultiTrack"}
FEATURES = {"Placemark": "P", "GroundOverlay": "G", "ScreenOverlay": "S",
            "PhotoOverlay": "H", "NetworkLink": "N"}
CLASS_SUFFIX = {"Point": "puntos", "Polyline": "lineas", "Polygon": "poligonos",
                "MultiPatch": "multipatch", "Multipoint": "multipuntos"}
TARGET_SUFFIXES = list(CLASS_SUFFIX.values()) + ["atributos", "balance"]
SDE_NAME = re.compile(r"[a-z][a-z0-9_]{0,39}")
LEGACY_NAME = re.compile(r"kmz_([0-9a-f]{12})_(" + "|".join(TARGET_SUFFIXES) + ")")
FIELDS = [
    ("KZ_PM_ID", "TEXT", 100), ("KZ_SHA256", "TEXT", 64),
    ("KZ_ARCHIVO", "TEXT", 255), ("KZ_NOMBRE", "TEXT", 1000),
    ("KZ_ESTADO", "TEXT", 32),
]
LOG = logging.getLogger("kmz_sde")


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].split(":")[-1]


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def save_json(path: Path, data: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    for attempt in range(6):
        try:
            temporary.replace(path)
            return
        except PermissionError as error:
            if attempt == 5:
                raise PermissionError(
                    f"No se pudo guardar {path} tras 6 intentos. "
                    f"El informe nuevo se conserva en {temporary}; no se borro el informe anterior. "
                    "Cierre visores de estos archivos y revise permisos o elija otra carpeta local "
                    "fuera del Escritorio y de carpetas sincronizadas."
                ) from error
            delay = 0.25 * (2 ** attempt)
            LOG.warning("Windows denego reemplazar %s; reintento %s/5 en %.2f segundos.",
                        path, attempt + 1, delay)
            time.sleep(delay)


class NamespaceStream:
    """Compatibilidad de lectura con los KMZ antiguos del inventario existente."""

    def __init__(self, source):
        self.source = source
        prefix = source.read(65536)
        root = re.search(rb"<(?:[A-Za-z_][\w.-]*:)?kml(?=[\s>])[^>]*>", prefix)
        if root and not re.search(rb"xmlns:xsi\s*=", root[0]):
            opening = re.match(rb"<(?:[A-Za-z_][\w.-]*:)?kml", root[0]).group()
            replacement = opening + b' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
            replacement += root[0][len(opening):]
            prefix = prefix[:root.start()] + replacement + prefix[root.end():]
        self.prefix = io.BytesIO(prefix)

    def read(self, size=-1):
        if size < 0:
            return self.prefix.read() + self.source.read()
        first = self.prefix.read(size)
        return first + self.source.read(size - len(first)) if len(first) < size else first

    def close(self):
        self.prefix.close()


def feature_id(sha: str, member_index: int, kind: str, ordinal: int) -> str:
    return f"KZ{sha}M{member_index:03d}{FEATURES[kind]}{ordinal:09d}"


class TaggedKML(XMLGenerator):
    """Inserta una clave estable en name de una copia; nunca altera el original."""

    def __init__(self, output, sha: str, member_index: int):
        super().__init__(output, encoding="utf-8")
        self.sha = sha
        self.member_index = member_index
        self.stack = []
        self.ordinal = 0
        self.suppressed = 0

    def startElement(self, name, attrs):
        parent = local(self.stack[-1]) if self.stack else ""
        if self.suppressed:
            self.suppressed += 1
        elif local(name) == "name" and parent == "Placemark":
            self.suppressed = 1
        else:
            super().startElement(name, attrs)
            if local(name) == "Placemark":
                self.ordinal += 1
                prefix = name.rsplit(":", 1)[0] + ":" if ":" in name else ""
                name_tag = prefix + "name"
                super().startElement(name_tag, {})
                super().characters(feature_id(self.sha, self.member_index, "Placemark", self.ordinal))
                super().endElement(name_tag)
        self.stack.append(name)

    def endElement(self, name):
        if self.suppressed:
            self.suppressed -= 1
        else:
            super().endElement(name)
        self.stack.pop()

    def characters(self, content):
        if not self.suppressed:
            super().characters(content)

    def ignorableWhitespace(self, content):
        self.characters(content)

    def processingInstruction(self, target, data):
        if not self.suppressed:
            super().processingInstruction(target, data)


def record_kml(stream, db, sha: str, member: str, member_index: int) -> Counter:
    stack = []
    containers = []
    ordinals = Counter()
    counts = Counter()
    feature_depth = 0
    with db:
        for event, elem in ET.iterparse(NamespaceStream(stream), events=("start", "end")):
            tag = local(elem.tag)
            if event == "start":
                stack.append(elem)
                if tag in {"Document", "Folder"}:
                    containers.append({"element": elem, "name": "", "id": counts["contenedores"] + 1})
                    counts["contenedores"] += 1
                if tag in FEATURES:
                    feature_depth += 1
                continue
            parent = stack[-2] if len(stack) > 1 else None
            if tag == "name" and parent is not None and local(parent.tag) in {"Document", "Folder"}:
                containers[-1]["name"] = elem.text or ""
            if tag in FEATURES:
                ordinals[tag] += 1
                counts[tag] += 1
                name = next((child.text or "" for child in elem if local(child.tag) == "name"), "")
                geometries = Counter(local(child.tag) for child in elem.iter()
                                     if local(child.tag) in GEOMETRIES)
                attributes = [ET.tostring(child, encoding="unicode") for child in elem
                              if local(child.tag) not in GEOMETRIES]
                payload = {
                    "source_sha256": sha, "kml": member, "kind": tag,
                    "ordinal": ordinals[tag], "name": name,
                    "containers": [{"id": c["id"], "name": c["name"]} for c in containers],
                    "feature_xml_attributes": elem.attrib, "attribute_xml": attributes,
                    "geometry_counts": dict(geometries),
                    "altitude_modes": [child.text for child in elem.iter()
                                       if local(child.tag) == "altitudeMode"],
                }
                key = feature_id(sha, member_index, tag, ordinals[tag])
                db.execute("INSERT INTO originals VALUES (?,?,?,?,?,?,?)",
                           (key, sha, member, ordinals[tag], tag, name,
                            json.dumps(payload, ensure_ascii=False)))
                feature_depth -= 1
                elem.clear()
                if parent is not None:
                    parent.remove(elem)
            elif tag in {"Document", "Folder"}:
                containers.pop()
                elem.clear()
                if parent is not None:
                    parent.remove(elem)
            elif not feature_depth and tag != "kml":
                elem.clear()
                if parent is not None:
                    parent.remove(elem)
            stack.pop()
    return counts


def prepare_archive(source: Path, destination: Path, db, sha: str) -> dict:
    totals = Counter()
    members = []
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(
            destination, "x", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as tagged:
        names = original.namelist()
        if len(names) != len(set(names)):
            raise RuntimeError(f"El ZIP tiene miembros repetidos: {source}")
        kml_names = [name for name in names if name.lower().endswith(".kml")]
        if not kml_names:
            raise RuntimeError(f"El KMZ no contiene KML: {source}")
        for index, name in enumerate(kml_names, start=1):
            with original.open(name) as stream:
                counts = record_kml(stream, db, sha, name, index)
            if counts["NetworkLink"]:
                raise RuntimeError(f"NetworkLink requiere tratamiento separado; no se consultara: {name}")
            totals.update(counts)
            members.append({"kml": name, "counts": dict(counts)})
        for info in original.infolist():
            with original.open(info) as inp, tagged.open(info.filename, "w", force_zip64=True) as out:
                if info.filename in kml_names:
                    index = kml_names.index(info.filename) + 1
                    handler = TaggedKML(out, sha, index)
                    parser = xml.sax.make_parser()
                    parser.setFeature(xml.sax.handler.feature_external_ges, False)
                    parser.setContentHandler(handler)
                    parser.parse(NamespaceStream(inp))
                else:
                    shutil.copyfileobj(inp, out, length=1024 * 1024)
    return {"counts": dict(totals), "members": members}


def connect_cache(path: Path, resume: bool = False):
    db = sqlite3.connect(path)
    if resume:
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            db.close()
            raise RuntimeError("La base de trazabilidad no supera integrity_check.")
        for table, columns in (
                ("originals", ["id", "sha", "member", "ordinal", "kind", "name", "payload"]),
                ("outputs", ["id", "class_name", "quantity"])):
            actual = [row[1] for row in db.execute(f"PRAGMA table_info({table})")]
            if actual != columns:
                db.close()
                raise RuntimeError(f"Esquema de trazabilidad incompatible: {table}")
        return db
    db.execute("""CREATE TABLE originals (
        id TEXT PRIMARY KEY, sha TEXT, member TEXT, ordinal INTEGER,
        kind TEXT, name TEXT, payload TEXT)""")
    db.execute("""CREATE TABLE outputs (
        id TEXT, class_name TEXT, quantity INTEGER,
        PRIMARY KEY (id, class_name))""")
    db.execute("CREATE INDEX originals_sha ON originals (sha)")
    return db


def scan_paths(inputs: list[Path]) -> list[Path]:
    paths = {}
    for folder in inputs:
        if not folder.is_dir():
            raise FileNotFoundError(f"No existe la carpeta de entrada: {folder}")
        for path in folder.rglob("*"):
            if path.is_file() and path.suffix.lower() == ".kmz":
                paths[str(path.resolve()).casefold()] = path.resolve()
    return sorted(paths.values())


def automatic_name(filename: str) -> str:
    text = unicodedata.normalize("NFKD", Path(filename).stem).encode("ascii", "ignore").decode().lower()
    text = re.sub(r"[^a-z0-9]+", "_", re.sub(r"^proyecto\s+", "", text)).strip("_")
    if not text or not text[0].isalpha():
        text = "f_" + text
    return text[:40].rstrip("_")


def load_inventory(manifest: Path) -> list[dict]:
    with manifest.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream, delimiter=";"))
    seen = {}
    for row in rows:
        name = (row.get("nombre_sde") or "").strip() or automatic_name(row["archivo"])
        if not SDE_NAME.fullmatch(name) or name.startswith(("sde_", "gdb_", "delta_", "kmz_")):
            raise ValueError(
                f"nombre_sde no valido para {row['archivo']}: {name!r}. Use minusculas, numeros y _, "
                "empiece con letra, maximo 40 caracteres y sin prefijos sde_, gdb_, delta_ ni kmz_.")
        if name in seen:
            raise ValueError(f"nombre_sde repetido en el inventario: {name} ({seen[name]} y {row['archivo']})")
        seen[name] = row["archivo"]
        row["nombre_sde"] = name
    return rows


def discover(manifest: Path, inputs: list[Path], selected: list[str],
             selected_paths: list[Path] | None = None) -> tuple[list[dict], list[str]]:
    expected = load_inventory(manifest)
    if selected:
        unknown = set(selected) - {row["sha256"] for row in expected}
        if unknown:
            raise ValueError(f"SHA no incluido en el inventario: {sorted(unknown)}")
        expected = [row for row in expected if row["sha256"] in selected]
    paths = scan_paths(inputs)
    if selected_paths:
        requested = {str(path.resolve()).casefold() for path in selected_paths}
        available = {str(path).casefold() for path in paths}
        if requested - available:
            raise ValueError("Seleccione KMZ que existan dentro de las carpetas de entrada.")
        paths = [path for path in paths if str(path).casefold() in requested]
        selected_hashes = {digest(path) for path in paths}
        unknown = selected_hashes - {row["sha256"] for row in expected}
        if unknown:
            raise ValueError("Uno de los KMZ seleccionados no coincide con el inventario por SHA-256.")
        expected = [row for row in expected if row["sha256"] in selected_hashes]
    found = {}
    ignored = []
    wanted = {row["sha256"] for row in expected}
    for path in paths:
        sha = digest(path)
        if sha in wanted:
            found.setdefault(sha, path)
        else:
            ignored.append(str(path))
    missing = [row["archivo"] for row in expected if row["sha256"] not in found]
    if missing:
        raise FileNotFoundError("Faltan KMZ del inventario: " + "; ".join(missing))
    for row in expected:
        row["path"] = str(found[row["sha256"]])
    return expected, ignored


def add_fields(a, table: str, fields) -> None:
    existing = {f.name.casefold() for f in a.ListFields(table)}
    for name, kind, length in fields:
        if name.casefold() in existing:
            raise RuntimeError(f"Campo de trazabilidad ya existente: {table}: {name}")
        if kind == "TEXT":
            a.management.AddField(table, name, kind, field_length=length)
        else:
            a.management.AddField(table, name, kind)


def bind_features(a, gdb: Path, db, sha: str, filename: str) -> list[dict]:
    result = []
    editable = gdb.with_name(f"preparado_{sha[:12]}.gdb")
    a.management.CreateFileGDB(str(editable.parent), editable.name)
    for root, _, names in a.da.Walk(str(gdb), datatype="FeatureClass"):
        for name in sorted(names):
            source_fc = str(Path(root) / name)
            fc = str(editable / name)
            LOG.info("Preparando clase %s / %s", filename, name)
            # KML To Layer mantiene su salida no editable en el proceso de conversion.
            a.management.CopyFeatures(source_fc, fc)
            if int(a.management.GetCount(source_fc)[0]) != int(a.management.GetCount(fc)[0]):
                raise RuntimeError(f"La copia editable no conserva el conteo: {source_fc}")
            desc = a.Describe(fc)
            if desc.shapeType not in CLASS_SUFFIX:
                raise RuntimeError(f"Geometria inesperada: {desc.shapeType}: {fc}")
            if desc.spatialReference.factoryCode != 4326:
                raise RuntimeError(f"Referencia espacial inesperada: {fc}")
            add_fields(a, fc, FIELDS)
            count = 0
            nulls = 0
            name_previews = 0
            with db, a.da.UpdateCursor(fc, ["Name"] + [f[0] for f in FIELDS]) as cursor:
                for row in cursor:
                    key = row[0]
                    record = db.execute("SELECT sha, name FROM originals WHERE id=? AND kind='Placemark'",
                                        (key,)).fetchone()
                    if record is None or record[0] != sha:
                        raise RuntimeError(f"Entidad sin vinculo exacto al Placemark: {fc}: {key!r}")
                    original_name = record[1]
                    row[1:] = [key, sha, filename[:255], original_name[:1000], "PENDIENTE_ENGIE"]
                    cursor.updateRow(row)
                    name_previews += len(original_name) > 1000
                    db.execute("""INSERT INTO outputs VALUES (?,?,1)
                        ON CONFLICT(id,class_name) DO UPDATE SET quantity=quantity+1""",
                               (key, desc.shapeType))
                    count += 1
                    if count % 10000 == 0:
                        LOG.info("%s / %s: %s entidades vinculadas", filename, name, count)
            with a.da.SearchCursor(fc, ["SHAPE@"]) as cursor:
                nulls = sum(shape is None or shape.pointCount == 0 for (shape,) in cursor)
            if int(a.management.GetCount(fc)[0]) != count:
                raise RuntimeError(f"Conteo de cursor distinto de GetCount: {fc}")
            result.append({
                "local": fc, "shape_type": desc.shapeType, "count": count,
                "null_or_empty_geometry": nulls, "name_previews_truncated": name_previews,
                "has_z": desc.hasZ, "spatial_reference": desc.spatialReference.name,
            })
            LOG.info("Clase preparada: %s, %s entidades, %s geometrias vacias", name, count, nulls)
    if not result:
        raise RuntimeError(f"La conversion no genero clases de entidad: {filename}")
    return result


def create_table(a, gdb: Path, name: str, fields) -> str:
    path = str(gdb / name)
    a.management.CreateTable(str(gdb), name)
    add_fields(a, path, fields)
    return path


def export_metadata(a, gdb: Path, db, sources: list[dict]) -> list[dict]:
    attribute_fields = [("KZ_PM_ID", "TEXT", 100), ("KZ_SHA256", "TEXT", 64),
                        ("KZ_PARTE", "LONG", 0), ("KZ_TOTAL", "LONG", 0),
                        ("KZ_JSON", "TEXT", 4000)]
    balance_fields = [("KZ_PM_ID", "TEXT", 100), ("KZ_SHA256", "TEXT", 64),
                      ("KZ_TIPO", "TEXT", 32), ("KZ_NOMBRE", "TEXT", 1000),
                      ("KZ_PUNTOS", "LONG", 0), ("KZ_LINEAS", "LONG", 0),
                      ("KZ_POLIGON", "LONG", 0), ("KZ_MULTI3D", "LONG", 0),
                      ("KZ_MULTIPT", "LONG", 0), ("KZ_ESTADO", "TEXT", 40)]
    result = []
    for row in sources:
        sha = row["sha256"]
        attrs = create_table(a, gdb, f"atributos_{sha[:12]}", attribute_fields)
        balance = create_table(a, gdb, f"balance_{sha[:12]}", balance_fields)
        attr_count = balance_count = 0
        with a.da.InsertCursor(attrs, [f[0] for f in attribute_fields]) as ac:
            for key, payload in db.execute(
                    "SELECT id, payload FROM originals WHERE sha=? ORDER BY member, ordinal, kind", (sha,)):
                # 2000 caracteres Unicode ocupan como maximo 4000 unidades UTF-16.
                chunks = [payload[n:n + 2000] for n in range(0, len(payload), 2000)]
                for index, chunk in enumerate(chunks, start=1):
                    ac.insertRow((key, sha, index, len(chunks), chunk))
                    attr_count += 1
        with a.da.InsertCursor(balance, [f[0] for f in balance_fields]) as bc:
            for key, kind, name in db.execute(
                    "SELECT id, kind, name FROM originals WHERE sha=? ORDER BY member, ordinal, kind", (sha,)):
                quantities = dict(db.execute("SELECT class_name, quantity FROM outputs WHERE id=?", (key,)))
                total = sum(quantities.values())
                state = "CONVERTIDO_PENDIENTE_ENGIE" if total else "SIN_ENTIDAD_REVISAR"
                bc.insertRow((key, sha, kind, name[:1000], quantities.get("Point", 0),
                              quantities.get("Polyline", 0), quantities.get("Polygon", 0),
                              quantities.get("MultiPatch", 0), quantities.get("Multipoint", 0), state))
                balance_count += 1
        result.append({"local": attrs, "target_name": f"{row['nombre_sde']}_atributos",
                       "count": attr_count, "table": True, "sha256": sha})
        result.append({"local": balance, "target_name": f"{row['nombre_sde']}_balance",
                       "count": balance_count, "table": True, "sha256": sha})
    return result


def verify_workspace(a, sde: Path) -> None:
    if not a.Exists(str(sde)):
        raise FileNotFoundError(f"Conexion SDE no accesible: {sde}")
    desc = a.Describe(str(sde))
    if desc.workspaceType != "RemoteDatabase":
        raise RuntimeError("El destino debe ser una geodatabase empresarial .sde.")
    if str(desc.connectionProperties.database).casefold() != "arcgisaws":
        raise RuntimeError("La conexion no apunta a ArcGisAWS.")
    result = a.ArcSDESQLExecute(str(sde)).execute("SELECT DB_NAME(), SCHEMA_NAME(), USER_NAME()")
    if not isinstance(result, list) or not result or len(result[0]) != 3:
        raise RuntimeError(f"No se pudo comprobar base/esquema/usuario: {result!r}")
    database, schema, user = result[0]
    if str(database).casefold() != "arcgisaws" or str(schema).casefold() != "gis":
        raise RuntimeError(f"Se requiere base ArcGisAWS y esquema predeterminado gis; obtenido: {result!r}")
    LOG.info("Conexion comprobada: base=%s, esquema=%s, usuario=%s", database, schema, user)


def target_path(sde: Path, name: str) -> str:
    return str(sde / f"ArcGisAWS.gis.{name}")


def target_names(sources: list[dict]) -> list[str]:
    return [f"{row['nombre_sde']}_{suffix}" for row in sources for suffix in TARGET_SUFFIXES]


def legacy_audit_prefix(sha: str) -> str:
    # Las versiones anteriores nombraban las tablas por el hash del lote; con un solo KMZ es este valor.
    return hashlib.sha256(sha.encode()).hexdigest()[:12]


def legacy_target_names(sources: list[dict]) -> list[str]:
    names = []
    for row in sources:
        sha = row["sha256"]
        names += [f"kmz_{sha[:12]}_{suffix}" for suffix in CLASS_SUFFIX.values()]
        names += [f"kmz_{legacy_audit_prefix(sha)}_{suffix}" for suffix in ("atributos", "balance")]
    return names


def verify_targets_absent(a, sde: Path, names: list[str], legacy: list[str] = ()) -> None:
    for name in names:
        if a.Exists(target_path(sde, name)):
            raise RuntimeError(f"El objeto ya existe; no se sobrescribe ni duplica: gis.{name}")
    for name in legacy:
        if a.Exists(target_path(sde, name)):
            raise RuntimeError(
                f"Este KMZ ya fue cargado con el nombre anterior gis.{name}. No se vuelve a cargar: "
                "use la operacion Renombrar sobre la carpeta de ejecucion que lo cargo.")


class TransferValidationError(RuntimeError):
    pass


def copy_objects(a, destination: Path, objects: list[dict], report: dict, report_path: Path,
                 enterprise: bool = True) -> None:
    for obj in objects:
        dest = target_path(destination, obj["target_name"]) if enterprise else str(destination / obj["target_name"])
        if a.Exists(dest):
            raise RuntimeError(f"El objeto destino ya existe: {dest}")
    for obj in objects:
        dest = target_path(destination, obj["target_name"]) if enterprise else str(destination / obj["target_name"])
        entry = {"path": dest, "source": obj["local"], "state": "INICIADO", "expected_count": obj["count"],
                 "name": obj["target_name"], "sha256": obj.get("sha256")}
        report["targets"].append(entry)
        save_json(report_path, report)
        LOG.info("Copiando %s (%s filas)", dest, obj["count"])
        try:
            if obj.get("table"):
                a.management.CopyRows(obj["local"], dest)
            else:
                a.management.CopyFeatures(obj["local"], dest)
            actual = int(a.management.GetCount(dest)[0])
            entry["actual_count"] = actual
            if actual != obj["count"]:
                raise TransferValidationError(
                    f"Conteo destino distinto del local: {dest}: {actual} != {obj['count']}")
            if enterprise:
                with a.EnvManager(workspace=str(destination)):
                    parsed = [part.strip() for part in a.ParseTableName(a.Describe(dest).name).split(",")]
                if len(parsed) != 3 or parsed[1].casefold() != "gis":
                    raise TransferValidationError(f"Propietario destino distinto de gis: {dest}: {parsed!r}")
            verify_transfer(a, obj["local"], dest)
            entry["state"] = "VERIFICADO"
        except (a.ExecuteError, TransferValidationError) as error:
            entry.update(state="ERROR", error=str(error))
            LOG.exception("Error en %s; se continua con los demas objetos sin borrar el fallido.", dest)
        save_json(report_path, report)
    failures = [item["path"] for item in report["targets"] if item["state"] == "ERROR"]
    if failures:
        raise RuntimeError(f"{len(failures)} objetos no se pudieron copiar/verificar; ver targets en informe.json.")


def verify_transfer(a, source: str, dest: str) -> None:
    fields = [f.name for f in a.ListFields(source) if f.type not in {"OID", "Geometry", "Blob", "Raster"}
              and not f.required]
    # Las claves y los atributos se comparan como multiconjunto, sin depender de OBJECTID u orden.
    def fingerprint(path):
        total = 0
        xor = 0
        count = 0
        with a.da.SearchCursor(path, fields) as cursor:
            for row in cursor:
                encoded = json.dumps(list(row), ensure_ascii=False, default=str).encode("utf-8")
                value = int.from_bytes(hashlib.sha256(encoded).digest(), "big")
                total = (total + value) % (1 << 256)
                xor ^= value
                count += 1
        return count, total, xor
    if fingerprint(source) != fingerprint(dest):
        raise TransferValidationError(f"Los atributos copiados difieren del origen local: {dest}")
    source_desc, dest_desc = a.Describe(source), a.Describe(dest)
    if source_desc.dataType == "FeatureClass":
        for property_name in ("shapeType", "hasZ", "hasM"):
            if getattr(source_desc, property_name) != getattr(dest_desc, property_name):
                raise TransferValidationError(f"{property_name} difiere en el destino: {dest}")
        if source_desc.spatialReference.factoryCode != dest_desc.spatialReference.factoryCode:
            raise TransferValidationError(f"La referencia espacial difiere en el destino: {dest}")
        sr = source_desc.spatialReference
        resolutions = [sr.XYResolution, sr.XYResolution]
        if source_desc.hasZ:
            resolutions.append(sr.ZResolution)
        if source_desc.hasM:
            resolutions.append(sr.MResolution)
        if any(not math.isfinite(value) or value <= 0 for value in resolutions):
            raise TransferValidationError(f"Resolucion espacial no valida para verificar: {source}")

        def coordinates(point):
            values = [point.X, point.Y]
            if source_desc.hasZ:
                values.append(point.Z)
            if source_desc.hasM:
                values.append(point.M)
            return [None if value is None else str(value) if not math.isfinite(value)
                    else round(value / resolution) for value, resolution in zip(values, resolutions)]

        def geometry_fingerprint(path):
            point_count = part_count = null_count = 0
            total = xor = 0
            with a.da.SearchCursor(path, ["KZ_PM_ID", "SHAPE@"]) as cursor:
                for key, shape in cursor:
                    h = hashlib.sha256(key.encode("utf-8"))
                    if shape is None or shape.pointCount == 0:
                        null_count += 1
                        h.update(b"EMPTY")
                    if shape is not None:
                        point_count += shape.pointCount
                        part_count += shape.partCount
                        if shape.type == "point" and shape.pointCount:
                            h.update(json.dumps(coordinates(shape.firstPoint)).encode("ascii"))
                        elif shape.pointCount:
                            for index in range(shape.partCount):
                                h.update(b"PART")
                                for point in shape.getPart(index):
                                    h.update(b"BREAK" if point is None else
                                             json.dumps(coordinates(point)).encode("ascii"))
                    value = int.from_bytes(h.digest(), "big")
                    total = (total + value) % (1 << 256)
                    xor ^= value
            return point_count, part_count, null_count, total, xor
        if geometry_fingerprint(source) != geometry_fingerprint(dest):
            raise TransferValidationError(
                f"Geometria distinta del origen (vertices/partes/XY/Z/M a resolucion de origen): {dest}")


def check_resume_report(report: dict) -> None:
    unverified = [item.get("path") for item in report.get("targets") or []
                  if item.get("state") != "VERIFICADO"]
    if unverified:
        raise RuntimeError(
            "La ejecucion previa tiene intentos de carga SDE sin verificar (INICIADO o ERROR). "
            "No se reanuda automaticamente: revise esos objetos destino con el administrador GIS: "
            + "; ".join(str(path) for path in unverified))
    if not isinstance(report.get("sources"), list) or not report["sources"]:
        raise RuntimeError("El informe anterior no contiene fuentes reconocibles.")


def object_name(path: str) -> str:
    return Path(path).name.rsplit(".", 1)[-1]


def legacy_owner(report: dict, name: str) -> tuple[str, str] | None:
    """Devuelve (sha, sufijo) de un nombre kmz_<hash>_<sufijo> de versiones anteriores."""
    match = LEGACY_NAME.fullmatch(name)
    if not match:
        return None
    prefix, suffix = match.groups()
    shas = {source.get("sha256") for source in report.get("sources", []) if source.get("sha256")}
    if suffix in CLASS_SUFFIX.values():
        owners = [sha for sha in shas if sha[:12] == prefix]
    else:
        owners = [sha for sha in shas if legacy_audit_prefix(sha) == prefix]
    if len(owners) != 1:
        raise RuntimeError(
            f"No se puede asignar gis.{name} a un unico KMZ (tabla de un lote de varios KMZ o informe "
            "incompleto). No se renombra ni se carga nada; revise con el administrador GIS.")
    return owners[0], suffix


def loaded_shas(report: dict) -> set[str]:
    loaded = set()
    for item in report.get("targets") or []:
        if item.get("sha256"):
            loaded.add(item["sha256"])
            continue
        name = object_name(item["path"])
        match = LEGACY_NAME.fullmatch(name)
        if match and match[2] in CLASS_SUFFIX.values():
            loaded.add(legacy_owner(report, name)[0])
    return loaded


def rename_loaded(a, output: Path, report: dict, report_path: Path, inventory: dict[str, dict],
                  workspace: Path, attempt: str, enterprise: bool = True) -> int:
    """Renombra objetos kmz_<hash> ya verificados a <nombre_sde>_<sufijo>, sin copiar ni borrar datos."""
    def path_for(name):
        return target_path(workspace, name) if enterprise else str(workspace / name)

    check_resume_report(report)
    plan = []
    for entry in report.get("targets") or []:
        if entry.get("renamed_from"):
            continue
        old_name = object_name(entry["path"])
        owner = legacy_owner(report, old_name)
        if owner is None:
            continue
        sha, suffix = owner
        if sha not in inventory:
            raise RuntimeError(f"El KMZ de gis.{old_name} no esta en el inventario; no se puede asignar nombre.")
        source = Path(entry["source"]).resolve()
        if not source.is_relative_to(output):
            raise RuntimeError(f"El origen local de gis.{old_name} esta fuera de la ejecucion: {source}")
        plan.append((entry, sha, old_name, f"{inventory[sha]['nombre_sde']}_{suffix}", str(source)))
    new_names = [item[3] for item in plan]
    if len(set(new_names)) != len(new_names):
        raise RuntimeError("El informe asigna el mismo nombre nuevo a dos objetos; no se renombra nada.")
    if not plan:
        LOG.info("No hay objetos con nombres anteriores kmz_<hash> en esta ejecucion; no se renombra nada.")
        return 0
    pending = []
    for entry, sha, old_name, new_name, source in plan:
        old, new = path_for(old_name), path_for(new_name)
        old_exists, new_exists = bool(a.Exists(old)), bool(a.Exists(new))
        if old_exists == new_exists:
            raise RuntimeError(
                f"Debe existir exactamente uno de gis.{old_name} o gis.{new_name} (existen: "
                f"{old_exists}/{new_exists}). No se renombro nada; revise con el administrador GIS.")
        current = old if old_exists else new
        expected = entry.get("actual_count", entry["expected_count"])
        if int(a.management.GetCount(current)[0]) != expected:
            raise RuntimeError(f"El conteo de {current} difiere del verificado en la carga; no se renombra nada.")
        LOG.info("Comprobando %s contra la preparacion local antes de renombrar", current)
        verify_transfer(a, source, current)
        if old_exists and not a.TestSchemaLock(old):
            raise RuntimeError(
                f"gis.{old_name} esta en uso. Quite sus capas de los mapas, cierre otras sesiones que lo usen "
                "y vuelva a ejecutar. No se renombro nada.")
        pending.append((entry, sha, old, new, old_exists, new_name, expected))
    shutil.copyfile(report_path, output / f"informe_anterior_{attempt}.json")
    for entry, sha, old, new, old_exists, new_name, expected in pending:
        if old_exists:
            LOG.info("Renombrando %s -> %s", old, new)
            try:
                a.management.Rename(old, new)
            except a.ExecuteError:
                if not enterprise or not a.Exists(old) or a.Exists(new):
                    raise
                LOG.warning("Rename no acepto el nombre calificado; se reintenta con %s", new_name)
                a.management.Rename(old, str(workspace / new_name))
        else:
            LOG.warning("%s ya tenia el nombre nuevo (renombrado anterior interrumpido); se registra.", new)
        if a.Exists(old) or not a.Exists(new) or int(a.management.GetCount(new)[0]) != expected:
            raise RuntimeError(f"El renombrado no quedo confirmado: {old} -> {new}")
        entry.update(renamed_from=entry["path"], path=new, name=new_name, sha256=sha, renamed_utc=attempt)
        save_json(report_path, report)
    report["last_rename_utc"] = attempt
    save_json(report_path, report)
    return len(pending)


def contained_path(value: str, output: Path, previous_root: Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = output / path
    elif not path.is_relative_to(output):
        if not path.is_relative_to(previous_root):
            raise RuntimeError(f"El informe apunta fuera de la ejecucion anterior: {path}")
        path = output / path.relative_to(previous_root)
    path = path.resolve()
    if not path.is_relative_to(output):
        raise RuntimeError(f"Ruta de preparacion fuera de la carpeta de ejecucion: {path}")
    return path


def validate_prepared(a, source: dict, row: dict, output: Path, db) -> list[dict]:
    sha = row["sha256"]
    previous_original = Path(source["preserved_original"])
    previous_root = previous_original.parent.parent
    original = contained_path(str(previous_original), output, previous_root)
    if not original.is_file() or digest(original) != sha:
        raise RuntimeError(f"Original preservado ausente o modificado: {row['archivo']}")
    count = db.execute("SELECT COUNT(*) FROM originals WHERE sha=? AND kind='Placemark'", (sha,)).fetchone()[0]
    if count != int(row["Placemark"]):
        raise RuntimeError(f"Trazabilidad incompleta para reutilizar {row['archivo']}.")
    classes = source["feature_classes"]
    if not classes or sum(obj["count"] for obj in classes) != source.get("converted_rows"):
        raise RuntimeError(f"Checkpoint de clases incompleto: {row['archivo']}")
    observed = Counter()
    shape_types = set()
    for obj in classes:
        fc = contained_path(obj["local"], output, previous_root)
        if not a.Exists(str(fc)):
            raise RuntimeError(f"Clase preparada ausente: {fc}")
        desc = a.Describe(str(fc))
        if desc.shapeType != obj["shape_type"] or desc.hasZ != obj["has_z"] or \
                desc.spatialReference.factoryCode != 4326:
            raise RuntimeError(f"Geometria/esquema de checkpoint modificado: {fc}")
        if desc.shapeType in shape_types:
            raise RuntimeError("El checkpoint contiene clases duplicadas de la misma geometria.")
        shape_types.add(desc.shapeType)
        needed = {field[0].casefold() for field in FIELDS}
        if not needed.issubset({field.name.casefold() for field in a.ListFields(str(fc))}):
            raise RuntimeError(f"Faltan campos de trazabilidad en {fc}")
        actual = 0
        with a.da.SearchCursor(str(fc), ["KZ_PM_ID", "KZ_SHA256", "KZ_NOMBRE", "KZ_ESTADO"]) as cursor:
            for key, stored_sha, name, state in cursor:
                cached = db.execute("SELECT sha,name FROM originals WHERE id=?", (key,)).fetchone()
                if cached is None or cached[0] != sha or stored_sha != sha or \
                        name != cached[1][:1000] or state != "PENDIENTE_ENGIE":
                    raise RuntimeError(f"Vinculo original alterado en {fc}: {key}")
                observed[(key, desc.shapeType)] += 1
                actual += 1
        if actual != obj["count"] or actual != int(a.management.GetCount(str(fc))[0]):
            raise RuntimeError(f"Conteo preparado modificado: {fc}")
        obj["local"] = str(fc)
    expected = {(key, kind): quantity for key, kind, quantity in db.execute(
        "SELECT o.id,o.class_name,o.quantity FROM outputs o JOIN originals r ON r.id=o.id WHERE r.sha=?",
        (sha,))}
    if dict(observed) != expected:
        raise RuntimeError(f"El balance de entidades no coincide con la trazabilidad: {row['archivo']}")
    source["preserved_original"] = str(original)
    LOG.info("Preparacion previa verificada y reutilizada: %s (%s entidades)",
             row["archivo"], source["converted_rows"])
    return classes


def prepare_source(a, row: dict, source_report: dict, output: Path, db, attempt: str) -> list[dict]:
    sha = row["sha256"]
    originals = output / "originales"
    originals.mkdir(exist_ok=True)
    archive_copy = originals / f"{sha}.kmz"
    LOG.info("Preparando %s", row["archivo"])
    if not archive_copy.exists():
        shutil.copyfile(row["path"], archive_copy)
    if digest(archive_copy) != sha:
        raise RuntimeError(f"El original preservado no coincide con el inventario: {archive_copy}")
    # Los parciales anteriores se conservan; el nuevo intento escribe en otra carpeta.
    conversions = output / "intentos" / attempt / sha[:12]
    conversions.mkdir(parents=True, exist_ok=False)
    with db:
        db.execute("DELETE FROM outputs WHERE id IN (SELECT id FROM originals WHERE sha=?)", (sha,))
        db.execute("DELETE FROM originals WHERE sha=?", (sha,))
    derived = conversions / f"{sha[:12]}.kmz"
    analysis = prepare_archive(archive_copy, derived, db, sha)
    source_report.update(analysis, preserved_original=str(archive_copy))
    if analysis["counts"].get("Placemark", 0) != int(row["Placemark"]):
        raise RuntimeError(f"Conteo de Placemarks distinto del inventario: {row['archivo']}")
    LOG.info("Atributos preservados; convirtiendo %s con KML To Layer", row["archivo"])
    try:
        gp = a.conversion.KMLToLayer(str(derived), str(conversions), f"kz_{sha[:12]}", "NO_GROUNDOVERLAY")
    except a.ExecuteError:
        LOG.error("Mensajes de KML To Layer para %s: %s", row["archivo"], a.GetMessages())
        raise
    source_report["conversion_messages"] = gp.getMessages()
    classes = bind_features(a, conversions / f"kz_{sha[:12]}.gdb", db, sha, row["archivo"])
    source_report["feature_classes"] = classes
    source_report["converted_rows"] = sum(obj["count"] for obj in classes)
    source_report["placemarks_with_output"] = db.execute(
        "SELECT COUNT(DISTINCT o.id) FROM outputs o JOIN originals r ON o.id=r.id WHERE r.sha=?",
        (sha,)).fetchone()[0]
    source_report["placemarks_without_output"] = int(row["Placemark"]) - source_report["placemarks_with_output"]
    source_report["originals_with_multiple_output_rows"] = db.execute(
        """SELECT COUNT(*) FROM (SELECT o.id FROM outputs o JOIN originals r ON o.id=r.id
           WHERE r.sha=? GROUP BY o.id HAVING SUM(o.quantity)>1)""", (sha,)).fetchone()[0]
    source_report["z_review_note"] = "Ver altitude_modes y XML original; no se supone cota de negocio."
    source_report["prepared_utc"] = attempt
    if source_report["placemarks_without_output"]:
        LOG.warning("%s: %s Placemarks sin entidad convertida; se conservan en originales y balance.",
                    row["archivo"], source_report["placemarks_without_output"])
    return classes


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entrada", action="append", type=Path,
                        help="Carpeta con KMZ; se puede repetir y busca en subcarpetas.")
    parser.add_argument("--sde", type=Path, default=Path(DEFAULT_SDE))
    parser.add_argument("--salida", type=Path, help="Carpeta NUEVA para originales, GDB, auditoria e informe.")
    parser.add_argument("--inventario", type=Path, default=HERE / "01_archivos.csv")
    parser.add_argument("--sha", action="append", default=[], help="Procesar solo este SHA del inventario (piloto).")
    parser.add_argument("--kmz", action="append", default=[], type=Path,
                        help="Seleccionar un archivo dentro de las entradas; repetible. Vacio: inventario completo.")
    parser.add_argument("--reanudar", type=Path,
                        help="Carpeta de ejecucion previa; sus cargas SDE anteriores deben estar VERIFICADO.")
    parser.add_argument("--aplicar", action="store_true", help="Preparar y cargar a SDE. Sin esta opcion solo valida.")
    parser.add_argument("--solo-preparar", action="store_true",
                        help="Preparar GDB y atributos localmente, sin conectar ni cargar a SDE.")
    parser.add_argument("--renombrar", action="store_true",
                        help="Con --reanudar: renombra objetos ya cargados kmz_<hash> a nombre_sde del inventario.")
    return parser


def main(argv=None, *, result_reports: list[Path] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.aplicar and args.solo_preparar:
        raise ValueError("--aplicar y --solo-preparar son excluyentes.")
    timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    if args.reanudar and args.salida:
        raise ValueError("--reanudar y --salida son excluyentes.")
    if args.kmz and args.sha:
        raise ValueError("--kmz y --sha son excluyentes.")
    if args.renombrar and (not args.reanudar or args.aplicar or args.solo_preparar or args.kmz
                           or args.sha or args.entrada):
        raise ValueError("--renombrar solo se usa con --reanudar <carpeta de ejecucion> y --sde.")
    output = args.reanudar or args.salida or HERE / "ejecuciones" / timestamp
    output = output.resolve()
    inputs = args.entrada or [HERE / "kmz"]
    for folder in inputs:
        if output == folder.resolve() or folder.resolve() in output.parents:
            raise ValueError("La salida debe quedar fuera de las carpetas de entrada.")
    if args.reanudar:
        previous = json.loads((output / "informe.json").read_text(encoding="utf-8"))
        check_resume_report(previous)
        if not (output / "trazabilidad.sqlite").is_file():
            raise RuntimeError("La carpeta previa no contiene trazabilidad.sqlite; no se puede reanudar.")
    else:
        previous = None
        output.mkdir(parents=True, exist_ok=False)
    lock_path = output / ".ejecucion.lock"
    try:
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as error:
        raise RuntimeError(
            "La carpeta esta bloqueada por otra ejecucion o una interrupcion. No ejecute en paralelo. "
            "Si el proceso anterior termino, retire .ejecucion.lock solo despues de comprobarlo.") from error
    log_handlers = []
    previous_level, previous_propagate = LOG.level, LOG.propagate
    report_path = output / "informe.json"
    report = {"state": "INICIADO", "started_utc": timestamp, "sde": str(args.sde),
              "apply_requested": args.aplicar, "sources": [], "targets": [],
              "business_mapping_approved": False,
              "pending": [
                  "Confirmar proyectos, componentes, alternativas e id_analisis con ENGIE.",
                  "Definir destinos tematicos EFT y granularidad Section/vano, Set, fase y circuito.",
                  "Revisar entidades sin conversion, cambios de geometria, Z y modos de altitud.",
                  "GroundOverlay, ScreenOverlay y PhotoOverlay se conservan en originales y atributos; "
                  "no se cargan como raster ni como entidades de negocio.",
                  "No se publican servicios, ni se registra versionado o tablas de negocio."
              ]}
    db = None
    error_snapshot = output / f"error_{timestamp}.json"
    try:
        with os.fdopen(lock_fd, "w", encoding="utf-8") as lock:
            lock.write(json.dumps({"pid": os.getpid(), "started_utc": timestamp}))
        log_handlers.append(logging.FileHandler(output / "ejecucion.log", encoding="utf-8"))
        log_handlers.append(logging.StreamHandler(sys.stdout))
        LOG.setLevel(logging.INFO)
        LOG.propagate = False
        for handler in log_handlers:
            handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
            LOG.addHandler(handler)
        if args.reanudar:
            previous = json.loads((output / "informe.json").read_text(encoding="utf-8"))
            check_resume_report(previous)
        import arcpy as a
        a.env.overwriteOutput = False
        a.env.qualifiedFieldNames = False
        a.env.extent = None
        a.env.outputCoordinateSystem = None
        if args.renombrar:
            report = previous
            inventory = {row["sha256"]: row for row in load_inventory(args.inventario)}
            verify_workspace(a, args.sde)
            renamed = rename_loaded(a, output, report, report_path, inventory, args.sde, timestamp)
            if result_reports is not None:
                result_reports.append(report_path)
            LOG.info("RENOMBRADO: %s objetos con nombre legible. Informe: %s", renamed, report_path)
            return 0
        sources, ignored = discover(args.inventario, inputs, args.sha, args.kmz)
        batch = hashlib.sha256("".join(sorted(row["sha256"] for row in sources)).encode()).hexdigest()[:12]
        report.update(batch=batch, ignored_kmz=ignored, arcgis=a.GetInstallInfo())
        report["planned_target_names"] = target_names(sources)
        loaded = loaded_shas(previous) if previous else set()
        report["sde_loaded_sha256"] = sorted(loaded)
        already = [row["archivo"] for row in sources if row["sha256"] in loaded]
        if already and not args.solo_preparar:
            raise RuntimeError(
                "Estos KMZ ya se cargaron a SDE desde esta carpeta; quitelos de la seleccion: " + "; ".join(already))
        if ignored:
            LOG.warning("%s KMZ fuera de la seleccion/inventario; ver ignored_kmz en informe.json.", len(ignored))
        if not args.solo_preparar:
            verify_workspace(a, args.sde)
            verify_targets_absent(a, args.sde, report["planned_target_names"], legacy_target_names(sources))
        old_sources = {source["sha256"]: source for source in previous["sources"]} if previous else {}
        current_sources = []
        for row in sources:
            source_report = old_sources.get(row["sha256"], {})
            source_report.update(file=row["archivo"], sha256=row["sha256"], path=row["path"],
                                 expected_placemarks=int(row["Placemark"]))
            current_sources.append(source_report)
        selected_shas = [row["sha256"] for row in sources]
        report["sources"] = current_sources + [source for sha, source in old_sources.items()
                                               if sha not in selected_shas]
        report["selected_sha256"] = selected_shas
        report["resumed_from"] = str(output) if previous else None
        if previous:
            report["targets"] = list(previous.get("targets") or [])
            report["started_utc"] = previous.get("started_utc", timestamp)
            report["last_attempt_utc"] = timestamp
            db = connect_cache(output / "trazabilidad.sqlite", resume=True)
            for row, source_report in zip(sources, current_sources):
                if source_report.get("feature_classes"):
                    validate_prepared(a, source_report, row, output, db)
            if args.aplicar or args.solo_preparar:
                shutil.copyfile(report_path, output / f"informe_anterior_{timestamp}.json")
        else:
            save_json(report_path, report)
        if not args.aplicar and not args.solo_preparar:
            report["state"] = "VALIDACION_PREVIA_SIN_CARGA"
            validation_path = output / f"validacion_{timestamp}.json" if previous else report_path
            save_json(validation_path, report)
            if result_reports is not None:
                result_reports.append(validation_path)
            LOG.info("VALIDACION PREVIA: %s KMZ. No se crearon objetos en SDE. Use --aplicar para cargar.", len(sources))
            return 0
        if db is None:
            db = connect_cache(output / "trazabilidad.sqlite")
        objects = []
        for row, source_report in zip(sources, current_sources):
            if source_report.get("feature_classes"):
                classes = source_report["feature_classes"]
            else:
                classes = prepare_source(a, row, source_report, output, db, timestamp)
            for obj in classes:
                # Los checkpoints antiguos guardaban nombres kmz_<hash>; el destino se decide al cargar.
                obj.update(target_name=f"{row['nombre_sde']}_{CLASS_SUFFIX[obj['shape_type']]}",
                           sha256=row["sha256"])
            objects.extend(classes)
            save_json(report_path, report)
            if result_reports is not None:
                result_reports.append(report_path)
        audit_folder = output / "intentos" / timestamp
        audit_folder.mkdir(parents=True, exist_ok=True)
        audit_gdb = audit_folder / "auditoria.gdb"
        LOG.info("Generando tablas de atributos originales y balance de todos los objetos.")
        a.management.CreateFileGDB(str(audit_folder), audit_gdb.name)
        objects.extend(export_metadata(a, audit_gdb, db, sources))
        names = [obj["target_name"] for obj in objects]
        if len(set(names)) != len(names) or not set(names) <= set(report["planned_target_names"]):
            raise RuntimeError("Nombres destino repetidos o fuera de lo planificado; no se carga nada.")
        for obj in objects:
            if int(a.management.GetCount(obj["local"])[0]) != obj["count"]:
                raise RuntimeError(f"Conteo local inconsistente: {obj['local']}")
        report["local_objects"] = objects
        report["state"] = "PREPARADO_LOCAL_CON_PENDIENTES"
        save_json(report_path, report)
        if args.aplicar:
            verify_workspace(a, args.sde)
            verify_targets_absent(a, args.sde, report["planned_target_names"], legacy_target_names(sources))
            copy_objects(a, args.sde, objects, report, report_path)
            report["sde_loaded_sha256"] = sorted(loaded_shas(report))
            report["state"] = "CARGADO_SDE_CON_PENDIENTES_ENGIE"
        save_json(report_path, report)
        LOG.info("%s: %s KMZ, %s objetos. Informe: %s",
                 report["state"], len(sources), len(objects), report_path)
        return 0
    except Exception as error:
        report.update(state="ERROR_REVISAR_CARGA_PARCIAL", error=str(error), traceback=traceback.format_exc())
        LOG.exception("La ejecucion fallo. No se borran objetos ni se ocultan cargas parciales.")
        try:
            failure_path = error_snapshot if previous else report_path
            save_json(failure_path, report)
            if result_reports is not None:
                result_reports.append(failure_path)
        except OSError:
            LOG.exception(
                "Tampoco se pudo actualizar informe.json. El error original esta en ejecucion.log "
                "y en los mensajes de ArcGIS. Revise tambien informe.json.tmp si existe.")
        return 1
    finally:
        if db is not None:
            db.close()
        for handler in log_handlers:
            LOG.removeHandler(handler)
            handler.close()
        LOG.setLevel(previous_level)
        LOG.propagate = previous_propagate
        lock_path.unlink()


if __name__ == "__main__":
    sys.exit(main())
