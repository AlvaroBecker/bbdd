"""Herramienta ArcGIS Pro: validacion por defecto, creacion por seleccion."""
import importlib.util
import json
from pathlib import Path
import sys

import arcpy

HERE = Path(__file__).resolve().parent


def load_runner():
    # Cargar el motor de esta carpeta, aunque exista otra version en sys.path.
    for name in ("normalizacion_kmz", "crear_esquema", "datos_proyecto", "referencia_cierre_tipos", "ajustar_tipos_estructuras", "validacion_texto_sqlserver", "actualizar_campos_aprobados", "reparar_texto_largo", "renombrar_clases", "diagnostico_renombrado", "verificar_textos_confirmados", "inspeccion_kmz", "validar_tipos_kmz", "cerrar_tipos_kmz", "fuentes_ingesta", "proyectos_ingesta", "plan_ingesta", "prevalidar_ingesta", "alta_proyectos_logica", "alta_proyectos", "configurar_proyecto", "reglas_sunarp_ingesta", "cobertura_ingesta", "inspeccionar_negocio_ingesta", "descripciones_ingesta", "preparar_carga_inicial"):
        spec = importlib.util.spec_from_file_location(name, HERE / (name + ".py"))
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules["datos_proyecto"]


class Toolbox:
    def __init__(self):
        self.label = "Datos Proyecto - esquema controlado 1.13"
        self.alias = "datosproyectoeft"
        self.tools = [PrepararDatosProyecto, AjustarTiposEstructuras, ActualizarCamposAprobados, RepararTextoLargo, RenombrarClases, DiagnosticarRenombrado, ValidarTextosConfirmados, ValidarTodosTiposKMZ, CerrarTiposKMZ, PrevalidarIngesta, RegistrarProyectosFaltantes, ConfigurarCatalogoProyectos, PrepararCargaInicialKMZ]


class PrepararCargaInicialKMZ:
    def __init__(self):
        self.label = "Preparar carga inicial de los KMZ"
        self.description = ("Reune las reglas de proyecto y analisis, separa oficinas SUNARP en campos existentes, "
            "propone destinos por tema y lee las claves de negocio. Genera un plan revisable; no crea clases ni carga registros.")
        self.canRunInBackground = False

    def getParameterInfo(self):
        def parameter(name, label, datatype, required=True):
            return arcpy.Parameter(name=name, displayName=label, datatype=datatype,
                parameterType="Required" if required else "Optional", direction="Input")
        workspace = parameter("workspace", "Conexion .sde / geodatabase existente", "DEWorkspace")
        sources = parameter("kmz_dir", "Carpeta raiz de los 13 KMZ", "DEFolder")
        mapping = parameter("project_csv", "CSV de proyectos confirmados", "DEFile", False)
        mapping.filter.list = ["csv"]
        mapping.value = str(HERE / "confirmar_proyectos_13_confirmados.csv")
        database = parameter("database", "Base de datos esperada", "GPString")
        database.value = "ArcGisAWS"
        owner = parameter("owner", "Propietario esperado", "GPString")
        owner.value = "gis"
        reports = parameter("reports", "Carpeta existente para los informes", "DEFolder")
        reports.value = str(HERE)
        output = arcpy.Parameter(name="report", displayName="Informe JSON", datatype="DEFile",
            parameterType="Derived", direction="Output")
        return [workspace, sources, mapping, database, owner, reports, output]

    def execute(self, parameters, messages):
        load_runner()
        try:
            _, report = sys.modules['preparar_carga_inicial'].run(parameters[0].valueAsText,
                kmz_dir=parameters[1].valueAsText, project_csv=parameters[2].valueAsText,
                database=parameters[3].valueAsText, owner=parameters[4].valueAsText,
                reports=parameters[5].valueAsText, arcpy_module=arcpy, emit=arcpy.AddMessage)
            parameters[6].value = report['archivo_resultado']
            arcpy.AddWarning("Plan generado. Revise cobertura y claves de negocio en resultado.json; no se cargaron registros.")
        except Exception as exc:
            arcpy.AddError(str(exc))
            raise


