"""Compara el estado actual con el informe original; no modifica la geodatabase."""
import importlib.util
from pathlib import Path
import sys

import arcpy

HERE = Path(__file__).resolve().parent


def load_diagnostic():
    # Resolver siempre los modulos de esta entrega, no los de otra toolbox abierta.
    for name in ("crear_esquema", "datos_proyecto", "ajustar_tipos_estructuras",
                 "validacion_texto_sqlserver", "actualizar_campos_aprobados",
                 "renombrar_clases", "diagnostico_renombrado"):
        spec = importlib.util.spec_from_file_location(name, HERE / (name + ".py"))
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules["diagnostico_renombrado"]


class Toolbox:
    def __init__(self):
        self.label = "Diagnostico de renombrado 1.6 (solo lectura)"
        self.alias = "diagnosticorenombradoeft"
        self.tools = [DiagnosticarRenombrado]


class DiagnosticarRenombrado:
    def __init__(self):
        self.label = "Comparar con el informe original de renombrado"
        self.description = (
            "Lee todas las clases incluidas en el informe original 1.6. "
            "Compara campos, indices y geometria y guarda las diferencias. "
            "No renombra, altera, crea ni elimina objetos de la geodatabase."
        )
        self.canRunInBackground = False

    def getParameterInfo(self):
        def parameter(name, label, datatype):
            return arcpy.Parameter(name=name, displayName=label, datatype=datatype,
                                   parameterType="Required", direction="Input")

        workspace = parameter("workspace", "Conexion .sde / geodatabase de la ejecucion original", "DEWorkspace")
        previous = parameter("previous_report", "Resultado JSON original del renombrado", "DEFile")
        previous.filter.list = ["json"]
        if (HERE / "resultado_origen.json").is_file():
            previous.value = str(HERE / "resultado_origen.json")
        database = parameter("database", "Base de datos esperada", "GPString")
        database.value = "ArcGisAWS"
        owner = parameter("owner", "Propietario esperado", "GPString")
        owner.value = "gis"
        reports = parameter("reports", "Carpeta existente para los informes", "DEFolder")
        reports.value = str(HERE)
        output = arcpy.Parameter(name="report", displayName="Diagnostico JSON", datatype="DEFile",
                                 parameterType="Derived", direction="Output")
        return [workspace, previous, database, owner, reports, output]

    def execute(self, parameters, messages):
        diagnostic = load_diagnostic()
        try:
            _, report = diagnostic.run(
                parameters[0].valueAsText, parameters[1].valueAsText,
                database=parameters[2].valueAsText, owner=parameters[3].valueAsText,
                reports=parameters[4].valueAsText, arcpy_module=arcpy, emit=arcpy.AddMessage)
            parameters[5].value = report["archivo_resultado"]
            if report["estado"] != "SIN_DIFERENCIAS_ACTUALES":
                arcpy.AddWarning("Revise el diagnostico generado antes de continuar el renombrado.")
            else:
                arcpy.AddMessage("La comparacion actual no explica por si sola el fallo anterior; conserve ambos informes.")
        except Exception as exc:
            arcpy.AddError(str(exc))
            raise
