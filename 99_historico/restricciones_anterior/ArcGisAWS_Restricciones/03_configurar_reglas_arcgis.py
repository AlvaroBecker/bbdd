"""Configurar restricciones de las ocho tablas Mapline mediante ArcGIS.

Sin --apply solo inspecciona y emite un informe. No registra tablas, no cambia
identificadores de negocio, no crea PK/FK SQL ni índices únicos, no versiona y
no publica. --apply puede añadir GlobalID (campo de sistema), dominios y reglas
de restricción. Requiere tablas ya registradas con ObjectID independiente.

Las reglas consultan la vista de edición de ArcGIS. No equivalen a una PK SQL
atómica entre sesiones/versiones concurrentes; la conciliación y la política
de asignación de identificadores requieren controles operativos adicionales.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import sys


EXPECTED_TABLES = {
    "mline_tc_proyecto", "mline_ta_proyecto_estado",
    "mline_td_proyecto_componente", "mline_td_proyecto_capa",
    "mline_td_proyecto_regla_cfg", "mline_td_proyecto_alternativa",
    "mline_td_celda_capa", "mline_td_infraestructura_celda",
}
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def arcade_text(value):
    return json.dumps(str(value), ensure_ascii=False)


def sql_text(value):
    return "N'" + str(value).replace("'", "''") + "'"


def property_value(obj, name, default=None):
    return obj.get(name, default) if isinstance(obj, dict) else getattr(obj, name, default)


def normalized_events(value):
    if isinstance(value, (list, tuple, set)):
        value = ";".join(map(str, value))
    return tuple(sorted(set(re.findall(r"INSERT|UPDATE|DELETE", str(value).upper()))))


def expression_text(value):
    return str(value).replace("\r\n", "\n").strip()


@dataclass(frozen=True)
class Rule:
    table: str
    name: str
    expression: str
    events: tuple[str, ...]
    error_number: int
    message: str
    description: str
    kind: str


def make_rule(prefix, table, identity, expression, events, message, kind):
    fingerprint = hashlib.sha256((table + "|" + identity).encode("utf-8")).hexdigest()
    short = (prefix + "_" + kind + "_" + table.removeprefix("mline_"))[:48]
    return Rule(table, short + "_" + fingerprint[:10], expression.strip(), tuple(events),
                200000 + int(fingerprint[:8], 16) % 700000,
                message[:256], "Mapline EFT: restricción lógica ArcGIS; no es una PK/FK SQL.", kind)


def qualified(manifest, table):
    return f"{manifest['database']}.{manifest['owner']}.{table}"


def primary_rule(manifest, table, key, gid):
    full = qualified(manifest, table)
    expression = f"""var keyValue = $feature[{arcade_text(key)}];
if (IsEmpty(keyValue)) {{ return false; }}
var currentGuid = $feature[{arcade_text(gid)}];
var rows = FeatureSetByName($datastore, {arcade_text(full)}, [{arcade_text(key)}, {arcade_text(gid)}], false);
if (IsEmpty(currentGuid)) {{
    return Count(Filter(rows, {arcade_text(key + ' = @keyValue')})) == 0;
}}
return Count(Filter(rows, {arcade_text(key + ' = @keyValue AND ' + gid + ' <> @currentGuid')})) == 0;"""
    return make_rule(manifest.get("rules_prefix", "mline"), table, "pk:" + key, expression,
                     ("INSERT", "UPDATE"), f"{key} es obligatorio y no puede repetirse en la vista de edición.", "pk")


def foreign_rules(manifest, relation, gids):
    parent, child = relation["parent"], relation["child"]
    pkey, ckey = relation["parent_key"], relation["child_key"]
    recursive = parent == child
    gid = gids[parent]
    fields = [pkey] + ([gid] if recursive else [])
    condition = pkey + " = @parentValue"
    self_check = ""
    if recursive:
        self_check = f"""if (parentValue == $feature[{arcade_text(pkey)}]) {{ return true; }}
var currentGuid = $feature[{arcade_text(gid)}];
"""
        condition += " AND " + gid + " <> @currentGuid"
    lookup = f"""var parentValue = $feature[{arcade_text(ckey)}];