class PrepararDatosProyecto:
    def __init__(self):
        self.label = "Validar o crear clases en Datos_Proyecto"
        self.description = "Trabaja solo en el dataset existente. Valida todo el lote antes de crear. No carga datos ni crea relaciones."
        self.canRunInBackground = False

    def getParameterInfo(self):
        def parameter(name, label, datatype, required=True, direction="Input", multi=False):
            return arcpy.Parameter(name=name, displayName=label, datatype=datatype,
                                   parameterType="Required" if required else "Optional", direction=direction, multiValue=multi)
        workspace = parameter("workspace", "Conexion .sde / geodatabase existente", "DEWorkspace")
        mode = parameter("mode", "Accion", "GPString")
        mode.filter.type = "ValueList"
        mode.filter.list = ["Validar (sin cambios)", "Crear clases vacias"]
        mode.value = "Validar (sin cambios)"
        classes = parameter("classes", "Clases seleccionadas", "GPString", multi=True)
        classes.filter.type = "ValueList"
        model = json.loads((HERE / "esquema.json").read_text(encoding="utf-8"))
        classes.filter.list = sorted(c["nombre"] for c in model["clases"] if c["dataset"] == "Datos_Proyecto")
        classes.value = "estructuras"
        database = parameter("database", "Base de datos esperada", "GPString")
        database.value = "ArcGisAWS"
        owner = parameter("owner", "Propietario esperado", "GPString")
        owner.value = "gis"
        reports = parameter("reports", "Carpeta existente para los informes", "DEFolder")
        reports.value = str(HERE)
        output = arcpy.Parameter(name="report", displayName="Informe JSON", datatype="DEFile", parameterType="Derived", direction="Output")
        return [workspace, mode, classes, database, owner, reports, output]

    def updateMessages(self, parameters):
        names = {str(v) for v in (parameters[2].values or [])}
        model = json.loads((HERE / "esquema.json").read_text(encoding="utf-8"))
        pending = sum("pendiente" in f.get("origen", "").lower()
                      for c in model["clases"] if c["nombre"] in names for f in c["campos"])
        if pending:
            parameters[1].setWarningMessage(f"La seleccion tiene {pending} campos con tipo provisional. Revise el informe antes de crear y cierre la revision antes de cargar datos.")

    def execute(self, parameters, messages):
        runner = load_runner()
        names = [str(v) for v in parameters[2].values]
        try:
            folder, report = runner.run(parameters[0].valueAsText, names=names,
                apply=parameters[1].valueAsText == "Crear clases vacias",
                database=parameters[3].valueAsText, owner=parameters[4].valueAsText,
                reports=parameters[5].valueAsText, arcpy_module=arcpy, emit=arcpy.AddMessage)
            parameters[6].value = report["archivo_resultado"]
            pending = sum(c["tipos_pendientes"] for c in report["clases"])
            if pending:
                arcpy.AddWarning(f"{pending} campos mantienen tipo provisional. Revisar campos.csv antes de cargar datos.")
        except Exception as exc:
            arcpy.AddError(str(exc))
            raise


