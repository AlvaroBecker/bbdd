import importlib
import json
import logging
import os
import sys

import arcpy


def _modulo():
    carpeta = os.path.dirname(os.path.abspath(__file__))
    if carpeta not in sys.path:
        sys.path.insert(0, carpeta)
    if "cargar_eft" in sys.modules:
        return importlib.reload(sys.modules["cargar_eft"])
    import cargar_eft
    return cargar_eft


class Toolbox:
    def __init__(self):
        self.label = "Mapline KMZ - EFT"
        self.alias = "Mapline_KMZ_EFT"
        self.tools = [MaplineEFT]


class _ArcPyHandler(logging.Handler):
    def emit(self, record):
        mensaje = self.format(record)
        if record.levelno >= logging.ERROR:
            arcpy.AddError(mensaje)
        elif record.levelno >= logging.WARNING:
            arcpy.AddWarning(mensaje)
        else:
            arcpy.AddMessage(mensaje)


class MaplineEFT:
    def __init__(self):
        self.label = "Preparar KMZ segun EFT 5.8"
        self.description = (
            "Propone el mapeo editable, prepara una geodatabase local y permite crear/cargar/versionar "
            "la estructura EFT en SDE. No reprocesa los KMZ."
        )
        self.canRunInBackground = False

    def getParameterInfo(self):
        modo = arcpy.Parameter(
            displayName="Operacion", name="modo", datatype="GPString", parameterType="Required", direction="Input"
        )
        modo.filter.type = "ValueList"
        modo.filter.list = ["PROPONER", "PREPARAR_LOCAL", "ESTRUCTURA_SDE", "CARGAR_SDE",
                            "VERSIONAR_SDE", "RETIRAR_KMZ"]
        modo.value = "PROPONER"

        trabajo = arcpy.Parameter(
            displayName="Carpeta de trabajo de la transferencia", name="trabajo",
            datatype="DEFolder", parameterType="Required", direction="Input"
        )

        kmz = arcpy.Parameter(
            displayName="KMZ preparados (vacio = todos)", name="kmz",
            datatype="GPString", parameterType="Optional", direction="Input", multiValue=True
        )
        kmz.filter.type = "ValueList"

        mapeo = arcpy.Parameter(
            displayName="Mapeo EFT CSV", name="mapeo", datatype="DEFile",
            parameterType="Optional", direction="Input"
        )
        mapeo.filter.list = ["csv"]

        sde = arcpy.Parameter(
            displayName="Conexion geodatabase enterprise", name="sde", datatype="DEWorkspace",
            parameterType="Optional", direction="Input"
        )
        sde.filter.list = ["Remote Database"]

        completa = arcpy.Parameter(
            displayName="Crear todas las clases EFT (no solo las del mapeo)", name="estructura_completa",
            datatype="GPBoolean", parameterType="Optional", direction="Input"
        )
        completa.value = False

        analisis = arcpy.Parameter(
            displayName="ID de analisis", name="id_analisis", datatype="GPString",
            parameterType="Optional", direction="Input"
        )
        analisis.value = "Carga inicial KMZ"

        confirmar = arcpy.Parameter(
            displayName="Confirmo retirar las entidades de los KMZ seleccionados", name="confirmar_retiro",
            datatype="GPBoolean", parameterType="Optional", direction="Input"
        )
        confirmar.value = False

        regenerar = arcpy.Parameter(
            displayName="Respaldar y regenerar mapeo (conservar comentarios)", name="regenerar",
            datatype="GPBoolean", parameterType="Optional", direction="Input"
        )
        regenerar.value = False

        resultado = arcpy.Parameter(
            displayName="Resultado", name="resultado", datatype="GPString",
            parameterType="Derived", direction="Output"
        )
        return [modo, trabajo, kmz, mapeo, sde, completa, analisis, confirmar, regenerar, resultado]

    def isLicensed(self):
        return True

    def updateParameters(self, parameters):
        modo = parameters[0].valueAsText or "PROPONER"
        carpeta = parameters[1].valueAsText
        requiere_sde = modo in ("ESTRUCTURA_SDE", "CARGAR_SDE", "VERSIONAR_SDE", "RETIRAR_KMZ")
        parameters[4].enabled = requiere_sde
        parameters[5].enabled = modo == "ESTRUCTURA_SDE"
        parameters[6].enabled = modo in ("PREPARAR_LOCAL", "CARGAR_SDE")
        parameters[7].enabled = modo == "RETIRAR_KMZ"
        parameters[8].enabled = modo == "PROPONER"
        if carpeta:
            info = os.path.join(carpeta, "informe.json")
            if os.path.isfile(info):
                try:
                    with open(info, "r", encoding="utf-8-sig") as archivo:
                        estado = json.load(archivo)
                    fuentes = {}
                    for fuente in estado.get("sources") or []:
                        nombre = os.path.basename(fuente.get("file") or "")
                        if nombre:
                            fuentes[nombre] = nombre
                    parameters[2].filter.list = sorted(fuentes, key=str.casefold)
                except (OSError, ValueError) as exc:
                    arcpy.AddWarning("No se pudo leer el catalogo de KMZ del informe.json: " + str(exc))
            default_mapeo = os.path.join(carpeta, "eft", "mapeo_eft.csv")
            if not parameters[3].altered and os.path.isfile(default_mapeo):
                parameters[3].value = default_mapeo
        return

    def updateMessages(self, parameters):
        modo = parameters[0].valueAsText
        if modo in ("ESTRUCTURA_SDE", "CARGAR_SDE", "VERSIONAR_SDE", "RETIRAR_KMZ") and not parameters[4].valueAsText:
            parameters[4].setErrorMessage("Seleccione la conexion .sde.")
        if modo == "RETIRAR_KMZ" and not parameters[2].valueAsText:
            parameters[2].setErrorMessage("Seleccione al menos un KMZ; retirar sin selector no esta permitido.")
        return

    def execute(self, parameters, messages):
        modulo = _modulo()
        handler = _ArcPyHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        modulo.LOGGER.addHandler(handler)
        try:
            modo = parameters[0].valueAsText
            trabajo = parameters[1].valueAsText
            seleccion = [x for x in (parameters[2].valueAsText or "").split(";") if x]
            mapping_path = parameters[3].valueAsText
            sde = parameters[4].valueAsText
            resultado = modulo.ejecutar(
                modo, trabajo, sde=sde, kmz=seleccion, mapping_path=mapping_path,
                id_analisis=parameters[6].valueAsText or "Carga inicial KMZ",
                completa=bool(parameters[5].value), confirmar=bool(parameters[7].value),
                regenerar=bool(parameters[8].value), arcpy=arcpy,
            )
            texto = resultado["result"].get("status", resultado["mode"])
            parameters[9].value = texto
            arcpy.AddMessage("Resultado: " + texto)
        except Exception as exc:
            arcpy.AddError(f"Operacion EFT fallida: {exc}")
            raise
        finally:
            modulo.LOGGER.removeHandler(handler)


if __name__ == "__main__":
    pass
