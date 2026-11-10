"""Clasificacion de los grupos del KMZ hacia las clases del EFT 5.8 (funciones puras, sin arcpy).

Un grupo es (archivo, ruta de carpetas, geometria). Cada regla devuelve una propuesta con confianza y los
supuestos (S-xx) y preguntas (Q-xx) que la sostienen; el mapeo editable decide al final que se carga.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import eft_modelo as modelo
from eft_atributos import ESTACION, compactar
from eft_modelo import LINEA, POLIGONO, PUNTO

REGLAS_VERSION = "1"
MULTIPATCH = "MULTIPATCH"
SIN_ENTIDAD = "SIN_ENTIDAD"
SUPERPOSICION = "SUPERPOSICION"
GEOMETRIA_DE_SALIDA = {"Point": PUNTO, "Polyline": LINEA, "Polygon": POLIGONO, "MultiPatch": MULTIPATCH}
CARGAR, PENDIENTE, EXCLUIDO = "CARGAR", "PENDIENTE", "EXCLUIDO"
ALTA, MEDIA, BAJA = "ALTA", "MEDIA", "BAJA"
INGENIERIA, PREDIAL, AMBIENTAL = modelo.DISCIPLINAS
NIVELES_RAIZ = 2  # documento y carpeta del proyecto: no aportan disciplina, alternativa ni fuente
ID_ANALISIS_INICIAL = "Carga inicial KMZ"

PROYECTOS = (
    ("chanchamayo", "PRY-00000005"), ("felam", "PRY-00000027"), ("huaraz", "PRY-00000004"),
    ("jaen norte", "PROV-JAENNORTE"), ("jaennorte", "PROV-JAENNORTE"), ("muyurina", "PRY-00000025"),
    ("palian", "PRY-00000026"), ("parinas", "PRY-00000009"), ("poroma", "PROV-POROMA"),
    ("pucallpa", "PRY-00000001"),
)


@dataclass(frozen=True)
class Grupo:
    grupo_id: str
    archivo: str
    ruta: tuple
    geometria: str
    objetos: int
    entidades: int


@dataclass
class Decision:
    estado: str = PENDIENTE
    destino: str = ""
    confianza: str = BAJA
    familia: str = ""
    motivo: str = ""
    supuestos: tuple = ()
    preguntas: tuple = ()
    proyecto: str = ""
    componente: str = ""
    alternativa: str = ""
    disciplina: str = ""
    condicion: str = ""
    fuente: str = ""
    tema: str = ""
    capa_origen: str = ""

    @property
    def incluir(self):
        return "SI" if self.estado == CARGAR else "NO"


_CAMEL_1 = re.compile(r"([a-záéíóúñ])([A-ZÁÉÍÓÚÑ])")
_CAMEL_2 = re.compile(r"([A-ZÁÉÍÓÚÑ])([A-ZÁÉÍÓÚÑ][a-záéíóúñ])")


def texto_visible(valor):
    return compactar(html.unescape(re.sub(r"<[^>]*>", " ", str(valor or ""))))


def norm(valor):
    texto = _CAMEL_2.sub(r"\1 \2", _CAMEL_1.sub(r"\1 \2", texto_visible(valor)))
    texto = "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", texto.casefold()).strip()


def grupo_id(archivo, ruta, geometria):
    """Identificador estable: depende del nombre del archivo y la ruta, no del hash, para sobrevivir a versiones nuevas."""
    base = "|".join((archivo, json.dumps(list(ruta), ensure_ascii=False, separators=(",", ":")), geometria))
    return "G" + hashlib.blake2b(base.encode("utf-8"), digest_size=6).hexdigest()


def ruta_texto(ruta):
    return " / ".join(texto_visible(parte) or "(sin nombre)" for parte in ruta)


def _geometria_de(tipo, clase):
    if tipo in ("GroundOverlay", "ScreenOverlay"):
        return SUPERPOSICION
    return GEOMETRIA_DE_SALIDA.get(clase, SIN_ENTIDAD)


def _ruta_de(contenedores):
    try:
        return tuple(str(item.get("name") or "") for item in json.loads(contenedores or "[]"))
    except (ValueError, AttributeError):
        return ()


def leer_grupos(ruta_db, archivos_por_sha):
    """Grupos de los KMZ indicados ({sha256: nombre de archivo}), leidos solo de trazabilidad.sqlite."""
    if not archivos_por_sha:
        return []
    conexion = sqlite3.connect(Path(ruta_db).resolve().as_uri() + "?mode=ro", uri=True)
    acumulado = {}
    try:
        marcas = ",".join("?" * len(archivos_por_sha))
        consulta = (
            "SELECT o.sha, json_extract(o.payload, '$.containers'), o.kind, s.class_name, "
            "COUNT(DISTINCT o.id), COALESCE(SUM(s.quantity), 0) "
            "FROM originals o LEFT JOIN outputs s ON s.id = o.id "
            f"WHERE o.sha IN ({marcas}) "
            "GROUP BY o.sha, json_extract(o.payload, '$.containers'), o.kind, s.class_name")
        for sha, contenedores, tipo, clase, objetos, entidades in conexion.execute(consulta, list(archivos_por_sha)):
            clave = (archivos_por_sha[sha], _ruta_de(contenedores), _geometria_de(tipo, clase))
            previo = acumulado.get(clave, (0, 0))
            acumulado[clave] = (previo[0] + objetos, previo[1] + entidades)
    finally:
        conexion.close()
    grupos = [Grupo(grupo_id(a, r, g), a, r, g, o, e) for (a, r, g), (o, e) in acumulado.items()]
    return sorted(grupos, key=lambda x: (x.archivo.casefold(), x.ruta, x.geometria))


_GENERICOS = frozenset({
    "", "points", "lines", "polygons", "placemarks", "folder", "document", "features", "puntos", "lineas",
    "poligonos", "elementos", "sin nombre", "final", "prefinal", "point", "line", "polygon", "polyline",
    "point features", "line features", "area features", "polygon features", "polyline features",
    "multipatch features",
})
_CAD = re.compile(r"^(?:cad|texts?|textos?|annotations?|anotaciones?|labels?|etiquetas?)$")

_OFICIALES = tuple((re.compile(patron), nombre) for patron, nombre in (
    (r"\bana\b|\bautoridad nacional del agua\b", "ANA"), (r"\bsernanp\b", "SERNANP"), (r"\bserfor\b", "SERFOR"),
    (r"\bminam\b", "MINAM"), (r"\bingemmet\b", "INGEMMET"),
    (r"\bmincul\b|\bministerio de cultura\b|\bsigda\b", "Ministerio de Cultura"), (r"\bsunarp\b", "SUNARP"),
    (r"\bmidagri\b|\bminagri\b|\bsicar\b", "MIDAGRI"), (r"\bminem\b", "MINEM"), (r"\bperupetro\b", "PERUPETRO"),
    (r"\bosinerg(?:min)?\b", "OSINERGMIN"), (r"\bmtc\d*\b", "MTC"), (r"\binei\b", "INEI"),
    (r"\binaigem\b", "INAIGEM"), (r"\bsenace\b", "SENACE"), (r"\bsbn\b", "SBN"),
))

# (patron, disciplina, inferida): la primera carpeta desde la raiz que coincide define la disciplina.
_DISCIPLINAS = (
    (re.compile(r"\bingenieria\b|\blineas? de (?:transmision|trasmision)\b|\bsubestaciones\b"), INGENIERIA, False),
    (re.compile(r"\bconsultor predial\b|\bpredial\b"), PREDIAL, False),
    (re.compile(r"\bconsultor ambiental\b|\bambiental\b"), AMBIENTAL, False),
    (re.compile(r"\banteproyecto\b|\bwsp\b|\bapplus\b|\bcomplementarios\b"), INGENIERIA, True),
    (re.compile(r"\bwalsh\b|\barqueologic\w*|\bpaleontologic\w*"), AMBIENTAL, True),
    (re.compile(r"\bsocial\b"), PREDIAL, True),
)
_ALTERNATIVA = re.compile(r"\balternativa \d+\b|\balt \d+\b|\bcaso base\b")
_COMPONENTE = re.compile(r"^(?:lt|l t|se|s e|linea|enlace|subestacion)\b|\b\d+ ?k ?v\b")
_CONDICIONES = (
    ("Nuevo", re.compile(r"\bnuev[oa]s?\b")),
    ("Proyectado", re.compile(r"\bproyectad[oa]s?\b|\bpropuest[oa]s?\b|\bfutur[oa]s?\b|\bampliacion(?:es)?\b")),
    ("Existente", re.compile(r"\bexistentes?\b|\boperativ[oa]s?\b|\ben operacion\b|\bsub oper\b")),
)
_FUENTE_POR_DISCIPLINA = {INGENIERIA: "Ingeniería", PREDIAL: "Consultor predial", AMBIENTAL: "Consultor ambiental"}
_CAMBIO_TEMA = {
    modelo.TEMA_AMBIENTAL: "Ambiental y cultural", modelo.TEMA_DERECHOS: "Derechos territoriales",
    modelo.TEMA_INFRAESTRUCTURA: "Infraestructura y referencia",
}


@dataclass
class _Hit:
    destino: str
    confianza: str
    familia: str
    motivo: str = ""
    supuestos: tuple = ()
    preguntas: tuple = ()


class _Contexto:
    def __init__(self, archivo, ruta, geometria):
        self.archivo = archivo
        self.ruta = tuple(ruta)
        self.geom = geometria
        self.partes = tuple(norm(parte) for parte in self.ruta)
        self.indice = self._significativo()
        self.hoja = self.partes[self.indice] if self.indice is not None else ""
        self.cad_generico = bool(self.partes) and bool(_CAD.match(self.partes[-1]))
        self.oficial = self._oficial()
        self.disciplina, self.disciplina_inferida = self._disciplina()

    def _significativo(self):
        for i in range(len(self.partes) - 1, NIVELES_RAIZ - 1, -1):
            parte = self.partes[i]
            if (parte not in _GENERICOS and not _CAD.match(parte)
                    and not _COMPONENTE.search(parte)
                    and not ESTACION.match(texto_visible(self.ruta[i]))):
                return i
        return None

    def nivel(self, k):
        i = None if self.indice is None else self.indice - k
        return self.partes[i] if i is not None and i >= NIVELES_RAIZ else ""

    def _oficial(self):
        if self.indice is None:
            return None
        for i in range(self.indice, NIVELES_RAIZ - 1, -1):
            for patron, nombre in _OFICIALES:
                if patron.search(self.partes[i]):
                    return nombre
        return None

    def _disciplina(self):
        for i in range(NIVELES_RAIZ, len(self.partes)):
            for patron, disciplina, inferida in _DISCIPLINAS:
                if patron.search(self.partes[i]):
                    return disciplina, inferida
        return "", False

    def ancestro(self, patron):
        return any(re.search(patron, parte) for parte in self.partes[NIVELES_RAIZ:])

    def en_cola(self, patron, cantidad=3):
        return any(re.search(patron, parte) for parte in self.partes[-cantidad:])


def _pendiente(familia, motivo, supuestos=(), preguntas=()):
    return _Hit("", BAJA, familia, motivo, supuestos, preguntas)


def _especial(ctx):
    if ctx.geom == SIN_ENTIDAD:
        return _pendiente("Geometria", "Placemarks sin entidad convertida (texto, modelo 3D, multiparte o sin geometria); "
                          "se conservan en originales y balance.", ("S-18",), ("Q-06",))
    if ctx.geom == SUPERPOSICION:
        return _pendiente("Geometria", "GroundOverlay/ScreenOverlay: no son geometria vectorial; se conservan en originales.",
                          ("S-18",), ("Q-06",))
    return _pendiente("Geometria", "Multipatch (modelo 3D): el EFT no define clase para modelos 3D.", ("S-18",), ("Q-07",))


def _pls(ctx):
    if not ctx.en_cola(r"\bstructure locations?\b|\bsection \d+|\bstructure [a-z0-9]+$|\bpls ?cadd\b|\bplscadd\b"):
        return None
    supuestos, preguntas = ("S-11",), ("Q-04",)
    if re.search(r"\bstructure locations?\b", ctx.hoja):
        if ctx.geom == PUNTO:
            return _Hit("Estructuras", MEDIA, "PLS-CADD", "Ubicaciones de estructuras de PLS-CADD.", supuestos, preguntas)
        return _pendiente("PLS-CADD", "Ubicaciones de estructuras que no son puntos.", supuestos, preguntas)
    if ctx.en_cola(r"\bsection \d+"):
        if ctx.geom == LINEA:
            return _Hit("Vanos", MEDIA, "PLS-CADD", "Seccion de PLS-CADD: lineas de vano.", supuestos, preguntas)
        return _pendiente("PLS-CADD", "Detalle de seccion de PLS-CADD (estructuras, poligonos o modelo 3D).",
                          supuestos, preguntas)
    return _pendiente("PLS-CADD", "Modelo o detalle de PLS-CADD sin identificar vano ni estructura.", supuestos, preguntas)


def _calicatas(ctx):
    if not ctx.ancestro(r"\bcalicatas?\b"):
        return None
    if ctx.geom == PUNTO:
        return _Hit("Calicatas", MEDIA, "Calicatas", "Punto de investigacion dentro de una carpeta de calicatas.",
                    ("S-15",), ())
    sugerencia = "RegistroCampo" if ctx.geom == LINEA else ""
    return _Hit(sugerencia, BAJA, "Calicatas", "Calicatas solo admite puntos; las lineas y poligonos de la carpeta "
                "(p. ej. lineas geofisicas o CAD) requieren decision.", ("S-15",), ("Q-14",))


def _con_estacion(ctx):
    for parte in reversed(ctx.ruta[NIVELES_RAIZ:]):
        if ESTACION.match(texto_visible(parte)):
            return True
    return False


def _estaciones(ctx):
    if ctx.geom == POLIGONO and (re.search(r"\barea (?:de )?estudio(?: de campo)?$", ctx.hoja)
                                 and (_con_estacion(ctx) or "de campo" in ctx.hoja)):
        return _Hit("AreaEstudioCampo", MEDIA, "Estacion", "Poligono de area de estudio de campo de una estacion.",
                    ("S-16",), ())
    if ctx.geom == PUNTO and re.search(r"\bmuestreo\b", ctx.hoja):
        return _Hit("Muestreo", MEDIA, "Estacion", "Puntos de muestreo.", ("S-16",), ())
    return None


def _ancho_franja(texto):
    coincidencia = re.search(r"\b(\d+) ?m\b", texto)
    return int(coincidencia.group(1)) if coincidencia else None


def _subestacion(ctx):
    if not re.search(r"\bsubestacion(?:es)?\b|^s e\b|^se\b|\bs e\b", ctx.hoja):
        return None
    if ctx.geom not in (PUNTO, POLIGONO):
        return None
    existente = re.search(r"\bexistentes?\b|\ben operacion\b|\bsub oper\b|\boperativ\w*\b", ctx.hoja)
    publica = ctx.oficial in ("OSINERGMIN", "MINEM") or "ly simp" in ctx.hoja or "distribucion" in ctx.hoja
    if ctx.geom == PUNTO and (publica or (existente and ctx.disciplina != INGENIERIA)):
        return _Hit("SE_Existente_Recorte", MEDIA, "Proyecto", "Subestaciones de una capa de referencia.", ("S-08",), ())
    return _Hit("Subestacion", MEDIA, "Proyecto", "Subestacion del proyecto.", (), ())


def _proyecto(ctx):
    hoja, geom = ctx.hoja, ctx.geom
    if not hoja:
        return None
    resultado = _subestacion(ctx)
    if resultado:
        return resultado
    if geom == PUNTO and re.search(r"\b(?:torres?|estructuras?|apoyos?)\b", hoja):
        return _Hit("Estructuras", MEDIA, "Proyecto", "Torres o estructuras.", (), ())
    if geom == PUNTO and re.search(r"\bvertices?\b", hoja):
        return _Hit("Vertices", MEDIA, "Proyecto", "Vertices del trazo.", (), ())
    if geom == LINEA and re.search(r"\bvanos?\b", hoja):
        return _Hit("Vanos", MEDIA, "Proyecto", "Vanos.", (), ())
    if geom == LINEA and (re.search(r"\baccesos?\b|\btrochas?\b|\bcarreteables?\b|\bcaminos? (?:de acceso|peatonal(?:es)?"
                                    r"|propuestos?|nuevos?|proyectados?|existentes?)\b", hoja)
                          or (re.search(r"\bcaminos?\b", hoja) and ctx.ancestro(r"\baccesos?\b"))):
        return _Hit("Accesos", MEDIA, "Proyecto", "Accesos al proyecto.", (), ())
    if re.search(r"\bfranja\b|\bfaja de servidumbre\b", hoja):
        ancho = _ancho_franja(hoja)
        if geom != POLIGONO:
            return None
        if ancho is not None and ancho > 60:
            return _Hit("FranjaServidumbre", BAJA, "Proyecto", f"Franja de {ancho} m: mas ancha que una servidumbre "
                        "(corredor de estudio).", ("S-24",), ("Q-13",))
        return _Hit("FranjaServidumbre", MEDIA, "Proyecto", "Franja de servidumbre.", ("S-24",), ("Q-13",))
    if geom == PUNTO and re.search(r"\bwaypoints?\b|\bimagenes? de campo\b|\bfotos? de campo\b|\bvisitas? de reconocimiento"
                                   r"|\bpuntos? (?:de )?visita\b", hoja):
        return _Hit("RegistroCampo", MEDIA, "Proyecto", "Registro de campo (puntos).", ("S-25",), ("Q-20",))
    if geom == LINEA and re.search(r"\btracks?\b|\btrack ?logs?\b|\brecorridos? de campo\b", hoja):
        return _Hit("RegistroCampo", MEDIA, "Proyecto", "Registro de campo (recorridos).", ("S-25",), ("Q-20",))
    return None


# (patron, destino, confianza base, supuestos, preguntas, motivo si queda pendiente)
_TEMAS_DEF = (
    (r"\bzon\w* (?:de )?amort\w*", "ZonaAmortiguamiento_Recorte", MEDIA, ("S-08",), (), ""),
    (r"\bareas? (?:de )?conservacion\b|\bacp\b|\bacr\b", "AreaConservacion_Recorte", MEDIA, ("S-08",), (), ""),
    (r"\banp\b|\bareas? naturales? protegidas?\b", "ANPNacional_Recorte", MEDIA, ("S-08",), (), ""),
    (r"\bfaj\w* marg\w*", "FajasMarginales_Recorte", MEDIA, ("S-08",), (), ""),
    (r"\brios?\b|\bred hidrografica\b|\bhidrografia\b", "Rios_Recorte", MEDIA, ("S-08",), (), ""),
    (r"\bcanal(?:es)?\b|\bcan (?:lat|deriv)\w*", "Canales_Recorte", MEDIA, ("S-08",), (), ""),
    (r"\blagunas?\b|\blagos?\b|\bcochas?\b", "Lagunas_Recorte", MEDIA, ("S-08",), (), ""),
    (r"\bbofedales?\b", "EcosistemasFragiles_Recorte", MEDIA, ("S-08", "S-13"), ("Q-11",), ""),
    (r"\becosistemas? fragiles?\b|\bhumedales?\b|\bparamos?\b|\blomas\b", "EcosistemasFragiles_Recorte", MEDIA,
     ("S-08",), ("Q-11",), ""),
    (r"\becosistemas?\b", "EcosistemasFragiles_Recorte", BAJA, ("S-08",), ("Q-11",),
     "Capa de ecosistemas general; solo parte de ella son ecosistemas fragiles."),
    (r"\b(?:iba|eba|kba)\b|\bareas? importantes? para (?:la conservacion de )?las aves\b", "IBA_EBA_KBA_Recorte",
     MEDIA, ("S-08",), (), ""),
    (r"\bcobertura vegetal\b", "CoberturaVegetal_Recorte", MEDIA, ("S-08",), (), ""),
    (r"\bcobertura agricola\b", "CoberturaVegetal_Recorte", BAJA, ("S-08",), ("Q-19",),
     "Cobertura agricola: se propone CoberturaVegetal, falta confirmar."),
    (r"\bgeologi\w*|\blitolog\w*|\bfallas?\b|\bpliegues?\b", "Geologia_Recorte", MEDIA, ("S-08",), (), ""),
    (r"\bgeomorfolog\w*", "Geomorfologia_Recorte", MEDIA, ("S-08",), (), ""),
    (r"\bzee\b|\bzonificacion ecologica\b", "ZEE_Recorte", MEDIA, ("S-08",), (), ""),
    (r"\bsitios? arqueologicos?\b|\bsa (?:registrados?|gabinete|campo|en campo)\b|\bareas? sa\b|\bcatastro arql\b"
     r"|\bcatastro arqueologico\b|\bsigda\b|\bzonas? arqueologicas?\b|\bmonumentos? arqueologicos?\b",
     "SitioArqueologico_Recorte", MEDIA, ("S-08",), ("Q-12",), ""),
    (r"\bqhapaq\b|\bcamino inca\b", "QhapaqNan_Recorte", MEDIA, ("S-08",), (), ""),
    (r"\bp[ae]leontolog\w*|\bfosiles?\b|\bammonites?\b", "Paleontologia_Recorte", MEDIA, ("S-08",), ("Q-12",), ""),
    (r"\bpredios? rurales?\b|\bcatastro rural\b", "PredioRural_Recorte", MEDIA, ("S-08", "S-17"), (), ""),
    (r"\bly simp (?:\d+ )*predios?\b|\bpredios? (?:inscritos?|privados?|sunarp)\b|\bsunarp\b|\bpartidas? registrales?\b",
     "PredioSUNARP_Recorte", MEDIA, ("S-08", "S-17"), (), ""),
    (r"\bcomunidad(?:es)? campesinas?\b", "ComunidadCampesina_Recorte", MEDIA, ("S-08",), (), ""),
    (r"\bcatastro minero\b|\bconcesion(?:es)? mineras?\b|\bcum\b|\bly simp mineras?\b|\bderechos? mineros?\b",
     "CatastroMinero_Recorte", MEDIA, ("S-08", "S-14"), ("Q-11",), ""),
    (r"\bconcesion(?:es)? electricas?\b|\bc (?:distribucion|generacion|transmision)\b", "ConcesionElectrica_Recorte",
     MEDIA, ("S-08",), (), ""),
    (r"\blotes? (?:de )?hidrocarburos?\b|\blotes? petroleros?\b", "LotesHidrocarburos_Recorte", MEDIA, ("S-08",), (), ""),
    (r"\bderechos? (?:de )?(?:uso (?:de )?)?agua\b|\blicencias? (?:de )?(?:uso (?:de )?)?agua\b",
     "DerechosAgua_Recorte", MEDIA, ("S-08",), (), ""),
    (r"\b(?:lineas? de transmision|lt|lineas? electricas?) (?:existentes?|en operacion)\b|\blt en operacion\b",
     "LT_Existente_Recorte", MEDIA, ("S-08",), (), ""),
    (r"\bredes? (?:de )?media tension\b|\bredes? mt\b|\bmedia tension\b", "RedesMT_Recorte", MEDIA, ("S-08",), (), ""),
    (r"\brvn\b|\bvias? nacional(?:es)?\b|\bred vial nacional\b|\bcarreteras? nacional(?:es)?\b", "ViasNacional_Recorte",
     MEDIA, ("S-08",), (), ""),
    (r"\brvd\b|\brvr\b|\bvias? (?:regional(?:es)?|departamental(?:es)?)\b|\bred vial (?:regional|departamental)\b",
     "ViasRegional_Recorte", MEDIA, ("S-08",), (), ""),
    (r"\brvv\b|\bvias? vecinal(?:es)?\b|\bred vial vecinal\b|\bcaminos? vecinal(?:es)?\b", "ViasVecinal_Recorte", MEDIA,
     ("S-08",), (), ""),
    (r"\bred vial\b|\bredes viales\b|\bvias? existentes?\b|\bcarreteras?\b", "", BAJA, (), ("Q-19",),
     "Red vial sin categoria nacional, regional o vecinal."),
    (r"\boleoductos?\b|\bgasoductos?\b|\bductos?\b|\bpozos?\b|\blineas? de recoleccion\b", "Ductos_Pozos_Recorte", MEDIA,
     ("S-08",), (), ""),
    (r"\blimites? (?:de )?departament\w*|\bdepartamentos?\b", "LimiteDepartamento_Recorte", MEDIA, ("S-08",), (), ""),
    (r"\blimites? (?:de )?provinc\w*|\bprovincias?\b", "LimiteProvincia_Recorte", MEDIA, ("S-08",), (), ""),
    (r"\blimites? (?:de )?distrit\w*|\bdistritos?\b", "LimiteDistrito_Recorte", MEDIA, ("S-08",), (), ""),
    (r"\bcentros? poblados?\b|\bccpp\b|\blocalidades?\b", "CentroPoblado_Recorte", MEDIA, ("S-08",), (), ""),
    (r"\buso actual\b|\busos? actuales?\b", "UsoActual_Recorte", MEDIA, ("S-08",), (), ""),
    (r"\bposeedores?\b|\bposesionarios?\b", "Poseedores_Recorte", MEDIA, ("S-08",), (), ""),
    (r"\bcaminos? (?:de )?herradura\b", "CaminosHerradura_Recorte", MEDIA, ("S-08",), (), ""),
    (r"\bsusceptibilidad\b|\bcapacidad (?:de )?uso mayor\b|\bcuencas?\b|\bunidades? hidrograficas?\b|\becorregiones?\b"
     r"|\bzonas? de vida\b|\bclasificacion (?:climatica|hidrogeologica)\b|\breservas? de biosfera\b|\bramsar\b"
     r"|\bhabitats? criticos?\b|\bfisiografia\b|\bsuelos?\b|\bconcesiones? forestales?\b|\bsenace\b",
     "", BAJA, (), ("Q-19",), "Tema sin clase en el EFT 5.8."),
)
_TEMAS = tuple((re.compile(p), d, c, s, q, m) for p, d, c, s, q, m in _TEMAS_DEF)


def _temas(ctx):
    for k in range(3):
        texto = ctx.nivel(k)
        if not texto:
            break
        for patron, destino, base, supuestos, preguntas, motivo in _TEMAS:
            if not patron.search(texto):
                continue
            confianza = base
            if k > 0:
                confianza = BAJA
            elif base == MEDIA and (ctx.oficial or "ly simp" in ctx.hoja):
                confianza = ALTA
            if not destino:
                return _Hit("", BAJA, "Tema", motivo, supuestos, preguntas)
            origen = "" if k == 0 else f" (tema inferido de la carpeta superior '{texto}')"
            nota = motivo or ("Tema de referencia reconocido por el nombre de la capa" + origen)
            return _Hit(destino, confianza, "Tema", nota, supuestos, preguntas)
    return None


def _area_estudio(ctx):
    if re.search(r"\barea (?:de )?(?:estudio|interes|influencia)\b", ctx.hoja):
        return _pendiente("Area de estudio", "Area de estudio o de interes general: pertenece a la clase migrada "
                          "mline_td_proyecto_area_interes (fuera de esta carga).", ("S-12",), ("Q-05",))
    return None


def _traza(ctx):
    if ctx.geom == LINEA and re.search(r"\blt\b|\blineas? de transmision\b|\beje de (?:linea de )?transmision\b"
                                       r"|\balternativa \d+\b|\btrazo\b", ctx.hoja):
        return _pendiente("Traza", "Trazo de linea de transmision: va a las clases migradas (td_proyecto_ltransmision).",
                          ("S-12",), ("Q-05",))
    if ctx.geom == PUNTO and re.search(r"\balternativa \d+\b|\btrazo\b", ctx.hoja):
        return _pendiente("Traza", "Puntos de una alternativa o trazo; el EFT no define clase.", ("S-12",), ("Q-05",))
    return None


def proyecto_de(archivo):
    texto = norm(Path(str(archivo)).stem)
    for palabra, codigo in PROYECTOS:
        if palabra in texto:
            return codigo
    return ""


def componente_de(archivo):
    stem = texto_visible(Path(str(archivo)).stem)
    if not re.match(r"(?i)^g1\b", stem):
        return ""
    stem = re.sub(r"(?i)^g1\s*", "", stem)
    return compactar(re.sub(r"\s*\(\d+\)\s*$", "", stem))


def _alternativa(ctx):
    for i in range(NIVELES_RAIZ, len(ctx.partes)):
        if _ALTERNATIVA.search(ctx.partes[i]):
            return re.sub(r"(?i)\.kmz$", "", texto_visible(ctx.ruta[i]))[:100]
    return ""


def _condicion(ctx):
    for k in range(3):
        texto = ctx.nivel(k)
        for nombre, patron in _CONDICIONES:
            if texto and patron.search(texto):
                return nombre
    return ""


def _componente(ctx):
    for i in range(len(ctx.partes) - 1, NIVELES_RAIZ - 1, -1):
        if _COMPONENTE.search(ctx.partes[i]):
            return re.sub(r"(?i)\.kmz$", "", texto_visible(ctx.ruta[i]))[:150]
    return ""


def _capa_origen(ctx):
    for parte in reversed(ctx.ruta):
        visible = texto_visible(parte)
        if visible:
            return visible[:150]
    return ""


def _completar(ctx, hit):
    decision = Decision(familia=hit.familia, destino=hit.destino, confianza=hit.confianza, motivo=hit.motivo)
    supuestos, preguntas = list(hit.supuestos), list(hit.preguntas)
    if ctx.cad_generico:
        decision.motivo = ("Primitivas CAD genericas. " + decision.motivo).strip()
        if hit.destino:
            decision.confianza = BAJA
        else:
            decision.familia = decision.familia or "CAD"
            decision.motivo = decision.motivo or "Primitivas CAD genericas; carga de una sola copia a revision manual."
            preguntas.append("Q-08")
    if decision.destino:
        valido, razon = modelo.validar_destino(decision.destino, ctx.geom)
        if not valido:
            decision.confianza = BAJA
            decision.motivo = f"{razon} {decision.motivo}".strip()
    decision.estado = CARGAR if (decision.destino and decision.confianza in (ALTA, MEDIA)
                                 and modelo.validar_destino(decision.destino, ctx.geom)[0]) else PENDIENTE
    decision.proyecto = proyecto_de(ctx.archivo)
    supuestos.append("S-03")
    if not decision.proyecto or decision.proyecto.startswith("PROV-"):
        preguntas.append("Q-01")
        if decision.estado == CARGAR:
            decision.estado = PENDIENTE
            decision.motivo = (decision.motivo + " " if decision.motivo else "") + \
                "Codigo de proyecto provisional o no reconocido; requiere asignacion antes de cargar."
    decision.disciplina = ctx.disciplina
    if ctx.disciplina:
        supuestos.append("S-04")
        if ctx.disciplina_inferida:
            preguntas.append("Q-02")
    else:
        preguntas.append("Q-02")
    decision.capa_origen = _capa_origen(ctx)
    decision.alternativa = _alternativa(ctx)
    clase, recorte = modelo.separar_destino(decision.destino) if decision.destino else ("", False)
    definicion = modelo.CLASES.get(clase)
    decision.componente = componente_de(ctx.archivo)
    if not decision.componente and definicion and definicion.seccion == "proyecto":
        decision.componente = _componente(ctx)
    if decision.alternativa or decision.componente:
        supuestos.append("S-05")
    if definicion:
        if definicion.seccion == "proyecto":
            supuestos.append("S-02")
        decision.condicion = _condicion(ctx)
        if not decision.condicion and definicion.seccion != "proyecto":
            decision.condicion = "Existente"
            supuestos.append("S-22")
        elif decision.condicion:
            supuestos.append("S-05")
        if definicion.seccion != "proyecto":
            decision.tema = definicion.tema
            decision.fuente = ctx.oficial if ctx.oficial in modelo.FUENTES else definicion.fuente
        else:
            decision.fuente = _FUENTE_POR_DISCIPLINA.get(ctx.disciplina, "")
        if decision.fuente:
            supuestos.append("S-06")
    decision.supuestos = tuple(dict.fromkeys(supuestos))
    decision.preguntas = tuple(dict.fromkeys(preguntas))
    return decision


def clasificar(archivo, ruta, geometria):
    ctx = _Contexto(archivo, ruta, geometria)
    if geometria not in modelo.GEOMETRIAS:
        hit = _especial(ctx)
    elif ctx.indice is None:
        hit = _pendiente("Raiz", "Elementos directamente en el documento o la carpeta del proyecto, sin carpeta tematica.")
    else:
        hit = None
        for regla in (_pls, _calicatas, _estaciones, _proyecto, _temas, _area_estudio, _traza):
            hit = regla(ctx)
            if hit:
                break
        hit = hit or _pendiente("Sin regla", "Ninguna regla reconoce la carpeta; revisar manualmente.", (), ("Q-19",))
    return _completar(ctx, hit)


def prioridad_de_copia(ruta):
    """0 para la copia preferida y 1 para versiones preliminares (carpeta 'Prefinal'), que se cargan al final."""
    return 1 if any(re.search(r"\bprefinal\b", norm(parte)) for parte in ruta) else 0