class AjustarTiposEstructuras:
    def __init__(self):
        self.label = "Actualizar tipos de estructuras"
        self.description = "Valida o cambia exclusivamente los siete tipos aprobados a DOUBLE. Requiere estructuras vacia y sin versionar."
        self.canRunInBackground = False

    def getParameterInfo(self):
        def parameter(name,label,datatype):
            return arcpy.Parameter(name=name,displayName=label,datatype=datatype,parameterType='Required',direction='Input')
        workspace=parameter('workspace','Conexion .sde / geodatabase existente','DEWorkspace')
        mode=parameter('mode','Accion','GPString')
        mode.filter.type='ValueList'
        mode.filter.list=['Validar (sin cambios)','Aplicar tipos aprobados']
        mode.value='Validar (sin cambios)'
        database=parameter('database','Base de datos esperada','GPString');database.value='ArcGisAWS'
        owner=parameter('owner','Propietario esperado','GPString');owner.value='gis'
        reports=parameter('reports','Carpeta existente para los informes','DEFolder');reports.value=str(HERE)
        output=arcpy.Parameter(name='report',displayName='Informe JSON',datatype='DEFile',parameterType='Derived',direction='Output')
        return [workspace,mode,database,owner,reports,output]

    def execute(self,parameters,messages):
        load_runner()
        migration=sys.modules['ajustar_tipos_estructuras']
        try:
            _,report=migration.run(parameters[0].valueAsText,
                apply=parameters[1].valueAsText=='Aplicar tipos aprobados',
                database=parameters[2].valueAsText,owner=parameters[3].valueAsText,
                reports=parameters[4].valueAsText,arcpy_module=arcpy,emit=arcpy.AddMessage)
            parameters[5].value=report['archivo_resultado']
        except Exception as exc:
            arcpy.AddError(str(exc))
            raise


class ActualizarCamposAprobados:
    def __init__(self):
        self.label = "Actualizar campos aprobados de Datos_Proyecto"
        self.description = "Valida los 99 cambios aprobados y reanuda los pendientes. En SQL Server repare primero el texto largo con la herramienta especifica. Solo clases existentes vacias y sin versionar."
        self.canRunInBackground = False

    def getParameterInfo(self):
        def parameter(name,label,datatype,multi=False):
            return arcpy.Parameter(name=name,displayName=label,datatype=datatype,parameterType='Required',direction='Input',multiValue=multi)
        workspace=parameter('workspace','Conexion .sde / geodatabase existente','DEWorkspace')
        mode=parameter('mode','Accion','GPString')
        mode.filter.type='ValueList'
        mode.filter.list=['Validar (sin cambios)','Aplicar actualizacion aprobada']
        mode.value='Validar (sin cambios)'
        classes=parameter('classes','Clases del lote aprobado','GPString',True)
        config=json.loads((HERE/'campos_aprobados_1_5.json').read_text(encoding='utf-8'))
        names=sorted({r['clase'] for r in config['cambios']})
        classes.filter.type='ValueList';classes.filter.list=names;classes.value=';'.join(names)
        database=parameter('database','Base de datos esperada','GPString');database.value='ArcGisAWS'
        owner=parameter('owner','Propietario esperado','GPString');owner.value='gis'
        reports=parameter('reports','Carpeta existente para los informes','DEFolder');reports.value=str(HERE)
        output=arcpy.Parameter(name='report',displayName='Informe JSON',datatype='DEFile',parameterType='Derived',direction='Output')
        return [workspace,mode,classes,database,owner,reports,output]

    def execute(self,parameters,messages):
        load_runner()
        migration=sys.modules['actualizar_campos_aprobados']
        try:
            _,report=migration.run(parameters[0].valueAsText,
                apply=parameters[1].valueAsText=='Aplicar actualizacion aprobada',
                names=[str(v) for v in parameters[2].values],
                database=parameters[3].valueAsText,owner=parameters[4].valueAsText,
                reports=parameters[5].valueAsText,arcpy_module=arcpy,emit=arcpy.AddMessage)
            parameters[6].value=report['archivo_resultado']
        except Exception as exc:
            arcpy.AddError(str(exc))
            raise


