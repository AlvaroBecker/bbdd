# -*- coding: utf-8 -*-
"""Caja de herramientas de transferencia neutral KMZ a ArcGisAWS."""
import datetime as dt
import importlib.util
import json
import logging
from pathlib import Path

import arcpy


HERE = Path(__file__).resolve().parent
MODES = ["Validar fuentes y conexion (sin cargar)",
         "Preparar solo geodatabases locales (sin SDE)",
         "Cargar a SDE (objetos nuevos en gis)",
         "Renombrar objetos ya cargados a nombres legibles"]
DEFAULT_SDE = (
    r"C:\Users\CT6788\Documents\ArcGIS\Projects\MyProject"
    r"\SQLServer-EEPAWSDBP01-ArcGisAWS(gis).sde"
)


def load_loader():
    path = HERE / "cargar_kmz_sde.py"
    spec = importlib.util.spec_from_file_location("mapline_kmz_sde_loader", path)
    if spec is None or spec.loader is None:
        raise ImportError("No se pudo cargar el script adjunto: " + str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def input_folders(parameter):
    return [Path(str(value)) for value in (parameter.values or [])]


class ArcGISLogHandler(logging.Handler):
    def emit(self, record):
        message = self.format(record)
        if record.levelno >= logging.ERROR:
            arcpy.AddError(message)
        elif record.levelno >= logging.WARNING:
            arcpy.AddWarning(message)
        else:
            arcpy.AddMessage(message)


class Toolbox:
    def __init__(self):
        self.label = "Mapline - Transferencia KMZ a SDE"
        self.alias = "maplinekmzsde"
        self.tools = [TransferirKMZSDE]


class TransferirKMZSDE:
    def __init__(self):
        self.label = "Transferir KMZ seleccionados a ArcGisAWS (gis)"
        self.description = (
            "Valida, prepara o carga KMZ seleccionados del inventario a objetos nuevos del esquema gis "
            "con nombres legibles (nombre_sde del inventario), o renombra cargas anteriores kmz_<hash>. "
            "Conserva lo ambiguo con trazabilidad y deja pendientes para ENGIE. "
            "No sobrescribe objetos ni aprueba el modelo tematico EFT."
        )
        self.canRunInBackground = False
        self._folder_signature = None

    def getParameterInfo(self):
        folders = arcpy.Parameter(
            displayName="Carpetas con KMZ originales (busca tambien en subcarpetas)",
            name="carpetas_kmz", datatype="DEFolder", multiValue=True,
            parameterType="Optional", direction="Input")
        mode = arcpy.Parameter(
            displayName="Operacion", name="operacion", datatype="GPString",
            parameterType="Required", direction="Input")
        mode.filter.type = "ValueList"
        mode.filter.list = MODES
        mode.value = MODES[0]
        connection = arcpy.Parameter(
            displayName="Conexion SDE destino (ArcGisAWS, propietario gis)",
            name="conexion_sde", datatype="DEWorkspace",
            parameterType="Optional", direction="Input")
        connection.filter.list = ["Remote Database"]
        if Path(DEFAULT_SDE).is_file():
            connection.value = DEFAULT_SDE
        output = arcpy.Parameter(
            displayName="Carpeta de trabajo existente (se creara una subcarpeta nueva por ejecucion)",
            name="carpeta_trabajo", datatype="DEFolder",
            parameterType="Optional", direction="Input")
        report = arcpy.Parameter(
            displayName="Informe JSON de la ejecucion", name="informe",
            datatype="DEFile", parameterType="Derived", direction="Output")
        execution = arcpy.Parameter(
            displayName="Carpeta de resultados de la ejecucion", name="resultados",
            datatype="DEFolder", parameterType="Derived", direction="Output")
        selected = arcpy.Parameter(
            displayName="KMZ a procesar (vacio: los 13 del inventario)",
            name="kmz_seleccionados", datatype="GPString", multiValue=True,
            parameterType="Optional", direction="Input")
        selected.filter.type = "ValueList"
        selected.filter.list = []
        resume = arcpy.Parameter(
            displayName="Continuar en una carpeta de ejecucion anterior (opcional)",
            name="reanudar_ejecucion", datatype="DEFolder",
            parameterType="Optional", direction="Input")
        return [folders, mode, connection, output, report, execution, selected, resume]

    def isLicensed(self):
        return True

    def updateParameters(self, parameters):
        renaming = parameters[1].valueAsText == MODES[3]
        parameters[0].enabled = not renaming
        parameters[2].enabled = parameters[1].valueAsText != MODES[1]
        parameters[3].enabled = not bool(parameters[7].valueAsText) and not renaming
        parameters[6].enabled = not renaming
        signature = tuple(str(folder) for folder in input_folders(parameters[0]))
        if signature != self._folder_signature:
            paths = set()
            for value in signature:
                folder = Path(value)
                if folder.is_dir():
                    paths.update(str(path.resolve()) for path in folder.rglob("*")
                                 if path.is_file() and path.suffix.lower() == ".kmz")
            choices = sorted(paths, key=str.casefold)
            parameters[6].filter.list = choices
            self._folder_signature = signature

    def updateMessages(self, parameters):
        renaming = parameters[1].valueAsText == MODES[3]
        if renaming:
            parameters[1].setWarningMessage(
                "Quite del mapa las capas de los objetos cargados y cierre otras sesiones que los usen: "
                "renombrar requiere bloqueo exclusivo. No copia ni borra datos.")
            if not parameters[7].valueAsText:
                parameters[7].setErrorMessage("Seleccione la carpeta de ejecucion que cargo los objetos a renombrar.")
        elif not input_folders(parameters[0]):
            parameters[0].setErrorMessage("Seleccione al menos una carpeta de KMZ.")
        selected = [str(value) for value in (parameters[6].values or [])]
        if not renaming and any(value not in parameters[6].filter.list for value in selected):
            parameters[6].setErrorMessage(
                "Hay KMZ seleccionados fuera de las carpetas actuales. Corrija la seleccion; "
                "no se ampliara automaticamente a todo el inventario.")
        if not parameters[7].valueAsText and not parameters[3].valueAsText and not renaming:
            parameters[3].setErrorMessage("Seleccione una carpeta de trabajo o una ejecucion para continuar.")
        if parameters[7].valueAsText:
            resume = Path(parameters[7].valueAsText)
            if not (resume / "informe.json").is_file() or not (resume / "trazabilidad.sqlite").is_file():
                parameters[7].setErrorMessage(
                    "Seleccione la subcarpeta de ejecucion que contiene informe.json y trazabilidad.sqlite.")
        if parameters[1].valueAsText != MODES[1] and not parameters[2].valueAsText:
            parameters[2].setErrorMessage("Seleccione la conexion .sde para validar, cargar o renombrar.")
        if not (HERE / "cargar_kmz_sde.py").is_file() or not (HERE / "01_archivos.csv").is_file():
            parameters[1 if renaming else 0].setErrorMessage(
                "Mantenga cargar_kmz_sde.py y 01_archivos.csv junto a esta caja de herramientas.")
        work_value = parameters[7].valueAsText or parameters[3].valueAsText
        if work_value:
            try:
                work = Path(work_value).resolve()
                for source in [] if renaming else input_folders(parameters[0]):
                    source = source.resolve()
                    if work == source or source in work.parents:
                        parameters[7 if parameters[7].valueAsText else 3].setErrorMessage(
                            "La carpeta de trabajo debe estar fuera de las carpetas de KMZ.")
                        break
            except (OSError, ValueError) as error:
                parameters[3].setErrorMessage("No se pudo comprobar la ruta: " + str(error))

    def execute(self, parameters, messages):
        folders = input_folders(parameters[0])
        mode = parameters[1].valueAsText
        if mode not in MODES:
            arcpy.AddError("Seleccione una operacion de la lista.")
            raise arcpy.ExecuteError
        renaming = mode == MODES[3]
        if not folders and not renaming:
            arcpy.AddError("Seleccione al menos una carpeta de KMZ.")
            raise arcpy.ExecuteError
        if renaming and not parameters[7].valueAsText:
            arcpy.AddError("Seleccione la carpeta de ejecucion que cargo los objetos a renombrar.")
            raise arcpy.ExecuteError
        if mode != MODES[1] and not parameters[2].valueAsText:
            arcpy.AddError("La conexion SDE es obligatoria para validar, cargar o renombrar.")
            raise arcpy.ExecuteError
        work_value = parameters[7].valueAsText or parameters[3].valueAsText
        if not work_value:
            arcpy.AddError("Seleccione carpeta de trabajo o ejecucion anterior.")
            raise arcpy.ExecuteError
        parent = Path(work_value)
        if not parent.is_dir():
            arcpy.AddError("Seleccione una carpeta de trabajo existente.")
            raise arcpy.ExecuteError
        timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
        output = parent if parameters[7].valueAsText else parent / ("Mapline_KMZ_" + timestamp)
        argv = ["--reanudar" if parameters[7].valueAsText else "--salida", str(output),
                "--inventario", str(HERE / "01_archivos.csv")]
        if not renaming:
            for folder in folders:
                argv.extend(["--entrada", str(folder)])
            for value in parameters[6].values or []:
                argv.extend(["--kmz", str(value)])
        if mode == MODES[1]:
            argv.append("--solo-preparar")
        else:
            argv.extend(["--sde", parameters[2].valueAsText])
            if mode == MODES[2]:
                argv.append("--aplicar")
            elif renaming:
                argv.append("--renombrar")
        handler = ArcGISLogHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        loader = load_loader()
        loader.LOG.addHandler(handler)
        arcpy.AddMessage("Operacion: " + mode)
        arcpy.AddMessage("Resultados: " + str(output))
        result_reports = []
        try:
            with arcpy.EnvManager(overwriteOutput=False, qualifiedFieldNames=False,
                                  extent=None, outputCoordinateSystem=None, addOutputsToMap=False):
                try:
                    code = loader.main(argv, result_reports=result_reports)
                except (OSError, ValueError, RuntimeError) as error:
                    arcpy.AddError(str(error))
                    raise arcpy.ExecuteError from error
        finally:
            loader.LOG.removeHandler(handler)
            handler.close()
            if output.is_dir():
                parameters[5].value = str(output)
            report_path = result_reports[-1] if result_reports else output / "informe.json"
            if report_path.is_file():
                parameters[4].value = str(report_path)
        if code != 0:
            arcpy.AddError(
                "La ejecucion no termino correctamente. Revise el informe de salida y ejecucion.log. "
                "No repita una carga parcial sin revisar los objetos ya creados.")
            raise arcpy.ExecuteError
        report = json.loads(report_path.read_text(encoding="utf-8"))
        arcpy.AddMessage("Resultado: " + report["state"])
        arcpy.AddMessage("Informe: " + str(report_path))
