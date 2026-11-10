"""Lectura, propuesta, validacion y balance del mapeo EFT editable."""
from __future__ import annotations

import csv
import shutil
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import eft_modelo as modelo
import eft_reglas as reglas
import eft_supuestos

COLUMNAS = (
    "grupo_id", "archivo_origen", "ruta_kml", "geometria", "entidades", "objetos", "incluir",
    "clase_destino", "clase_fisica", "proyecto", "componente", "alternativa", "disciplina",
    "condicion", "fuente", "tema", "capa_origen", "familia", "confianza", "estado", "motivo",
    "supuestos", "preguntas", "comentario_revision",
)


def _codigos(valores):
    return ",".join(dict.fromkeys(valores))


def fila_propuesta(grupo):
    decision = reglas.clasificar(grupo.archivo, grupo.ruta, grupo.geometria)
    clase_fisica = ""
    if decision.destino:
        valido, _ = modelo.validar_destino(decision.destino, grupo.geometria)
        if valido:
            clase_fisica = modelo.nombre_fisico(decision.destino, grupo.geometria)
    return {
        "grupo_id": grupo.grupo_id,
        "archivo_origen": grupo.archivo,
        "ruta_kml": reglas.ruta_texto(grupo.ruta),
        "geometria": grupo.geometria,
        "entidades": grupo.entidades,
        "objetos": grupo.objetos,
        "incluir": decision.incluir,
        "clase_destino": decision.destino,
        "clase_fisica": clase_fisica,
        "proyecto": decision.proyecto,
        "componente": decision.componente,
        "alternativa": decision.alternativa,
        "disciplina": decision.disciplina,
        "condicion": decision.condicion,
        "fuente": decision.fuente,
        "tema": decision.tema,
        "capa_origen": decision.capa_origen,
        "familia": decision.familia,
        "confianza": decision.confianza,
        "estado": decision.estado,
        "motivo": decision.motivo,
        "supuestos": _codigos(decision.supuestos),
        "preguntas": _codigos(decision.preguntas),
        "comentario_revision": "",
    }


def leer(path):
    path = Path(path)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as archivo:
        lector = csv.DictReader(archivo, delimiter=";")
        faltantes = set(COLUMNAS) - set(lector.fieldnames or ())
        if faltantes:
            raise ValueError(f"El mapeo {path} no tiene las columnas requeridas: {', '.join(sorted(faltantes))}.")
        filas = list(lector)
    vistos = set()
    for fila in filas:
        grupo_id = (fila.get("grupo_id") or "").strip()
        if not grupo_id:
            raise ValueError(f"El mapeo {path} contiene una fila sin grupo_id.")
        if grupo_id in vistos:
            raise ValueError(f"El mapeo {path} contiene grupo_id duplicado: {grupo_id}.")
        vistos.add(grupo_id)
    return filas


def escribir(path, filas):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";", extrasaction="ignore")
        escritor.writeheader()
        for fila in filas:
            escritor.writerow({columna: fila.get(columna, "") for columna in COLUMNAS})
    return path


def proponer(grupos, path, regenerar=False):
    """Añadir grupos nuevos y refrescar contadores, preservando las decisiones editadas."""
    path = Path(path)
    anteriores = leer(path) if path.exists() and not regenerar else []
    if regenerar and path.exists():
        sello = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        copia = path.with_name(f"{path.stem}.bak_{sello}{path.suffix}")
        shutil.copy2(path, copia)
        anteriores = leer(copia)
    por_id = {fila["grupo_id"]: fila for fila in anteriores} if not regenerar else {}
    comentarios = {fila["grupo_id"]: fila.get("comentario_revision", "") for fila in anteriores}
    encontrados = set()
    resultado = []
    for grupo in grupos:
        base = fila_propuesta(grupo)
        encontrados.add(grupo.grupo_id)
        if grupo.grupo_id in por_id:
            existente = dict(por_id[grupo.grupo_id])
            existente.update({
                "archivo_origen": grupo.archivo,
                "ruta_kml": reglas.ruta_texto(grupo.ruta),
                "geometria": grupo.geometria,
                "entidades": grupo.entidades,
                "objetos": grupo.objetos,
            })
            resultado.append(existente)
        else:
            base["comentario_revision"] = comentarios.get(grupo.grupo_id, "")
            resultado.append(base)
    if not regenerar:
        resultado.extend(f for f in anteriores if f["grupo_id"] not in encontrados)
    escribir(path, resultado)
    return resultado


def estado_efectivo(fila):
    incluir = (fila.get("incluir") or "").strip().upper()
    estado = (fila.get("estado") or "").strip().upper()
    destino = (fila.get("clase_destino") or "").strip()
    geometria = (fila.get("geometria") or "").strip()
    if incluir == "SI":
        valido, motivo = modelo.validar_destino(destino, geometria)
        if not valido:
            return reglas.PENDIENTE, motivo
        codigo = (fila.get("proyecto") or "").strip()
        if not codigo or codigo.startswith("PROV-"):
            return reglas.PENDIENTE, "Falta un codigo de proyecto definitivo compatible con mline_tc_proyecto."
        return reglas.CARGAR, ""
    if incluir == "NO" and estado in ("EXCLUIDO", "CARGAR"):
        return reglas.EXCLUIDO, ""
    return reglas.PENDIENTE, fila.get("motivo") or "El grupo requiere decision de mapeo."


