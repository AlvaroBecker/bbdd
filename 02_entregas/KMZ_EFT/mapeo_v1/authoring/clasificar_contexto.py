"""Propuestas de mapeo por contexto para revisión del EFT 5.8.

classify(row) es pura: conserva jerarquías JSON, no carga datos ni aprueba filas,
no crea identificadores de negocio y no excluye copias. Los nombres devueltos
son clases conceptuales expresas en el EFT o sus recortes, pendientes de INDRA.
"""
from __future__ import annotations

from html.parser import HTMLParser
import json
import re
import unicodedata


class _VisibleText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, value):
        self.parts.append(value)


def _norm(value):
    parser = _VisibleText()
    parser.feed(str(value))
    visible = " ".join(parser.parts)
    visible = re.sub(r"([a-záéíóúñ])([A-ZÁÉÍÓÚÑ])", r"\1 \2", visible)
    visible = re.sub(r"([A-ZÁÉÍÓÚÑ])([A-ZÁÉÍÓÚÑ][a-záéíóúñ])", r"\1 \2", visible)
    folded = "".join(c for c in unicodedata.normalize("NFKD", visible.casefold()) if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", folded).strip()


def _parts(row):
    raw = row.get("ruta_componentes_json", "")
    value = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(value, list) or not all(isinstance(part, str) for part in value):
        raise ValueError("La jerarquía debe ser una lista de textos.")
    return list(value)


def _context(row, parts, geometry, role):
    # Las barras y etiquetas HTML pueden pertenecer al nombre de un componente.
    return json.dumps({"archivo": row.get("archivo_origen", ""), "ruta": parts,
                       "rol": role, "geometria": geometry}, ensure_ascii=False, separators=(",", ":"))


def _result(row, parts, geometry, family, proposed="", options=(), role="", reason="", pending="", reference="5.8.6; 5.8.8"):
    return {"familia": family, "clase_propuesta": proposed, "opciones_destino": list(options),
            "contexto_agrupacion": _context(row, parts, geometry, role or family), "motivo": reason,
            "pendiente_especifico": pending or "Revisar el contenido y aprobar el mapeo; asociar proyecto y análisis válidos.",
            "referencia_eft": reference}


def _station(text):
    compact = text.replace(" ", "")
    return re.fullmatch(r"(?:ebi|f|soc)\d{1,3}[a-z]{0,2}", compact) is not None


def _last_significant(parts, normalized):
    generic = {"point features", "line features", "area features", "polygon features", "text features",
               "points", "lines", "polygons", "placemarks", "folder", "document", "features",
               "puntos", "lineas", "poligonos", "elementos", "sin nombre"}
    for index in range(len(parts) - 1, -1, -1):
        if normalized[index] not in generic and normalized[index]:
            return parts[:index + 1]
    return parts[:1]


def _pls(row, parts, names, geometry, index):
    root = parts[:index + 1]
    tail = names[index + 1:]
    if any(name == "structure locations" for name in tail):
        role = "Ubicaciones de estructuras"
        proposed = "Estructuras" if geometry == "PUNTO" else ""
        options = ["Estructuras"]
        reason = "Exportación PLS-CADD con ubicaciones de estructuras; la clase del EFT admite puntos."
    elif any(re.match(r"section\s+\d+\b", name) for name in tail):
        role, proposed, options = "Secciones PLS-CADD", "", ["Estructuras", "Vanos"]
        reason = "Section agrupa representaciones de conductor y detalles; su nombre y geometría no identifican por sí solos una entidad Vanos."
    elif any(re.match(r"structure\b", name) for name in tail):
        role, proposed, options = "Detalles de estructuras PLS-CADD", "", ["Estructuras"]
        reason = "Geometría de representación de una estructura; no equivale automáticamente a su ubicación puntual."
    else:
        role, proposed, options = "Contenido del modelo PLS-CADD", "", ["Estructuras", "Vanos"]
        reason = "Contenido del modelo agrupado para interpretación especializada, sin multiplicar clases por cada sección."
    if geometry not in {"PUNTO", "LINEA", "POLIGONO"}:
        proposed, options = "", []
        role = "Modelo PLS-CADD de geometría especial"
    return _result(row, root, geometry, "PLS-CADD", proposed, options, role, reason,
                   "Interpretar la fuente PLS-CADD, conectividad y atributos; comprobar la compatibilidad geométrica y las copias CAD antes de elegir destino.", "5.8.6; 5.8.9")


# Patrones conservadores sobre nombres de temas; nunca inventan nuevas clases.
# Geometrías admitidas y nombres conceptuales proceden del cuadro de 5.8.6.
_PUBLIC_THEMES = [
    (r"\bzon\w* (?:de )?amort\w*\b", "ZonaAmortiguamiento", {"POLIGONO"}),
    (r"\b(?:area\w* de conservacion|area cons(?: pri| reg)?|area conservacion)\b", "AreaConservacion", {"POLIGONO"}),
    (r"\b(?:faj\w* marg\w*|fajas? marginales?)\b", "FajasMarginales", {"PUNTO"}),
    (r"\brios?\b|\bred hidrografica\b", "Rios", {"LINEA"}),
    (r"\bcanal(?:es)?\b", "Canales", {"LINEA"}),
    (r"\blagunas?\b", "Lagunas", {"POLIGONO"}),
    (r"\banp(?: nacional)?\b|\barea natural protegida\b", "ANPNacional", {"POLIGONO"}),
    (r"\becosistemas? fragiles?\b", "EcosistemasFragiles", {"POLIGONO"}),
    (r"\b(?:ibas?|ebas?|kbas?|areas? clave de biodiversidad)\b", "IBA_EBA_KBA", {"POLIGONO"}),
    (r"\bcobertura vegetal\b", "CoberturaVegetal", {"POLIGONO"}),
    (r"\bgeologia\b|\bclasificacion geologica\b", "Geologia", {"LINEA", "POLIGONO"}),
    (r"\bgeomorfologia\b|\bclasificacion geomorfologica\b", "Geomorfologia", {"POLIGONO"}),
    (r"\bzee\b|\bzonificacion ecologica economica\b", "ZEE", {"POLIGONO"}),
    (r"\bsitios? arqueologicos?\b", "SitioArqueologico", {"PUNTO", "POLIGONO"}),
    (r"\bqhapaq nam\b|\bqhapaq nan\b", "QhapaqNan", {"LINEA"}),
    (r"\bp[ae]leontologia\b|\bfosiles?\b", "Paleontologia", {"PUNTO"}),
    (r"\bsunarp\b", "PredioSUNARP", {"POLIGONO"}),
    (r"\bcomunidad(?:es)? campesina(?:s)?\b", "ComunidadCampesina", {"POLIGONO"}),
    (r"\bcatastro minero\b|\bconcesion(?:es)? minera(?:s)?\b|\bly simp mineras? (?:17|18|19)s\b", "CatastroMinero", {"POLIGONO"}),
    (r"\bconcesion(?:es)? electrica(?:s)?\b", "ConcesionElectrica", {"POLIGONO"}),
    (r"\blotes? hidrocarburos\b|\blotes? de hidrocarburos\b", "LotesHidrocarburos", {"POLIGONO"}),
    (r"\bderechos? (?:de )?agua\b", "DerechosAgua", {"PUNTO"}),
    (r"\b(?:red vial|vias?) nacional(?:es)?\b", "ViasNacional", {"LINEA"}),
    (r"\b(?:red vial|vias?) (?:regional(?:es)?|departamental(?:es)?)\b", "ViasRegional", {"LINEA"}),
    (r"\b(?:red vial|vias?) vecinal(?:es)?\b", "ViasVecinal", {"LINEA"}),
    (r"\bredes? (?:de )?media tension\b|\bredes? mt\b", "RedesMT", {"LINEA"}),
    (r"\b(?:limite de |limites de |limite |limites )?departamentos?\b", "LimiteDepartamento", {"POLIGONO"}),
    (r"\b(?:limite de |limites de |limite |limites )?provincias?\b", "LimiteProvincia", {"POLIGONO"}),
    (r"\b(?:limite de |limites de |limite |limites )?distritos?\b", "LimiteDistrito", {"POLIGONO"}),
    (r"\bcentros? poblados?\b", "CentroPoblado", {"PUNTO"}),
    (r"\b(?:linea(?:s)? de transmision|lt) existente(?:s)?\b", "LT_Existente", {"LINEA"}),
    (r"\bsubestacion(?:es)? existente(?:s)?\b", "SE_Existente", {"PUNTO"}),
    (r"\bductos?\b|\bpozos?\b", "Ductos_Pozos", {"PUNTO", "LINEA"}),
]


def _public(row, parts, names, geometry):
    official = re.compile(r"\b(?:ana|sernanp|sunarp|mtc|ingemmet|inei|minam|serfor|mincul|osiner[g]?min|minem|midagri|perupetro)\b|ministerio de cultura")
    source_indexes = [i for i, name in enumerate(names) if official.search(name)]
    simplified = any(name.startswith("ly simp ") for name in names)
    if not source_indexes and not simplified:
        return None
    # Revisar primero la capa más específica; un padre ANP no tapa una zona de amortiguamiento.
    found = None
    for index in range(len(names) - 1, -1, -1):
        for pattern, concept, geometries in _PUBLIC_THEMES:
            if re.search(pattern, names[index]):
                found = index, concept, geometries
                break
        if found:
            break
    if not found:
        return None
    index, concept, geometries = found
    # Evitar que el nombre de la entidad SUNARP sustituya un tema hijo explícito no identificado.
    if concept == "PredioSUNARP" and index != len(names) - 1 and not any("predio" in name for name in names[index:]):
        return None
    target = concept + "_Recorte"
    source_root = parts[:max((i for i in source_indexes if i <= index), default=max(index - 1, 0)) + 1]
    pending = "Confirmar entidad, capa matriz, id_origen y alcance del recorte histórico; conservar las copias correspondientes a cada proyecto."
    ambiguous_internal = any(re.search(r"\bampliad\w*\b|\bcomplement\w*\b", name) for name in names)
    if geometry not in geometries or ambiguous_internal:
        return _result(row, source_root, geometry, "Tema de recorte por revisar", "", [target], concept,
                       "El nombre identifica un tema del EFT, pero la geometría o la condición de complemento necesita definición.",
                       pending + " Revisar Datos_Internos y prevalencia cuando corresponda.", "5.8.6; 5.8.9")
    return _result(row, source_root, geometry, "Recorte de referencia", target, [target], concept,
                   "Fuente o capa LY_SIMP y nombre temático compatibles con el EFT; el KMZ representa una instantánea del proyecto.",
                   pending, "5.8.6; 5.8.8; 5.8.9")


def classify(row):
    """Devolver únicamente propuesta y pendientes, sin modificar la fila recibida."""
    geometry = str(row.get("geometria", "")).strip().upper()
    try:
        parts = _parts(row)
    except (ValueError, TypeError, json.JSONDecodeError):
        return _result(row, [], geometry, "Jerarquía por recuperar", reason="Falta una jerarquía JSON válida; no se separa la ruta por barras.",
                       pending="Recuperar ruta_componentes_json del inventario antes de clasificar.")
    names = [_norm(part) for part in parts]
    leaf = names[-1] if names else ""
    meaningful = _last_significant(parts, names)
    pls = next((i for i, name in enumerate(names) if re.search(r"\bpls\s*cadd\b", name)), None)
    if pls is not None:
        return _pls(row, parts, names, geometry, pls)
    if geometry not in {"PUNTO", "LINEA", "POLIGONO"}:
        return _result(row, meaningful, geometry, "Geometría especial por revisar", reason="Modelo 3D, traza GX, ausencia de geometría o tipo no contemplado como punto, línea o polígono.",
                       pending="Revisar la representación original y el tratamiento de exclusión o extracción; conservar la fila pendiente.", reference="5.8.6; 5.8.9")
    calicatas = [i for i, name in enumerate(names) if re.search(r"\bcalicatas?\b", name)]
    if calicatas:
        return _result(row, parts[:calicatas[-1] + 1], geometry, "Calicatas y auxiliares", "Calicatas" if geometry == "PUNTO" else "", ["Calicatas"],
                       reason="El ancestro Calicatas identifica el trabajo geotécnico, aunque la hoja se llame LT, Subestación o Vértices.",
                       pending="Validar los puntos de calicata; interpretar por separado líneas y polígonos auxiliares sin convertirlos a calicatas puntuales.", reference="5.8.6; 5.8.8")
    stations = [i for i, name in enumerate(names[:-1]) if _station(name)]
    explicit_field = [i for i, name in enumerate(names) if re.search(r"\bareas? de estudio de campo\b", name)]
    study_leaf = re.search(r"\bareas? de estudio\b", leaf) is not None
    if geometry == "POLIGONO" and (explicit_field or (stations and study_leaf)):
        anchor = stations[-1] if stations else explicit_field[-1]
        return _result(row, parts[:anchor + 1], geometry, "Área de estudio de campo", "AreaEstudioCampo", ["AreaEstudioCampo"],
                       reason="Polígono de estudio de campo explícito o área de estudio bajo una estación EBI, F o SOC.",
                       pending="Conservar y validar la estación de origen; asociar proyecto/análisis sin sustituir el área de interés general.", reference="5.8.6 Polígonos de estudio; 5.8.8")
    public = _public(row, parts, names, geometry)
    if public:
        return public
    if leaf == "structure locations":
        return _result(row, parts[:-1], geometry, "Ubicaciones de estructuras por confirmar", "Estructuras" if geometry == "PUNTO" else "", ["Estructuras"],
                       reason="La etiqueta Structure locations aporta un rol específico de exportación, aunque PLS-CADD no figure como ancestro.",
                       pending="Confirmar procedencia PLS-CADD y revisar copias CAD; la propuesta no excluye repeticiones.", reference="5.8.6; 5.8.9")
    if re.fullmatch(r"(?:point|line|area|polygon|polyline|text|multipatch) features|(?:cad|texts?|annotations?)", leaf):
        return _result(row, meaningful, geometry, "Entidades CAD por interpretar", reason="La hoja describe primitivas CAD y no un tema de negocio.",
                       pending="Identificar entidades, textos y copias; determinar tema con la documentación del diseño antes de elegir clase.", reference="5.8.8; 5.8.9")
    if geometry in {"PUNTO", "POLIGONO"} and (re.search(r"\bsubestacion(?:es)?\b", leaf) or re.match(r"^se\s+", leaf)):
        return _result(row, meaningful, geometry, "Subestaciones de proyecto", "Subestacion", ["Subestacion"],
                       reason="Tema Subestación y geometría incluidos expresamente en el EFT.",
                       pending="Definir nombres físicos distintos para puntos y polígonos y confirmar el rol de la instalación; no hay nombre SQL aprobado.", reference="5.8.6; 5.8.8")
    if geometry == "PUNTO" and re.search(r"\b(?:torres?|estructuras?)\b", leaf):
        return _result(row, meaningful, geometry, "Estructuras de proyecto", "Estructuras", ["Estructuras"],
                       reason="Capa puntual rotulada como torres o estructuras; la fuente válida se confirma con PLS-CADD.",
                       pending="Revisar correspondencia con PLS-CADD y copias CAD de PARIÑAS; conservar todas las filas hasta decidir qué copia es válida.", reference="5.8.6; 5.8.9")
    for token, expected_geom, concept in ((r"\bvanos?\b", "LINEA", "Vanos"), (r"\baccesos?\b", "LINEA", "Accesos"),
                                           (r"\bfranja(?: de servidumbre)?\b|\bfaja de servidumbre\b", "POLIGONO", "FranjaServidumbre"),
                                           (r"\bmuestreo\b", "PUNTO", "Muestreo"), (r"\bregistro(?: de)? campo\b", geometry, "RegistroCampo")):
        if re.search(token, leaf) and geometry == expected_geom and (concept != "RegistroCampo" or geometry in {"PUNTO", "LINEA"}):
            return _result(row, meaningful, geometry, "Tema de proyecto", concept, [concept], reason="Nombre de tema y geometría compatibles con una clase expresa del EFT.",
                           pending="Confirmar contenido y atributos; Vanos requiere interpretar PLS-CADD y FranjaServidumbre requiere comprobar la servidumbre.", reference="5.8.6; 5.8.8; 5.8.9")
    if geometry == "POLIGONO" and (study_leaf or "area de interes" in leaf):
        general = ("general" in leaf or "del proyecto" in leaf or "area de interes" in leaf) and not stations
        return _result(row, meaningful, geometry, "Área de estudio por determinar", "mline_td_proyecto_area_interes" if general else "",
                       ["mline_td_proyecto_area_interes", "AreaEstudioCampo"],
                       reason="La distinción entre polígono general y área por estación requiere contexto; una hoja Área de estudio no basta.",
                       pending="Confirmar alcance general o estación y vínculo con componente; comprobar equivalencia con el área de interés de Mapline.", reference="5.8.6 Polígonos de estudio; 5.8.8")
    if geometry == "LINEA" and (re.search(r"\blt(?=\s|\d|$)|\blineas? de transmision\b|\beje de (?:linea de )?transmision\b", leaf) or re.fullmatch(r"alternativa\s+\d+", leaf)):
        return _result(row, meaningful, geometry, "Trazado de transmisión por determinar", "", ["mline_td_proyecto_ltransmision", "mline_td_proyecto_infraestructura"],
                       reason="El rótulo de LT o alternativa no distingue la infraestructura del componente frente al trazo analizado de una alternativa.",
                       pending="Determinar componente, alternativa y correspondencia SQL antes de elegir una de las dos clases.", reference="5.8.4; 5.8.6; 5.8.10")
    if geometry == "PUNTO" and re.search(r"\bvertices?\b", leaf):
        return _result(row, meaningful, geometry, "Vértices por determinar", "", ["Vertices"],
                       reason="Los vértices editados históricos de Mapline no se recuperan desde una tabla; el EFT prevé generarlos desde trazos.",
                       pending="Distinguir vértices de trazo de límites prediales u otros diseños y validar su secuencia y padre.", reference="5.8.4 Vértices; 5.8.6")
    return _result(row, meaningful, geometry, "Contexto pendiente de tema", reason="Se conserva el último ancestro significativo para revisar el contenido; la geometría no define por sí sola un tema del EFT.",
                   pending="Identificar el tema con los atributos, contexto y documentación; no crear una clase nueva sin revisar la tabla de mapeo.")
