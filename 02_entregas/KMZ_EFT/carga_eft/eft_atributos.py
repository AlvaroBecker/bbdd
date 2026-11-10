"""Atributos de un Placemark KML: ExtendedData, tablas HTML de la descripcion y texto libre.

Funciones puras (sin arcpy). Los campos de sistema que el EFT 5.8.5 manda no cargar (FID, OBJECTID,
SHAPE_LENG, GLOBALID) y los campos tecnicos que ArcGIS agrega al exportar a KML se omiten de kz_atributos;
el payload completo sigue en trazabilidad.sqlite y en las tablas neutras de la carga 1.
"""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

LARGO_MAXIMO = 100000
LARGO_VALOR = 1000
LARGO_DESCRIPCION = 4000

OMITIDOS = frozenset({
    "fid", "oid_", "oid", "objectid", "objectid_1", "shape_leng", "shape_len", "shape_length", "shape_area",
    "shape__area", "shape__length", "globalid", "folderpath", "symbolid", "altmode", "base", "clamped",
    "extruded", "snippet", "popupinfo", "name",
})
CLAVES_ID_ORIGEN = ("CODRUTA", "ANP_CODI", "CODIGOU", "COD_PREDIO")
ESTACION = re.compile(r"^(?:EBI|F|SOC|IBA|PL|M)\s?\d{1,3}[A-Z]{0,2}$", re.IGNORECASE)
_CLAVE_LINEA = re.compile(r"^\s*([^:\n]{1,60}?)\s*:\s*(.+)$")


def compactar(valor):
    return re.sub(r"\s+", " ", str(valor).replace("\xa0", " ")).strip()


class _Html(HTMLParser):
    """Recoge filas de tabla (anidadas incluidas) y las lineas de texto visible."""

    _IGNORAR = ("style", "script", "head", "title")
    _CORTES = ("br", "p", "div", "li", "tr")

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.filas = []
        self.lineas = [""]
        self._pila = []
        self._ignorar = 0

    def _cerrar_celda(self):
        if self._pila and self._pila[-1][1] is not None:
            celdas, actual = self._pila[-1]
            celdas.append(compactar("".join(actual)))
            self._pila[-1][1] = None

    def handle_starttag(self, tag, attrs):
        if tag in self._IGNORAR:
            self._ignorar += 1
            return
        if tag == "tr":
            self._pila.append([[], None])
        elif tag in ("td", "th") and self._pila:
            self._cerrar_celda()
            self._pila[-1][1] = []
        if tag in self._CORTES:
            self.lineas.append("")

    def handle_startendtag(self, tag, attrs):
        if tag in self._CORTES:
            self.lineas.append("")

    def handle_endtag(self, tag):
        if tag in self._IGNORAR:
            self._ignorar = max(0, self._ignorar - 1)
            return
        if tag in ("td", "th"):
            self._cerrar_celda()
        elif tag == "tr" and self._pila:
            self._cerrar_celda()
            self.filas.append(self._pila.pop()[0])

    def handle_data(self, dato):
        if self._ignorar:
            return
        if self._pila and self._pila[-1][1] is not None:
            self._pila[-1][1].append(dato)
        self.lineas[-1] += dato


def pares_de_html(texto):
    """Devolver (pares, texto_visible) de una descripcion HTML o de texto plano."""
    analizador = _Html()
    try:
        analizador.feed(texto)
        analizador.close()
    except Exception:
        return [], compactar(re.sub(r"<[^>]+>", " ", texto))
    pares = [(f[0], f[1]) for f in analizador.filas if len(f) == 2 and f[0] and f[1]]
    lineas = [compactar(linea) for linea in analizador.lineas if compactar(linea)]
    if not pares:
        resto = []
        for linea in lineas:
            m = _CLAVE_LINEA.match(linea)
            if m and len(m.group(1).split()) <= 6:
                pares.append((m.group(1), m.group(2)))
            else:
                resto.append(linea)
        visible = compactar(" ".join(resto)) if pares else compactar(" ".join(lineas))
        return pares, visible
    return pares, compactar(" ".join(lineas))


