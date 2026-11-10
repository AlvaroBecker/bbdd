"""Prueba local del modelo sin extensiones, nunca conecta a SDE."""
import datetime as dt
import argparse
import json
from pathlib import Path
import uuid

import arcpy as a
import datos_proyecto as runner


def main():
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', help='Solo una GDB sintetica existente bajo _validacion/eft12_*')
    parser.add_argument('--preparar', action='store_true')
    args = parser.parse_args()
    if args.workspace:
        path = Path(args.workspace).resolve()
        assert path.suffix == '.gdb' and path.is_relative_to(here / '_validacion') and path.parent.name.startswith('eft12_')
        folder = path.parent
        gdb = str(path)
        ds = gdb + '/Datos_Proyecto'
    else:
        folder = here / "_validacion" / ("eft12_" + dt.datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8])
        folder.mkdir(parents=True)
        gdb = a.management.CreateFileGDB(str(folder), "ensayo.gdb").getOutput(0)
        ds = a.management.CreateFeatureDataset(gdb, "Datos_Proyecto", a.SpatialReference(4326)).getOutput(0)
        parent = a.management.CreateTable(gdb, "mline_tc_proyecto").getOutput(0)
        a.management.AddField(parent, "co_proyecto", "TEXT", field_length=12)
        with a.da.InsertCursor(parent, ["co_proyecto"]) as cur:
            cur.insertRow(["PRY-00000001"])
    if args.preparar:
        print(gdb, flush=True)
        return
    names = ["estructuras", "area_estudio_campo"]
    _, report = runner.run(gdb, names, apply=True, reports=folder, arcpy_module=a)
    assert report["estado"] == "CREACION_VERIFICADA"
    fields = {f.name for f in a.ListFields(ds + "/estructuras")}
    assert len(fields) == 41
    assert not {"descripcion_origen", "tipo_tema", "codigo_estacion", "tema", "id_origen"} & fields
    assert "codigo_estacion" in {f.name for f in a.ListFields(ds + "/area_estudio_campo")}
    _, repeated = runner.run(gdb, names, apply=True, reports=folder, arcpy_module=a)
    assert not repeated["completadas"]
    # Unicamente la clase sintetica de este ensayo recibe una extension,
    # para comprobar que una clase de version anterior no se acepta en silencio.
    a.management.AddField(ds + "/estructuras", "descripcion_origen", "TEXT", field_length=80)
    try:
        runner.run(gdb, ["estructuras", "calicatas"], apply=True, reports=folder, arcpy_module=a)
        raise AssertionError("Se acepto una extension fuera del modelo")
    except ValueError as exc:
        assert "campos fuera del esquema EFT" in str(exc), exc
    assert not a.Exists(ds + "/calicatas")
    result = dict(version_paquete="1.2", arcgis=a.GetInstallInfo()["Version"],
                  clases_creadas=names, estructuras_campos_modelo=34, estructuras_campos_fisicos=41,
                  codigo_estacion_en_area_estudio=True, segunda_ejecucion_sin_duplicados=True,
                  extension_existente_bloquea_lote=True, gdb=gdb, validacion_sde=False,
                  preparacion_en_proceso_separado=bool(args.workspace),
                  alcance="Campos y estructura; tipos y mapeos de carga siguen pendientes")
    (here / "VALIDACION_CAMPOS_EFT_ARCGIS.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
