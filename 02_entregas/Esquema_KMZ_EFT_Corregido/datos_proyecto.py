"""Validacion y creacion controlada en un Datos_Proyecto ya existente.

Sin --aplicar no modifica la geodatabase. Las relaciones y la carga son fases
separadas. No borra, mueve, rellena ni repara objetos existentes.
"""
from __future__ import annotations

import argparse
import copy
import csv
import datetime as dt
import gc
import hashlib
import json
import os
from pathlib import Path
import re
from types import SimpleNamespace
import uuid

import crear_esquema as engine

HERE = Path(__file__).resolve().parent
DATASET = "Datos_Proyecto"


def validate_eft_fields(c):
    common = {"proyecto", "id_analisis", "disciplina", "componente", "alternativa", "condicion",
              "fuente", "nombre", "archivo_origen", "ruta_kml", "fecha_carga"}
    if c.get("rol") == "recorte":
        common.update({"tema", "capa_origen", "id_origen"})
    if c["geometria"] == "POLYLINE":
        common.add("longitud_m")
    elif c["geometria"] == "POLYGON":
        common.add("area_ha")
    for f in c["campos"]:
        origin = f.get("origen", "")
        if not origin.startswith('DDL MapLine'):
            engine.require(re.fullmatch(r'[a-z][a-z0-9]*(?:_[a-z0-9]+)*', f['nombre']) is not None,
                           f'{c["nombre"]}.{f["nombre"]}: el nombre debe estar en snake_case.')
        if origin.startswith("Atributo KMZ") and f.get("campo_fuente"):
            continue
        if origin.startswith("DDL MapLine") and c.get("rol") == "migrada":
            continue
        if origin == "EFT 5.8.7" and f["nombre"] in common:
            continue
        if (c["nombre"] == "area_estudio_campo" and f["nombre"] == "codigo_estacion"
                and origin == "EFT 5.8.6: codigo de estacion en AreaEstudioCampo"):
            continue
        if (c["nombre"] == "vertices" and f["nombre"] == "id_proyecto_infraestructura"
                and origin == "Llave del trazado, EFT 5.8.10"):
            continue
        raise ValueError(f'{c["nombre"]}.{f["nombre"]}: campo sin fundamento EFT aplicable. No se permiten extensiones en esta fase.')


