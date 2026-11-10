"""Plan puro de altas JAENNORTE/POROMA: no escribe ni reserva codigos.

``plan_projects(rows)`` recibe diccionarios con las claves de negocio de
``REQUIRED_FIELDS``. Las columnas adicionales se ignoran y nunca se copian a
un alta. ``fe_eliminacion`` o ``tiene_fecha_eliminacion`` son opcionales y se
consultan unicamente para advertir que un proyecto existente esta inactivo.

El resultado es serializable a JSON y contiene ``altas``, ``existentes`` y
``proyectos`` (estos ultimos en orden JAENNORTE, POROMA). Cada alta contiene
``valores`` para los siete campos de ``INSERT_FIELDS``. ``solo_plan`` y
``codigos_reservados`` expresan que estos valores son una prevision, no una
reserva. El llamador debe releer y planificar dentro de su sesion controlada
antes de insertar. Esta funcion no proporciona exclusion entre escritores.

Ante catalogo incompleto, ambiguo o inconsistente, levanta ``PlanError`` con
``incidencias`` serializables. Nunca devuelve un plan parcial con incidencias.
"""

import re
import unicodedata
from collections.abc import Mapping


MAX_PROJECT_ID = 99999999
REQUIRED_FIELDS = (
    "id_proyecto", "co_proyecto", "no_proyecto", "de_proyecto", "es_registro",
)
INSERT_FIELDS = (
    "id_proyecto", "id_tipo_proyecto", "id_estado_proyecto", "co_proyecto",
    "no_proyecto", "de_proyecto", "es_registro",
)
BUSINESS_DEFAULTS = {"id_tipo_proyecto": 8, "id_estado_proyecto": 3, "es_registro": "1"}
# Nombres internos documentados de los dos KML; no se infieren de otras filas.
PROJECTS = (
    {
        "proyecto": "JAENNORTE",
        "archivo_kmz": "Proyecto JAENNORTE.kmz",
        "no_proyecto": "Proyecto JAENNORTE",
        "de_proyecto": "LT 220 kV Caclic-Jaen Norte",
        "aliases": ("JAENNORTE", "JAEN NORTE", "LT 220 kV Caclic-Jaen Norte"),
    },
    {
        "proyecto": "POROMA",
        "archivo_kmz": "Proyecto POROMA.kmz",
        "no_proyecto": "Proyecto POROMA",
        "de_proyecto": "LT 220 kV Ica-Poroma",
        "aliases": ("POROMA", "LT 220 kV Ica-Poroma"),
    },
)


class PlanError(ValueError):
    """Error de prevalidacion; ``incidencias`` puede guardarse en un informe."""

    def __init__(self, incidencias):
        self.incidencias = incidencias
        super().__init__("Plan de altas detenido: " + "; ".join(
            item["mensaje"] for item in incidencias
        ))


def normalize_name(value):
    """Normaliza un nombre, sin tildes/puntuacion/espacios/prefijo Proyecto.

    Se ignora tambien la extension KMZ final. No se quitan otros prefijos,
    cifras ni palabras: por ejemplo G1, 138 kV o ampliacion siguen siendo
    diferencias semanticas que requieren revision.
    """
    if value is None:
        return ""
    if not isinstance(value, str):
        raise TypeError("El nombre debe ser texto o None.")
    text = "".join(c for c in unicodedata.normalize("NFKD", value.casefold())
                   if not unicodedata.combining(c))
    words = re.findall(r"[a-z0-9]+", text)
    if words and words[0] == "proyecto":
        words.pop(0)
    if words and words[-1] == "kmz":
        words.pop()
    return "".join(words)


def _issue(code, message, row=None, project=None, field=None):
    result = {"codigo": code, "mensaje": message}
    if row is not None:
        result["fila"] = row
    if project is not None:
        result["proyecto"] = project
    if field is not None:
        result["campo"] = field
    return result