def validar(filas, codigos_proyecto=None):
    """Validar destinos y dominios; retorna errores accionables sin silenciar fallas."""
    errores = []
    proyectos = set(codigos_proyecto or ())
    for fila in filas:
        grupo = fila.get("grupo_id") or "(sin grupo_id)"
        estado, motivo = estado_efectivo(fila)
        if estado == reglas.PENDIENTE and (fila.get("incluir") or "").strip().upper() == "SI":
            errores.append(f"{grupo}: {motivo}")
            continue
        if estado != reglas.CARGAR:
            continue
        for campo, dominio in (("disciplina", modelo.DISCIPLINAS), ("condicion", modelo.CONDICIONES),
                               ("fuente", modelo.FUENTES), ("tema", modelo.TEMAS)):
            valor = (fila.get(campo) or "").strip()
            if valor and valor not in dominio:
                errores.append(f"{grupo}: {campo}='{valor}' no pertenece al dominio EFT.")
        if proyectos and fila.get("proyecto") not in proyectos:
            errores.append(f"{grupo}: el proyecto {fila.get('proyecto')} no existe en {modelo.TABLA_PROYECTO}.")
    return errores


def specs(filas):
    pares = set()
    for fila in filas:
        estado, _ = estado_efectivo(fila)
        if estado == reglas.CARGAR:
            pares.add((fila["clase_destino"], fila["geometria"]))
    errores = validar(filas)
    if errores:
        raise ValueError("El mapeo tiene errores y no puede cargarse:\n" + "\n".join(errores[:30]))
    return modelo.specs_de_destinos(sorted(pares))


def balance(filas):
    """Totales de objetos y entidades por estado efectivo y por KMZ/clase."""
    total = Counter()
    por_kmz = defaultdict(Counter)
    por_clase = defaultdict(Counter)
    for fila in filas:
        estado, motivo = estado_efectivo(fila)
        if motivo and (fila.get("incluir") or "").strip().upper() == "SI":
            estado = reglas.PENDIENTE
        objetos = int(fila.get("objetos") or 0)
        entidades = int(fila.get("entidades") or 0)
        for medida, cantidad in (("objetos", objetos), ("entidades", entidades)):
            total[(medida, estado)] += cantidad
            por_kmz[fila.get("archivo_origen") or "(sin archivo)"][(medida, estado)] += cantidad
            por_clase[fila.get("clase_fisica") or "(pendiente)"][(medida, estado)] += cantidad
    return {"total": total, "por_kmz": por_kmz, "por_clase": por_clase}


def escribir_balance(path, filas):
    """Escribir un CSV legible por Excel y un resumen Markdown con conteos verificables."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    datos = balance(filas)
    columnas = ("grupo_id", "archivo_origen", "ruta_kml", "geometria", "clase_fisica", "objetos",
                "entidades", "estado_efectivo", "motivo")
    with path.open("w", encoding="utf-8-sig", newline="") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=columnas, delimiter=";")
        escritor.writeheader()
        for fila in filas:
            estado, motivo = estado_efectivo(fila)
            if motivo and (fila.get("incluir") or "").strip().upper() == "SI":
                estado = reglas.PENDIENTE
            escritor.writerow({
                "grupo_id": fila.get("grupo_id"), "archivo_origen": fila.get("archivo_origen"),
                "ruta_kml": fila.get("ruta_kml"), "geometria": fila.get("geometria"),
                "clase_fisica": fila.get("clase_fisica"), "objetos": fila.get("objetos"),
                "entidades": fila.get("entidades"), "estado_efectivo": estado,
                "motivo": motivo or fila.get("motivo", ""),
            })
    md_path = path.with_suffix(".md")
    with md_path.open("w", encoding="utf-8", newline="\n") as archivo:
        archivo.write("# Balance de mapeo EFT\n\n")
        archivo.write("Los conteos de objetos provienen de Placemark/Overlay originales; las entidades son partes vectoriales.\n\n")
        archivo.write("| Medida | Cargar | Excluido | Pendiente | Total |\n|---|---:|---:|---:|---:|\n")
        for medida in ("objetos", "entidades"):
            valores = [datos["total"][(medida, estado)] for estado in
                       (reglas.CARGAR, reglas.EXCLUIDO, reglas.PENDIENTE)]
            archivo.write(f"| {medida} | {valores[0]} | {valores[1]} | {valores[2]} | {sum(valores)} |\n")
    eft_supuestos.escribir_registro(filas, path.parent)
    return path, md_path