class RepararTextoLargo:
    def __init__(self):
        self.label = "Reparar texto largo de predios"
        self.description = ("Sustituye exclusivamente cargas_y_gravamenes en predios_inscritos_sunarp_recorte, "
            "solo si la clase esta vacia. Crea y verifica un campo temporal TEXT(10000)/NVARCHAR(MAX), "
            "conserva el original como respaldo hasta verificar el sustituto y retira el respaldo vacio. "
            "No carga datos. El campo puede quedar al final de la tabla. Use el JSON de esta herramienta para recuperar una interrupcion.")
        self.canRunInBackground = False

    def getParameterInfo(self):
        def parameter(name, label, datatype, required=True):
            return arcpy.Parameter(name=name, displayName=label, datatype=datatype,
                parameterType='Required' if required else 'Optional', direction='Input')
        workspace=parameter('workspace','Conexion .sde / geodatabase existente','DEWorkspace')
        mode=parameter('mode','Accion','GPString')
        mode.filter.type='ValueList'
        mode.filter.list=['Validar (sin cambios)','Reparar campo vacio aprobado']
        mode.value='Validar (sin cambios)'
        database=parameter('database','Base de datos esperada','GPString');database.value='ArcGisAWS'
        owner=parameter('owner','Propietario esperado','GPString');owner.value='gis'
        reports=parameter('reports','Carpeta existente para los informes','DEFolder');reports.value=str(HERE)
        recovery=parameter('recovery','JSON de reparacion interrumpida (solo para recuperar)','DEFile',False)
        recovery.filter.list=['json']
        output=arcpy.Parameter(name='report',displayName='Informe JSON',datatype='DEFile',parameterType='Derived',direction='Output')
        return [workspace,mode,database,owner,reports,recovery,output]

    def execute(self,parameters,messages):
        load_runner()
        try:
            _,report=sys.modules['reparar_texto_largo'].run(parameters[0].valueAsText,
                apply=parameters[1].valueAsText=='Reparar campo vacio aprobado',
                database=parameters[2].valueAsText,owner=parameters[3].valueAsText,
                reports=parameters[4].valueAsText,recovery_path=parameters[5].valueAsText or None,
                arcpy_module=arcpy,emit=arcpy.AddMessage)
            parameters[6].value=report['archivo_resultado']
        except Exception as exc:
            arcpy.AddError(str(exc))
            raise


class RenombrarClases:
    def __init__(self):
        self.label = "Normalizar nombres de Datos_Proyecto"
        self.description = ("Aplica el mapeo de nombres 1.6 sobre clases existentes vacias. "
            "Puede comparar contra el informe original para reanudar sin sustituir su referencia. "
            "Reconoce el cambio exacto de calificacion de un alias al nombre aprobado. No cambia campos ni carga datos.")
        self.canRunInBackground = False

    def getParameterInfo(self):
        def parameter(name,label,datatype,multi=False):
            return arcpy.Parameter(name=name,displayName=label,datatype=datatype,
                parameterType='Required',direction='Input',multiValue=multi)
        workspace=parameter('workspace','Conexion .sde / geodatabase existente','DEWorkspace')
        mode=parameter('mode','Accion','GPString')
        mode.filter.type='ValueList';mode.filter.list=['Validar (sin cambios)','Aplicar nombres aprobados']
        mode.value='Validar (sin cambios)'
        classes=parameter('classes','Clases (nombres finales)','GPString',True)
        mapping=json.loads((HERE/'nombres_clases_1_6.json').read_text(encoding='utf-8'))
        names=sorted(row['nombre_nuevo'] for row in mapping['clases'])
        classes.filter.type='ValueList';classes.filter.list=names;classes.value=';'.join(names)
        database=parameter('database','Base de datos esperada','GPString');database.value='ArcGisAWS'
        owner=parameter('owner','Propietario esperado','GPString');owner.value='gis'
        reports=parameter('reports','Carpeta existente para los informes','DEFolder');reports.value=str(HERE)
        previous=arcpy.Parameter(name='previous_report',displayName='Informe JSON original para reanudar',
            datatype='DEFile',parameterType='Optional',direction='Input')
        previous.filter.list=['json']
        output=arcpy.Parameter(name='report',displayName='Informe JSON',datatype='DEFile',parameterType='Derived',direction='Output')
        return [workspace,mode,classes,database,owner,reports,previous,output]

    def execute(self,parameters,messages):
        load_runner()
        try:
            _,report=sys.modules['renombrar_clases'].run(parameters[0].valueAsText,
                apply=parameters[1].valueAsText=='Aplicar nombres aprobados',
                names=[str(value) for value in parameters[2].values],
                database=parameters[3].valueAsText,owner=parameters[4].valueAsText,
                reports=parameters[5].valueAsText,arcpy_module=arcpy,emit=arcpy.AddMessage,
                previous_report_path=parameters[6].valueAsText)
            parameters[7].value=report['archivo_resultado']
        except Exception as exc:
            arcpy.AddError(str(exc))
            raise