def _validated_rows(rows):
    if isinstance(rows, (str, bytes, Mapping)):
        raise PlanError([_issue("CATALOGO_INVALIDO", "Se requiere una coleccion de filas.")])
    try:
        rows = list(rows)
    except TypeError as error:
        raise PlanError([_issue("CATALOGO_INVALIDO", "No se recibieron filas del catalogo.")]) from error
    incidences, clean, seen_ids, seen_codes = [], [], {}, {}
    for position, row in enumerate(rows, 1):
        if not isinstance(row, Mapping):
            incidences.append(_issue("FILA_INVALIDA", "La fila no es un diccionario.", position))
            continue
        absent = [field for field in REQUIRED_FIELDS if field not in row]
        if absent:
            incidences.append(_issue("CAMPOS_AUSENTES", "Faltan campos: " + ", ".join(absent), position))
            continue
        current = dict(row)
        identifier = row["id_proyecto"]
        valid_id = type(identifier) is int and 1 <= identifier <= MAX_PROJECT_ID
        if not valid_id:
            incidences.append(_issue("ID_INVALIDO", "id_proyecto debe ser entero entre 1 y 99999999.", position, field="id_proyecto"))
        elif identifier in seen_ids:
            incidences.append(_issue("ID_DUPLICADO", "id_proyecto repetido: %d." % identifier, position, field="id_proyecto"))
        else:
            seen_ids[identifier] = position
        code = row["co_proyecto"]
        # nchar puede devolver espacios de relleno; no se aceptan otros cambios.
        code = code.rstrip(" ") if isinstance(code, str) else code
        valid_code = isinstance(code, str) and re.fullmatch(r"PRY-[0-9]{8}", code) is not None
        if not valid_code:
            incidences.append(_issue("CODIGO_INVALIDO", "co_proyecto debe tener formato PRY-00000001.", position, field="co_proyecto"))
        else:
            if code in seen_codes:
                incidences.append(_issue("CODIGO_DUPLICADO", "co_proyecto repetido: " + code + ".", position, field="co_proyecto"))
            seen_codes[code] = position
            if valid_id and int(code[4:]) != identifier:
                incidences.append(_issue("SECUENCIA_CONTRADICTORIA", "El sufijo de co_proyecto no coincide con id_proyecto.", position))
        current["co_proyecto"] = code
        for field in ("no_proyecto", "de_proyecto", "es_registro"):
            if row[field] is not None and not isinstance(row[field], str):
                incidences.append(_issue("TEXTO_INVALIDO", field + " debe ser texto o NULL.", position, field=field))
        clean.append(current)
    if incidences:
        raise PlanError(incidences)
    return clean


def plan_projects(rows):
    """Valida todo el catalogo y propone solamente las dos altas autorizadas.

    Incluye filas inactivas al buscar coincidencias y calcular el maximo.
    Reconoce solo aliases exactos tras normalizacion. Un candidato por texto
    que no sea alias conocido, dos filas para el mismo proyecto o identidades
    contradictorias bloquean el plan completo. Los huecos no se reutilizan.
    """
    catalog = _validated_rows(rows)
    aliases = {project["proyecto"]: {normalize_name(value) for value in project["aliases"]}
               for project in PROJECTS}
    matches = {project["proyecto"]: [] for project in PROJECTS}
    incidences = []
    for position, row in enumerate(catalog, 1):
        names = {field: normalize_name(row[field]) for field in ("no_proyecto", "de_proyecto")}
        targets = set()
        for project in PROJECTS:
            key = project["proyecto"]
            marker = key.casefold()
            exact_fields = [field for field, name in names.items() if name in aliases[key]]
            candidates = [field for field, name in names.items() if marker in name and name not in aliases[key]]
            for field in candidates:
                incidences.append(_issue("COINCIDENCIA_AMBIGUA", "Candidato no reconocido para " + key + ": " + row[field], position, key, field))
            if exact_fields:
                targets.add(key)
                matches[key].append(row)
                # Una etiqueta exacta con otra identidad no vacia debe revisarse,
                # no se interpreta silenciosamente como la misma obra.
                if any(name and name not in aliases[key] for name in names.values()):
                    incidences.append(_issue("IDENTIDAD_CONTRADICTORIA", "Nombre y descripcion no identifican inequivocamente " + key + ".", position, key))
        if len(targets) > 1:
            incidences.append(_issue("PROYECTOS_CRUZADOS", "La misma fila identifica JAENNORTE y POROMA.", position))
    for key, found in matches.items():
        if len(found) > 1:
            incidences.append(_issue("PROYECTO_DUPLICADO", "Varias filas identifican " + key + ".", project=key))
    maximum = max((row["id_proyecto"] for row in catalog), default=0)
    missing_count = sum(not found for found in matches.values())
    if maximum + missing_count > MAX_PROJECT_ID:
        incidences.append(_issue("SECUENCIA_AGOTADA", "No hay codigos de ocho digitos para todas las altas pendientes."))
    if incidences:
        raise PlanError(incidences)

    planned, existing, all_projects = [], [], []
    next_id = maximum
    for project in PROJECTS:
        key = project["proyecto"]
        item = {"proyecto": key, "archivo_kmz": project["archivo_kmz"]}
        if matches[key]:
            row = matches[key][0]
            item.update({field: row[field] for field in ("id_proyecto", "co_proyecto", "no_proyecto", "de_proyecto")})
            item.update({
                "accion": "REUTILIZAR",
                "inactivo": (row["es_registro"] or "").strip() != "1"
                    or row.get("fe_eliminacion") is not None
                    or bool(row.get("tiene_fecha_eliminacion", False)),
                "sin_modificar": True,
            })
            existing.append(item)
        else:
            next_id += 1
            values = dict(BUSINESS_DEFAULTS)
            values.update({"id_proyecto": next_id, "co_proyecto": "PRY-%08d" % next_id,
                           "no_proyecto": project["no_proyecto"], "de_proyecto": project["de_proyecto"]})
            item.update({"accion": "CREAR", "valores": values, "codigo_previsional": True})
            planned.append(item)
        all_projects.append(item)
    return {
        "version": 1,
        "estado": "PLAN_ALTAS_PREVISTO" if planned else "PROYECTOS_YA_EXISTEN",
        "solo_plan": True,
        "codigos_reservados": False,
        "catalogo_filas": len(catalog),
        "max_id_proyecto": maximum,
        "altas": planned,
        "existentes": existing,
        "proyectos": all_projects,
    }