def scoped_model(model, names=None):
    """Seleccion explicita, sin alterar el modelo de entrada."""
    result = copy.deepcopy(model)
    engine.require(model.get("referencia_espacial") == 4326, "El modelo debe usar EPSG:4326.")
    available = {c["nombre"]: c for c in model["clases"] if c["dataset"] == DATASET}
    engine.require(len(available) == sum(c["dataset"] == DATASET for c in model["clases"]), "Clases duplicadas.")
    selected = set(names) if names else set(available)
    engine.require(bool(selected) and selected <= available.keys(), "Seleccion vacia o clases desconocidas.")
    result["datasets"] = [DATASET]
    result["clases"] = [copy.deepcopy(available[n]) for n in sorted(selected)]
    used_domains = set()
    for c in result["clases"]:
        engine.require(c["geometria"] in {"POINT", "POLYLINE", "POLYGON"}, "Geometria no admitida.")
        fields = {f["nombre"].lower(): f for f in c["campos"]}
        engine.require(len(fields) == len(c["campos"]), f'{c["nombre"]}: campos duplicados sin distinguir mayusculas.')
        validate_eft_fields(c)
        engine.require(not ({"objectid", "shape", "globalid", "created_user", "created_date", "last_edited_user", "last_edited_date"} & fields.keys()), f'{c["nombre"]}: campo reservado en el modelo.')
        for key in ("proyecto", "id_analisis"):
            engine.require(key in fields and fields[key]["tipo"] == "TEXT" and fields[key]["nullable"] is False,
                           f'{c["nombre"]}: {key} debe ser texto obligatorio.')
        engine.require(fields["proyecto"]["longitud"] == 12, "El modelo de proyecto requiere 12 caracteres.")
        engine.require(c.get("relacion_proyecto") is True, f'{c["nombre"]}: falta vinculo al proyecto.')
        for f in c["campos"]:
            engine.require(f["tipo"] in engine.TYPE, f'Tipo no admitido: {f["tipo"]}')
            if f["tipo"] == "TEXT":
                valid_length = type(f["longitud"]) is int and (
                    0 < f["longitud"] <= 4000 or
                    (c["nombre"],f["nombre"],f["longitud"]) ==
                    ("predios_inscritos_en_sunarp_recorte","cargas_y_gravamenes",10000) or
                    (c['nombre'],f['nombre'],f['longitud']) ==
                    ("predios_inscritos_sunarp_recorte","cargas_y_gravamenes",10000))
                engine.require(valid_length, "Longitud de texto invalida; solo cargas_y_gravamenes de predios SUNARP admite la ampliacion aprobada a10000.")
            if f.get("dominio"):
                used_domains.add(f["dominio"])
                engine.require(f["dominio"] in model["dominios"] and f["tipo"] == "TEXT", "Dominio inexistente o tipo incompatible.")
                engine.require(all(len(v) <= f["longitud"] for v in model["dominios"][f["dominio"]]["valores"]), "Un codigo de dominio excede la longitud del campo.")
    result["dominios"] = {n: copy.deepcopy(model["dominios"][n]) for n in sorted(used_domains)}
    result["relaciones"] = [r for r in model.get("relaciones", []) if r["destino"] in selected]
    result["relaciones_negocio"] = [r for r in model.get("relaciones_negocio", []) if r["destino"] in selected]
    return result


def provisional(field):
    return "pendiente" in field.get("origen", "").lower()


def unexpected_fields(actual, description, c):
    allowed = {f['nombre'].casefold() for f in c['campos']}
    allowed.update({'objectid', 'shape', 'globalid', 'shape_length', 'shape_area',
                    'created_user', 'created_date', 'last_edited_user', 'last_edited_date'})
    for prop in ('OIDFieldName', 'shapeFieldName', 'globalIDFieldName', 'lengthFieldName', 'areaFieldName'):
        value = getattr(description, prop, '')
        if value:
            allowed.add(value.casefold())
            allowed.add(engine.simple(value).casefold())
    return sorted(f.name for f in actual if engine.field_base_name(f).casefold() not in allowed)


def validate_existing_names(actual, c):
    names = {key: engine.field_base_name(f) for key, f in engine.field_index(actual).items()}
    differences = [f'{names[f["nombre"].casefold()]} -> {f["nombre"]}' for f in c['campos']
                   if f['nombre'].casefold() in names and names[f['nombre'].casefold()] != f['nombre']]
    engine.require(not differences, f'{c["nombre"]}: nombres existentes sin normalizar: {", ".join(differences)}. No se renombran columnas automaticamente.')