class DiagnosticarRenombrado:
    def __init__(self):
        self.label = "Diagnosticar renombrado (solo lectura)"
        self.description = (
            "Compara todas las clases del informe original 1.6 con su estado actual. "
            "Guarda diferencias de campos, indices y geometria sin modificar la geodatabase."
        )
        self.canRunInBackground = False

    def getParameterInfo(self):
        def parameter(name, label, datatype):
            return arcpy.Parameter(name=name, displayName=label, datatype=datatype,
                                   parameterType="Required", direction="Input")

        workspace = parameter("workspace", "Conexion .sde / geodatabase de la ejecucion original", "DEWorkspace")
        previous = parameter("previous_report", "Resultado JSON original del renombrado", "DEFile")
        previous.filter.list = ["json"]
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
        load_runner()
        diagnostic = sys.modules["diagnostico_renombrado"]
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


class ValidarTextosConfirmados:
    def __init__(self):
        self.label = "Validar tipos de texto confirmados"
        self.description = ("Comprueba los 1356 campos de texto confirmados en la version 1.7. "
            "Solo lectura: conserva columnas y datos. Informa los tipos provisionales del modelo vigente.")
        self.canRunInBackground = False

    def getParameterInfo(self):
        def parameter(name, label, datatype):
            return arcpy.Parameter(name=name, displayName=label, datatype=datatype,
                parameterType="Required", direction="Input")
        workspace = parameter("workspace", "Conexion .sde / geodatabase existente", "DEWorkspace")
        database = parameter("database", "Base de datos esperada", "GPString")
        database.value = "ArcGisAWS"
        owner = parameter("owner", "Propietario esperado", "GPString")
        owner.value = "gis"
        reports = parameter("reports", "Carpeta existente para los informes", "DEFolder")
        reports.value = str(HERE)
        output = arcpy.Parameter(name="report", displayName="Informe JSON", datatype="DEFile",
            parameterType="Derived", direction="Output")
        return [workspace, database, owner, reports, output]

    def execute(self, parameters, messages):
        load_runner()
        try:
            _, report = sys.modules['verificar_textos_confirmados'].run(
                parameters[0].valueAsText, database=parameters[1].valueAsText,
                owner=parameters[2].valueAsText, reports=parameters[3].valueAsText,
                arcpy_module=arcpy, emit=arcpy.AddMessage)
            parameters[4].value = report['archivo_resultado']
        except Exception as exc:
            arcpy.AddError(str(exc))
            raise