def _agregar(destino, clave, valor):
    clave = compactar(clave)
    valor = compactar(valor)
    if not clave or not valor or clave.lower() in OMITIDOS:
        return
    existentes = {k.lower(): v for k, v in destino.items()}
    if clave.lower() in existentes:
        if existentes[clave.lower()] == valor:
            return
        sufijo = 2
        while f"{clave}_{sufijo}".lower() in existentes:
            sufijo += 1
        clave = f"{clave}_{sufijo}"
    destino[clave] = valor[:LARGO_VALOR]


def _local(etiqueta):
    return etiqueta.rsplit("}", 1)[-1]


def _extendido(elemento, destino):
    for hijo in elemento.iter():
        nombre = _local(hijo.tag)
        if nombre == "SimpleData" and hijo.get("name"):
            _agregar(destino, hijo.get("name"), hijo.text or "")
        elif nombre == "Data" and hijo.get("name"):
            valor = next((v.text or "" for v in hijo if _local(v.tag) == "value"), "")
            _agregar(destino, hijo.get("name"), valor)


def atributos_de(payload):
    """Atributos propios del Placemark como dict ordenado; nunca lanza por un XML mal formado."""
    atributos = {}
    descripciones = []
    for texto in payload.get("attribute_xml") or []:
        try:
            elemento = ET.fromstring(str(texto).strip())
        except ET.ParseError:
            continue
        nombre = _local(elemento.tag)
        if nombre == "ExtendedData":
            _extendido(elemento, atributos)
        elif nombre == "description" and (elemento.text or "").strip():
            descripciones.append(elemento.text)
        elif nombre == "TimeStamp":
            cuando = next((h.text for h in elemento.iter() if _local(h.tag) == "when"), "")
            _agregar(atributos, "kml_timestamp", cuando or "")
    for descripcion in descripciones:
        pares, visible = pares_de_html(descripcion)
        for clave, valor in pares:
            _agregar(atributos, clave, valor)
        if visible and not pares:
            _agregar(atributos, "descripcion", visible[:LARGO_DESCRIPCION])
    return atributos


def serializar(atributos, largo_maximo=LARGO_MAXIMO):
    """JSON compacto; si excede el campo se recortan valores y despues claves, y se marca _truncado."""
    def dumps(valor):
        return json.dumps(valor, ensure_ascii=False, separators=(",", ":"))

    texto = dumps(atributos)
    if len(texto) <= largo_maximo:
        return texto
    recortado = {k: v[:200] for k, v in atributos.items()}
    recortado["_truncado"] = True
    while len(dumps(recortado)) > largo_maximo and len(recortado) > 1:
        claves = [k for k in recortado if k != "_truncado"]
        recortado.pop(claves[-1])
    return dumps(recortado)


def id_origen(atributos):
    por_clave = {k.upper(): v for k, v in atributos.items()}
    for clave in CLAVES_ID_ORIGEN:
        if por_clave.get(clave):
            return por_clave[clave][:100]
    return None


def codigo_estacion(ruta, nombre=""):
    """Codigo de estacion (EBI01A, F03, SOC02, IBA05) del ancestro mas cercano a la hoja, o del nombre."""
    for parte in reversed(list(ruta)):
        limpio = compactar(re.sub(r"<[^>]+>", " ", str(parte)))
        if ESTACION.match(limpio):
            return limpio.replace(" ", "").upper()
    limpio = compactar(nombre)
    if ESTACION.match(limpio):
        return limpio.replace(" ", "").upper()
    return None


def nombre_de(nombre_original, ruta):
    """Nombre del KML; si esta vacio, el nombre de la carpeta hoja (supuesto S-23)."""
    nombre = compactar(nombre_original or "")
    if nombre:
        return nombre[:1000], False
    for parte in reversed(list(ruta)):
        limpio = compactar(re.sub(r"<[^>]+>", " ", str(parte)))
        if limpio:
            return limpio[:1000], True
    return None, False
