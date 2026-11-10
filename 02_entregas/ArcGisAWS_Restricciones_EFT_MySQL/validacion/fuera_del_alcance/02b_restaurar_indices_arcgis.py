"""Restaurar los 27 indices secundarios originales mediante ArcGIS Pro.

Alternativa a 02_restaurar_indices_no_unicos.sql. La seleccion de tablas es
del EFT y nombres/columnas de indices proceden del DDL MySQL sin inferencias.
No restaura PK/FK ni crea reglas de negocio.

Sin --apply solo valida y escribe un plan. No modifica filas, PK/FK, campos,
indices existentes ni tablas internas de geodatabase. ArcSDESQLExecute se usa
exclusivamente con SELECT para comprobar el catalogo fisico SQL Server.

Ejemplo con el Python de ArcGIS Pro:
  python 02b_restaurar_indices_arcgis.py --connection C:\\Conexiones\\gis.sde
  python 02b_restaurar_indices_arcgis.py --connection C:\\Conexiones\\gis.sde --apply

AddIndex no comparte una transaccion global con el resto de herramientas.
Un fallo puede dejar algunos indices creados. El reporte registra los intentos
y resultados; el script no elimina automaticamente esos indices.

Documentacion:
https://doc.esri.com/en/arcgis-pro/latest/tool-reference/data-management/add-attribute-index.html
https://doc.esri.com/en/arcgis-pro/latest/arcpy/functions/listindexes.html
https://doc.esri.com/en/arcgis-pro/latest/arcpy/functions/gdb-table-properties.html
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import sys


IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,127}\Z")


def fail(message):
    raise RuntimeError(message)


def identifier(value):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        fail(f"Identificador no admitido en el modelo: {value!r}")
    return value


def quote(value):
    return "[" + identifier(value) + "]"


def literal(value):
    return "N'" + identifier(value).replace("'", "''") + "'"


def key_signature(columns, descending=None):
    descending = descending if descending is not None else [False] * len(columns)
    if len(columns) != len(descending):
        fail("Columnas y orden del indice no coinciden.")
    return tuple((column.casefold(), bool(desc)) for column, desc in zip(columns, descending))


def usable(index):
    return (
        index["type"] in (1, 2)
        and not index["disabled"]
        and not index["hypothetical"]
        and not index["filtered"]
    )


def plan_index(expected, actual):
    """Funcion pura: distinguir cobertura de columnas y conflictos de nombre.

    INCLUDE adicional permite la misma busqueda y se informa expresamente.
    Un indice UNIQUE ya existente cubre la busqueda, pero requiere revisar su
    compatibilidad branch; nunca se crea uno nuevo ni se transforma el existente.
    No se considera suficiente tener solo las columnas de un prefijo compuesto.
    """
    signature = key_signature(expected["columns"])
    same_name = [a for a in actual if a["name"].casefold() == expected["name"].casefold()]
    if len(same_name) > 1:
        fail(f"Nombre de indice ambiguo: {expected['table']}.{expected['name']}")
    for item in same_name:
        if not usable(item) or key_signature(item["columns"], item["descending"]) != signature:
            fail(f"Conflicto con un indice existente: {expected['table']}.{expected['name']}")
    covering = [a for a in actual if usable(a) and key_signature(a["columns"], a["descending"]) == signature]
    covering.sort(key=lambda a: (
        a["name"].casefold() != expected["name"].casefold(),
        bool(a["unique"]), bool(a["included"]), a["id"],
    ))
    result = {"table": expected["table"], "name": expected["name"], "columns": expected["columns"],
              "action": "create_non_unique", "covering_index": None}
    if covering:
        item = covering[0]
        result["covering_index"] = item
        if item["unique"]:
            result["action"] = "skip_existing_unique_review_branch"
        elif item["included"]:
            result["action"] = "skip_existing_include_review_publication"
        else:
            result["action"] = "skip_existing_index"
    return result


def validate_manifest(model):
    if model.get("database", "").casefold() != "arcgisaws" or model.get("owner", "").casefold() != "gis":
        fail("El manifiesto debe describir ArcGisAWS.gis.")
    tables = model.get("tables", [])
    indexes = model.get("original_indexes", [])
    if len(tables) != 8 or len(indexes) != 27:
        fail("Se esperaban ocho tablas y 27 indices secundarios en el manifiesto.")
    names = set()
    fields = {}
    for table in tables:
        name = identifier(table["name"])
        if name.casefold() in names:
            fail(f"Tabla repetida en el modelo: {name}")
        names.add(name.casefold())
        fields[name] = {identifier(field["name"]).casefold() for field in table["fields"]}
    index_names = set()
    for index in indexes:
        table, name = identifier(index["table"]), identifier(index["name"])
        if table not in fields or not index.get("columns") or index.get("unique", False):
            fail("Indice fuera del alcance o unico en el manifiesto.")
        for column in index["columns"]:
            if identifier(column).casefold() not in fields[table]:
                fail(f"Campo de indice no declarado: {table}.{column}")
        key = (table.casefold(), name.casefold())
        if key in index_names:
            fail(f"Indice repetido en el manifiesto: {table}.{name}")
        index_names.add(key)


class IndexRestorer:
    def __init__(self, arcpy, connection, model, report):
        self.a = arcpy
        self.connection = str(connection)
        self.model = model
        self.database = model["database"]
        self.owner = model["owner"]
        self.tables = {table["name"]: table for table in model["tables"]}
        self.report = report
        self.sql = None
        self.paths = {}
        self.field_names = {}

    def path(self, table):
        return os.path.join(self.connection, f"{self.database}.{self.owner}.{table}")

    def select(self, query):
        # Ninguna llamada SQL de este archivo admite DDL ni DML.
        if not re.match(r"\s*SELECT\b", query, re.IGNORECASE):
            fail("Solo se permiten SELECT en ArcSDESQLExecute.")
        result = self.sql.execute(query)
        if result is None or result is True:
            return []
        if result is False or not isinstance(result, (list, tuple)):
            fail("El catalogo SQL no devolvio un conjunto de resultados valido.")
        return result

    def validate_connection(self):
        if not self.connection.lower().endswith(".sde") or not self.a.Exists(self.connection):
            fail("Se requiere un archivo .sde existente y accesible.")
        desc = self.a.Describe(self.connection)
        if desc.workspaceType != "RemoteDatabase":
            fail("La conexion no es una geodatabase empresarial.")
        cp = desc.connectionProperties
        if str(getattr(cp, "database", "")).casefold() != self.database.casefold():
            fail("La conexion no apunta a ArcGisAWS.")
        self.sql = self.a.ArcSDESQLExecute(self.connection)
        rows = self.select("SELECT DB_NAME(),USER_NAME(),SCHEMA_NAME()")
        if len(rows) != 1 or len(rows[0]) != 3:
            fail("No fue posible comprobar base, usuario y esquema de la conexion.")
        database, user, schema = (str(value or "") for value in rows[0])
        if (database.casefold() != self.database.casefold() or user.casefold() != self.owner.casefold()
                or schema.casefold() != self.owner.casefold()):
            fail("Conectese como propietario gis con esquema predeterminado gis en ArcGisAWS.")
        self.report["connection_check"] = {"database": database, "user": user, "default_schema": schema}
        self.a.env.overwriteOutput = False

    def describe_tables(self):
        for name, table in self.tables.items():
            path = self.path(name)
            if not self.a.Exists(path):
                fail(f"Tabla no accesible: {self.database}.{self.owner}.{name}")
            desc = self.a.Describe(path)
            actual_fields = {field.name.casefold(): field for field in self.a.ListFields(path)}
            oid = str(getattr(desc, "OIDFieldName", "") or "")
            # Propiedades de tabla de geodatabase y un campo OID administrado.
            # No se consulta ni modifica el registro interno SDE/GDB por SQL.
            if (not getattr(desc, "hasOID", False) or not oid
                    or oid.casefold() not in actual_fields
                    or actual_fields[oid.casefold()].type != "OID"
                    or not hasattr(desc, "hasGlobalID")
                    or not hasattr(desc, "relationshipClassNames")):
                fail(f"ArcPy no confirma tabla de geodatabase con OID administrado: {name}")
            missing = [field["name"] for field in table["fields"] if field["name"].casefold() not in actual_fields]
            if missing:
                fail(f"Campos del modelo ausentes en {name}: {', '.join(missing)}")
            self.paths[name] = path
            self.field_names[name] = {key: value.name for key, value in actual_fields.items()}
            fields = []
            for field in table["fields"]:
                actual = actual_fields[field["name"].casefold()]
                fields.append({"name": actual.name, "origin_type": field["sql_type"],
                               "arcgis_type": actual.type, "length": getattr(actual, "length", None),
                               "nullable": getattr(actual, "isNullable", None),
                               "origin_nullable": field.get("nullable", True)})
            for index in self.model["original_indexes"]:
                if index["table"] != name:
                    continue
                for column in index["columns"]:
                    actual = actual_fields[column.casefold()]
                    if actual.type not in ("SmallInteger", "Integer", "BigInteger", "String", "Date", "Single", "Double", "GUID"):
                        fail(f"Tipo de campo no admitido para el indice: {name}.{column} ({actual.type})")
            self.report["tables"].append({"name": name, "oid_field": oid,
                "registration_evidence": "ArcPy geodatabase table properties and managed OID",
                "is_versioned": bool(getattr(desc, "isVersioned", False)),
                "is_branch_versioned": bool(getattr(desc, "isBranchVersioned", False)), "fields": fields})

    def arcgis_indexes(self, table):
        result = []
        for index in self.a.ListIndexes(self.paths[table]) or []:
            result.append({"name": index.name, "columns": [field.name for field in index.fields],
                           "unique": bool(index.isUnique), "ascending": bool(index.isAscending),
                           "full_text": bool(getattr(index, "isFullText", False))})
        return result

    def sql_indexes(self, only_table=None):
        tables = [only_table] if only_table else list(self.tables)
        allowed = ",".join(literal(table) for table in tables)
        query = f"""SELECT t.name,i.index_id,i.name,i.type,i.is_unique,i.is_disabled,
            i.is_hypothetical,i.has_filter,ic.key_ordinal,ic.is_descending_key,
            ic.is_included_column,c.name,ic.index_column_id
            FROM sys.tables t JOIN sys.schemas s ON s.schema_id=t.schema_id
            JOIN sys.indexes i ON i.object_id=t.object_id
            LEFT JOIN sys.index_columns ic ON ic.object_id=i.object_id AND ic.index_id=i.index_id
            LEFT JOIN sys.columns c ON c.object_id=ic.object_id AND c.column_id=ic.column_id
            WHERE s.name={literal(self.owner)} AND t.name IN({allowed}) AND i.index_id>0
            ORDER BY t.name,i.index_id,ic.index_column_id"""
        grouped = {}
        for row in self.select(query):
            if len(row) != 13:
                fail("Resultado inesperado al consultar indices del catalogo SQL.")
            table, index_id, name, kind, unique, disabled, hypothetical, filtered, ordinal, descending, included, column, _ = row
            key = (str(table), int(index_id))
            if key not in grouped:
                grouped[key] = {"table": str(table), "id": int(index_id), "name": str(name),
                    "type": int(kind), "unique": bool(unique), "disabled": bool(disabled),
                    "hypothetical": bool(hypothetical), "filtered": bool(filtered),
                    "columns": [], "descending": [], "included": [], "_keys": []}
            item = grouped[key]
            if column and ordinal and int(ordinal) > 0:
                item["_keys"].append((int(ordinal), str(column), bool(descending)))
            if column and included:
                item["included"].append(str(column))
        result = {table: [] for table in tables}
        for item in grouped.values():
            keys = sorted(item.pop("_keys"))
            item["columns"] = [key[1] for key in keys]
            item["descending"] = [key[2] for key in keys]
            canonical = next((table for table in tables if table.casefold() == item["table"].casefold()), None)
            if canonical is None:
                fail("El catalogo devolvio una tabla fuera del alcance.")
            item["table"] = canonical
            result[canonical].append(item)
        # Las tablas registradas deben tener, como minimo, el indice del OID.
        # Sin visibilidad suficiente no se supone que el inventario este vacio.
        if any(not result[table] for table in tables):
            fail("Catalogo SQL incompleto o sin visibilidad de indices en todas las tablas.")
        return result

    def preflight(self):
        self.validate_connection()
        self.describe_tables()
        self.report["arcgis_indexes_before"] = {name: self.arcgis_indexes(name) for name in self.tables}
        actual = self.sql_indexes()
        self.report["sql_indexes_before"] = actual
        # Se validan LOS 27 antes del primer AddIndex, incluidos conflictos de nombre.
        self.report["plan"] = [plan_index(index, actual[index["table"]]) for index in self.model["original_indexes"]]
        self.report["warnings"].append("Los indices UNIQUE o INCLUDE preexistentes se conservan y se informan; revisar su compatibilidad con branch y publicacion.")
        self.report["warnings"].append("La nulabilidad y los tipos de campos se inventarian; este script no los altera ni restaura PK/FK o reglas de integridad.")

    def apply(self):
        for expected, item in zip(self.model["original_indexes"], self.report["plan"]):
            if item["action"] != "create_non_unique":
                continue
            name = expected["table"]
            current = plan_index(expected, self.sql_indexes(name)[name])
            if current["action"] != "create_non_unique":
                self.report["concurrent_skips"].append(current)
                continue
            attempt = {"table": name, "name": expected["name"], "columns": expected["columns"], "confirmed": False}
            self.report["attempts"].append(attempt)
            columns = [self.field_names[name][column.casefold()] for column in expected["columns"]]
            self.a.management.AddIndex(self.paths[name], columns, expected["name"], "NON_UNIQUE", "ASCENDING")
            after = self.sql_indexes(name)[name]
            own = [index for index in after if index["name"].casefold() == expected["name"].casefold()]
            if (len(own) != 1 or not usable(own[0]) or own[0]["unique"] or own[0]["included"]
                    or key_signature(own[0]["columns"], own[0]["descending"]) != key_signature(expected["columns"])):
                fail(f"No se confirmo la definicion fisica del indice creado: {name}.{expected['name']}")
            gis = self.arcgis_indexes(name)
            if not any(index["name"].split(".")[-1].casefold() == expected["name"].casefold()
                       and not index["unique"] and index["ascending"]
                       and key_signature(index["columns"]) == key_signature(columns) for index in gis):
                fail(f"ArcGIS no enumera la definicion esperada despues de AddIndex: {name}.{expected['name']}")
            attempt["confirmed"] = True
        actual = self.sql_indexes()
        final_plan = [plan_index(index, actual[index["table"]]) for index in self.model["original_indexes"]]
        if any(item["action"] == "create_non_unique" for item in final_plan):
            fail("La verificacion final encontro indices originales sin cobertura.")
        self.report["final_plan"] = final_plan
        self.report["arcgis_indexes_after"] = {name: self.arcgis_indexes(name) for name in self.tables}
        self.report["applied"] = True


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--connection", required=True, type=Path, help="Conexion .sde como propietario gis a ArcGisAWS")
    parser.add_argument("--manifest", type=Path, default=Path(__file__).with_name("modelo_restricciones.json"))
    parser.add_argument("--report", type=Path, default=Path("resultado_indices_arcgis.json"))
    parser.add_argument("--apply", action="store_true", help="Crear solo indices secundarios no unicos faltantes mediante AddIndex")
    args = parser.parse_args()
    report = {"status": "pending", "applied": False, "partial_changes_possible": False,
              "tables": [], "plan": [], "attempts": [], "concurrent_skips": [], "warnings": []}
    exit_code = 0
    try:
        model = json.loads(args.manifest.read_text(encoding="utf-8-sig"))
        validate_manifest(model)
        try:
            import arcpy
        except ImportError:
            fail("Ejecute con el Python de ArcGIS Pro; ArcPy no se instala mediante pip.")
        restorer = IndexRestorer(arcpy, args.connection, model, report)
        restorer.preflight()
        if args.apply:
            restorer.apply()
        report["status"] = "applied_and_verified" if args.apply else "read_only_plan_ready"
    except Exception as exc:
        report["status"] = "failed"
        report["error"] = str(exc)
        report["partial_changes_possible"] = bool(report["attempts"])
        exit_code = 1
    finally:
        report["timestamp_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Indices creados y verificados." if report["applied"] else
          "Plan listo sin modificaciones." if exit_code == 0 else "Fallo. Consulte el reporte; no se eliminaron indices.")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