class ValidarTodosTiposKMZ:
    def __init__(self):
        self.label = "Validar todos los tipos de los KMZ"
        self.description = ("Contrasta el perfil completo de los 13 KMZ con las 76 clases de Datos_Proyecto. "
            "Incluye tipos declarados, valores, longitudes, precision y propuestas para los pendientes. "
            "Solo lectura. No carga datos ni modifica tipos.")
        self.canRunInBackground = False

    def getParameterInfo(self):
        def parameter(name, label, datatype, required=True):
            return arcpy.Parameter(name=name, displayName=label, datatype=datatype,
                parameterType="Required" if required else "Optional", direction="Input")
        workspace = parameter("workspace", "Conexion .sde / geodatabase existente", "DEWorkspace")
        sources = parameter("kmz_dir", "Carpeta KMZ (opcional; vacio usa el perfil completo incluido)", "DEFolder", False)
        database = parameter("database", "Base de datos esperada", "GPString")
        database.value = "ArcGisAWS"
        owner = parameter("owner", "Propietario esperado", "GPString")
        owner.value = "gis"
        reports = parameter("reports", "Carpeta existente para los informes", "DEFolder")
        reports.value = str(HERE)
        output = arcpy.Parameter(name="report", displayName="Informe JSON", datatype="DEFile",
            parameterType="Derived", direction="Output")
        return [workspace, sources, database, owner, reports, output]

    def execute(self, parameters, messages):
        load_runner()
        try:
            _, report = sys.modules['validar_tipos_kmz'].run(
                parameters[0].valueAsText, kmz_dir=parameters[1].valueAsText,
                database=parameters[2].valueAsText, owner=parameters[3].valueAsText,
                reports=parameters[4].valueAsText, arcpy_module=arcpy, emit=arcpy.AddMessage)
            parameters[5].value = report['archivo_resultado']
            if report['estado'] != 'TIPOS_VERIFICADOS':
                arcpy.AddWarning("Revise las propuestas y las incidencias del informe antes de aplicar tipos o cargar datos.")
        except Exception as exc:
            arcpy.AddError(str(exc))
            raise


class CerrarTiposKMZ:
    def __init__(self):
        self.label = "Cerrar tipos de Datos_Proyecto"
        self.description = ("Valida el cierre de los 730 tipos: 722 TEXT conservados y ocho cambios numericos. "
            "Aplicar solo modifica los ocho campos autorizados en clases existentes y vacias. "
            "Verifica el resultado completo y conserva las incidencias de ingesta por separado.")
        self.canRunInBackground = False

    def getParameterInfo(self):
        def parameter(name, label, datatype):
            return arcpy.Parameter(name=name, displayName=label, datatype=datatype,
                parameterType="Required", direction="Input")
        workspace = parameter("workspace", "Conexion .sde / geodatabase existente", "DEWorkspace")
        action = parameter("accion", "Accion", "GPString")
        action.filter.type = "ValueList"
        action.filter.list = ["Validar cierre (sin cambios)", "Aplicar cierre de tipos"]
        action.value = action.filter.list[0]
        database = parameter("database", "Base de datos esperada", "GPString")
        database.value = "ArcGisAWS"
        owner = parameter("owner", "Propietario esperado", "GPString")
        owner.value = "gis"
        reports = parameter("reports", "Carpeta existente para los informes", "DEFolder")
        reports.value = str(HERE)
        output = arcpy.Parameter(name="report", displayName="Informe JSON", datatype="DEFile",
            parameterType="Derived", direction="Output")
        return [workspace, action, database, owner, reports, output]

    def execute(self, parameters, messages):
        load_runner()
        try:
            action = parameters[1].valueAsText
            if action not in ("Validar cierre (sin cambios)", "Aplicar cierre de tipos"):
                raise ValueError("Accion de cierre no admitida.")
            _, report = sys.modules['cerrar_tipos_kmz'].run(parameters[0].valueAsText,
                apply=action == "Aplicar cierre de tipos", database=parameters[2].valueAsText,
                owner=parameters[3].valueAsText, reports=parameters[4].valueAsText,
                arcpy_module=arcpy, emit=arcpy.AddMessage)
            parameters[5].value = report['archivo_resultado']
            if report.get('cierre_verificado'):
                arcpy.AddWarning("Tipos cerrados y verificados. Los pendientes de ingesta siguen en el informe; no se cargaron registros.")
            else:
                arcpy.AddMessage("La validacion conserva el destino; revise los cambios pendientes en el informe antes de aplicar.")
        except Exception as exc:
            arcpy.AddError(str(exc))
            raise


