"""Cobertura v1.13: propuestas auditables, sin ArcPy ni modificaciones del destino.

generar_plan(base) lee y verifica el paquete. La API pura preparar_cobertura
recibe objetos ya leidos. Ninguna ruta se considera cargable por este modulo.
Los identificadores hash son referencias del informe, nunca codigos de negocio.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path


VERSION = "1.13"
RULES_FILE = "reglas_cobertura_1_13.json"
PROFILE_FILE = "PERFIL_COMPLETO_KMZ_1_9.json"
SECTION_RE = re.compile(
    r"^Section #(?P<seccion>\d+),\s*(?P<tension>[+-]?\d+(?:[.,]\d+)?)\s*kV,\s*"
    r"'(?P<conductor>.*?)',\s*from Str\.\s*#(?P<origen>.+?)\s+Set\s+"
    r"(?P<set_origen>\d+)\s+'(?P<descriptor_origen>.*?)'\s+to Str\.\s*#"
    r"(?P<destino>.+?)\s+Set\s+(?P<set_destino>\d+)\s+'(?P<descriptor_destino>.*?)',"
    r"\s*Section at\s+(?P<condicion>.+)$", re.IGNORECASE,
)
STRUCTURE_RE = re.compile(r"^Structure\s+'(?P<estructura>.+)'$", re.IGNORECASE)
CIRCUIT_RE = re.compile(r"\b(?:CTO|CIRCUITO)\s*(\d+)\b", re.IGNORECASE)


def _norm(value):
    return "".join(c for c in unicodedata.normalize("NFKD", str(value).lower())
                   if not unicodedata.combining(c)).strip()


def _basename(value):
    return str(value).replace("\\", "/").rsplit("/", 1)[-1]


def _hash_obj(value):
    data = json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _key(row):
    return (_basename(row["archivo"]), row["ruta"], row["geometria"])


def _integer(value, label):
    if isinstance(value, bool) or not re.fullmatch(r"\d+", str(value)):
        raise ValueError("Conteo no entero no negativo: " + label)
    return int(value)


def _summary(rows):
    return {"rutas": len(rows), "elementos": sum(r["elementos"] for r in rows)}


def _group(rows, columns):
    groups = {}
    for row in rows:
        key = tuple(row.get(c, "") for c in columns)
        out = groups.setdefault(key, dict(zip(columns, key), rutas=0, elementos=0,
                                         filas_capas=[]))
        out["rutas"] += 1
        out["elementos"] += row["elementos"]
        out["filas_capas"].append(row["fila_capas"])
    return sorted(groups.values(), key=lambda g: (-g["elementos"], str(g)))


def extraer_conectividad(nombre):
    """Parsea el texto exacto de una seccion; no crea ni cuenta vanos finales."""
    match = SECTION_RE.fullmatch(nombre)
    if not match:
        return {"estado": "NOMBRE_NO_INTERPRETADO", "nombre_original": nombre,
                "numero_vanos_final": None}
    values = match.groupdict()
    circuits_origin = sorted(set(CIRCUIT_RE.findall(values["descriptor_origen"])))
    circuits_end = sorted(set(CIRCUIT_RE.findall(values["descriptor_destino"])))
    circuit = (circuits_origin[0] if len(circuits_origin) == 1
               and circuits_origin == circuits_end else None)
    return {
        "estado": "CONECTIVIDAD_EXTRAIDA_PENDIENTE_GEOMETRIA",
        "nombre_original": nombre, "seccion_pls": values["seccion"],
        "estructura_origen": values["origen"],
        "estructura_destino": values["destino"],
        "tension_kv": float(values["tension"].replace(",", ".")),
        "conductor": values["conductor"], "circuito": circuit,
        "circuitos_descriptor_origen": circuits_origin,
        "circuitos_descriptor_destino": circuits_end,
        "set_origen": values["set_origen"], "set_destino": values["set_destino"],
        "descriptor_origen": values["descriptor_origen"],
        "descriptor_destino": values["descriptor_destino"],
        "condicion_original": values["condicion"],
        "numero_vanos_final": None,
        "pendientes": ["Cotejar extremos con estructuras y geometria de cada elemento",
                       "Una seccion puede contener varios vanos o fases; no contar 1:1"]
        + ([] if circuit is not None else ["Circuito no explicito o diferente entre extremos; Set no equivale a circuito"]),
    }


def _family(row):
    leaf = row["ruta"].split(" / ")[-1]
    path, description = _norm(row["ruta"]), _norm(row["descripcion"])
    if leaf == "Structure locations":
        return "PLS_ESTRUCTURAS_PUNTO"
    if leaf.startswith("Section #"):
        return "PLS_SECCION"
    if STRUCTURE_RE.fullmatch(leaf):
        return "PLS_GRAFICO_ESTRUCTURA"
    if leaf in ("Line Features", "Point Features", "Area Features"):
        return "CAD_TEMA_NO_IDENTIFICADO"
    if "pls-cadd" in description or "pls-cadd" in path or "plscadd" in path:
        return "PLS_OTROS"
    if any(x in description for x in ("textos / anotaciones", "created with sketchup")) \
            or row["geometria"] == "Modelo3D":
        return "CAD_TEXTO_MODELO"
    if "cad exportad" in description or "entidades cad" in description:
        return "CAD_TEMA_NO_IDENTIFICADO"
    return "TEMA_VECTORIAL"


def _field_evidence(csv_fields, profile_fields, names):
    """Exige campo en inventario y perfil con valores utiles; no solo etiqueta."""
    wanted = set(names)
    csv_matches = [f for f in csv_fields if _norm(f["campo_fuente"]) in wanted]
    profile_matches = [f for f in profile_fields
                       if _norm(f["campo_original"]) in wanted
                       and f.get("valores_utiles", 0) > 0]
    if not csv_matches or not profile_matches:
        return []
    return [{"campo_original": f["campo_original"], "canal": f.get("canal"),
             "ocurrencia": f.get("ocurrencia"), "registros": f.get("registros"),
             "valores_utiles": f.get("valores_utiles"),
             "max_utf16": f.get("max_utf16"),
             "muestras": f.get("ejemplos", [])[:5],
             "perfil_campo_sha256": _hash_obj(f),
             "filas_campos_csv_sha256": [_hash_obj(c) for c in csv_matches]}
            for f in profile_matches]


def _candidate(row, csv_fields, profile_fields, rules):
    rr, dest = rules["reutilizacion"], rules["destinos"]
    geometry, leaf = row["geometria"], row["ruta"].split(" / ")[-1]
    evidence = _field_evidence(csv_fields, profile_fields, [rr["vertices"]["campo_fuente"]])
    if geometry == rr["vertices"]["geometria"] and evidence:
        return dest["vertices"], "VERTICE_EXPLICITO", evidence
    if geometry == rr["estructuras"]["geometria"] and leaf == rr["estructuras"]["hoja_exacta"]:
        return dest["estructuras"], "STRUCTURE_LOCATIONS_PLS", []
    evidence = _field_evidence(csv_fields, profile_fields, rr["alternativas_lt"]["campos_fuente"])
    if geometry == rr["alternativas_lt"]["geometria"] and evidence \
            and _norm(row["descripcion"]) == rr["alternativas_lt"]["descripcion_normalizada"]:
        return dest["alternativas_lt"], "ALTERNATIVA_LT_EXPLICITA", evidence
    archaeology = rr["arqueologia_campo"]
    if geometry == archaeology["geometria"] and leaf == archaeology["hoja_exacta"] \
            and row["descripcion"] == archaeology["descripcion_exacta"] \
            and "arqueol" in _norm(row["ruta"]):
        fields = [f for f in profile_fields if f["campo_original"] == "description"
                  and archaeology["descripcion_exacta"] in f.get("ejemplos", [])]
        if fields:
            return dest["arqueologia_campo"], "ARQUEOLOGIA_PROSPECCION_EXPLICITA", [
                {"campo_original": "description", "muestras": f["ejemplos"][:5],
                 "perfil_campo_sha256": _hash_obj(f)} for f in fields]
    bof = rr["bofedales"]
    evidence = _field_evidence(csv_fields, profile_fields, [bof["campo_fuente"]])
    if geometry == bof["geometria"] and leaf == bof["hoja_exacta"] \
            and bof["dominio_fuente"] in row["descripcion"] and evidence \
            and any(bof["ejemplo_normalizado"] in {_norm(v) for v in e["muestras"]}
                    for e in evidence):
        return dest["bofedales"], "BOFEDAL_FUENTE_INAIGEM_EXPLICITA", (
            evidence + _field_evidence(csv_fields, profile_fields, ["fid"]))
    return "", "", []


def _proposal_fields(kind, routes, rules, model):
    """Propuestas nuevas derivadas del EFT y fuentes, sin DDL ni campos tecnicos."""
    fields = [
        {"nombre": "proyecto", "tipo_propuesto": "TEXT", "fundamento": "EFT 5.8.7 y 5.8.9; asociacion a catalogo existente", "estado": "COTEJAR_CLAVE_DESTINO"},
        {"nombre": "id_analisis", "tipo_propuesto": "TEXT", "fundamento": "EFT 5.8.7 y 5.8.9; carga inicial", "estado": "COTEJAR_MODELO"},
    ]
    if kind == "vanos":
        parsed = [r["conectividad_pls"] for r in routes
                  if r.get("conectividad_pls", {}).get("estado") == "CONECTIVIDAD_EXTRAIDA_PENDIENTE_GEOMETRIA"]
        for name in ["estructura_origen", "estructura_destino", "circuito", "tension_kv", "conductor"]:
            values = [p[name] for p in parsed if p.get(name) is not None]
            fields.append({"nombre": name, "tipo_propuesto": "DOUBLE" if name == "tension_kv" else "TEXT",
                           "fundamento": "EFT 5.8.9 parrafo 772 y descriptores Section de la fuente",
                           "muestras": list(dict.fromkeys(values))[:5],
                           "longitud_observada_max": max((len(str(x).encode("utf-16-le")) // 2 for x in values), default=0) if name != "tension_kv" else None,
                           "estado": "PROPUESTA_POR_REVISAR"})
        return {"nombre": rules["destinos"][kind], "dataset_propuesto": "Datos_Proyecto",
                "geometria_propuesta": "POLYLINE", "has_z": "POR_VERIFICAR",
                "estado": "PROPUESTA_ESQUEMA_PLS_NO_DDL", "campos": fields,
                "fuente": "EFT 771-773; nombres PLS conservados por ruta",
                "rutas_evidencia": [r["fila_capas"] for r in routes if r["familia"] == "PLS_SECCION"],
                "numero_vanos_final": None, "creada": False,
                "pendientes": ["Conectividad y geometria de vanos reales; no una entidad por carpeta",
                               "Validar identificadores, atributos, longitudes y Z",
                               "No copiar campos genericos del esquema antiguo Vanos"]}
    bof_routes = [r for r in routes if r["regla_propuesta"] == "BOFEDAL_FUENTE_INAIGEM_EXPLICITA"]
    source_fields = [f for r in bof_routes for f in r["evidencia"]["atributos_discriminantes"]]
    cover_fields = [f for f in source_fields if _norm(f["campo_original"]) == "desc_cober"]
    fid_routes = sum(any(_norm(f["campo_original"]) == "fid" for f in r["evidencia"]["atributos_discriminantes"])
                     for r in bof_routes)
    fields.extend([
        {"nombre": "id_origen", "tipo_propuesto": "TEXT", "fundamento": "EFT 767 pide id_origen en recortes", "fuente_candidata": "FID del KMZ" if fid_routes == len(bof_routes) else "POR_RESOLVER", "rutas_con_fid_util": fid_routes, "estado": "VALIDAR_IDENTIFICADOR_LOCAL_NO_ASUMIR_ID_OFICIAL"},
        {"nombre": "desc_cober", "tipo_propuesto": "TEXT", "fundamento": "Campo original desc_cober del KMZ", "muestras": list(dict.fromkeys(v for f in cover_fields for v in f["muestras"]))[:5], "longitud_observada_max": max((f["max_utf16"] or 0 for f in cover_fields), default=0), "estado": "PROPUESTA_POR_REVISAR"},
    ])
    return {"nombre": rules["destinos"][kind], "dataset_propuesto": "Datos_Proyecto",
            "geometria_propuesta": "POLYGON", "has_z": "POR_VERIFICAR",
            "estado": "PROPUESTA_ESQUEMA_RECORTE_NO_DDL", "campos": fields,
            "fuente": "INAIGEM identificado por URL y desc_cober; conservar recortes por proyecto/estacion",
            "rutas_evidencia": [r["fila_capas"] for r in routes if r["regla_propuesta"] == "BOFEDAL_FUENTE_INAIGEM_EXPLICITA"],
            "creada": False, "pendientes": ["Revisar esquema y geometria, compatibilidad y relacion a proyecto",
                                              "La capa maestra oficial es independiente y corresponde a Datos_Externos",
                                              "Validar FID como identificador de la exportacion, no como identificador oficial INAIGEM"]}


def preparar_cobertura(*, rutas, campos_por_ruta, perfil, modelo, referencias, reglas):
    """Construye plan sin I/O. Conteos/fuentes/geometria discrepantes impiden propuesta.

    referencias: {verificados: bool, archivos_sha256: {nombre: sha256}}.
    perfil admite el documento con clave perfil o el objeto perfil interior.
    """
    if not isinstance(referencias, dict) or not isinstance(reglas, dict):
        raise ValueError("Se requieren referencias y reglas explicitas")
    p = perfil.get("perfil", perfil)
    models = {c["nombre"]: c for c in modelo["clases"]}
    if len(models) != len(modelo["clases"]):
        raise ValueError("Nombres de clases repetidos en el modelo")
    observed, field_index, csv_index, source_index = {}, defaultdict(list), defaultdict(list), {}
    for source in p["fuentes"]:
        key = _basename(source["archivo"])
        if key in source_index:
            raise ValueError("Fuente ambigua por nombre de archivo: " + key)
        if not re.fullmatch(r"[0-9a-f]{64}", source.get("sha256", "")):
            raise ValueError("SHA256 de fuente ausente/invalido: " + key)
        source_index[key] = source
    for item in p["rutas"]:
        key = _key(item)
        if key in observed:
            raise ValueError("Ruta repetida en perfil: " + str(key))
        observed[key] = item
    for item in p["campos_fuente"]:
        field_index[_key(item)].append(item)
    for item in campos_por_ruta:
        csv_index[_key(item)].append(item)
    output, seen_ids, seen_keys = [], set(), set()
    for row in rutas:
        rid = _integer(row["fila_capas"], "fila_capas")
        key = _key(row)
        if rid in seen_ids or key in seen_keys:
            raise ValueError("Ruta/fila duplicada en inventario: " + str(rid))
        seen_ids.add(rid)
        seen_keys.add(key)
        elements = _integer(row["elementos"], "elementos fila " + str(rid))
        current = row.get("clase_propuesta", "")
        match = observed.get(key)
        source = source_index.get(key[0])
        incidents = []
        if not referencias.get("verificados"):
            incidents.append("REFERENCIAS_NO_VERIFICADAS")
        if not match or match.get("estado") != "COINCIDE" \
                or match.get("esperados") != elements or match.get("observados") != elements:
            incidents.append("CONTEO_O_RUTA_NO_VERIFICADOS_EN_PERFIL")
        if not source:
            incidents.append("FUENTE_SIN_HASH_EN_PERFIL")
        if match and match.get("clase", "") != current:
            incidents.append("DESTINO_DIFIERE_ENTRE_PERFIL_E_INVENTARIO")
        if row.get("clase_confirmada") or row.get("incluir"):
            incidents.append("DECISION_CSV_REQUIERE_CONCILIACION_EXPLICITA")
        expected_geom = reglas["geometrias"].get(row["geometria"])
        if current and (current not in models or models[current]["geometria"] != expected_geom
                        or models[current].get("dataset") != row.get("dataset_propuesto")):
            incidents.append("CLASE_ACTUAL_INEXISTENTE_O_GEOMETRIA_INCOMPATIBLE")
        family = _family(row)
        leaf = row["ruta"].split(" / ")[-1]
        state = "MAPEO_ACTUAL" if current else "REVISION"
        target, rule, field_evidence = "", "", []
        if not current and not incidents:
            target, rule, field_evidence = _candidate(row, csv_index[key], field_index[key], reglas)
            if target:
                new_bof = target == reglas["destinos"]["bofedales"] and target not in models
                if not new_bof and (target not in models or models[target]["geometria"] != expected_geom
                                    or models[target].get("dataset") != "Datos_Proyecto"):
                    incidents.append("CLASE_CANDIDATA_INEXISTENTE_O_GEOMETRIA_INCOMPATIBLE")
                    target, rule, field_evidence = "", "", []
                else:
                    state = "PROPUESTA_SUSTENTADA"
            elif family == "CAD_TEXTO_MODELO":
                state = "DESCARTE_POR_APROBAR"
            elif family.startswith("PLS_") or family == "CAD_TEMA_NO_IDENTIFICADO":
                state = "TRATAMIENTO_ESPECIAL"
        if incidents:
            state = "REVISION"
        route_out = {
            "fila_capas": rid, "archivo": row["archivo"], "ruta": row["ruta"],
            "geometria": row["geometria"], "descripcion": row["descripcion"],
            "elementos": elements, "clase_destino_actual": current,
            "clase_propuesta": target, "estado": state, "cargable": False,
            "familia": family, "regla_propuesta": rule,
            "dataset_actual": row.get("dataset_propuesto", ""),
            "dataset_propuesto": "Datos_Proyecto" if target else "",
            "motivo_pendiente_original": row.get("motivo", ""),
            "disciplina_propuesta": row.get("disciplina_propuesta", ""),
            "maestro_dataset_original": row.get("maestro_dataset", ""),
            "incidencias": incidents,
            "evidencia": {"fila_csv_sha256": _hash_obj(row),
                          "perfil_ruta_sha256": _hash_obj(match) if match else None,
                          "kmz_sha256_en_perfil": source["sha256"] if source else None,
                          "conteo_observado": match.get("observados") if match else None,
                          "atributos_discriminantes": field_evidence},
            "pendientes": ["PLAN_REVISABLE_NO_AUTORIZA_CARGA"],
            "disposicion_final": "PENDIENTE",
        }
        if current:
            route_out["pendientes"].append("VALIDAR_MAPEO_VALORES_GEOMETRIA_CLAVES_Y_AUDITORIA")
        if target:
            route_out["pendientes"].append("REVISAR_PROPUESTA_Y_MAPEO_COMPLETO_DE_ATRIBUTOS")
        if target == reglas["destinos"]["alternativas_lt"]:
            route_out["pendientes"].append("RESOLVER_ID_PROYECTO_ALTERNATIVA_SIN_INVENTAR_CODIGOS")
        if family.startswith("PLS_"):
            route_out["tratamiento_eft"] = "PLS_SEPARADO_ESTRUCTURAS_VANOS"
            route_out["pendientes"].append("PROCESAR_PLS_SEGUN_EFT_771_773")
        elif family.startswith("CAD_"):
            route_out["tratamiento_eft"] = "COPIAS_CAD_REVISION_EFT_774_776"
            route_out["pendientes"].append("IDENTIFICAR_COPIA_VALIDA_O_REVISAR_EXCLUSION_SIN_DESCARTE_AUTOMATICO")
        elif row.get("maestro_dataset") == "Datos_Internos":
            route_out["tratamiento_eft"] = "REVISAR_INTERNO_COMPLEMENTARIO_EFT_778"
            route_out["pendientes"].append("DIFERENCIAR_INSTANTANEA_KMZ_DE_CAPA_INTERNA_COMPLEMENTARIA_Y_PREVALENCIA")
        else:
            route_out["tratamiento_eft"] = "CLASIFICAR_CAPA_PROYECTO_O_RECORTE"
        if family == "PLS_SECCION":
            route_out["conectividad_pls"] = extraer_conectividad(leaf)
        elif family == "PLS_GRAFICO_ESTRUCTURA":
            route_out["estructura_pls"] = {"codigo_fuente": STRUCTURE_RE.fullmatch(leaf).group("estructura"),
                                            "nombre_original": leaf,
                                            "geometria_puntual_derivada": False}
            route_out["pendientes"].append("GRAFICO_LINEAL_NO_EQUIVALE_A_PUNTO_ESTRUCTURA_NO_CALCULAR_CENTROIDE")
        if state == "DESCARTE_POR_APROBAR":
            route_out["opciones_disposicion"] = ["REVISION_MANUAL", "EXCLUSION_DOCUMENTADA_POR_APROBAR"]
        output.append(route_out)
    extra = sorted(set(observed) - seen_keys)
    if extra:
        raise ValueError("El perfil contiene rutas no presentes en inventario: " + str(len(extra)))
    pending = [r for r in output if not r["clase_destino_actual"]]
    current = [r for r in output if r["clase_destino_actual"]]
    proposals = [r for r in output if r["estado"] == "PROPUESTA_SUSTENTADA"]
    groups = _group(pending, ["descripcion", "geometria"])
    pls_routes = [r for r in output if r["familia"].startswith("PLS_")]
    sections = [r for r in output if r["familia"] == "PLS_SECCION"]
    parsed = [r for r in sections if r["conectividad_pls"]["estado"] == "CONECTIVIDAD_EXTRAIDA_PENDIENTE_GEOMETRIA"]
    native_groups = defaultdict(list)
    for row in pls_routes:
        parent = row["ruta"].rsplit(" / ", 1)[0]
        if " / PLS-CADD Model" in parent:
            parent = parent.split(" / PLS-CADD Model", 1)[0]
        native_groups[(_basename(row["archivo"]), parent)].append(row)
    native = []
    for (file, path), group in sorted(native_groups.items()):
        samples = [r["conectividad_pls"] for r in group if "conectividad_pls" in r]
        native.append({"archivo": file, "ruta_grupo": path, **_summary(group),
                       "filas_capas": [r["fila_capas"] for r in group],
                       "muestras_descriptores": samples[:3], "numero_vanos_final": None,
                       "destinos_a_preparar": [reglas["destinos"]["estructuras"], reglas["destinos"]["vanos"]],
                       "estado": "PROCESAMIENTO_SEPARADO_PENDIENTE"})
    new_classes = []
    if sections and reglas["destinos"]["vanos"] not in models:
        new_classes.append(_proposal_fields("vanos", output, reglas, modelo))
    if any(r["regla_propuesta"] == "BOFEDAL_FUENTE_INAIGEM_EXPLICITA" for r in proposals) \
            and reglas["destinos"]["bofedales"] not in models:
        new_classes.append(_proposal_fields("bofedales", output, reglas, modelo))
    valid = not any(r["incidencias"] for r in output)
    return {
        "version": VERSION, "estado": "COBERTURA_PREPARADA_CON_PENDIENTES" if valid else "COBERTURA_CON_INCIDENCIAS",
        "modo": "SOLO_PLAN", "ingesta_autorizada": False, "cambios_en_sde": False,
        "cambios_en_modelo": False, "registros_insertados": 0,
        "validacion_geometria_ejecutada": False, "mapeo_completo_campos_aprobado": False,
        "referencias": referencias, "reglas_sha256_logico": _hash_obj(reglas),
        "fuentes_del_perfil": [{"archivo": x["archivo"], "sha256": x["sha256"]} for x in p["fuentes"]],
        "eft": reglas["eft"], "limitaciones": reglas["limitaciones"],
        "resumen": {"inventario": _summary(output), "mapeo_actual": _summary(current),
                    "sin_destino_original": _summary(pending), "grupos_pendientes": len(groups),
                    "propuestas_sustentadas": _summary(proposals),
                    "por_estado": _group(output, ["estado"]),
                    "por_clase_propuesta": _group(proposals, ["clase_propuesta"]),
                    "incidencias": sum(len(r["incidencias"]) for r in output),
                    "cargables": 0},
        "rutas": output, "grupos_revision": groups,
        "familias_pendientes": _group(pending, ["familia", "geometria"]),
        "top20_pendientes": sorted(pending, key=lambda r: (-r["elementos"], r["fila_capas"]))[:20],
        "procesamiento_pls": {"grupos": native, "secciones_rutas": len(sections),
                              "secciones_parseadas": len(parsed),
                              "secciones_no_interpretadas": [r["fila_capas"] for r in sections if r not in parsed],
                              "numero_vanos_final": None,
                              "regla": "EFT 771-773: procesar aparte; no 1 carpeta/Placemark = 1 vano"},
        "clases_propuestas": new_classes,
    }


def generar_plan(base, salida=None):
    """Lee el paquete, verifica hashes y retorna plan. salida crea un JSON NUEVO."""
    base = Path(base)
    rule_bytes = (base / RULES_FILE).read_bytes()
    rules = json.loads(rule_bytes.decode("utf-8-sig"))
    if rules.get("version") != VERSION or rules.get("modo") != "PLAN_REVISABLE_SIN_CARGA":
        raise ValueError("Version o modo no admitido en reglas de cobertura")
    contents, hashes = {}, {}
    required = {"esquema.json", "mapeo_capas_revision.csv", "campos_por_ruta.csv", PROFILE_FILE}
    if set(rules.get("archivos_sha256", {})) != required:
        raise ValueError("Lista de referencias incompleta o no prevista en reglas de cobertura")
    for name, expected in rules["archivos_sha256"].items():
        data = (base / name).read_bytes()
        actual = hashlib.sha256(data).hexdigest()
        if actual != expected:
            raise ValueError("Referencia alterada; no se prepara cobertura: " + name)
        contents[name], hashes[name] = data, actual
    profile = json.loads(contents[PROFILE_FILE].decode("utf-8-sig"))
    for name in ("esquema.json", "mapeo_capas_revision.csv", "campos_por_ruta.csv"):
        if profile.get("referencias_sha256", {}).get(name) != hashes[name]:
            raise ValueError("El perfil no corresponde a la referencia: " + name)
    model = json.loads(contents["esquema.json"].decode("utf-8-sig"))
    import io
    routes = list(csv.DictReader(io.StringIO(contents["mapeo_capas_revision.csv"].decode("utf-8-sig")), delimiter=";"))
    fields = list(csv.DictReader(io.StringIO(contents["campos_por_ruta.csv"].decode("utf-8-sig")), delimiter=";"))
    exp = rules["esperados"]
    if len(routes) != exp["rutas"] or sum(_integer(r["elementos"], "elementos") for r in routes) != exp["elementos"] \
            or len(profile["perfil"]["fuentes"]) != exp["fuentes"] or len(model["clases"]) != exp["clases_actuales"]:
        raise ValueError("Paquete incompleto o conteos distintos de la revision aprobada")
    if profile["perfil"].get("estado") != "LECTURA_COMPLETA":
        raise ValueError("Perfil sin lectura completa")
    hashes[RULES_FILE] = hashlib.sha256(rule_bytes).hexdigest()
    result = preparar_cobertura(rutas=routes, campos_por_ruta=fields, perfil=profile,
                               modelo=model, referencias={"verificados": True, "archivos_sha256": hashes}, reglas=rules)
    if salida is not None:
        with Path(salida).open("x", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    return result


preparar_cobertura_desde_paquete = generar_plan