def report_files(folder, report, model):
    """Guardar estados inmutables: nunca reemplazar un informe abierto en Windows."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    # La definicion de campos no cambia durante una ejecucion. Escribirla una vez
    # permite abrir el CSV en Excel mientras se procesa el lote.
    try:
        stream = (folder / "campos.csv").open("x", encoding="utf-8-sig", newline="")
    except FileExistsError:
        pass
    else:
        with stream:
            writer = csv.writer(stream, delimiter=";")
            writer.writerow(["clase", "campo", "tipo", "longitud", "permite_nulos", "dominio", "origen", "revision_tipo_pendiente"])
            for c in model.get("clases", []):
                for f in c["campos"]:
                    writer.writerow([c["nombre"], f["nombre"], f["tipo"], f.get("longitud"), f["nullable"], f.get("dominio"), f.get("origen"), provisional(f)])
    revision = folder / "estados" / (dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ") + "_" + uuid.uuid4().hex[:8])
    revision.mkdir(parents=True, exist_ok=False)
    report["archivo_resultado"] = str(revision / "resultado.json")
    report["archivo_informe"] = str(revision / "informe.md")
    report["archivo_campos"] = str(folder / "campos.csv")
    with (revision / "resultado.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    lines = ["# Datos_Proyecto: informe de ejecucion", "", f'Estado: **{report["estado"]}**', "",
             f'Modo: {report["modo"]}', f'Conexion: `{report["workspace"]}`', f'Modelo SHA256: `{report["modelo_sha256"]}`', "",
             "| Clase | Geometria | Campos definidos | Tipos pendientes | Accion |", "|---|---|---:|---:|---|"]
    for c in report["clases"]:
        lines.append(f'| {c["nombre"]} | {c["geometria"]} | {c["campos"]} | {c["tipos_pendientes"]} | {c["accion"]} |')
    lines += ["", "## Limites", ""] + [f"- {s}" for s in report["advertencias"]]
    if report.get("error"):
        lines += ["", "## Error", "", report["error"], "", "Se detuvo el lote. Consulte clase_en_curso y completadas en resultado.json. No se borro ningun objeto para deshacer operaciones."]
    with (revision / "informe.md").open("x", encoding="utf-8") as stream:
        stream.write("\n".join(lines) + "\n")


def preflight(a, args, model):
    engine.require(a.Exists(args.workspace), "La conexion/geodatabase debe existir.")
    inventory = engine.find_objects(a, args)
    naming_path = HERE / 'nombres_clases_1_6.json'
    if naming_path.exists():
        selected = {c['nombre'] for c in model['clases']}
        for row in json.loads(naming_path.read_text(encoding='utf-8'))['clases']:
            if row['nombre_nuevo'] in selected and row['nombre_anterior'] != row['nombre_nuevo']:
                engine.require(row['nombre_anterior'].casefold() not in inventory,
                    f"{row['nombre_anterior']}: ejecute primero Normalizar nombres de Datos_Proyecto. "
                    'Se evita crear una clase duplicada con el nombre nuevo.')
    ds = inventory.get(DATASET.lower())
    engine.require(ds is not None, "No existe Datos_Proyecto para el propietario indicado; esta herramienta no crea datasets.")
    d = a.Describe(ds)
    engine.require(d.dataType == "FeatureDataset", "Datos_Proyecto debe ser un feature dataset.")
    engine.require(d.spatialReference.factoryCode == 4326, "Datos_Proyecto debe usar EPSG:4326.")
    engine.require(not getattr(d, "isVersioned", False), "Datos_Proyecto ya esta versionado; requiere otro procedimiento de administracion.")
    inventory, domains = engine.inspect(a, args, model, model["clases"])
    parent = inventory.get(model["tabla_proyecto"].lower())
    engine.require(parent is not None, f'Falta la tabla real {model["tabla_proyecto"]}; no se creara un sustituto vacio.')
    pk, keys = engine.parent_keys(a, parent, model["clave_proyecto"])
    engine.require(pk.length == 12, "La longitud real de co_proyecto no coincide con proyecto (12).")
    engine.require(getattr(a.Describe(parent), "hasOID", False), "La tabla de proyectos debe estar registrada en la geodatabase.")
    for c in model["clases"]:
        path = inventory.get(c["nombre"].lower())
        if path:
            d = a.Describe(path)
            actual_fields = a.ListFields(path)
            validate_existing_names(actual_fields, c)
            extra = unexpected_fields(actual_fields, d, c)
            engine.require(not extra, f'{c["nombre"]}: campos fuera del esquema EFT seleccionado: {", ".join(extra)}. Revisar la clase existente; no se eliminan campos automaticamente.')
            engine.require(not d.hasM, f'{c["nombre"]}: tiene M; el esquema seleccionado usa Z sin M.')
            engine.require(not getattr(d, "isVersioned", False), f'{c["nombre"]}: ya esta versionada.')
    # En Pro 3.7.1 el ensayo devuelve False para un feature dataset vacio
    # aunque CreateFeatureclass tenga exito. Registrar, no usar como veto:
    # las herramientas ArcGIS adquieren/verifican el bloqueo real al ejecutar.
    return inventory, domains, len(keys), bool(a.TestSchemaLock(ds))


def verify_created(a, args, model, c):
    inventory, domains = engine.inspect(a, args, model, [c])
    path = inventory[c["nombre"].lower()]
    d = a.Describe(path)
    engine.require(not d.hasM, "La clase creada no debe tener M.")
    for prop, field in (("creatorFieldName", "created_user"), ("createdAtFieldName", "created_date"),
                        ("editorFieldName", "last_edited_user"), ("editedAtFieldName", "last_edited_date")):
        engine.require(getattr(d, prop, "").lower() == field, f'{c["nombre"]}: campo activo de auditoria incorrecto ({prop}).')
    engine.require(int(a.management.GetCount(path).getOutput(0)) == 0, "La clase nueva no esta vacia; se detiene para revision.")
    return inventory, domains


def run(workspace, names=None, apply=False, all_classes=False, database="ArcGisAWS", owner="gis",
        model_path=None, reports=None, arcpy_module=None, emit=print):
    engine.require(not (names and all_classes), "Use clases seleccionadas o todas, no ambas.")
    engine.require(not apply or names or all_classes, "Para crear indique clases o --todas; la seleccion vacia solo permite diagnostico.")
    engine.require(all(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", v) for v in (database, owner)), "Base o propietario invalido.")
    model_path = Path(model_path or HERE / "esquema.json")
    raw = model_path.read_bytes()
    model = scoped_model(json.loads(raw.decode("utf-8-sig")), names)
    args = SimpleNamespace(workspace=os.path.abspath(workspace), database=database, owner=owner, aplicar=apply)
    folder = Path(reports or HERE / "informes_datos_proyecto") / (dt.datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8])
    report = dict(estado="INICIADO", modo="CREAR" if apply else "VALIDAR", workspace=args.workspace,
                  database=database, owner=owner, modelo_sha256=hashlib.sha256(raw).hexdigest(),
                  inicio_utc=dt.datetime.now(dt.timezone.utc).isoformat(), completadas=[], clase_en_curso=None,
                  clases=[dict(nombre=c["nombre"], geometria=c["geometria"], campos=len(c["campos"]),
                               tipos_pendientes=sum(provisional(f) for f in c["campos"]), accion="POR_VALIDAR") for c in model["clases"]],
                  advertencias=["El catalogo de 76 clases sigue siendo una propuesta funcional, no una aprobacion de INDRA.",
                    "Los atributos marcados pendientes mantienen texto conservador; requieren perfil de valores y unidades antes de cargar.",
                    "Los campos propios no se eliminan por tener nombres parecidos. El informe no certifica la equivalencia de sus valores.",
                    "Esta fase crea clases vacias con GlobalID y auditoria UTC. No carga KMZ, no crea relaciones y no activa branch.",
                    "Las relaciones con proyecto y las relaciones de negocio se validan y crean en una fase posterior.",
                    "DDL ArcGIS no es una transaccion atomica: un fallo puede dejar una clase parcial. Se informa y se detiene, sin borrado automatico."])
    report_files(folder, report, model)
    emit(f"Informe: {folder}")
    try:
        if arcpy_module is None:
            import arcpy as arcpy_module
        a = arcpy_module
        report["arcgis"] = a.GetInstallInfo().get("Version")
        with a.EnvManager(overwriteOutput=False, outputMFlag="Disabled", outputZFlag="Enabled"):
            inventory, domains, projects, lock_observation = preflight(a, args, model)
            report["proyectos_en_padre"] = projects
            report["test_schema_lock_dataset_informativo"] = lock_observation
            if not lock_observation:
                report["advertencias"].append("TestSchemaLock del contenedor devolvio False; esta comprobacion no es concluyente en el ensayo local. ArcGIS verificara los bloqueos reales durante cada creacion.")
            for row in report["clases"]:
                row["accion"] = "VALIDADA_EXISTENTE" if row["nombre"].lower() in inventory else "CREAR"
            report["estado"] = "PREVALIDADO"
            report_files(folder, report, model)
            emit(f'Prevalidacion completa: {len(model["clases"])} clases. Campos con tipo pendiente: {sum(c["tipos_pendientes"] for c in report["clases"])}.')
            if apply:
                for c, row in zip(model["clases"], report["clases"]):
                    if row["accion"] == "VALIDADA_EXISTENTE":
                        emit(f'VALIDADA existente: {c["nombre"]}')
                        continue
                    report["clase_en_curso"] = c["nombre"]
                    report_files(folder, report, model)
                    # Revalidar antes de cada mutacion, incluso si otro proceso creo un objeto.
                    inventory, domains = engine.inspect(a, args, model, [c])
                    try:
                        engine.create(a, args, model, [c], inventory, domains)
                    except a.ExecuteError as operation_error:
                        # Algunas operaciones pueden informar error despues de aplicar
                        # el cambio. Nunca reintentarlas ni declararlas correctas a ciegas.
                        # Solo continuar si se demuestra el estado final completo.
                        gc.collect()
                        a.management.ClearWorkspaceCache(args.workspace)
                        try:
                            inventory, domains = verify_created(a, args, model, c)
                        except Exception as verification_error:
                            raise RuntimeError(f'{operation_error}\nLa comprobacion posterior tampoco confirma la clase completa: {verification_error}') from operation_error
                        warning = f'{c["nombre"]}: ArcGIS informo un error, pero la comprobacion posterior confirmo todos los campos, dominios, GlobalID, auditoria UTC y clase vacia. Mensaje original: {operation_error}'
                        report["advertencias"].append(warning)
                        emit(warning)
                    inventory, domains = verify_created(a, args, model, c)
                    row["accion"] = "CREADA_VERIFICADA"
                    report["completadas"].append(c["nombre"])
                    report["clase_en_curso"] = None
                    report_files(folder, report, model)
                    emit(f'CREADA y verificada: {c["nombre"]}')
                # Si todas existian, la validacion inicial ya comprobo el lote
                # y no hubo mutaciones: evitar releer todo el workspace otra vez.
                if report["completadas"]:
                    preflight(a, args, model)
            report["estado"] = "CREACION_VERIFICADA" if apply else "VALIDACION_OK_SIN_CAMBIOS"
    except Exception as exc:
        report["estado"] = "ERROR_DETENIDO"
        report["error"] = str(exc)
        raise
    finally:
        report["fin_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
        try:
            report_files(folder, report, model)
        except OSError as report_error:
            # Un fallo al registrar un error no debe ocultar la causa original.
            if not report.get("error"):
                raise
            emit(f'No se pudo guardar el estado final del informe: {report_error}. Error original: {report["error"]}')
        else:
            emit(f'Estado: {report["estado"]}. Informe: {report["archivo_informe"]}')
            emit(f'Resultado JSON: {report["archivo_resultado"]}')
    return folder, report


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--workspace", required=True)
    p.add_argument("--clase", action="append")
    p.add_argument("--todas", action="store_true")
    p.add_argument("--aplicar", action="store_true")
    p.add_argument("--database", default="ArcGisAWS")
    p.add_argument("--owner", default="gis")
    p.add_argument("--modelo")
    p.add_argument("--informes")
    v = p.parse_args(argv)
    run(v.workspace, v.clase, v.aplicar, v.todas, v.database, v.owner, v.modelo, v.informes)


if __name__ == "__main__":
    main()