class PrevalidarIngesta:
    def __init__(self):
        self.label = "Prevalidar ingesta de los KMZ"
        self.description = ("Comprueba los 13 KMZ actuales por SHA-256, consulta los proyectos reales "
            "y genera un plan por ruta, clase y proyecto. Revisa los valores y las correspondencias "
            "pendientes. Solo lectura: no carga registros ni modifica la geodatabase.")
        self.canRunInBackground = False

    def getParameterInfo(self):
        def parameter(name, label, datatype, required=True):
            return arcpy.Parameter(name=name, displayName=label, datatype=datatype,
                parameterType="Required" if required else "Optional", direction="Input")
        workspace = parameter("workspace", "Conexion .sde / geodatabase existente", "DEWorkspace")
        sources = parameter("kmz_dir", "Carpeta raiz con los 13 KMZ (incluye subcarpetas)", "DEFolder")
        projects = parameter("project_csv", "CSV de proyectos confirmados (opcional en primera ejecucion)", "DEFile", False)
        projects.filter.list = ["csv"]
        database = parameter("database", "Base de datos esperada", "GPString")
        database.value = "ArcGisAWS"
        owner = parameter("owner", "Propietario esperado", "GPString")
        owner.value = "gis"
        reports = parameter("reports", "Carpeta existente para los informes", "DEFolder")
        reports.value = str(HERE)
        output = arcpy.Parameter(name="report", displayName="Informe JSON", datatype="DEFile",
            parameterType="Derived", direction="Output")
        return [workspace, sources, projects, database, owner, reports, output]

    def execute(self, parameters, messages):
        load_runner()
        try:
            _, report = sys.modules['prevalidar_ingesta'].run(parameters[0].valueAsText,
                kmz_dir=parameters[1].valueAsText, project_csv=parameters[2].valueAsText,
                database=parameters[3].valueAsText, owner=parameters[4].valueAsText,
                reports=parameters[5].valueAsText, arcpy_module=arcpy, emit=arcpy.AddMessage)
            parameters[6].value = report['archivo_resultado']
            arcpy.AddWarning("Plan generado sin cargar datos. Revise fuentes, proyectos, rutas y pendientes en el informe.")
        except Exception as exc:
            arcpy.AddError(str(exc))
            raise


class RegistrarProyectosFaltantes:
    def __init__(self):
        self.label = "Registrar proyectos faltantes de los KMZ"
        self.description = ("Consulta JAENNORTE y POROMA en el catalogo y calcula los siguientes codigos. "
            "Por defecto solo valida. Crear inserta exclusivamente los proyectos faltantes mediante "
            "ArcGIS y verifica el resultado. Requiere evitar otras altas simultaneas durante toda la "
            "ejecucion: la declaracion del operador no establece un bloqueo de la base. "
            "No reactiva proyectos ni carga geometrias de los KMZ.")
        self.canRunInBackground = False

    def getParameterInfo(self):
        def parameter(name, label, datatype, required=True):
            return arcpy.Parameter(name=name, displayName=label, datatype=datatype,
                parameterType="Required" if required else "Optional", direction="Input")
        workspace = parameter("workspace", "Conexion .sde / geodatabase existente", "DEWorkspace")
        action = parameter("mode", "Accion", "GPString")
        action.filter.type = "ValueList"
        action.filter.list = ["Validar altas (sin cambios)", "Crear proyectos faltantes"]
        action.value = action.filter.list[0]
        exclusive = parameter("exclusive", "Sin otras altas simultaneas durante esta ejecucion", "GPBoolean")
        exclusive.value = False
        projects = parameter("project_csv", "CSV de proyectos confirmados para completar (opcional)", "DEFile", False)
        projects.filter.list = ["csv"]
        database = parameter("database", "Base de datos esperada", "GPString")
        database.value = "ArcGisAWS"
        owner = parameter("owner", "Propietario esperado", "GPString")
        owner.value = "gis"
        reports = parameter("reports", "Carpeta existente para los informes", "DEFolder")
        reports.value = str(HERE)
        output = arcpy.Parameter(name="report", displayName="Informe JSON", datatype="DEFile",
            parameterType="Derived", direction="Output")
        return [workspace, action, exclusive, projects, database, owner, reports, output]

    def execute(self, parameters, messages):
        load_runner()
        try:
            action = parameters[1].valueAsText
            if action not in ("Validar altas (sin cambios)", "Crear proyectos faltantes"):
                raise ValueError("Accion de alta de proyectos no admitida.")
            _, report = sys.modules['alta_proyectos'].run(parameters[0].valueAsText,
                apply=action == "Crear proyectos faltantes",
                exclusive=str(parameters[2].valueAsText).casefold() == "true",
                project_csv=parameters[3].valueAsText, database=parameters[4].valueAsText,
                owner=parameters[5].valueAsText, reports=parameters[6].valueAsText,
                arcpy_module=arcpy, emit=arcpy.AddMessage)
            parameters[7].value = report['archivo_resultado']
            arcpy.AddMessage("Esta herramienta no carga los registros de los KMZ; revise el informe y las asociaciones resultantes.")
        except Exception as exc:
            arcpy.AddError(str(exc))
            raise


