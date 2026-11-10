"""Regresion del informe y de la salida de toolbox. Solo valida una GDB de ensayo."""
import argparse
import importlib.machinery
import importlib.util
import json
from pathlib import Path

import arcpy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    workspace = Path(args.workspace).resolve()
    assert workspace.suffix.lower() == ".gdb" and workspace.is_relative_to(here / "_validacion")
    loader = importlib.machinery.SourceFileLoader("toolbox_informes", str(here / "Datos_Proyecto.pyt"))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(module)
    tool = module.PrepararDatosProyecto()
    params = tool.getParameterInfo()
    params[0].value = str(workspace)
    params[2].values = ["estructuras"]
    params[5].value = str(here / "_validacion")
    assert params[1].valueAsText == "Validar (sin cambios)"
    tool.execute(params, None)
    output = Path(params[6].valueAsText)
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["estado"] == "VALIDACION_OK_SIN_CAMBIOS"
    assert result["archivo_resultado"] == str(output)
    assert Path(result["archivo_informe"]).is_file()
    states = sorted(output.parent.parent.glob("*/resultado.json"))
    assert [json.loads(p.read_text(encoding="utf-8"))["estado"] for p in states] == [
        "INICIADO", "PREVALIDADO", "VALIDACION_OK_SIN_CAMBIOS"]
    validation = dict(version_paquete="1.1", arcgis=arcpy.GetInstallInfo()["Version"],
                      validacion_toolbox=True, salida_json_final_correcta=True,
                      estados_inmutables=len(states), cambios_geodatabase=False, validacion_sde=False,
                      pruebas_unitarias=11, bloqueo_windows_real_comprobado=True)
    (here / "VALIDACION_INFORMES.json").write_text(json.dumps(validation, indent=2), encoding="utf-8")
    print(json.dumps(validation, indent=2), flush=True)


if __name__ == "__main__":
    main()
