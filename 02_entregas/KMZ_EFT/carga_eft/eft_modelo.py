"""Estructura de datos del EFT 5.8: catalogo de clases, dominios y creacion en una geodatabase.

El catalogo es datos puros (sin arcpy) para que las reglas y las pruebas lo usen sin ArcGIS.
arcpy se importa solo dentro de las funciones que crean o consultan la geodatabase, y todas
son idempotentes: crean lo que falta, nunca modifican ni borran lo que ya existe.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

DS_EXTERNOS = "Datos_Externos"
DS_INTERNOS = "Datos_Internos"
DS_PROYECTO = "Datos_Proyecto"
DATASETS = (DS_EXTERNOS, DS_INTERNOS, DS_PROYECTO)
WKID = 4326
RECORTE = "_Recorte"
TABLA_PROYECTO = "mline_tc_proyecto"
CLAVE_PROYECTO = "co_proyecto"

PUNTO, LINEA, POLIGONO = "PUNTO", "LINEA", "POLIGONO"
GEOMETRIAS = (PUNTO, LINEA, POLIGONO)
ARC_GEOMETRIA = {PUNTO: "POINT", LINEA: "POLYLINE", POLIGONO: "POLYGON"}
SUFIJO_GEOMETRIA = {PUNTO: "Pto", LINEA: "Lin", POLIGONO: "Pol"}

TEMA_AMBIENTAL = "Ambiental y cultural"
TEMA_DERECHOS = "Derechos territoriales"
TEMA_INFRAESTRUCTURA = "Infraestructura y referencia"
TEMAS = (TEMA_AMBIENTAL, TEMA_DERECHOS, TEMA_INFRAESTRUCTURA)
DISCIPLINAS = ("Ingeniería", "Predial", "Ambiental")
CONDICIONES = ("Existente", "Proyectado", "Nuevo")
FUENTES_EFT = ("ANA", "SERNANP", "SERFOR", "MINAM", "INGEMMET", "Ministerio de Cultura", "SUNARP",
               "MIDAGRI", "MINEM", "PERUPETRO", "OSINERGMIN", "MTC", "INEI")
FUENTES_ADICIONALES = ("SBN", "SENACE", "INAIGEM", "ENGIE", "Consultor predial", "Consultor ambiental", "Ingeniería")
FUENTES = FUENTES_EFT + FUENTES_ADICIONALES

DOMINIOS = {
    "dom_disciplina": ("Disciplina del elemento", DISCIPLINAS),
    "dom_condicion": ("Condicion del elemento", CONDICIONES),
    "dom_tema": ("Tema de la capa de referencia", TEMAS),
    "dom_fuente": ("Entidad o area de origen", FUENTES),
}

# Campo de texto largo: SQL Server lo crea como nvarchar(max) a partir de 4.001 caracteres.
LARGO_ATRIBUTOS = 100000
LARGO_TEXTO_MAXIMO = 4000


@dataclass(frozen=True)
class Clase:
    nombre: str
    seccion: str  # proyecto, externa o interna
    geometrias: tuple
    tema: str = ""
    fuente: str = ""


def _clases():
    proyecto = [
        ("Estructuras", (PUNTO,)), ("Vanos", (LINEA,)), ("Vertices", (PUNTO,)),
        ("Subestacion", (POLIGONO, PUNTO)), ("Accesos", (LINEA,)), ("FranjaServidumbre", (POLIGONO,)),
        ("Muestreo", (PUNTO,)), ("AreaEstudioCampo", (POLIGONO,)), ("Calicatas", (PUNTO,)),
        ("RegistroCampo", (PUNTO, LINEA)),
    ]
    externas = [
        ("Rios", (LINEA,), TEMA_AMBIENTAL, "ANA"), ("FajasMarginales", (PUNTO,), TEMA_AMBIENTAL, "ANA"),
        ("Canales", (LINEA,), TEMA_AMBIENTAL, "ANA"), ("Lagunas", (POLIGONO,), TEMA_AMBIENTAL, "ANA"),
        ("ANPNacional", (POLIGONO,), TEMA_AMBIENTAL, "SERNANP"),
        ("ZonaAmortiguamiento", (POLIGONO,), TEMA_AMBIENTAL, "SERNANP"),
        ("AreaConservacion", (POLIGONO,), TEMA_AMBIENTAL, "SERNANP"),
        ("EcosistemasFragiles", (POLIGONO,), TEMA_AMBIENTAL, "SERFOR"),
        ("IBA_EBA_KBA", (POLIGONO,), TEMA_AMBIENTAL, "MINAM"),
        ("CoberturaVegetal", (POLIGONO,), TEMA_AMBIENTAL, "MINAM"),
        ("Geologia", (POLIGONO, LINEA), TEMA_AMBIENTAL, "INGEMMET"),
        ("Geomorfologia", (POLIGONO,), TEMA_AMBIENTAL, "MINAM"), ("ZEE", (POLIGONO,), TEMA_AMBIENTAL, "MINAM"),
        ("SitioArqueologico", (POLIGONO, PUNTO), TEMA_AMBIENTAL, "Ministerio de Cultura"),
        ("QhapaqNan", (LINEA,), TEMA_AMBIENTAL, "Ministerio de Cultura"),
        ("Paleontologia", (PUNTO,), TEMA_AMBIENTAL, "Ministerio de Cultura"),
        ("PredioSUNARP", (POLIGONO,), TEMA_DERECHOS, "SUNARP"),
        ("ComunidadCampesina", (POLIGONO,), TEMA_DERECHOS, "MIDAGRI"),
        ("CatastroMinero", (POLIGONO,), TEMA_DERECHOS, "INGEMMET"),
        ("ConcesionElectrica", (POLIGONO,), TEMA_DERECHOS, "MINEM"),
        ("LotesHidrocarburos", (POLIGONO,), TEMA_DERECHOS, "PERUPETRO"),
        ("DerechosAgua", (PUNTO,), TEMA_DERECHOS, "ANA"),
        ("LT_Existente", (LINEA,), TEMA_INFRAESTRUCTURA, "OSINERGMIN"),
        ("SE_Existente", (PUNTO,), TEMA_INFRAESTRUCTURA, "OSINERGMIN"),
        ("RedesMT", (LINEA,), TEMA_INFRAESTRUCTURA, "OSINERGMIN"),
        ("ViasNacional", (LINEA,), TEMA_INFRAESTRUCTURA, "MTC"),
        ("ViasRegional", (LINEA,), TEMA_INFRAESTRUCTURA, "MTC"),
        ("ViasVecinal", (LINEA,), TEMA_INFRAESTRUCTURA, "MTC"),
        ("Ductos_Pozos", (LINEA, PUNTO), TEMA_INFRAESTRUCTURA, "PERUPETRO"),
        ("LimiteDepartamento", (POLIGONO,), TEMA_INFRAESTRUCTURA, "INEI"),
        ("LimiteProvincia", (POLIGONO,), TEMA_INFRAESTRUCTURA, "INEI"),
        ("LimiteDistrito", (POLIGONO,), TEMA_INFRAESTRUCTURA, "INEI"),
        ("CentroPoblado", (PUNTO,), TEMA_INFRAESTRUCTURA, "INEI"),
    ]
    internas = [
        ("PredioRural", (POLIGONO,), TEMA_DERECHOS, "Consultor predial"),
        ("Poseedores", (POLIGONO, PUNTO), TEMA_DERECHOS, "Consultor predial"),
        ("UsoActual", (POLIGONO,), TEMA_AMBIENTAL, "Consultor predial"),
        ("CaminosHerradura", (LINEA,), TEMA_INFRAESTRUCTURA, "Consultor predial"),
    ]
    catalogo = {}
    for nombre, geometrias in proyecto:
        catalogo[nombre] = Clase(nombre, "proyecto", geometrias)
    for nombre, geometrias, tema, fuente in externas:
        catalogo[nombre] = Clase(nombre, "externa", geometrias, tema, fuente)
    for nombre, geometrias, tema, fuente in internas:
        catalogo[nombre] = Clase(nombre, "interna", geometrias, tema, fuente)
    return catalogo


CLASES = _clases()


def separar_destino(destino):
    """Devolver (clase, es_recorte) del nombre logico usado en el mapeo."""
    texto = str(destino or "").strip()
    if texto.endswith(RECORTE):
        return texto[:-len(RECORTE)], True
    return texto, False


def validar_destino(destino, geometria):
    """Devolver (True, '') o (False, motivo) para un destino logico y una geometria."""
    clase, recorte = separar_destino(destino)
    if not clase:
        return False, "Falta la clase de destino."
    if clase not in CLASES:
        return False, f"La clase {clase} no existe en el catalogo del EFT."
    definicion = CLASES[clase]
    if recorte and definicion.seccion == "proyecto":
        return False, f"{clase} es una clase de proyecto y no tiene variante {RECORTE}."
    if geometria not in definicion.geometrias:
        permitidas = "/".join(definicion.geometrias)
        return False, f"{clase} admite {permitidas}; el grupo es {geometria}."
    return True, ""


def nombre_fisico(destino, geometria):
    clase, recorte = separar_destino(destino)
    definicion = CLASES[clase]
    base = clase if len(definicion.geometrias) == 1 else f"{clase}_{SUFIJO_GEOMETRIA[geometria]}"
    return base + (RECORTE if recorte else "")


def dataset_de(destino):
    clase, recorte = separar_destino(destino)
    seccion = CLASES[clase].seccion
    if recorte or seccion == "proyecto":
        return DS_PROYECTO
    return DS_EXTERNOS if seccion == "externa" else DS_INTERNOS


@dataclass(frozen=True)
class Spec:
    fisico: str
    dataset: str
    geometria: str
    destino: str


def spec_de(destino, geometria):
    return Spec(nombre_fisico(destino, geometria), dataset_de(destino), geometria, destino)


def specs_de_destinos(destinos):
    """Especificaciones unicas para pares (destino logico, geometria)."""
    resultado = {}
    for destino, geometria in destinos:
        spec = spec_de(destino, geometria)
        resultado[spec.fisico.lower()] = spec
    return sorted(resultado.values(), key=lambda s: (s.dataset, s.fisico))


def specs_completas():
    """Estructura completa: todas las clases del EFT y el recorte de cada capa externa o interna."""
    pares = []
    for clase in CLASES.values():
        for geometria in clase.geometrias:
            pares.append((clase.nombre, geometria))
            if clase.seccion != "proyecto":
                pares.append((clase.nombre + RECORTE, geometria))
    return specs_de_destinos(pares)


def campos_de(spec):
    """Campos (nombre, tipo, largo, alias, dominio) de una clase fisica segun las secciones 5.8.5 y 5.8.7."""
    clase, recorte = separar_destino(spec.destino)
    definicion = CLASES[clase]
    en_proyecto = spec.dataset == DS_PROYECTO
    campos = []
    if en_proyecto:
        campos += [("proyecto", "TEXT", 20, "Proyecto", None),
                   ("id_analisis", "TEXT", 100, "Analisis", None)]
    if recorte or not en_proyecto:
        campos.append(("tema", "TEXT", 40, "Tema", "dom_tema"))
    campos.append(("disciplina", "TEXT", 20, "Disciplina", "dom_disciplina"))
    if en_proyecto:
        campos += [("componente", "TEXT", 150, "Componente", None),
                   ("alternativa", "TEXT", 100, "Alternativa", None)]
    campos += [("condicion", "TEXT", 20, "Condicion", "dom_condicion"),
               ("fuente", "TEXT", 60, "Fuente", "dom_fuente")]
    if recorte:
        campos.append(("capa_origen", "TEXT", 150, "Capa de origen", None))
    if recorte or definicion.seccion == "externa":
        campos.append(("id_origen", "TEXT", 100, "Id de origen", None))
    campos.append(("nombre", "TEXT", 1000, "Nombre", None))
    if en_proyecto:
        campos += [("archivo_origen", "TEXT", 255, "Archivo de origen", None),
                   ("ruta_kml", "TEXT", LARGO_TEXTO_MAXIMO, "Ruta en el KML", None)]
    campos.append(("fecha_carga", "DATE", None, "Fecha de carga", None))
    if spec.geometria == LINEA:
        campos.append(("longitud_m", "DOUBLE", None, "Longitud (m)", None))
    elif spec.geometria == POLIGONO:
        campos.append(("area_ha", "DOUBLE", None, "Area (ha)", None))
    if clase in ("AreaEstudioCampo", "Muestreo"):
        campos.append(("codigo_estacion", "TEXT", 50, "Codigo de estacion", None))
    if en_proyecto:
        campos += [("kz_pm_id", "TEXT", 100, "KZ Placemark", None),
                   ("kz_sha256", "TEXT", 64, "KZ SHA-256", None),
                   ("kz_grupo", "TEXT", 20, "KZ grupo de mapeo", None),
                   ("kz_supuestos", "TEXT", 200, "KZ supuestos", None),
                   ("kz_atributos", "TEXT", LARGO_ATRIBUTOS, "KZ atributos del KML", None)]
    return campos


def nombres_campos(spec):
    return [campo[0] for campo in campos_de(spec)]


def sin_calificar(nombre):
    return str(nombre).split(".")[-1]


def inventario(workspace):
    """Clases, datasets y tablas existentes, indexados por nombre sin calificar en minusculas."""
    import arcpy
    resultado = {"datasets": {}, "clases": {}, "tablas": {}}
    with arcpy.EnvManager(workspace=workspace):
        for dataset in arcpy.ListDatasets(feature_type="Feature") or []:
            resultado["datasets"][sin_calificar(dataset).lower()] = os.path.join(workspace, dataset)
            for clase in arcpy.ListFeatureClasses(feature_dataset=dataset) or []:
                resultado["clases"][sin_calificar(clase).lower()] = os.path.join(workspace, dataset, clase)
        for clase in arcpy.ListFeatureClasses() or []:
            resultado["clases"].setdefault(sin_calificar(clase).lower(), os.path.join(workspace, clase))
        for tabla in arcpy.ListTables() or []:
            resultado["tablas"][sin_calificar(tabla).lower()] = os.path.join(workspace, tabla)
    return resultado


def asegurar_dominios(workspace, log=None):
    import arcpy
    existentes = {d.name.lower(): d for d in arcpy.da.ListDomains(workspace)}
    for nombre, (descripcion, valores) in DOMINIOS.items():
        dominio = existentes.get(nombre.lower())
        if dominio is None:
            arcpy.management.CreateDomain(workspace, nombre, descripcion, "TEXT", "CODED")
            presentes = set()
            if log:
                log(f"Dominio creado: {nombre}")
        else:
            presentes = set(dominio.codedValues)
        for valor in valores:
            if valor not in presentes:
                arcpy.management.AddCodedValueToDomain(workspace, nombre, valor, valor)


def _asegurar_dataset(workspace, inv, nombre, referencia, log):
    import arcpy
    ruta = inv["datasets"].get(nombre.lower())
    if ruta:
        return ruta
    ruta = arcpy.management.CreateFeatureDataset(workspace, nombre, referencia).getOutput(0)
    inv["datasets"][nombre.lower()] = ruta
    if log:
        log(f"Dataset creado: {nombre}")
    return ruta


def _asegurar_clase(spec, ruta_dataset, referencia, inv, global_id, seguimiento, log):
    import arcpy
    ruta = inv["clases"].get(spec.fisico.lower())
    creada = ruta is None
    if creada:
        ruta = arcpy.management.CreateFeatureclass(ruta_dataset, spec.fisico, ARC_GEOMETRIA[spec.geometria],
                                                   has_z="ENABLED", spatial_reference=referencia).getOutput(0)
        inv["clases"][spec.fisico.lower()] = ruta
    presentes = {campo.name.lower() for campo in arcpy.ListFields(ruta)}
    faltantes = [c for c in campos_de(spec) if c[0].lower() not in presentes]
    if faltantes:
        arcpy.management.AddFields(ruta, [[nombre, tipo, alias, largo, None, dominio]
                                          for nombre, tipo, largo, alias, dominio in faltantes])
    descripcion = arcpy.Describe(ruta)
    if global_id and not getattr(descripcion, "hasGlobalID", False):
        arcpy.management.AddGlobalIDs(ruta)
    if seguimiento and not getattr(descripcion, "editorTrackingEnabled", False):
        arcpy.management.EnableEditorTracking(ruta, "created_user", "created_date", "last_edited_user",
                                              "last_edited_date", "ADD_FIELDS", "UTC")
    if log and (creada or faltantes):
        log(f"{'Clase creada' if creada else 'Clase completada'}: {spec.dataset}\\{spec.fisico}")
    return ruta


def crear_estructura(workspace, specs, *, global_id=True, seguimiento=True, log=None):
    """Crear datasets, dominios y clases que falten. Devuelve {fisico_en_minusculas: ruta}."""
    import arcpy
    referencia = arcpy.SpatialReference(WKID)
    asegurar_dominios(workspace, log)
    inv = inventario(workspace)
    for dataset in DATASETS:
        _asegurar_dataset(workspace, inv, dataset, referencia, log)
    rutas = {}
    for spec in specs:
        ruta_dataset = inv["datasets"][spec.dataset.lower()]
        rutas[spec.fisico.lower()] = _asegurar_clase(spec, ruta_dataset, referencia, inv, global_id, seguimiento, log)
    return rutas


def crear_relaciones(workspace, specs, log=None):
    """Relacion 1:N con mline_tc_proyecto para cada clase de Datos_Proyecto, solo si la tabla existe."""
    import arcpy
    inv = inventario(workspace)
    origen = inv["tablas"].get(TABLA_PROYECTO.lower())
    if not origen:
        return {"creadas": [], "motivo": f"No existe {TABLA_PROYECTO} en la geodatabase; relaciones pendientes."}
    creadas = []
    for spec in specs:
        if spec.dataset != DS_PROYECTO:
            continue
        nombre = f"rel_proyecto_{spec.fisico}"
        ruta_relacion = os.path.join(workspace, nombre)
        if arcpy.Exists(ruta_relacion):
            continue
        destino = inv["clases"][spec.fisico.lower()]
        arcpy.management.CreateRelationshipClass(origen, destino, ruta_relacion, "SIMPLE",
                                                 spec.fisico, "Proyecto", "NONE", "ONE_TO_MANY", "NONE",
                                                 CLAVE_PROYECTO, "proyecto")
        creadas.append(nombre)
        if log:
            log(f"Relacion creada: {nombre}")
    return {"creadas": creadas, "motivo": ""}


def estado_versionado(workspace, dataset=DS_PROYECTO):
    import arcpy
    inv = inventario(workspace)
    ruta = inv["datasets"].get(dataset.lower())
    if not ruta:
        return None
    return bool(getattr(arcpy.Describe(ruta), "isVersioned", False))


def registrar_versionado(workspace, log=None):
    """Registrar Datos_Proyecto como versionado. El tipo (rama) lo decide la conexion, no esta funcion."""
    import arcpy
    inv = inventario(workspace)
    ruta = inv["datasets"].get(DS_PROYECTO.lower())
    if not ruta:
        raise RuntimeError(f"No existe el dataset {DS_PROYECTO}; cree la estructura antes de versionar.")
    if bool(getattr(arcpy.Describe(ruta), "isVersioned", False)):
        if log:
            log(f"{DS_PROYECTO} ya esta registrado como versionado.")
        return False
    arcpy.management.RegisterAsVersioned(ruta)
    if log:
        log(f"{DS_PROYECTO} registrado como versionado.")
    return True
