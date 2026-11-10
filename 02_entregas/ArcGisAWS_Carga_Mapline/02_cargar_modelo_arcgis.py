"""Carga inicial de los 14 objetos Mapline mediante ArcPy, antes de publicar servicios.

Sin --apply solo valida. No elimina, actualiza ni sobrescribe objetos existentes.
Requiere geometrías históricas y mapeos revisados; el dump SQL no los contiene.
Ejecutar con el Python de ArcGIS Pro y una conexión del propietario de los datos.
"""
from __future__ import annotations

import argparse
import datetime as dt
import decimal
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import uuid


PROJECT_ROUTE = {
    "mline_tc_proyecto": None,
    "mline_ta_proyecto_estado": ("id_proyecto", "mline_tc_proyecto"),
    "mline_td_proyecto_componente": ("id_proyecto", "mline_tc_proyecto"),
    "mline_td_proyecto_capa": ("id_proyecto", "mline_tc_proyecto"),
    "mline_td_proyecto_regla_cfg": ("id_proyecto", "mline_tc_proyecto"),
    "mline_td_proyecto_ltransmision": ("id_proyecto_componente", "mline_td_proyecto_componente"),
    "mline_td_proyecto_cgeneracion": ("id_proyecto_componente", "mline_td_proyecto_componente"),
    "mline_td_proyecto_area_interes": ("id_proyecto_componente", "mline_td_proyecto_componente"),
    "mline_td_proyecto_envelope": ("id_proyecto_area_interes", "mline_td_proyecto_area_interes"),
    "mline_td_proyecto_celda": ("id_proyecto_envelope", "mline_td_proyecto_envelope"),
    "mline_td_celda_capa": ("id_proyecto_celda", "mline_td_proyecto_celda"),
    "mline_td_proyecto_alternativa": ("id_proyecto_componente", "mline_td_proyecto_componente"),
    "mline_td_proyecto_infraestructura": ("id_proyecto_alternativa", "mline_td_proyecto_alternativa"),
    "mline_td_infraestructura_celda": ("id_proyecto_infraestructura", "mline_td_proyecto_infraestructura"),
}


def fail(message):
    raise RuntimeError(message)


def read_json(value, base):
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    path = Path(value)
    if not path.is_absolute():
        path = base / path
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sqlname(value):
    return "[" + value.replace("]", "]]") + "]"