if (IsEmpty(parentValue)) {{ return true; }}
{self_check}var parents = FeatureSetByName($datastore, {arcade_text(qualified(manifest, parent))}, {json.dumps(fields)}, false);
{('if (IsEmpty(currentGuid)) { return Count(Filter(parents, ' + arcade_text(pkey + ' = @parentValue') + ')) > 0; }') if recursive else ''}
return Count(Filter(parents, {arcade_text(condition)})) > 0;"""
    children_fields = [ckey] + ([gid] if recursive else [])
    child_condition = ckey + " = @oldValue"
    exclusion = ""
    if recursive:
        exclusion = f"var currentGuid = $feature[{arcade_text(gid)}];\n"
        child_condition += " AND " + gid + " <> @currentGuid"
    protection = f"""var editType = Upper($editcontext.editType);
var oldValue = $feature[{arcade_text(pkey)}];
if (editType == 'UPDATE') {{
    oldValue = $originalFeature[{arcade_text(pkey)}];
    if ($feature[{arcade_text(pkey)}] == oldValue) {{ return true; }}
}}
if (IsEmpty(oldValue)) {{ return true; }}
{exclusion}var children = FeatureSetByName($datastore, {arcade_text(qualified(manifest, child))}, {json.dumps(children_fields)}, false);
return Count(Filter(children, {arcade_text(child_condition)})) == 0;"""
    prefix = manifest.get("rules_prefix", "mline")
    identity = relation["name"]
    return (
        make_rule(prefix, child, "fk:" + identity, lookup, ("INSERT", "UPDATE"),
                  f"{ckey} debe existir en {parent}.{pkey}, o ser nulo.", "fk"),
        make_rule(prefix, parent, "protect:" + identity, protection, ("UPDATE", "DELETE"),
                  f"No puede borrar o cambiar {pkey}: existen referencias en {child}.{ckey}.", "ref"),
    )


def build_rule_plan(manifest, gid_fields):
    rules = []
    table_map = {table["name"]: table for table in manifest["tables"]}
    for name, table in sorted(table_map.items()):
        rules.append(primary_rule(manifest, name, table["primary_key"][0], gid_fields[name]))
    for relation in sorted(manifest["relations"], key=lambda rel: rel["name"]):
        if relation.get("obsolete") or relation.get("treatment") != "arcgis_constraint":
            continue
        require(relation["parent"] in table_map and relation["child"] in table_map,
                f"Relación fuera de alcance marcada activa: {relation['name']}")
        require(relation.get("on_delete", "NO_ACTION") == "NO_ACTION" and relation.get("on_update", "NO_ACTION") == "NO_ACTION",
                "Este paquete solo implementa relaciones NO ACTION.")
        rules.extend(foreign_rules(manifest, relation, gid_fields))
    for mapping in sorted(manifest.get("domain_fields", []), key=lambda item: (item["table"], item["field"])):
        table, field, group = mapping["table"], mapping["field"], mapping["parameter_type"]
        codes = sorted(int(code) for code in manifest["domain_codes"][group])
        nullable = next(f for f in table_map[table]["fields"] if f["name"] == field).get("nullable", True)
        expression = (f"var value = $feature[{arcade_text(field)}];\n"
                      f"if (IsEmpty(value)) {{ return {'true' if nullable else 'false'}; }}\n"
                      f"return IndexOf({json.dumps(codes)}, value) >= 0;")
        rules.append(make_rule(manifest.get("rules_prefix", "mline"), table, "domain:" + field + ":" + group,
                     expression, ("INSERT", "UPDATE"), f"{field} debe pertenecer al dominio {group}.", "dom"))
    if manifest.get("enforce_obsolete_null", False):
        for table, fields in sorted(manifest.get("obsolete_fields", {}).items()):
            if table not in table_map:
                continue
            for field in sorted(fields):
                rules.append(make_rule(manifest.get("rules_prefix", "mline"), table, "obsolete:" + field,
                             f"return IsEmpty($feature[{arcade_text(field)}]);", ("INSERT", "UPDATE"),
                             f"{field} es una referencia retirada por el EFT y debe quedar nula.", "old"))
    return sorted(rules, key=lambda rule: (rule.table, rule.name))


def rules_equivalent(existing, planned):
    """No sobrescribir reglas con el mismo nombre y una definición distinta."""
    subtype_codes = property_value(existing, "subtypeCodes", []) or []
    all_subtypes = not subtype_codes or set(subtype_codes) == {-1}
    subtype_code = property_value(existing, "subtypeCode", -1)
    checks = {
        "type": property_value(existing, "type") == "esriARTConstraint",
        "expression": expression_text(property_value(existing, "scriptExpression", "")) == expression_text(planned.expression),
        "events": normalized_events(property_value(existing, "triggeringEvents", "")) == tuple(sorted(planned.events)),
        "enabled": property_value(existing, "isEnabled", False) is True,
        "exclude": property_value(existing, "excludeFromClientEvaluation", False) is True,
        "batch": property_value(existing, "batch", False) is False,
        "all_fields": not property_value(existing, "triggeringFields", []),
        "subtypes": all_subtypes and subtype_code in (None, -1),
        "error_number": str(property_value(existing, "errorNumber", "")) == str(planned.error_number),
        "error_message": property_value(existing, "errorMessage", "") == planned.message,
        "description": property_value(existing, "description", "") == planned.description,
    }
    return [key for key, value in checks.items() if not value]


class Configurator:
    def __init__(self, arcpy, connection, manifest, report):
        self.a = arcpy
        self.connection = str(connection)
        self.manifest = manifest
        self.report = report
        self.tables = {table["name"]: table for table in manifest["tables"]}
        self.paths = {name: os.path.join(self.connection, qualified(manifest, name)) for name in self.tables}
        self.fields = {}
        self.gids = {}
        self.keys = {}
        self.values = {}
        self.domains_to_add = {}
        self.domain_assignments = []
        self.rules_to_add = []

    def validate_manifest(self):
        require(self.manifest.get("database") == "ArcGisAWS" and self.manifest.get("owner") == "gis",
                "Este paquete requiere exactamente la base ArcGisAWS y propietario gis.")
        require(set(self.tables) == EXPECTED_TABLES and len(self.manifest["tables"]) == 8,
                "El manifiesto debe contener exactamente las ocho tablas del alcance.")
        for name, table in self.tables.items():
            require(IDENTIFIER.fullmatch(name), "Nombre de tabla no válido.")
            require(len(table["primary_key"]) == 1, f"Clave compuesta no soportada en {name}.")
            known = {field["name"] for field in table["fields"]}
            require(all(IDENTIFIER.fullmatch(field) for field in known), "Nombre de campo no válido.")
            require(table["primary_key"][0] in known, f"Clave no definida en {name}.")
        for relation in self.manifest.get("relations", []):
            require(all(IDENTIFIER.fullmatch(relation[field]) for field in ("name", "parent", "child", "parent_key", "child_key")),
                    "Nombre no válido en una relación.")
        for group, codes in self.manifest.get("domain_codes", {}).items():
            require(bool(codes), f"Dominio sin códigos: {group}")
            require(all(re.fullmatch(r"-?\d+", key) and -2147483648 <= int(key) <= 2147483647 for key in codes),
                    f"Código no entero de 32 bits en {group}.")

    def sql_rows(self, statement):
        result = self.a.ArcSDESQLExecute(self.connection).execute(statement)
        return result if isinstance(result, list) else []

    def verify_connection(self):
        require(self.a.Exists(self.connection), "La conexión .sde no existe o no es accesible.")
        desc = self.a.Describe(self.connection)
        require(desc.workspaceType == "RemoteDatabase", "Se requiere una geodatabase empresarial.")
        properties = desc.connectionProperties
        require(str(getattr(properties, "database", "")).lower() == "arcgisaws", "La conexión no apunta a ArcGisAWS.")
        info = self.sql_rows("SELECT DB_NAME(), USER_NAME(), SCHEMA_NAME()")
        require(bool(info) and str(info[0][0]).lower() == "arcgisaws" and
                str(info[0][1]).lower() == "gis" and str(info[0][2]).lower() == "gis",
                "La conexión debe ser del propietario gis con esquema predeterminado gis.")
        # No se altera la propiedad Branch, ni se registra el versionado.
        self.report["connection_versioning"] = "BRANCH" if hasattr(properties, "branch") else "no_branch_connection"
        self.a.env.overwriteOutput = False

    def verify_tables(self):
        for name, meta in self.tables.items():
            path = self.paths[name]
            require(self.a.Exists(path), f"Falta la tabla {qualified(self.manifest, name)}.")
            desc = self.a.Describe(path)
            require(desc.dataType == "Table" and hasattr(desc, "hasGlobalID") and getattr(desc, "hasOID", False),
                    f"Registre {name} con la geodatabase y asigne un ObjectID administrado por ArcGIS antes de configurar reglas.")
            key = meta["primary_key"][0]
            require(desc.OIDFieldName.lower() != key.lower(), f"{name}: el identificador de negocio no puede ser el ObjectID de ArcGIS.")
            self.fields[name] = {field.name.lower(): field for field in self.a.ListFields(path)}
            require(all(field["name"].lower() in self.fields[name] for field in meta["fields"]), f"Faltan campos de origen en {name}.")
            require(self.fields[name][key.lower()].type in ("Integer", "SmallInteger", "BigInteger"), f"El identificador de negocio {name}.{key} debe ser numérico entero.")
            gid = getattr(desc, "globalIDFieldName", "") if getattr(desc, "hasGlobalID", False) else "GlobalID"
            if not getattr(desc, "hasGlobalID", False):
                require(gid.lower() not in self.fields[name], f"{name} tiene un campo llamado GlobalID que no es el GlobalID del sistema; revisar registro.")
                self.report["globalids_to_add"].append(name)
            self.gids[name] = gid
            allowed_unique = {desc.OIDFieldName.lower()}
            if getattr(desc, "hasGlobalID", False):
                allowed_unique.add(gid.lower())
            for index in self.a.ListIndexes(path):
                if index.isUnique:
                    fields = {field.name.lower() for field in index.fields}
                    require(bool(fields) and fields.issubset(allowed_unique),
                            f"{name}: índice único de negocio {index.name}; debe resolverse con el administrador antes de branch. Este script no lo elimina.")
            if getattr(desc, "isVersioned", False) and not getattr(desc, "isBranchVersioned", False):
                self.report["warnings"].append(f"{name} usa versionado tradicional; este script no lo convierte a branch.")
            self.report["tables"].append({"name": name, "oid_field": desc.OIDFieldName,
                                          "has_globalid": bool(getattr(desc, "hasGlobalID", False)),
                                          "branch_versioned": bool(getattr(desc, "isBranchVersioned", False))})
        # Leer solamente el catálogo SQL: no ejecutar ALTER/DROP/UPDATE.
        names = ",".join(sql_text(name) for name in sorted(self.tables))
        foreign = self.sql_rows("SELECT p.name, f.name, r.name FROM sys.foreign_keys f "
            "JOIN sys.tables p ON p.object_id=f.parent_object_id JOIN sys.tables r ON r.object_id=f.referenced_object_id "
            f"WHERE (p.schema_id=SCHEMA_ID(N'gis') AND p.name IN ({names})) OR "
            f"(r.schema_id=SCHEMA_ID(N'gis') AND r.name IN ({names}))")
        require(not foreign, "Existen claves foráneas físicas SQL sobre las tablas objetivo; no se modifican. Revisar antes de aplicar reglas ArcGIS.")

    def rows(self, table, fields):
        with self.a.da.SearchCursor(self.paths[table], fields) as cursor:
            yield from cursor

    def verify_data(self):
        for name, meta in self.tables.items():
            required_fields = {meta["primary_key"][0]}
            required_fields.update(mapping["field"] for mapping in self.manifest.get("domain_fields", []) if mapping["table"] == name)
            required_fields.update(relation["child_key"] for relation in self.manifest.get("relations", []) if relation["child"] == name)
            if self.manifest.get("enforce_obsolete_null", False):
                required_fields.update(self.manifest.get("obsolete_fields", {}).get(name, []))
            fields = sorted(required_fields)
            seen = set()
            global_seen = set()
            has_gid = self.gids[name].lower() in self.fields[name]
            if has_gid:
                fields.append(self.gids[name])
            aggregates = {field: set() for field in fields}
            for row in self.rows(name, fields):
                data = dict(zip(fields, row))
                key = data[meta["primary_key"][0]]
                require(key is not None and key not in seen, f"{name}: identificador de negocio nulo o repetido. No se aplicó ninguna regla.")
                seen.add(key)
                if has_gid:
                    gid = data[self.gids[name]]
                    require(bool(gid) and str(gid).upper() not in global_seen,
                            f"{name}: GlobalID nulo o repetido; revisar la geodatabase antes de configurar reglas.")
                    global_seen.add(str(gid).upper())
                for field, value in data.items():
                    aggregates[field].add(value)
            self.keys[name] = seen
            self.values[name] = aggregates
            self.report["data_counts"][name] = len(seen)
        for relation in self.manifest.get("relations", []):
            treatment = relation.get("treatment", "")
            if treatment == "arcgis_constraint" and not relation.get("obsolete"):
                parent, child = relation["parent"], relation["child"]
                require(parent in self.tables and child in self.tables, "Relación activa fuera de las ocho tablas.")
                values = self.values[child][relation["child_key"]] - {None}
                require(values.issubset(self.keys[parent]), f"Referencia huérfana: {relation['name']}. Resolver los datos antes de configurar reglas.")
            elif treatment.startswith("pending_"):
                item = {"relation": relation["name"], "reason": treatment, "rules_applied": False}
                if treatment == "pending_spatial_parent":
                    path = os.path.join(self.connection, qualified(self.manifest, relation["parent"]))
                    if self.a.Exists(path):
                        with self.a.da.SearchCursor(path, [relation["parent_key"]]) as cursor:
                            parent_ids = {row[0] for row in cursor}
                        require((self.values[relation["child"]][relation["child_key"]] - {None}).issubset(parent_ids),
                                f"Referencia espacial huérfana: {relation['name']}")
                        item["existing_data_checked"] = True
                    else:
                        item["existing_data_checked"] = False
                self.report["deferred_dependencies"].append(item)
        for relation in self.manifest.get("deferred_incoming_relations", []):
            item = {"relation": relation["name"], "reason": "pending_spatial_child_delete_update_protection",
                    "rules_applied": False, "parent": relation["parent"], "child": relation["child"]}
            child_path = os.path.join(self.connection, qualified(self.manifest, relation["child"]))
            if self.a.Exists(child_path) and relation["parent"] in self.keys:
                with self.a.da.SearchCursor(child_path, [relation["child_key"]]) as cursor:
                    foreign_ids = {row[0] for row in cursor} - {None}
                require(foreign_ids.issubset(self.keys[relation["parent"]]),
                        f"Referencia espacial entrante huérfana: {relation['name']}")
                item["existing_data_checked"] = True
            else:
                item["existing_data_checked"] = False
            self.report["deferred_dependencies"].append(item)
        if self.manifest.get("enforce_obsolete_null", False):
            for name, fields in self.manifest.get("obsolete_fields", {}).items():
                if name not in self.tables:
                    continue
                for field in fields:
                    require(not (self.values[name][field] - {None}),
                            f"El EFT exige retirar {name}.{field}, pero conserva valores. Revisar la migración; este script no los vacía.")

    def verify_domains(self):
        existing = {domain.name.lower(): domain for domain in self.a.da.ListDomains(self.connection)}
        assignments = set()
        for mapping in self.manifest.get("domain_fields", []):
            table, field, group = mapping["table"], mapping["field"], mapping["parameter_type"]
            require(group in self.manifest["domain_codes"], f"Falta snapshot de códigos de {group}")
            codes = {int(code): str(label) for code, label in self.manifest["domain_codes"][group].items()}
            require((self.values[table][field] - {None}).issubset(codes), f"Valores fuera del dominio {table}.{field} → {group}")
            native_field = self.fields[table][field.lower()]
            require(native_field.type == "Integer", f"El campo {table}.{field} debe ser LONG para conservar códigos de parámetro.")
            desired = mapping.get("domain_name", "mline_" + group.lower().replace(".", "_"))
            assigned = native_field.domain
            chosen = assigned or desired
            domain = existing.get(chosen.lower())
            if domain is not None:
                require(domain.domainType == "CodedValue" and domain.type in ("Integer", "Long") and
                        dict(domain.codedValues) == codes,
                        f"El dominio existente {chosen} no equivale al snapshot de {group}; no se sobrescribe.")
            else:
                require(not assigned, f"El campo apunta a un dominio no accesible: {assigned}")
                if chosen in self.domains_to_add:
                    require(self.domains_to_add[chosen]["codes"] == codes, "Colisión de nombres de dominio.")
                self.domains_to_add[chosen] = {"group": group, "codes": codes}
            # Los subtipos pueden imponer un dominio distinto al del campo.
            for subtype in self.a.da.ListSubtypes(self.paths[table]).values():
                values = subtype.get("FieldValues", {}).get(field)
                subtype_domain = values[1] if values else None
                if subtype_domain is not None:
                    require(subtype_domain.domainType == "CodedValue" and subtype_domain.type in ("Integer", "Long") and
                            dict(subtype_domain.codedValues) == codes,
                            f"Un subtipo usa un dominio incompatible en {table}.{field}.")
            if not assigned and (table, field, chosen) not in assignments:
                assignments.add((table, field, chosen))
                self.domain_assignments.append((table, field, chosen))
        self.report["domains_to_add"] = sorted(self.domains_to_add)
        self.report["domain_assignments"] = [list(item) for item in self.domain_assignments]

    def verify_rules(self):
        planned = build_rule_plan(self.manifest, self.gids)
        existing_by_table = {}
        for name in self.tables:
            existing_by_table[name] = {property_value(rule, "name"): rule for rule in
                                       (getattr(self.a.Describe(self.paths[name]), "attributeRules", []) or [])}
        for rule in planned:
            existing = existing_by_table[rule.table].get(rule.name)
            if existing is not None:
                differences = rules_equivalent(existing, rule)
                require(not differences, f"Regla {rule.name} existente con diferencias ({', '.join(differences)}); no se modifica.")
                self.report["rules_preserved"].append(rule.name)
            else:
                self.rules_to_add.append(rule)
        self.report["rules_to_add"] = [asdict(rule) for rule in self.rules_to_add]

    def preflight(self):
        self.validate_manifest()
        self.verify_connection()
        self.verify_tables()
        self.verify_data()
        self.verify_domains()
        self.verify_rules()

    def apply(self):
        # Comprobar todos los bloqueos necesarios antes de la primera mutacion.
        affected = set(self.report["globalids_to_add"])
        affected.update(table for table, _, _ in self.domain_assignments)
        affected.update(rule.table for rule in self.rules_to_add)
        self.report["schema_locks"] = {name: bool(self.a.TestSchemaLock(self.paths[name])) for name in sorted(affected)}
        require(all(self.report["schema_locks"].values()),
                "Hay bloqueos de esquema. Cierre tablas, sesiones de edicion o servicios afectados y vuelva a validar; no se aplico ningun cambio.")
        self.report["mutations_attempted"] = True
        for name in self.report["globalids_to_add"]:
            self.a.management.AddGlobalIDs(self.paths[name])
            desc = self.a.Describe(self.paths[name])
            require(desc.hasGlobalID and desc.globalIDFieldName.lower() == self.gids[name].lower(),
                    f"No se creó el GlobalID previsto en {name}; detener y revisar.")
            self.report["actions_completed"].append({"action": "AddGlobalIDs", "table": name})
        for name, domain in self.domains_to_add.items():
            self.a.management.CreateDomain(self.connection, name, domain["group"], "LONG", "CODED")
            self.report["actions_completed"].append({"action": "CreateDomain", "domain": name})
            for code, label in sorted(domain["codes"].items()):
                self.a.management.AddCodedValueToDomain(self.connection, name, code, label)
                self.report["actions_completed"].append({"action": "AddCodedValueToDomain", "domain": name, "code": code})
        for table, field, domain in self.domain_assignments:
            self.a.management.AssignDomainToField(self.paths[table], field, domain)
            self.report["actions_completed"].append({"action": "AssignDomainToField", "table": table, "field": field, "domain": domain})
        for rule in self.rules_to_add:
            self.a.management.AddAttributeRule(
                in_table=self.paths[rule.table], name=rule.name, type="CONSTRAINT",
                script_expression=rule.expression, triggering_events=";".join(rule.events),
                error_number=str(rule.error_number), error_message=rule.message,
                description=rule.description, exclude_from_client_evaluation="EXCLUDE",
                batch="NOT_BATCH", tags="Mapline;EFT;Integridad")
            self.report["actions_completed"].append({"action": "AddAttributeRule", "table": rule.table, "rule": rule.name})
        # Leer la definición efectivamente almacenada; no reescribirla si difiere.
        for name in self.tables:
            stored = {property_value(rule, "name"): rule for rule in
                      (getattr(self.a.Describe(self.paths[name]), "attributeRules", []) or [])}
            for planned in build_rule_plan(self.manifest, self.gids):
                if planned.table == name:
                    require(planned.name in stored and not rules_equivalent(stored[planned.name], planned),
                            f"No se confirmó la regla almacenada {planned.name}.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--connection", required=True, type=Path, help="Conexión ArcGIS .sde del propietario gis a ArcGisAWS")
    parser.add_argument("--manifest", type=Path, default=Path(__file__).with_name("modelo_restricciones.json"))
    parser.add_argument("--report", type=Path, default=Path("resultado_reglas_arcgis.json"))
    parser.add_argument("--apply", action="store_true", help="Añadir GlobalIDs, dominios y reglas después de validar")
    args = parser.parse_args()
    report = {"status": "iniciado", "applied": False, "tables": [], "data_counts": {}, "globalids_to_add": [],
              "domains_to_add": [], "domain_assignments": [], "rules_to_add": [], "rules_preserved": [],
              "deferred_dependencies": [], "actions_completed": [],
              "warnings": [
                  "Estas restricciones se evalúan en ArcGIS; no protegen escrituras SQL directas que omitan la geodatabase.",
                  "La unicidad y referencias se comprueban en la vista de edición. No son restricciones SQL atómicas entre sesiones/versiones concurrentes; validar en conciliación e integración.",
                  "Las reglas que consultan otras tablas requieren que todas sean accesibles en el mismo servicio al publicar; validar con el usuario de servicio.",
                  "Las dependencias espaciales y el mapeo de Portal diferidos impiden declarar el modelo completo protegido.",
                  "Las autorreferencias conservan semántica NO ACTION con exclusión de la propia fila; probar INSERT/UPDATE/DELETE recursivos en el servicio antes de habilitar edición.",
                  "No se cambia el mecanismo de asignación de identificadores ni se añade generación automática de IDs.",
              ]}
    try:
        import arcpy
        manifest_bytes = args.manifest.read_bytes()
        manifest = json.loads(manifest_bytes.decode("utf-8-sig"))
        report["manifest_sha256"] = hashlib.sha256(manifest_bytes).hexdigest()
        runner = Configurator(arcpy, args.connection, manifest, report)
        runner.preflight()
        if args.apply:
            runner.apply()
            report["applied"] = True
        report["status"] = "configuracion_parcial_del_modelo_aplicada" if args.apply else "validacion_previa_correcta_sin_cambios"
        print("Configuración aplicada a las ocho tablas; consultar dependencias diferidas." if args.apply else
              "Validación previa correcta. No se modificó la geodatabase. Revisar el informe antes de usar --apply.")
    except ImportError as exc:
        report["status"] = "fallo"
        report["error"] = "Ejecute con el entorno Python de ArcGIS Pro; ArcPy no está disponible."
        print(report["error"], file=sys.stderr)
        raise SystemExit(1) from exc
    except Exception as exc:
        report["status"] = "fallo"
        report["error"] = str(exc)
        report["partial_changes_possible"] = bool(report.get("mutations_attempted", False))
        print("Error: " + str(exc) + ". Revisar el informe; no se ejecuta eliminación o reversión automática.", file=sys.stderr)
        raise SystemExit(1) from exc
    finally:
        report["timestamp_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