class ConfigurarCatalogoProyectos:
    def __init__(self):
        self.label = "Preparar catalogo de proyectos para altas"
        self.description = ("Revisa los dominios de tipo y estado de proyecto y la auditoria nativa. "
            "Validar genera el plan sin modificar la base. Aplicar requiere autorizar cuatro campos "
            "de auditoria ArcGIS separados de las fechas y usuarios historicos; configura los dominios "
            "y Editor Tracking en UTC. No interpreta ni reconstruye la zona de fechas historicas. "
            "No crea proyectos ni carga registros de los KMZ.")
        self.canRunInBackground = False

    def getParameterInfo(self):
        def parameter(name, label, datatype):
            return arcpy.Parameter(name=name, displayName=label, datatype=datatype,
                parameterType="Required", direction="Input")
        workspace = parameter("workspace", "Conexion .sde / geodatabase existente", "DEWorkspace")
        action = parameter("mode", "Accion", "GPString")
        action.filter.type = "ValueList"
        action.filter.list = ["Validar configuracion (sin cambios)", "Aplicar configuracion aprobada"]
        action.value = action.filter.list[0]
        approved = parameter("approve_native_audit",
            "Autorizar cuatro campos de auditoria ArcGIS separados del historico", "GPBoolean")
        approved.value = False
        database = parameter("database", "Base de datos esperada", "GPString")
        database.value = "ArcGisAWS"
        owner = parameter("owner", "Propietario esperado", "GPString")
        owner.value = "gis"
        reports = parameter("reports", "Carpeta existente para los informes", "DEFolder")
        reports.value = str(HERE)
        output = arcpy.Parameter(name="report", displayName="Informe JSON", datatype="DEFile",
            parameterType="Derived", direction="Output")
        return [workspace, action, approved, database, owner, reports, output]

    def execute(self, parameters, messages):
        load_runner()
        try:
            action = parameters[1].valueAsText
            if action not in ("Validar configuracion (sin cambios)", "Aplicar configuracion aprobada"):
                raise ValueError("Accion de configuracion del catalogo no admitida.")
            _, report = sys.modules['configurar_proyecto'].run(parameters[0].valueAsText,
                apply=action == "Aplicar configuracion aprobada",
                approve_native_audit=str(parameters[2].valueAsText).casefold() == "true",
                database=parameters[3].valueAsText, owner=parameters[4].valueAsText,
                reports=parameters[5].valueAsText, arcpy_module=arcpy, emit=arcpy.AddMessage)
            parameters[6].value = report['archivo_resultado']
            if report.get('estado') == 'CONFIGURACION_PENDIENTE_APROBACION_AUDITORIA':
                arcpy.AddWarning("Pendiente de aprobar la auditoria propuesta: created_user, created_date, "
                    "last_edited_user y last_edited_date. Revise el plan; esta validacion no autoriza aplicar los cambios.")
            arcpy.AddMessage("Esta herramienta prepara el catalogo; no asigna codigos ni carga registros de los KMZ.")
        except Exception as exc:
            arcpy.AddError(str(exc))
            raise