class Loader:
    def __init__(self, arcpy, model, config, cache):
        self.a = arcpy
        self.model = model
        self.cfg = config
        self.cache = cache
        self.tables = {t["name"]: t for t in model["tables"]}
        self.database = model.get("database", "ArcGisAWS")
        self.stage_schema = model.get("staging_schema", "mapline_carga_20261030")
        self.source = config.get("source_sde", "")
        self.dest = config.get("destination_sde", "")
        self.owner = config.get("destination_owner", "")
        self.project_maps = {}
        self.keys = {}
        self.domains = {}
        self.geometry_flags = {}
        self.targets = {}
        self.warnings = []
        self.report = {"database": self.database, "applied": False, "objects": [], "warnings": self.warnings}
        self.cache.execute("CREATE TABLE geometry_cache (tab TEXT, pk TEXT, shape TEXT, analysis TEXT, PRIMARY KEY(tab,pk))")

    def source_path(self, name):
        return os.path.join(self.source, f"{self.database}.{self.stage_schema}.{name}")

    def target_path(self, name, feature=False):
        root = self.dest
        if feature:
            root = os.path.join(root, f"{self.database}.{self.owner}.Datos_Proyecto")
        return os.path.join(root, f"{self.database}.{self.owner}.{name}")

    def rows(self, name, fields):
        with self.a.da.SearchCursor(self.source_path(name), fields) as cursor:
            yield from cursor

    def pk(self, name):
        key = self.tables[name]["primary_key"]
        if len(key) != 1:
            fail(f"Se requiere clave simple revisada: {name}")
        return key[0]

    def verify_connections(self):
        if not self.source or not self.dest or not self.owner:
            fail("Complete source_sde, destination_sde y destination_owner en la configuración.")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", self.owner):
            fail("destination_owner debe ser un propietario/esquema SQL simple.")
        for label, connection in (("origen", self.source), ("destino", self.dest)):
            if not self.a.Exists(connection):
                fail(f"Conexión {label} no accesible: {connection}")
            desc = self.a.Describe(connection)
            if desc.workspaceType != "RemoteDatabase":
                fail(f"La conexión {label} no es una geodatabase empresarial.")
            cp = desc.connectionProperties
            if str(getattr(cp, "database", "")).lower() != self.database.lower():
                fail(f"La conexión {label} no apunta a {self.database}.")
        sql = self.a.ArcSDESQLExecute(self.dest)
        result = sql.execute("SELECT SCHEMA_NAME(), USER_NAME()")
        if not result or str(result[0][0]).lower() != self.owner.lower():
            fail("El esquema predeterminado del usuario destino debe coincidir con destination_owner.")
        # Registro branch depende de esta propiedad; no basta un booleano del config.
        cp = self.a.Describe(self.dest).connectionProperties
        if not hasattr(cp, "branch"):
            fail("Configure Versioning Type = Branch en la conexión destino de ArcGIS Pro.")
        self.a.env.overwriteOutput = False

    def verify_targets_absent(self):
        for name, meta in self.tables.items():
            path = self.target_path(name, bool(meta.get("geometry_type")))
            self.targets[name] = path
            # Comprobar también raíz: nombres de clase son únicos por propietario.
            if self.a.Exists(path) or self.a.Exists(self.target_path(name)):
                fail(f"El objeto destino ya existe; no se sobrescribirá: {name}")
            if meta.get("geometry_type") and self.a.Exists(self.target_path("rc_proyecto_" + name)):
                fail(f"La relación de proyecto destino ya existe: {name}")
        for rel in self.model.get("relations", []):
            if rel.get("obsolete") or rel["parent"] == rel["child"]:
                continue
            if self.a.Exists(self.target_path("rc_" + rel["name"])):
                fail(f"La relación destino ya existe: {rel['name']}")
        for dataset in ("Datos_Externos", "Datos_Internos", "Datos_Proyecto"):
            path = self.target_path(dataset)
            if self.a.Exists(path):
                d = self.a.Describe(path)
                if d.spatialReference.factoryCode != 4326:
                    fail(f"{dataset} existente no usa EPSG:4326.")
                if dataset == "Datos_Proyecto" and getattr(d, "isVersioned", False):
                    fail("Datos_Proyecto ya está versionado; revisar carga con administrador GIS.")
                if dataset == "Datos_Proyecto":
                    with self.a.EnvManager(workspace=path):
                        if self.a.ListFeatureClasses() or self.a.ListTables():
                            fail("Datos_Proyecto debe estar vacío antes de esta carga inicial; no se modificarán clases ajenas.")

    def verify_stage(self):
        for name, meta in self.tables.items():
            names = [f["name"] for f in meta["fields"]]
            available = {f.name.lower() for f in self.a.ListFields(self.source_path(name))}
            if any(n.lower() not in available for n in names):
                fail(f"El esquema staging no coincide: {name}")
            count = 0
            seen = set()
            for (key,) in self.rows(name, [self.pk(name)]):
                if key is None or key in seen:
                    fail(f"Clave nula o repetida en staging: {name}")
                seen.add(key)
                count += 1
            if count != meta["rows"]:
                fail(f"Conteo de staging incorrecto en {name}: {count} != {meta['rows']}")
            self.keys[name] = seen
            self.report["objects"].append({"name": name, "rows": count, "geometry": meta.get("geometry_type")})
        for rel in self.model.get("relations", []):
            if rel.get("obsolete"):
                continue
            parent_projects = self.resolve_projects(rel["parent"])
            child_projects = self.resolve_projects(rel["child"])
            for key, value in self.rows(rel["child"], [self.pk(rel["child"]), rel["child_key"]]):
                if value is not None and value not in self.keys[rel["parent"]]:
                    fail(f"Referencia huérfana en staging: {rel['name']}")
                if value is not None and parent_projects[value] != child_projects[key]:
                    fail(f"La relación cruza proyectos distintos en staging: {rel['name']}")

    def resolve_projects(self, name):
        if name in self.project_maps:
            return self.project_maps[name]
        route = PROJECT_ROUTE[name]
        if route is None:
            mapped = {}
            for key, code in self.rows(name, [self.pk(name), "co_proyecto"]):
                code = str(code or "").strip()
                if not code or len(code) > 12 or code in mapped.values():
                    fail("Códigos co_proyecto vacíos, repetidos o incompatibles en staging.")
                mapped[key] = code
        else:
            foreign, parent = route
            parents = self.resolve_projects(parent)
            mapped = {}
            for key, parent_key in self.rows(name, [self.pk(name), foreign]):
                if parent_key not in parents:
                    fail(f"No se puede determinar el proyecto de cada fila de {name}.")
                mapped[key] = parents[parent_key]
        self.project_maps[name] = mapped
        return mapped

    def verify_geometries(self):
        for name, meta in self.tables.items():
            kind = meta.get("geometry_type")
            if not kind:
                continue
            src = self.cfg.get("geometry_sources", {}).get(name, {})
            path, field, analysis = src.get("path"), src.get("key_field"), src.get("analysis_field")
            if not path or not field or not analysis:
                fail(f"Falta fuente geométrica, clave histórica o analysis_field: {name}")
            desc = self.a.Describe(path)
            if desc.spatialReference.factoryCode != 4326:
                fail(f"La geometría fuente debe estar previamente validada en EPSG:4326: {name}")
            if desc.shapeType.upper() != kind:
                fail(f"Tipo geométrico incompatible: {name}")
            self.geometry_flags[name] = (bool(desc.hasZ), bool(desc.hasM))
            fields = {f.name.lower() for f in self.a.ListFields(path)}
            if field.lower() not in fields or analysis.lower() not in fields:
                fail(f"No existen clave o analysis_field en la fuente geométrica: {name}")
            check = "memory/mapline_geom_" + uuid.uuid4().hex
            try:
                self.a.management.CheckGeometry(path, check, "ESRI")
                if int(self.a.management.GetCount(check)[0]):
                    fail(f"La fuente tiene errores geométricos: {name}. Corregir y revisar fuera del cargador.")
            finally:
                if self.a.Exists(check):
                    self.a.management.Delete(check)
            seen = set()
            with self.a.da.SearchCursor(path, [field, analysis, "SHAPE@JSON", "SHAPE@"]) as cursor:
                for key, run, shape_json, shape in cursor:
                    if key is None or key in seen or key not in self.keys[name]:
                        fail(f"Clave histórica inválida/repetida/no existente en la geometría de {name}")
                    if shape is None or not shape.pointCount:
                        fail(f"Geometría vacía: {name}")
                    if run is None or not str(run).strip() or len(str(run)) > 128:
                        fail(f"Identificador de análisis no válido: {name}")
                    seen.add(key)
                    self.cache.execute("INSERT INTO geometry_cache VALUES (?,?,?,?)", (name, str(key), shape_json, str(run)))
            self.cache.commit()
            if seen != self.keys[name]:
                fail(f"La cobertura geométrica no coincide con las claves del dump: {name}")
            self.resolve_projects(name)

    def verify_domains(self):
        types = dict(self.rows("mline_tp_tipoparametro", ["id_tipo_parametro", "co_tipo_parametro"]))
        params = {}
        by_type = {}
        for key, type_id, label, weight in self.rows("mline_tp_parametro", ["id_parametro", "id_tipo_parametro", "no_valor_parametro", "nu_valor_numerico"]):
            params[key] = (types.get(type_id), label, weight)
            by_type.setdefault(types.get(type_id), {})[key] = str(label or key)
        for mapping in self.model.get("domain_fields", []):
            name, field, group = mapping["table"], mapping["field"], mapping["parameter_type"]
            values = by_type.get(group)
            if not values:
                fail(f"No hay parámetros para el dominio {group}")
            for (value,) in self.rows(name, [field]):
                if value is not None and value not in values:
                    fail(f"Valor fuera de dominio: {name}.{field} → {group}")
            self.domains[group] = values
        self.parameters = params
        for (key,) in self.rows("mline_td_proyecto_regla_cfg", ["id_valor_ponderacion"]):
            if key is not None and (key not in params or params[key][2] is None):
                fail("Hay ponderaciones referenciadas sin valor numérico; revisar antes de migrar.")
        existing = {d.name.lower() for d in self.a.da.ListDomains(self.dest)}
        for group in self.domains:
            if self.domain_name(group).lower() in existing:
                fail(f"Ya existe dominio destino {self.domain_name(group)}; revisar equivalencia antes de continuar.")

    @staticmethod
    def domain_name(group):
        return "mline_" + group.lower().replace(".", "_")

    def verify_portal_and_filters(self):
        required_layers = set()
        for rel in self.model.get("relations", []):
            if not rel.get("obsolete") and rel["parent"] == "mline_td_proyecto_capa":
                required_layers.update(v for (v,) in self.rows(rel["child"], [rel["child_key"]]) if v is not None)
        self.portal = self.cfg.get("portal_mappings", {})
        for key in self.keys["mline_td_proyecto_capa"]:
            item = self.portal.get(str(key))
            if not isinstance(item, dict):
                fail(f"Falta mapeo Portal para id_proyecto_capa {key}")
            if item.get("retired"):
                if key in required_layers or not item.get("reason"):
                    fail("No puede retirarse una capa aún usada por relaciones vigentes.")
                continue
            if not re.fullmatch(r"[0-9a-fA-F]{32}", item.get("item_id", "")):
                fail(f"item_id Portal no válido en capa {key}")
            if not isinstance(item.get("layer_id"), int) or item["layer_id"] < 0:
                fail(f"layer_id requerido para capa {key}")
            if not item.get("class_name") or len(item["class_name"]) > 128:
                fail(f"class_name inválido en capa {key}")
        self.filters = self.cfg.get("filter_mappings", {})
        for key, prop, old_code in self.rows("mline_td_proyecto_regla_cfg", ["id_proyecto_regla_cfg", "id_capa_propiedad", "co_capa_propiedad_filtro"]):
            if prop is None and not old_code:
                continue
            mapping = self.filters.get(str(key), {})
            field, path = mapping.get("field_name"), mapping.get("validation_path")
            if not field or len(field) > 128 or not path:
                fail(f"Falta campo físico y validation_path para la regla {key}")
            if field.lower() not in {f.name.lower() for f in self.a.ListFields(path)}:
                fail(f"El campo de evaluación no existe para la regla {key}")
            if not isinstance(mapping.get("filter_code"), str) or len(mapping["filter_code"]) > 64:
                fail(f"filter_code requerido y máximo 64 caracteres para regla {key}")
        self.warnings.append("Los identificadores Portal se verificaron por formato y cobertura; debe comprobarse su existencia y permisos en Portal antes de publicar.")

    def preflight(self):
        self.verify_connections()
        self.verify_targets_absent()
        self.verify_stage()
        self.verify_domains()
        self.verify_portal_and_filters()
        self.verify_geometries()

    def add_field(self, path, field):
        sql = field["sql_type"].lower()
        length = field.get("length")
        precision, scale = field.get("precision"), field.get("scale")
        if sql == "int":
            kind = "LONG"
        elif sql.startswith(("varchar", "nvarchar", "char", "nchar")) or sql in ("longtext", "text"):
            kind = "TEXT"
            if length is None:
                found = re.search(r"\((\d+)\)", sql)
                length = int(found[1]) if found else 10000
        elif sql.startswith("decimal"):
            found = re.search(r"\((\d+),(\d+)\)", sql)
            if found:
                precision, scale = map(int, found.groups())
            kind = "LONG" if scale == 0 and precision <= 9 else "DOUBLE"
        elif sql.startswith(("datetime", "date")):
            kind = "DATE"
        elif sql == "double":
            kind = "DOUBLE"
        else:
            fail(f"Tipo no soportado sin revisión: {sql}")
        self.a.management.AddField(path, field["name"], kind, field_precision=precision, field_scale=scale,
                                   field_length=length, field_is_nullable="NULLABLE" if field.get("nullable", True) else "NON_NULLABLE")

    def extra_fields(self, name):
        fields = []
        if self.tables[name].get("geometry_type"):
            fields.extend([
                {"name": "proyecto", "sql_type": "nvarchar(12)", "length": 12, "nullable": False},
                {"name": "id_analisis", "sql_type": "nvarchar(128)", "length": 128, "nullable": False},
                {"name": "id_origen", "sql_type": "nvarchar(128)", "length": 128},
                {"name": "fecha_carga", "sql_type": "datetime"},
                {"name": "fuente", "sql_type": "nvarchar(128)", "length": 128},
                {"name": "tema", "sql_type": "nvarchar(128)", "length": 128},
                {"name": "disciplina", "sql_type": "nvarchar(128)", "length": 128},
                {"name": "condicion", "sql_type": "nvarchar(128)", "length": 128},
                {"name": "componente", "sql_type": "nvarchar(256)", "length": 256},
                {"name": "alternativa", "sql_type": "nvarchar(256)", "length": 256},
                {"name": "nombre", "sql_type": "nvarchar(512)", "length": 512},
                {"name": "archivo_origen", "sql_type": "nvarchar(1024)", "length": 1024},
                {"name": "ruta_kml", "sql_type": "nvarchar(2048)", "length": 2048},
                {"name": "longitud_m", "sql_type": "double"},
                {"name": "area_ha", "sql_type": "double"},
            ])
        if name == "mline_td_proyecto_capa":
            fields.extend([
                {"name": "id_capa_arcgis", "sql_type": "nvarchar(32)", "length": 32},
                {"name": "id_subcapa_arcgis", "sql_type": "int"},
                {"name": "clase_destino", "sql_type": "nvarchar(128)", "length": 128},
            ])
        if name == "mline_td_proyecto_regla_cfg":
            fields.extend([
                {"name": "nombre_campo_evaluacion", "sql_type": "nvarchar(128)", "length": 128},
                {"name": "valor_ponderacion", "sql_type": "double"},
            ])
        return fields

    def create_schema(self):
        for dataset in ("Datos_Externos", "Datos_Internos", "Datos_Proyecto"):
            if not self.a.Exists(self.target_path(dataset)):
                self.a.management.CreateFeatureDataset(self.dest, dataset, self.a.SpatialReference(4326))
        for name, meta in self.tables.items():
            kind = meta.get("geometry_type")
            if kind:
                z, m = self.geometry_flags[name]
                self.a.management.CreateFeatureclass(self.target_path("Datos_Proyecto"), name, kind,
                    has_m="ENABLED" if m else "DISABLED", has_z="ENABLED" if z else "DISABLED",
                    spatial_reference=self.a.SpatialReference(4326))
            else:
                self.a.management.CreateTable(self.dest, name)
            for field in meta["fields"] + self.extra_fields(name):
                self.add_field(self.targets[name], field)

    def load_data(self):
        for name, meta in self.tables.items():
            fields = [f["name"] for f in meta["fields"]]
            extra = [f["name"] for f in self.extra_fields(name)]
            spatial = bool(meta.get("geometry_type"))
            insert_fields = fields + extra + (["SHAPE@"] if spatial else [])
            key_index = fields.index(self.pk(name))
            obsolete = set(self.model.get("obsolete_fields", {}).get(name, []))
            count = 0
            with self.a.da.InsertCursor(self.targets[name], insert_fields, explicit=True) as insert:
                for source_row in self.rows(name, fields):
                    values = list(source_row)
                    key = values[key_index]
                    for i, field in enumerate(fields):
                        if field in obsolete:
                            values[i] = None
                        elif isinstance(values[i], decimal.Decimal):
                            values[i] = float(values[i])
                    additions = []
                    shape = None
                    if spatial:
                        found = self.cache.execute("SELECT shape, analysis FROM geometry_cache WHERE tab=? AND pk=?", (name, str(key))).fetchone()
                        if found is None:
                            fail(f"Geometría validada desaparecida del caché: {name}")
                        shape = self.a.AsShape(json.loads(found[0]), True)
                        name_field = next((n for n in ("no_linea_transmision", "no_central_generacion", "co_infraestructura") if n in fields), None)
                        visible_name = source_row[fields.index(name_field)] if name_field else None
                        load_time = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
                        additions += [self.project_maps[name][key], found[1], str(key), load_time,
                                      "Mapline", None, None, None, None, None, visible_name, None, None,
                                      shape.getLength("GEODESIC", "METERS") if meta["geometry_type"] == "POLYLINE" else None,
                                      shape.getArea("GEODESIC", "HECTARES") if meta["geometry_type"] == "POLYGON" else None]
                    if name == "mline_td_proyecto_capa":
                        item = self.portal[str(key)]
                        additions += [item.get("item_id"), item.get("layer_id"), item.get("class_name")]
                    elif name == "mline_td_proyecto_regla_cfg":
                        mapping = self.filters.get(str(key), {})
                        if mapping:
                            values[fields.index("co_capa_propiedad_filtro")] = mapping["filter_code"]
                        parameter = source_row[fields.index("id_valor_ponderacion")]
                        weight = self.parameters[parameter][2] if parameter is not None else None
                        additions += [mapping.get("field_name"), float(weight) if weight is not None else None]
                    insert.insertRow(values + additions + ([shape] if spatial else []))
                    count += 1
            actual = int(self.a.management.GetCount(self.targets[name])[0])
            if actual != meta["rows"] or count != actual:
                fail(f"No coincide el conteo final en {name}")

    def verify_decimal_values(self):
        """Comprobar todos los decimales a la escala exacta declarada en origen."""
        for name, meta in self.tables.items():
            decimal_fields = []
            for field in meta["fields"]:
                match = re.fullmatch(r"decimal\((\d+),(\d+)\)", field["sql_type"].lower())
                if match:
                    decimal_fields.append((field["name"], int(match[2])))
            if not decimal_fields:
                continue
            fields = [self.pk(name)] + [field for field, _ in decimal_fields]
            expected = {row[0]: row[1:] for row in self.rows(name, fields)}
            checked = set()
            with self.a.da.SearchCursor(self.targets[name], fields) as cursor:
                for row in cursor:
                    key = row[0]
                    if key not in expected or key in checked:
                        fail(f"Claves no coincidentes en validación numérica: {name}")
                    checked.add(key)
                    for actual, original, (field, scale) in zip(row[1:], expected[key], decimal_fields):
                        if actual is None or original is None:
                            if actual is not None or original is not None:
                                fail(f"Cambio de nulos en {name}.{field}")
                            continue
                        quantum = decimal.Decimal(1).scaleb(-scale)
                        actual_decimal = decimal.Decimal(str(actual))
                        original_decimal = decimal.Decimal(str(original))
                        if (not actual_decimal.is_finite() or
                                actual_decimal.quantize(quantum) != original_decimal.quantize(quantum) or
                                abs(actual_decimal - original_decimal) > quantum / 2):
                            fail(f"Diferencia de precisión decimal en {name}.{field}; no se registrará branch.")
            if checked != set(expected):
                fail(f"Cobertura incompleta en la validación numérica de {name}")

    def verify_loaded_geometry(self):
        for name, meta in self.tables.items():
            if not meta.get("geometry_type"):
                continue
            seen = set()
            fields = [self.pk(name), "proyecto", "id_analisis", "id_origen", "SHAPE@"]
            with self.a.da.SearchCursor(self.targets[name], fields) as cursor:
                for key, project, analysis, origin, shape in cursor:
                    expected = self.cache.execute("SELECT analysis FROM geometry_cache WHERE tab=? AND pk=?", (name, str(key))).fetchone()
                    if (key in seen or key not in self.keys[name] or expected is None or
                            project != self.project_maps[name][key] or analysis != expected[0] or
                            origin != str(key) or shape is None or not shape.pointCount):
                        fail(f"La geometría o trazabilidad cargada no coincide: {name}")
                    seen.add(key)
            if seen != self.keys[name]:
                fail(f"Faltan claves espaciales cargadas: {name}")
            check = "memory/mapline_final_" + uuid.uuid4().hex
            try:
                self.a.management.CheckGeometry(self.targets[name], check, "ESRI")
                if int(self.a.management.GetCount(check)[0]):
                    fail(f"Geometría final no válida en {name}; no se registrará branch.")
            finally:
                if self.a.Exists(check):
                    self.a.management.Delete(check)

    def configure_domains_relations_versioning(self):
        for group, values in self.domains.items():
            domain = self.domain_name(group)
            self.a.management.CreateDomain(self.dest, domain, group, "LONG", "CODED")
            for code, label in values.items():
                self.a.management.AddCodedValueToDomain(self.dest, domain, code, label)
        for mapping in self.model.get("domain_fields", []):
            self.a.management.AssignDomainToField(self.targets[mapping["table"]], mapping["field"], self.domain_name(mapping["parameter_type"]))
        # Se conservan las claves de negocio, pero NO sus índices únicos SQL.
        # Esos índices impedirían registrar branch versioning.
        for name, meta in self.tables.items():
            self.a.management.AddIndex(self.targets[name], self.pk(name), "ix_mline_" + self.pk(name), "NON_UNIQUE")
            self.a.management.AddGlobalIDs(self.targets[name])
            self.a.management.EnableEditorTracking(self.targets[name], "gis_creador", "gis_fe_creacion",
                "gis_editor", "gis_fe_edicion", "ADD_FIELDS", "UTC")
        # Claves GUID adicionales para las relaciones GIS; las claves de negocio
        # originales siguen intactas. Se pueblan ANTES del registro branch.
        global_ids = {}
        for name in self.tables:
            gid = self.a.Describe(self.targets[name]).globalIDFieldName
            with self.a.da.SearchCursor(self.targets[name], [self.pk(name), gid]) as cursor:
                global_ids[name] = dict(cursor)
        for rel in self.model.get("relations", []):
            if rel.get("obsolete") or rel["parent"] == rel["child"]:
                continue
            child = self.targets[rel["child"]]
            foreign = "rel_" + rel["child_key"]
            if foreign.lower() not in {f.name.lower() for f in self.a.ListFields(child)}:
                self.a.management.AddField(child, foreign, "GUID")
            with self.a.da.UpdateCursor(child, [rel["child_key"], foreign]) as cursor:
                for row in cursor:
                    row[1] = global_ids[rel["parent"]].get(row[0]) if row[0] is not None else None
                    cursor.updateRow(row)
        project_ids = {}
        gid = self.a.Describe(self.targets["mline_tc_proyecto"]).globalIDFieldName
        with self.a.da.SearchCursor(self.targets["mline_tc_proyecto"], ["co_proyecto", gid]) as cursor:
            project_ids = {str(code).strip(): value for code, value in cursor}
        for name, meta in self.tables.items():
            if meta.get("geometry_type"):
                self.a.management.AddField(self.targets[name], "guid_proyecto", "GUID")
                with self.a.da.UpdateCursor(self.targets[name], ["proyecto", "guid_proyecto"]) as cursor:
                    for row in cursor:
                        row[1] = project_ids[row[0]]
                        cursor.updateRow(row)
        # Las autorreferencias se conservan como llaves de negocio validadas;
        # ArcGIS no admite una relationship class de una tabla consigo misma.
        # Registrar los 14 objetos antes de crear relaciones entre ellos evita
        # una combinación temporal de lados versionados y no versionados.
        self.a.management.RegisterAsVersioned(self.target_path("Datos_Proyecto"), "NO_EDITS_TO_BASE")
        for name, meta in self.tables.items():
            if not meta.get("geometry_type"):
                self.a.management.RegisterAsVersioned(self.targets[name], "NO_EDITS_TO_BASE")
        for name in self.tables:
            d = self.a.Describe(self.targets[name])
            if not getattr(d, "isBranchVersioned", False):
                fail(f"No se confirmó branch versioning en {name}; detener la publicación.")
        for rel in self.model.get("relations", []):
            if rel.get("obsolete") or rel["parent"] == rel["child"]:
                continue
            self.a.management.CreateRelationshipClass(self.targets[rel["parent"]], self.targets[rel["child"]],
                self.target_path("rc_" + rel["name"]), "SIMPLE", rel["child"], rel["parent"], "NONE",
                "ONE_TO_MANY", "NONE", self.a.Describe(self.targets[rel["parent"]]).globalIDFieldName,
                "rel_" + rel["child_key"])
        # Vínculo de negocio adicional de todas las FC con el código de proyecto.
        for name, meta in self.tables.items():
            if meta.get("geometry_type"):
                self.a.management.CreateRelationshipClass(self.targets["mline_tc_proyecto"], self.targets[name],
                    self.target_path("rc_proyecto_" + name), "SIMPLE", name, "Proyecto", "NONE",
                    "ONE_TO_MANY", "NONE", self.a.Describe(self.targets["mline_tc_proyecto"]).globalIDFieldName,
                    "guid_proyecto")

    def apply(self):
        self.create_schema()
        self.load_data()
        self.verify_decimal_values()
        self.verify_loaded_geometry()
        self.configure_domains_relations_versioning()
        self.report["applied"] = True
        self.warnings.append("Quedan fuera de esta carga los temas KMZ adicionales, su mapeo, recortes, simbología, servicios y publicación Portal.")
        self.warnings.append("Se verificaron los campos decimales contra staging a su escala de origen. El dato exacto permanece en staging SQL.")
        self.warnings.append("Los campos tema, disciplina, condición y procedencia KMZ quedan nulos cuando no existen en el dump. Sus dominios y valores requieren el mapeo temático; no se inventaron clasificaciones.")
        self.warnings.append("Se conservaron las autorreferencias alternativa/origen y regla/origen como campos validados; no se crean relationship classes recursivas. Las relaciones GIS usan GlobalID y GUID adicionales, conservando las claves de negocio.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--model", type=Path, default=Path(__file__).with_name("modelo_eft.json"))
    parser.add_argument("--apply", action="store_true", help="Crear y cargar solo después de superar todas las validaciones")
    parser.add_argument("--report", type=Path, default=Path("resultado_carga_arcgis.json"))
    args = parser.parse_args()
    try:
        import arcpy
    except ImportError:
        fail("Ejecute este script con el entorno Python de ArcGIS Pro; no se instala ArcPy por pip.")
    cfg = json.loads(args.config.read_text(encoding="utf-8-sig"))
    for key in ("portal_mappings", "filter_mappings"):
        cfg[key] = read_json(cfg.get(key), args.config.parent)
    model = json.loads(args.model.read_text(encoding="utf-8-sig"))
    with tempfile.TemporaryDirectory(prefix="mapline_carga_") as tmp:
        with sqlite3.connect(str(Path(tmp) / "geometries.sqlite")) as cache:
            loader = Loader(arcpy, model, cfg, cache)
            try:
                loader.preflight()
                if args.apply:
                    loader.apply()
                loader.report["status"] = "cargado" if args.apply else "validacion_previa_correcta_sin_cambios"
            except Exception as exc:
                loader.report["status"] = "fallo"
                loader.report["error"] = str(exc)
                loader.report["partial_load_possible"] = bool(args.apply)
                raise
            finally:
                loader.report["timestamp_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
                args.report.write_text(json.dumps(loader.report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Carga completada." if args.apply else "Validación previa correcta. No se modificó la geodatabase.")


if __name__ == "__main__":
    main()
