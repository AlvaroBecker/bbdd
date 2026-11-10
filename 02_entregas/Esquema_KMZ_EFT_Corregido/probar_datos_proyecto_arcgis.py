"""Ensayo aislado. Crea solamente una GDB de prueba bajo _validacion."""
import datetime as dt
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import uuid

import arcpy as a
import datos_proyecto as runner


def main():
    base = Path(__file__).resolve().parent / "_validacion"
    base.mkdir(exist_ok=True)
    folder = base / ("controlado_" + dt.datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6])
    folder.mkdir()
    gdb = str(folder / "ensayo.gdb")
    a.management.CreateFileGDB(str(folder), "ensayo.gdb")
    names = ["estructuras", "accesos", "red_vial_nacional_mtc_recorte", "subestacion_poligono"]
    tests = []

    def run(**kwargs):
        return runner.run(gdb, reports=folder, arcpy_module=a, **kwargs)

    try:
        run(names=["estructuras"], apply=True)
        raise AssertionError("Acepto un destino sin dataset")
    except ValueError as exc:
        assert "No existe Datos_Proyecto" in str(exc), exc
    assert not a.Exists(gdb + "/Datos_Proyecto")
    tests.append("Rechaza dataset ausente sin crearlo")
    ds = a.management.CreateFeatureDataset(gdb, "Datos_Proyecto", a.SpatialReference(4326)).getOutput(0)
    try:
        run(names=["estructuras"], apply=True)
        raise AssertionError("Acepto padre ausente")
    except ValueError as exc:
        assert "Falta la tabla real" in str(exc), exc
    assert not a.Exists(ds + "/estructuras")
    tests.append("Rechaza padre ausente sin crear clases")
    parent = a.management.CreateTable(gdb, "mline_tc_proyecto").getOutput(0)
    a.management.AddField(parent, "co_proyecto", "TEXT", field_length=12)
    with a.da.InsertCursor(parent, ["co_proyecto"]) as cursor:
        cursor.insertRow(["PRY-00000001"])

    # Un conflicto al final del lote debe impedir incluso la primera clase nueva.
    a.management.CreateFeatureclass(ds, "subestacion_poligono", "POINT", spatial_reference=a.SpatialReference(4326))
    try:
        run(names=names, apply=True)
        raise AssertionError("Acepto geometria incompatible")
    except ValueError as exc:
        assert "incompatible" in str(exc), exc
    assert not a.Exists(ds + "/accesos")
    assert not a.da.ListDomains(gdb)
    tests.append("Conflicto tardio bloquea todo el lote antes de crear dominios o clases")
    # Borrar exclusivamente el objeto sintetico que este ensayo acaba de crear.
    a.management.Delete(ds + "/subestacion_poligono")
    _, plan = run(names=names)
    assert plan["estado"] == "VALIDACION_OK_SIN_CAMBIOS"
    assert all(not a.Exists(ds + "/" + n) for n in names)
    assert not a.da.ListDomains(gdb)
    tests.append("Diagnostico no modifica la geodatabase")
    _, created = run(names=names, apply=True)
    assert created["estado"] == "CREACION_VERIFICADA"
    assert len(created["completadas"]) == len(names)
    for name in names:
        desc = a.Describe(ds + "/" + name)
        assert desc.hasZ and not desc.hasM and desc.hasGlobalID
        assert desc.editorTrackingEnabled and desc.isTimeInUTC
        assert int(a.management.GetCount(ds + "/" + name).getOutput(0)) == 0
    tests.append("Crea y verifica punto, linea y poligono; incluye red vial nacional con el esquema vigente")
    with a.EnvManager(workspace=gdb):
        assert a.ListDatasets(feature_type="Feature") == ["Datos_Proyecto"]
    tests.append("No crea Datos_Externos ni Datos_Internos")
    _, repeated = run(names=names, apply=True)
    assert not repeated["completadas"]
    assert all(c["accion"] == "VALIDADA_EXISTENTE" for c in repeated["clases"])
    tests.append("Repeticion valida sin duplicar ni recrear")

    # Carga de la toolbox y ejecucion real de su accion por defecto.
    path = str(Path(__file__).with_name("Datos_Proyecto.pyt"))
    loader = importlib.machinery.SourceFileLoader("toolbox_prueba", path)
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    tool = module.PrepararDatosProyecto()
    params = tool.getParameterInfo()
    assert params[1].valueAsText == "Validar (sin cambios)"
    params[0].value = gdb
    params[2].values = ["estructuras"]
    params[5].value = str(folder)
    tool.execute(params, None)
    assert Path(params[6].valueAsText).is_file()
    tests.append("Toolbox abre parametros y ejecuta validacion con salida JSON")
    result = dict(arcgis=a.GetInstallInfo()["Version"], pruebas=tests, gdb=gdb,
                  clases=names, validacion_sde=False, validacion_branch=False,
                  alcance="Creacion de clases vacias; no valida semantica ni tipos definitivos de los KMZ")
    Path(__file__).with_name("VALIDACION_DATOS_PROYECTO.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
