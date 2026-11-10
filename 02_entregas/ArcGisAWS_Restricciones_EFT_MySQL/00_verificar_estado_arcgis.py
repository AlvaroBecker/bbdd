"""Verificar el estado ArcGIS y generar una copia SQL habilitada para revisión.

Solo lee el servidor mediante ArcPy Describe/ListFields y una consulta SELECT.
No ejecuta el SQL generado ni modifica tablas, campos o configuración ArcGIS.
La comprobación ArcGIS es necesaria porque el versionado tradicional puede no
identificarse inspeccionando únicamente las columnas SQL de la tabla base.

Se exigen las ocho tablas registradas con ObjectID independiente, sin versionado
tradicional/branch ni archivado. Tras superar todos los controles, se reemplazan
solo tres marcas del SQL: estado verificado, servidor y fecha UTC. El SQL conserva
su control de vigencia de 15 minutos y debe ejecutarse inmediatamente después,
sin cambiar registro, versionado ni archivado entre los dos pasos.
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


TABLE_KEYS = {
    "mline_tc_proyecto": "id_proyecto",
    "mline_ta_proyecto_estado": "id_proyecto_estado",
    "mline_td_proyecto_componente": "id_proyecto_componente",
    "mline_td_proyecto_capa": "id_proyecto_capa",
    "mline_td_proyecto_regla_cfg": "id_proyecto_regla_cfg",
    "mline_td_proyecto_alternativa": "id_proyecto_alternativa",
    "mline_td_celda_capa": "id_celda_capa",
    "mline_td_infraestructura_celda": "id_infraestructura_celda",
}
STATE_MARKER = "DECLARE @EstadoArcGISVerificado bit = 0; -- ACTIVAR_SOLO_TRAS_VERIFICACION_ARCGIS"
SERVER_MARKER = "DECLARE @ServidorVerificado nvarchar(256) = N'__PENDIENTE__';"
DATE_MARKER = "DECLARE @FechaVerificacion datetime2(0) = NULL;"
IDENTITY_QUERY = (
    "SELECT DB_NAME(), CONVERT(nvarchar(256), SERVERPROPERTY('ServerName')), "
    "USER_NAME(), SCHEMA_NAME(), CONVERT(varchar(19), SYSUTCDATETIME(), 126)"
)


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sql_literal(value):
    return "N'" + value.replace("'", "''") + "'"


def normalize_sql_template(template):
    """Corrige una plantilla antigua sin modificar el archivo original.

    Las primeras copias del SQL declaraban ``existente sysname`` en @Plan.
    Esa columna recibe NULL cuando la restriccion aun no existe y debe crearse.
    El helper acepta esas copias antiguas y solo corrige el texto que escribira
    en la salida verificada.
    """
    legacy = "existente sysname, accion nvarchar(50), ddl nvarchar(max));"
    fixed = "existente sysname NULL, accion nvarchar(50), ddl nvarchar(max));"
    count = template.count(legacy)
    require(count <= 1, "La plantilla contiene varias declaraciones antiguas de @Plan.")
    return template.replace(legacy, fixed)


def render_verified_sql(template, server, utc_timestamp):
    """Transformación pura de tres líneas exactas; conserva sus finales de línea."""
    require(isinstance(server, str) and 0 < len(server) <= 256 and not any(ord(c) < 32 for c in server),
            "SERVERPROPERTY('ServerName') no devolvió un nombre válido.")
    require(re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", utc_timestamp), "Fecha UTC de verificación inválida.")
    dt.datetime.fromisoformat(utc_timestamp)
    replacements = {
        STATE_MARKER: STATE_MARKER.replace("bit = 0;", "bit = 1;"),
        SERVER_MARKER: "DECLARE @ServidorVerificado nvarchar(256) = " + sql_literal(server) + ";",
        DATE_MARKER: "DECLARE @FechaVerificacion datetime2(0) = CONVERT(datetime2(0), " + sql_literal(utc_timestamp) + ", 126);",
    }
    lines = template.splitlines(keepends=True)
    counts = {key: 0 for key in replacements}
    rendered = []
    for line in lines:
        content = line.rstrip("\r\n")
        marker = content.strip()
        if marker in replacements:
            counts[marker] += 1
            indent = content[:len(content) - len(content.lstrip())]
            line = indent + replacements[marker] + line[len(content):]
        rendered.append(line)
    require(all(count == 1 for count in counts.values()),
            "La plantilla debe contener una sola vez cada una de las tres marcas originales sin activar.")
    for variable in ("EstadoArcGISVerificado", "ServidorVerificado", "FechaVerificacion"):
        require(len(re.findall(r"(?mi)^\s*DECLARE\s+@" + variable + r"\b", template)) == 1,
                f"La plantilla contiene declaraciones duplicadas o ambiguas de @{variable}.")
    return "".join(rendered)


def verify_arcgis(arcpy, connection, report):
    """Inspección de solo lectura; cualquier propiedad ausente impide habilitar SQL."""
    connection = str(connection)
    require(arcpy.Exists(connection), "La conexión .sde no existe o no es accesible.")
    workspace = arcpy.Describe(connection)
    require(workspace.workspaceType == "RemoteDatabase", "Se requiere una geodatabase empresarial.")
    require(str(getattr(workspace.connectionProperties, "database", "")).casefold() == "arcgisaws",
            "La conexión no apunta a ArcGisAWS.")
    result = arcpy.ArcSDESQLExecute(connection).execute(IDENTITY_QUERY)
    require(isinstance(result, list) and len(result) == 1 and len(result[0]) == 5,
            "No pudo confirmarse la identidad y hora UTC del servidor mediante SELECT.")
    database, server, user, schema, server_utc = result[0]
    require(str(database).casefold() == "arcgisaws" and str(user).casefold() == "gis" and str(schema).casefold() == "gis",
            "La conexión debe apuntar a ArcGisAWS como usuario y esquema propietario gis.")
    require(isinstance(server, str) and server.strip(), "No se identificó el servidor SQL.")
    require(isinstance(server_utc, str), "No se obtuvo la hora UTC del servidor.")
    report["identity"] = {"database": database, "server": server, "user": user, "schema": schema,
                           "server_utc": server_utc}
    for table, key in sorted(TABLE_KEYS.items()):
        path = os.path.join(connection, "ArcGisAWS.gis." + table)
        require(arcpy.Exists(path), f"Falta ArcGisAWS.gis.{table}.")
        desc = arcpy.Describe(path)
        dataset_id = getattr(desc, "DSID", None)
        record = {"table": table, "business_id": key, "dataset_id": dataset_id,
                  "oid_field": getattr(desc, "OIDFieldName", None)}
        report["tables"].append(record)
        require(desc.dataType == "Table" and type(dataset_id) is int and dataset_id >= 0 and
                hasattr(desc, "defaultSubtypeCode") and hasattr(desc, "relationshipClassNames") and hasattr(desc, "aliasName"),
                f"{table}: ArcPy no confirma una tabla registrada en la geodatabase con DSID válido.")
        require(getattr(desc, "hasOID", None) is True and isinstance(record["oid_field"], str) and record["oid_field"],
                f"{table}: falta un ObjectID administrado por ArcGIS.")
        require(record["oid_field"].casefold() != key.casefold(),
                f"{table}: el identificador de negocio {key} está siendo usado como ObjectID; no se habilitará la PK física.")
        fields = {field.name.casefold(): field for field in arcpy.ListFields(path)}
        require(key.casefold() in fields and record["oid_field"].casefold() in fields and
                fields[record["oid_field"].casefold()].type == "OID",
                f"{table}: no se confirmó el campo de negocio y el ObjectID independiente.")
        for flag in ("isVersioned", "isTraditionalVersioned", "isBranchVersioned", "isArchived"):
            value = getattr(desc, flag, None)
            record[flag] = value
            require(type(value) is bool, f"{table}: ArcPy no expone {flag}; no se asumirá que está desactivado.")
            require(value is False, f"{table}: {flag} está activo. Este paquete SQL físico no es aplicable en ese estado.")
    # La función pura valida también que el servidor y timestamp sean literales seguros.
    return server, server_utc


def choose_path(requested, default, overwrite):
    path = requested or default
    if not path.exists() or overwrite:
        return path
    require(requested is None, f"Ya existe {path}. Use otro nombre o --overwrite explícitamente.")
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    candidate = path.with_name(path.stem + "_" + stamp + path.suffix)
    index = 1
    while candidate.exists():
        candidate = path.with_name(path.stem + "_" + stamp + "_" + str(index) + path.suffix)
        index += 1
    return candidate


def main():
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--connection", required=True, type=Path, help="Conexión .sde a ArcGisAWS del propietario gis")
    parser.add_argument("--template", type=Path, default=root / "03_agregar_PK_FK_SQLServer.sql")
    parser.add_argument("--output", type=Path, help="SQL nuevo; por defecto, 03_agregar_PK_FK_VERIFICADO.sql junto al script")
    parser.add_argument("--report", type=Path, help="Informe JSON; por defecto, 00_estado_arcgis.json junto al script")
    parser.add_argument("--overwrite", action="store_true", help="Permitir sustituir archivos de salida existentes; nunca la plantilla")
    args = parser.parse_args()
    report = {"status": "iniciado", "tables": [], "sql_generated": False, "server_modified": False,
              "notes": ["La inspección solo lee ArcGIS y ejecuta SELECT; el SQL resultante no se ejecutó.",
                        "La verificación es una instantánea. No cambie registro, versionado o archivado entre esta comprobación y la ejecución SQL.",
                        "La vigencia temporal y coincidencia de servidor se verifican nuevamente en el SQL generado."]}
    report_path = None
    output_path = None
    exit_code = 0
    try:
        output_path = choose_path(args.output, root / "03_agregar_PK_FK_VERIFICADO.sql", args.overwrite)
        candidate_report = choose_path(args.report, root / "00_estado_arcgis.json", args.overwrite)
        template_path = args.template.resolve()
        output_path = output_path.resolve()
        candidate_report = candidate_report.resolve()
        require(len({os.path.normcase(str(path)) for path in (template_path, output_path, candidate_report)}) == 3,
                "La plantilla, SQL generado e informe deben tener rutas distintas.")
        report_path = candidate_report
        require(template_path.is_file(), "No existe la plantilla SQL: " + str(template_path))
        source = template_path.read_bytes()
        has_bom = source.startswith(b"\xef\xbb\xbf")
        text = normalize_sql_template(source.decode("utf-8-sig"))
        # Validar marcas antes de abrir la conexión; el contenido definitivo usa la hora real del servidor.
        render_verified_sql(text, "VALIDACION_LOCAL_DE_PLANTILLA", "2000-01-01T00:00:00")
        report["template"] = str(template_path)
        report["template_sha256"] = hashlib.sha256(source).hexdigest()
        import arcpy
        server, server_utc = verify_arcgis(arcpy, args.connection, report)
        rendered = render_verified_sql(text, server, server_utc)
        data = rendered.encode("utf-8-sig" if has_bom else "utf-8")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("wb" if args.overwrite else "xb") as file:
            file.write(data)
        report.update(status="verificacion_correcta_sql_generado", sql_generated=True,
                      output=str(output_path), output_sha256=hashlib.sha256(data).hexdigest(), verified_utc=server_utc)
        print("Verificación correcta. SQL nuevo generado sin ejecutarlo: " + str(output_path))
    except ImportError:
        exit_code = 1
        report.update(status="fallo", error="Ejecute este helper con el Python de ArcGIS Pro; ArcPy no está disponible.")
        print(report["error"], file=sys.stderr)
    except Exception as exc:
        exit_code = 1
        report.update(status="fallo", error=str(exc))
        print("Error: " + str(exc) + ". No se ejecutó SQL en el servidor.", file=sys.stderr)
    finally:
        report["local_timestamp_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
        if report_path is not None:
            try:
                report_path.parent.mkdir(parents=True, exist_ok=True)
                with report_path.open("w" if args.overwrite else "x", encoding="utf-8") as file:
                    json.dump(report, file, ensure_ascii=False, indent=2)
                print("Informe: " + str(report_path))
            except OSError as exc:
                exit_code = 1
                print("No pudo guardarse el informe: " + str(exc), file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
