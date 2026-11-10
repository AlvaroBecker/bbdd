"""Ensayo nativo de reanudacion 1.6.2 sobre clases locales ya normalizadas.

Solo permite APIs de lectura. No abre SDE ni altera la GDB de prueba existente.
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
    original = json.loads(previous.read_text(encoding="utf-8"))
    selected = sorted(original["campos_y_metadatos_antes"])
    assert selected == sorted(native["clases_ensayadas"])
    production = HERE.parents[1] / "resultado.json"
    production_sha = sha(production)

    loader = importlib.machinery.SourceFileLoader("reanudacion162_toolbox_native", str(HERE / "Datos_Proyecto.pyt"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    toolbox_module = importlib.util.module_from_spec(spec)
    loader.exec_module(toolbox_module)
    toolbox = toolbox_module.Toolbox()
    assert "1.6.2" in toolbox.label
    declared = toolbox.tools
    assert len(declared) == 6
    assert declared[4] is toolbox_module.RenombrarClases
    assert declared[5] is toolbox_module.DiagnosticarRenombrado
    parameter_inventory = {}
    for declared_tool in declared:
        parameters = declared_tool().getParameterInfo()
        parameter_inventory[declared_tool.__name__] = [p.name for p in parameters]
        if declared_tool is not toolbox_module.DiagnosticarRenombrado:
            assert next(p for p in parameters if p.name == "mode").valueAsText == "Validar (sin cambios)"
    renamer = toolbox_module.RenombrarClases()
    validation_parameters = renamer.getParameterInfo()
    application_parameters = renamer.getParameterInfo()
    expected_names = ["workspace", "mode", "classes", "database", "owner", "reports", "previous_report", "report"]
    assert [p.name for p in validation_parameters] == expected_names
    assert validation_parameters[6].parameterType == "Optional"
    assert validation_parameters[7].parameterType == "Derived"
    diagnostic = toolbox_module.DiagnosticarRenombrado()
    diagnostic_parameters = diagnostic.getParameterInfo()
    assert len(diagnostic_parameters) == 6
    assert all(p.name != "mode" for p in diagnostic_parameters)

    reports = HERE / "_validacion" / ("reanudacion162_" + uuid.uuid4().hex[:10])
    reports.mkdir()
    for parameters, action in ((validation_parameters, "Validar (sin cambios)"),
                               (application_parameters, "Aplicar nombres aprobados")):
        for index, value in enumerate((str(gdb), action, ";".join(selected), "ArcGisAWS", "gis", str(reports), str(previous))):
            parameters[index].value = value
    calls = []
    allowed = dict.fromkeys(("Describe", "Exists", "EnvManager", "ListDatasets", "ListFeatureClasses",
                            "ListTables", "ListFields", "ListIndexes", "GetInstallInfo", "TestSchemaLock",
                            "ValidateTableName", "ValidateFieldName", "AddMessage", "AddWarning", "AddError"), True)
    allowed["management"] = {"GetCount": True}
    allowed["da"] = {"ListDomains": True, "ListSubtypes": True, "SearchCursor": True}
    toolbox_module.arcpy = ReadOnly(arcpy, allowed, calls)

    emitted_reports = {}
    for label, parameters, expected in (
            ("validar", validation_parameters, "VALIDACION_OK_SIN_CAMBIOS"),
            ("aplicar_sin_repetir", application_parameters, "NOMBRES_VERIFICADOS")):
        renamer.execute(parameters, None)
        result_path = Path(parameters[7].valueAsText)
        result = json.loads(result_path.read_text(encoding="utf-8"))
        assert result["estado"] == expected, result["estado"]
        assert result["version_paquete"] == "1.6.2"
        assert result["completadas"] == []
        assert result["campos_y_metadatos_antes"] == original["campos_y_metadatos_antes"]
        assert result["informe_referencia"]["sha256"] == original_sha
        assert Path(result["informe_referencia"]["ruta"]) == previous
        assert set(result["rutas_referencia"]) == set(selected)
        emitted_reports[label] = str(result_path)
    # La sexta herramienta sigue comparando literalmente. Tambien debe poder
    # leer el informe 1.6.2 sin reemplazar la referencia original conservada.
    for index, value in enumerate((str(gdb), emitted_reports["aplicar_sin_repetir"], "ArcGisAWS", "gis", str(reports))):
        diagnostic_parameters[index].value = value
    diagnostic.execute(diagnostic_parameters, None)
    diagnostic_path = Path(diagnostic_parameters[5].valueAsText)
    diagnostic_result = json.loads(diagnostic_path.read_text(encoding="utf-8"))
    assert diagnostic_result["estado"] == "SIN_DIFERENCIAS_ACTUALES", diagnostic_result["estado"]
    emitted_reports["diagnostico"] = str(diagnostic_path)
    assert sha(previous) == original_sha
    assert sha(production) == production_sha
    assert not any("api_bloqueada" in call for call in calls)
    evidence = dict(
        version_paquete="1.6.2", arcgis=arcpy.GetInstallInfo()["Version"],
        validacion_sde=False, geodatabase=str(gdb), clases_ensayadas=selected,
        informe_original=str(previous), informe_original_sha256=original_sha,
        informe_original_conservado=True, referencia_original_preservada=True,
        informe_usuario_sha256=production_sha, informe_usuario_conservado=True,
        toolbox_cargada=True, parametros_verificados=True, toolbox_ejecutada=True,
        herramientas_declaradas=[t.__name__ for t in declared], parametros_herramientas=parameter_inventory,
        primeras_cinco_en_validacion=True, parametro_referencia_opcional=True,
        validacion_con_referencia=True, reanudacion_ya_aplicada_sin_repetir=True,
        estado="NOMBRES_VERIFICADOS", estado_diagnostico=diagnostic_result["estado"],
        estados={"validar": "VALIDACION_OK_SIN_CAMBIOS", "aplicar": "NOMBRES_VERIFICADOS",
                 "diagnostico": diagnostic_result["estado"]},
        informes=emitted_reports,
        llamadas=sorted(set(x["api"] for x in calls)), llamadas_totales=len(calls),
        mutaciones_geodatabase=0,
        alcance="Reanudacion con el informe original sobre tres clases locales ya normalizadas. El alias cualificado SDE se verifica por pruebas simuladas, no en esta GDB.",
        archivos_sha256={p: sha(HERE / p) for p in (
            "Datos_Proyecto.pyt", "diagnostico_renombrado.py",
            "probar_reanudacion_1_6_2_arcgis.py", "crear_esquema.py", "datos_proyecto.py",
            "ajustar_tipos_estructuras.py", "renombrar_clases.py",
            "actualizar_campos_aprobados.py", "validacion_texto_sqlserver.py", "reparar_texto_largo.py",
            "esquema.json", "nombres_clases_1_6.json", "campos_aprobados_1_5.json")})
    output = HERE / "VALIDACION_REANUDACION_1_6_2_ARCGIS.json"
    output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"estado": evidence["estado"], "informe": str(output), "mutaciones_gdb": 0}))


if __name__ == "__main__":
    main()
