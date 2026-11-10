"""Configurar los ocho dominios de parámetros definidos en el EFT de Mapline.

Sin --apply, valida y guarda el plan sin modificar la geodatabase. Con --apply
crea dominios codificados LONG, incorpora los 28 códigos históricos y asigna
dominios a los diez campos previstos. Conserva valores y nulabilidad.

Requiere ArcGIS Pro y conexión del propietario gis a ArcGisAWS. Las ocho tablas
deben estar previamente registradas con la geodatabase. Este script se limita
a dominios; no implementa integridad referencial o restricciones SQL.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import sys


TABLES = {
    "mline_tc_proyecto", "mline_ta_proyecto_estado",
    "mline_td_proyecto_componente", "mline_td_proyecto_capa",
    "mline_td_proyecto_regla_cfg", "mline_td_proyecto_alternativa",
    "mline_td_celda_capa", "mline_td_infraestructura_celda",
}
FIELD_GROUPS = {
    ("mline_tc_proyecto", "id_tipo_proyecto"): "PROYECTO.TIPO",
    ("mline_tc_proyecto", "id_estado_proyecto"): "PROYECTO.ESTADO",
    ("mline_ta_proyecto_estado", "id_estado_proyecto_inicial"): "PROYECTO.ESTADO",
    ("mline_ta_proyecto_estado", "id_estado_proyecto_final"): "PROYECTO.ESTADO",
    ("mline_td_proyecto_componente", "id_estado_componente"): "PROYECTO.COMPONENTE.ESTADO",
    ("mline_td_proyecto_alternativa", "id_estado_alternativa"): "PROYECTO.ALTERNATIVA.ESTADO",
    ("mline_td_proyecto_alternativa", "id_tipo_fuente_infraestructura"): "PROYECTO.ALTERNATIVA.FUENTE",
    ("mline_td_proyecto_regla_cfg", "id_estado_regla_cfg"): "PROYECTO.REGLA_CFG.ESTADO",
    ("mline_td_proyecto_regla_cfg", "id_tipo_funcion_espacial"): "PROYECTO.REGLA_CFG.FUNCION_ESPACIAL",
    ("mline_td_proyecto_regla_cfg", "id_valor_ponderacion"): "PROYECTO.REGLA_CFG.PONDERACION",
}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def domain_name(group):
    return "ML_" + group.replace(".", "_")


def build_plan(manifest):
    """Plan puro: no importa ArcPy, no lee la base y no filtra códigos históricos."""
    require(manifest.get("database") == "ArcGisAWS" and manifest.get("owner") == "gis",
            "El manifiesto debe identificar ArcGisAWS y propietario gis.")
    require(len(manifest.get("tables", [])) == 8 and
            {table["name"] for table in manifest["tables"]} == TABLES,
            "El alcance debe contener exactamente las ocho tablas del EFT.")
    mappings = manifest.get("domain_fields", [])
    actual = {(item["table"], item["field"]): item["parameter_type"] for item in mappings}
    require(len(mappings) == 10 and actual == FIELD_GROUPS,
            "El manifiesto debe contener exactamente los diez campos y sus grupos de parámetros del EFT.")
    snapshots = manifest.get("domain_codes", {})
    require(set(snapshots) == set(FIELD_GROUPS.values()), "Deben existir exactamente los ocho grupos de dominio.")
    definitions = {}
    all_codes = set()
    for group, raw_codes in sorted(snapshots.items()):
        require(isinstance(raw_codes, dict) and bool(raw_codes), f"Snapshot vacío o inválido: {group}")
        codes = {}
        for code, label in raw_codes.items():
            require(isinstance(code, str) and re.fullmatch(r"-?\d+", code), f"Código no entero en {group}")
            number = int(code)
            require(-2147483648 <= number <= 2147483647 and number not in codes,
                    f"Código duplicado o fuera del rango LONG en {group}")
            require(isinstance(label, str) and 0 < len(label) <= 255,
                    f"La etiqueta de un código de {group} debe tener de 1 a 255 caracteres.")
            require(number not in all_codes, "Un id_parametro aparece en más de un grupo del snapshot.")
            codes[number] = label
            all_codes.add(number)
        definitions[group] = {"group": group, "name": domain_name(group), "codes": codes}
    require(len(definitions) == 8 and sum(len(item["codes"]) for item in definitions.values()) == 28,
            "El snapshot esperado contiene ocho dominios y 28 códigos históricos.")
    return {"domains": definitions, "fields": [
        {"table": table, "field": field, "group": group, "domain": domain_name(group)}
        for (table, field), group in sorted(FIELD_GROUPS.items())
    ]}


def equivalent_domain(actual, expected):
    return (actual.get("kind") == "CodedValue" and actual.get("type") in ("Integer", "Long") and
            actual.get("codes") == expected["codes"])


def resolve_existing(plan, native_domains, field_states):
    """Resolver conflictos antes de cualquier cambio; preservar dominios equivalentes."""
    existing = {name.casefold(): value for name, value in native_domains.items()}
    creations = {}
    assignments, preserved = [], []
    for definition in plan["domains"].values():
        found = existing.get(definition["name"].casefold())
        require(found is None or equivalent_domain(found, definition),
                f"El dominio existente {definition['name']} difiere en tipo, códigos o etiquetas; no se sobrescribe.")
    for mapping in plan["fields"]:
        key = (mapping["table"], mapping["field"])
        state = field_states[key]
        require(state["type"] == "Integer", f"{key[0]}.{key[1]} debe ser INT/LONG.")
        expected = plan["domains"][mapping["group"]]
        assigned = state.get("domain") or ""
        if assigned:
            found = existing.get(assigned.casefold())
            require(found is not None and equivalent_domain(found, expected),
                    f"El campo {key[0]}.{key[1]} tiene un dominio asignado incompatible; no se reemplaza.")
            preserved.append({**mapping, "assigned_domain": assigned,
                              "reason": "dominio existente equivalente"})
            continue
        found = existing.get(expected["name"].casefold())
        chosen = found["name"] if found else expected["name"]
        assignments.append({**mapping, "domain": chosen})
        if found is None:
            creations[expected["name"]] = expected
    return {"create_domains": list(creations.values()), "assign_fields": assignments,
            "preserve_fields": preserved}


class DomainConfigurator:
    def __init__(self, arcpy, connection, manifest, report):
        self.a = arcpy
        self.connection = str(connection)
        self.manifest = manifest
        self.report = report
        self.paths = {name: os.path.join(self.connection, "ArcGisAWS.gis." + name) for name in TABLES}
        self.plan = build_plan(manifest)
        self.field_states = {}
        self.resolved = None

    def inspect_domains(self):
        return {domain.name: {"name": domain.name, "kind": domain.domainType, "type": domain.type,
                             "codes": dict(domain.codedValues) if domain.domainType == "CodedValue" else {}}
                for domain in self.a.da.ListDomains(self.connection)}

    def verify_connection_and_tables(self):
        require(self.a.Exists(self.connection), "La conexión .sde no existe o no es accesible.")
        desc = self.a.Describe(self.connection)
        require(desc.workspaceType == "RemoteDatabase", "Se requiere una geodatabase empresarial.")
        require(str(getattr(desc.connectionProperties, "database", "")).casefold() == "arcgisaws",
                "La conexión debe apuntar a ArcGisAWS.")
        # Consulta de identificación solamente; no ejecuta SQL DDL ni DML.
        result = self.a.ArcSDESQLExecute(self.connection).execute("SELECT DB_NAME(), USER_NAME(), SCHEMA_NAME()")
        require(isinstance(result, list) and bool(result) and
                tuple(str(value).casefold() for value in result[0]) == ("arcgisaws", "gis", "gis"),
                "Conéctese como el propietario de base de datos gis, con esquema predeterminado gis.")
        for name, path in sorted(self.paths.items()):
            require(self.a.Exists(path), f"Falta ArcGisAWS.gis.{name}.")
            desc = self.a.Describe(path)
            require(desc.dataType == "Table" and getattr(desc, "hasOID", False) and
                    hasattr(desc, "defaultSubtypeCode") and hasattr(desc, "relationshipClassNames"),
                    f"La tabla {name} debe estar previamente registrada con la geodatabase.")
            self.report["tables_checked"].append(name)
        for mapping in self.plan["fields"]:
            table, field = mapping["table"], mapping["field"]
            native = {item.name.casefold(): item for item in self.a.ListFields(self.paths[table])}
            require(field.casefold() in native, f"Falta el campo {table}.{field}.")
            current = native[field.casefold()]
            self.field_states[(table, field)] = {"type": current.type, "domain": current.domain,
                                                "nullable": current.isNullable}

    def verify_values_and_subtypes(self):
        for table in sorted({mapping["table"] for mapping in self.plan["fields"]}):
            mappings = [mapping for mapping in self.plan["fields"] if mapping["table"] == table]
            fields = [mapping["field"] for mapping in mappings]
            count = 0
            nulls = {field: 0 for field in fields}
            with self.a.da.SearchCursor(self.paths[table], fields) as cursor:
                for row in cursor:
                    count += 1
                    for mapping, value in zip(mappings, row):
                        if value is None:
                            nulls[mapping["field"]] += 1
                        else:
                            require(value in self.plan["domains"][mapping["group"]]["codes"],
                                    f"Hay valores fuera del snapshot en {table}.{mapping['field']}; no se modificó la base.")
            self.report["data_checked"][table] = {"rows": count, "nulls_by_field": nulls}
            for subtype in self.a.da.ListSubtypes(self.paths[table]).values():
                values = {name.casefold(): value for name, value in subtype.get("FieldValues", {}).items()}
                for mapping in mappings:
                    field_value = values.get(mapping["field"].casefold())
                    domain = field_value[1] if field_value else None
                    if domain is not None:
                        current = {"kind": domain.domainType, "type": domain.type,
                                   "codes": dict(domain.codedValues) if domain.domainType == "CodedValue" else {}}
                        require(equivalent_domain(current, self.plan["domains"][mapping["group"]]),
                                f"Un subtipo usa un dominio incompatible en {table}.{mapping['field']}.")

    def preflight(self):
        self.verify_connection_and_tables()
        self.resolved = resolve_existing(self.plan, self.inspect_domains(), self.field_states)
        self.verify_values_and_subtypes()
        self.report["plan"] = self.resolved
        self.report["nullable_before"] = {table + "." + field: state["nullable"]
                                          for (table, field), state in self.field_states.items()}

    def apply(self):
        assignments = self.resolved["assign_fields"]
        affected = sorted({mapping["table"] for mapping in assignments})
        # Comprobar todas las tablas afectadas ANTES de crear el primer dominio.
        locks = {name: bool(self.a.TestSchemaLock(self.paths[name])) for name in affected}
        self.report["schema_locks_checked"] = locks
        require(all(locks.values()), "No hay bloqueo exclusivo de esquema en las tablas afectadas. Cierre sus vistas y servicios antes de volver a aplicar.")
        self.report["mutations_attempted"] = bool(self.resolved["create_domains"] or assignments)
        for definition in self.resolved["create_domains"]:
            self.a.management.CreateDomain(self.connection, definition["name"], definition["group"], "LONG", "CODED")
            self.report["actions_completed"].append({"action": "CreateDomain", "domain": definition["name"]})
            for code, label in sorted(definition["codes"].items()):
                self.a.management.AddCodedValueToDomain(self.connection, definition["name"], code, label)
                self.report["actions_completed"].append({"action": "AddCodedValueToDomain", "domain": definition["name"], "code": code})
        for mapping in assignments:
            self.a.management.AssignDomainToField(self.paths[mapping["table"]], mapping["field"], mapping["domain"])
            self.report["actions_completed"].append({"action": "AssignDomainToField", **mapping})
        # Lectura posterior: comprobar códigos/etiquetas/asignaciones y nulabilidad.
        domains = {name.casefold(): value for name, value in self.inspect_domains().items()}
        for mapping in self.plan["fields"]:
            table, field = mapping["table"], mapping["field"]
            native = {item.name.casefold(): item for item in self.a.ListFields(self.paths[table])}[field.casefold()]
            definition = self.plan["domains"][mapping["group"]]
            require(native.domain and native.domain.casefold() in domains and
                    equivalent_domain(domains[native.domain.casefold()], definition),
                    f"No se confirmó la asignación final del dominio de {table}.{field}.")
            require(native.isNullable == self.field_states[(table, field)]["nullable"],
                    f"La nulabilidad de {table}.{field} cambió; revisar antes de continuar.")
        self.report["nullable_preserved"] = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--connection", required=True, type=Path, help="Conexión .sde del propietario gis a ArcGisAWS")
    parser.add_argument("--manifest", type=Path, default=Path(__file__).with_name("modelo_restricciones.json"))
    parser.add_argument("--report", type=Path, default=Path("resultado_dominios_arcgis.json"))
    parser.add_argument("--apply", action="store_true", help="Crear y asignar los dominios tras superar todas las verificaciones")
    args = parser.parse_args()
    report = {"status": "iniciado", "applied": False, "tables_checked": [], "data_checked": {},
              "actions_completed": [], "scope": "8 dominios de parámetros y 10 campos explícitos del EFT",
              "notes": ["Los 28 códigos incluyen valores históricos; se conservan id_parametro y etiquetas del dump.",
                        "La asignación de dominios no sustituye claves primarias/foráneas SQL ni garantiza integridad referencial.",
                        "Se conservan dominios ya asignados cuando su tipo, códigos y etiquetas son equivalentes."]}
    exit_code = 0
    try:
        import arcpy
        manifest_bytes = args.manifest.read_bytes()
        manifest = json.loads(manifest_bytes.decode("utf-8-sig"))
        report["manifest_sha256"] = hashlib.sha256(manifest_bytes).hexdigest()
        report["source_sha256"] = manifest.get("source_sha256")
        runner = DomainConfigurator(arcpy, args.connection, manifest, report)
        runner.preflight()
        if args.apply:
            runner.apply()
            report["applied"] = True
        report["status"] = "dominios_configurados" if args.apply else "validacion_previa_correcta_sin_cambios"
        print("Dominios configurados; consulte el informe." if args.apply else
              "Validación previa correcta. No se modificó la geodatabase; revise el informe antes de usar --apply.")
    except ImportError:
        exit_code = 1
        report.update(status="fallo", error="Ejecute con el Python de ArcGIS Pro; ArcPy no está disponible.")
        print(report["error"], file=sys.stderr)
    except Exception as exc:
        exit_code = 1
        report.update(status="fallo", error=str(exc), partial_changes_possible=bool(report.get("mutations_attempted")))
        print("Error: " + str(exc) + ". Consulte el informe; no se ejecuta reversión o eliminación automática.", file=sys.stderr)
    finally:
        report["timestamp_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
        try:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        except OSError as exc:
            exit_code = 1
            print("Además, no pudo guardarse el informe: " + str(exc), file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
