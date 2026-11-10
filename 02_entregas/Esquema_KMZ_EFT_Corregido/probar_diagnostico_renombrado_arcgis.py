"""Ensayo nativo de solo lectura sobre la GDB local ya usada en 1.6.

No abre conexiones SDE. Una fachada limita las APIs a lectura y mensajes.
"""
import hashlib
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import uuid

import arcpy

HERE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class ReadOnly:
    def __init__(self, wrapped, allowed, calls, prefix="arcpy"):
        self.wrapped, self.allowed, self.calls, self.prefix = wrapped, allowed, calls, prefix

    def __getattr__(self, key):
        name = self.prefix + "." + key
        if key not in self.allowed:
            self.calls.append({"api_bloqueada": name})
            raise AssertionError("API fuera del ensayo de lectura: " + name)
        item = getattr(self.wrapped, key)
        if isinstance(self.allowed[key], dict):
            return ReadOnly(item, self.allowed[key], self.calls, name)
        if callable(item):
            def call(*args, **kwargs):
                self.calls.append({"api": name})
                return item(*args, **kwargs)
            return call
        return item


def main():
    native = json.loads((HERE / "VALIDACION_NOMBRES_1_6_ARCGIS.json").read_text(encoding="utf-8"))
    gdb = Path(native["gdb"]).resolve()
    assert gdb.suffix == ".gdb" and gdb.is_dir()
    assert gdb.is_relative_to(HERE / "_validacion")
    previous = Path(native["informes"]["aplicar"])
    original_sha = sha(previous)
    production = HERE.parents[1] / "resultado.json"
    production_sha = sha(production)
    loader = importlib.machinery.SourceFileLoader("diagnostico_toolbox_native", str(HERE / "Diagnostico_Renombrado.pyt"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    toolbox_module = importlib.util.module_from_spec(spec)
    loader.exec_module(toolbox_module)
    tool = toolbox_module.DiagnosticarRenombrado()
    parameters = tool.getParameterInfo()
    assert len(parameters) == 6
    assert all(p.name != "mode" for p in parameters)
    assert toolbox_module.Toolbox().tools == [toolbox_module.DiagnosticarRenombrado]
    reports = HERE / "_validacion" / ("diagnostico16_" + uuid.uuid4().hex[:10])
    reports.mkdir()
    for index, value in enumerate((str(gdb), str(previous), "ArcGisAWS", "gis", str(reports))):
        parameters[index].value = value
    calls = []
    allowed = dict.fromkeys(("Describe", "Exists", "EnvManager", "ListDatasets", "ListFeatureClasses",
                            "ListTables", "ListFields", "ListIndexes", "GetInstallInfo",
                            "ValidateTableName", "ValidateFieldName", "AddMessage", "AddWarning", "AddError"), True)
    allowed["management"] = {"GetCount": True}
    allowed["da"] = {"ListDomains": True, "ListSubtypes": True}
    toolbox_module.arcpy = ReadOnly(arcpy, allowed, calls)
    tool.execute(parameters, None)
    result_path = Path(parameters[5].valueAsText)
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["estado"] == "SIN_DIFERENCIAS_ACTUALES", result["estado"]
    assert sha(previous) == original_sha
    assert sha(production) == production_sha
    assert not any("api_bloqueada" in call for call in calls)
    evidence = dict(
        diagnostico_version="1.6-diagnostico-1", arcgis=arcpy.GetInstallInfo()["Version"],
        validacion_sde=False, geodatabase=str(gdb), informe_original=str(previous),
        informe_original_sha256=original_sha, informe_original_conservado=True,
        informe_usuario_sha256=production_sha, informe_usuario_conservado=True,
        toolbox_cargada=True, parametros_verificados=True, toolbox_ejecutada=True,
        estado=result["estado"], informe_diagnostico=str(result_path),
        llamadas=sorted(set(x["api"] for x in calls)), llamadas_totales=len(calls),
        mutaciones_geodatabase=0,
        archivos_sha256={p: sha(HERE / p) for p in (
            "Diagnostico_Renombrado.pyt", "diagnostico_renombrado.py",
            "probar_diagnostico_renombrado_arcgis.py", "crear_esquema.py", "datos_proyecto.py",
            "ajustar_tipos_estructuras.py", "renombrar_clases.py",
            "actualizar_campos_aprobados.py", "validacion_texto_sqlserver.py",
            "esquema.json", "nombres_clases_1_6.json", "campos_aprobados_1_5.json")})
    output = HERE / "VALIDACION_DIAGNOSTICO_RENOMBRADO_ARCGIS.json"
    output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"estado": result["estado"], "informe": str(output), "mutaciones_gdb": 0}))


if __name__ == "__main__":
    main()
