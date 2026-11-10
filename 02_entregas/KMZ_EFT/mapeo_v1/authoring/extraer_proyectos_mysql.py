"""Extraer referencia de proyectos/componentes sin ejecutar SQL ni filtrar historia.

Solo escribe proyectos_mysql.json (o --output). No abre conexiones, no importa
generadores y no asigna nuevos codigos. Los mapeos de KMZ son candidatos que
requieren revision; sus nombres no prueban correspondencia geometrica.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re


TABLES = {"mline_tc_proyecto", "mline_td_proyecto_componente"}
ESCAPES = {"0": "\0", "b": "\b", "n": "\n", "r": "\r", "t": "\t", "Z": "\x1a",
           "'": "'", '"': '"', "\\": "\\"}


def parse_values(text):
    """Lector de literales mysqldump; nunca evalua expresiones ni ejecuta SQL."""
    pos, result = 0, []

    def whitespace():
        nonlocal pos
        while pos < len(text) and text[pos].isspace():
            pos += 1

    while True:
        whitespace()
        if pos >= len(text):
            raise ValueError("Falta el punto y coma del INSERT.")
        if text[pos] == ";":
            pos += 1
            whitespace()
            if pos != len(text):
                raise ValueError("Texto inesperado despues del INSERT.")
            return result
        if text[pos] != "(":
            raise ValueError("Inicio de fila inesperado.")
        pos += 1
        row = []
        while True:
            whitespace()
            if pos >= len(text):
                raise ValueError("Fila incompleta.")
            if text[pos] == "'":
                pos += 1
                pieces = []
                while True:
                    if pos >= len(text):
                        raise ValueError("Cadena sin cierre.")
                    char = text[pos]
                    pos += 1
                    if char == "\\":
                        if pos >= len(text):
                            raise ValueError("Escape incompleto.")
                        escaped = text[pos]
                        pos += 1
                        pieces.append(ESCAPES.get(escaped, "\\" + escaped if escaped in ("%", "_") else escaped))
                    elif char == "'":
                        if text[pos:pos + 1] == "'":
                            pieces.append("'")
                            pos += 1
                        else:
                            break
                    else:
                        pieces.append(char)
                value = "".join(pieces)
            else:
                start = pos
                while pos < len(text) and text[pos] not in ",)":
                    pos += 1
                token = text[start:pos].strip()
                if token == "NULL":
                    value = None
                elif re.fullmatch(r"[-+]?\d+", token):
                    value = int(token)
                elif re.fullmatch(r"[-+]?\d+\.\d+", token):
                    value = token  # No introducir redondeo de decimales.
                else:
                    raise ValueError("El INSERT contiene un token no literal.")
            row.append(value)
            whitespace()
            if pos >= len(text):
                raise ValueError("Fila incompleta.")
            if text[pos] == ")":
                pos += 1
                break
            if text[pos] != ",":
                raise ValueError("Separador de columnas inesperado.")
            pos += 1
        result.append(row)
        whitespace()
        if pos < len(text) and text[pos] == ",":
            pos += 1
        elif pos >= len(text) or text[pos] != ";":
            raise ValueError("Separador de filas inesperado.")


def extract_tables(source):
    result = {name: [] for name in TABLES}
    column_names = {}
    with source.open(encoding="utf-8-sig") as stream:
        for line in stream:
            if not line.startswith("INSERT INTO `"):
                continue
            table_match = re.match(r"INSERT INTO `([^`]+)` ", line)
            if not table_match or table_match[1] not in TABLES:
                continue
            match = re.fullmatch(r"INSERT INTO `([^`]+)` (\(.*?\)) VALUES (.*)\s*", line)
            if not match:
                raise ValueError("Formato de INSERT no soportado para las tablas seleccionadas.")
            name = match[1]
            columns = re.findall(r"`([^`]+)`", match[2])
            if name in column_names and column_names[name] != columns:
                raise ValueError("Cambio de columnas entre lotes del mismo objeto.")
            column_names[name] = columns
            rows = parse_values(match[3])
            if any(len(row) != len(columns) for row in rows):
                raise ValueError("Numero de valores distinto del numero de columnas.")
            result[name].extend(dict(zip(columns, row)) for row in rows)
    if len(result["mline_tc_proyecto"]) != 40 or len(result["mline_td_proyecto_componente"]) != 120:
        raise ValueError("El respaldo no coincide con el snapshot esperado de 40 proyectos y 120 componentes.")
    return result, column_names


def candidates():
    def row(filename, codes, evidence):
        return {"archivo": filename, "codigos_candidatos": codes, "evidencia": evidence,
                "pendiente": True, "validado": False}

    return [
        row("Proyecto CHANCHAMAYO.kmz", ["PRY-00000005"],
            ["Proyecto Chanchamayo y componentes Campas/Nueva Campas/La Virgen/Chanchamayo.",
             "Las carpetas del KMZ incluyen LT 138 kV Campas - La Virgen y LT 60 KV Campas - Chanchamayo.",
             "PRY-00000021 tambien menciona Campas, pero su ruta es Yurinaki; compartir localidad no prueba identidad."]),
        row("Proyecto FELAM.kmz", ["PRY-00000010", "PRY-00000027"],
            ["Existen dos proyectos con Felam - Tierras Nuevas - Salitral y componentes comunes.",
             "El KMZ contiene rutas Felam/Tierras Nuevas/Salitral y Nueva Olmos. No se elige automaticamente un proyecto por estado o por ciudad."]),
        row("Proyecto HUARAZ.kmz", ["PRY-00000004"],
            ["Coinciden Huaraz, Huaylas y derivaciones; el KMZ tiene trazos 220/138/66 kV.",
             "PRY-00000002 contiene un componente de prueba relacionado con Huaylas; no se usa como equivalencia por localidad."]),
        row("Proyecto JAENNORTE.kmz", [],
            ["El KMZ menciona Caclic - Jaen Norte, Jaen y Bagua Chica; no se encontro correspondencia nominal en los 40 proyectos o 120 componentes.",
             "Se requiere decision de ENGIE; no se asigno ni genero un codigo nuevo."]),
        row("Proyecto MUYURINA.kmz", ["PRY-00000025"],
            ["Coinciden Muyurina - Mollepata y componente 63; la carpeta del KMZ dice LT 220 KV MUYURINA_MOLLEPATA."]),
        row("Proyecto PALIAN.kmz", ["PRY-00000026"],
            ["Coinciden Pali\u00e1n, Huancayo Este, Pucara y sus circuitos.",
             "PRY-00000028 y PRY-00000029 son proyectos de prueba con componentes similares; no se eliminan del historico ni se eligen automaticamente.",
             "PRY-00000026 contiene varios componentes con nombres repetidos; el nombre no determina id_componente."]),
        row("Proyecto PARI\u00d1AS.kmz", ["PRY-00000009"],
            ["Coinciden Miguel Grau - Nueva Pari\u00f1as 500 kV y Nueva Pari\u00f1as - Pari\u00f1as 220 kV.",
             "Hay varios IDs de componente con nombres equivalentes en el mismo proyecto; falta corroborar geometria e identificadores."]),
        row("Proyecto POROMA.kmz", [],
            ["El KMZ menciona Ica - Poroma e Ica - Intermedia - Poroma; no se encontro correspondencia nominal en los 40 proyectos o 120 componentes.",
             "Otros componentes mencionan Ica, pero eso no acredita identidad. No se genero un codigo nuevo."]),
        row("Proyecto PUCALLPA.kmz", ["PRY-00000001", "PRY-00000022"],
            ["El candidato principal por descripcion es Aguaytia - Pucallpa (PRY-00000001); el KMZ incluye planillas LT Ag.Pu.",
             "PRY-00000022 es Shipibo - Manantay y tiene un seccionamiento Pucallpa; es una coincidencia secundaria que requiere revision, no validacion."]),
        row("G1 Enlace 500 kV Miguel Grau - Pari\u00f1as.kmz", ["PRY-00000009"],
            ["Coincidencia del nombre completo del resultado con el proyecto. Falta validar vinculos y geometria."]),
        row("G1 LT 220 kV Felam \u2013 Tierras Nuevas \u2013 Salitral (1).kmz", ["PRY-00000027", "PRY-00000010"],
            ["El titulo completo del resultado coincide con PRY-00000027; PRY-00000010 usa Enlaces en su nombre y comparte circuitos.",
             "Se conservan ambos candidatos para revision; no se decide por vigencia ni similitud parcial."]),
        row("G1 LT 220 kV Muyurina \u2013 Mollepata.kmz", ["PRY-00000025"],
            ["Coincidencia del nombre completo con el proyecto y su componente 63. No se considera validacion geométrica."]),
        row("G1 Nueva SE Pali\u00e1n 22060 kV y LT.kmz", ["PRY-00000026"],
            ["La carpeta del resultado conserva Nueva SE Pali\u00e1n 220/60 kV y LT, coincidente con el proyecto.",
             "No se usan los componentes semejantes de proyectos de prueba como aprobacion de este mapeo."]),
    ]


def build(source):
    checksum = hashlib.sha256()
    with source.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(chunk)
        stream.seek(max(0, source.stat().st_size - 32768))
        tail = stream.read().decode("utf-8", errors="replace")
    footer = re.search(r"-- Dump completed on ([^\r\n]+)", tail)
    if not footer:
        raise ValueError("El respaldo no tiene marcador de exportacion completada.")
    tables, columns = extract_tables(source)
    projects = [{"id": row["id_proyecto"], "co": row["co_proyecto"], "no": row["no_proyecto"],
                 "de": row["de_proyecto"], "es_registro": row.get("es_registro")}
                for row in tables["mline_tc_proyecto"]]
    description = next((field for field in ("de_componente", "de_proyecto_componente", "descripcion")
                        if field in columns["mline_td_proyecto_componente"]), None)
    components = []
    for row in tables["mline_td_proyecto_componente"]:
        item = {"id": row["id_proyecto_componente"], "id_proyecto": row["id_proyecto"],
                "no": row["no_componente"], "es_registro": row.get("es_registro"),
                "zona_geografica": row.get("no_zona_geografica"), "departamento": row.get("no_departamento")}
        if description:
            item["de"] = row[description]
        components.append(item)
    if len({row["id"] for row in projects}) != 40 or len({row["id"] for row in components}) != 120:
        raise ValueError("El snapshot contiene identificadores repetidos.")
    project_ids = {row["id"] for row in projects}
    if any(row["id_proyecto"] not in project_ids for row in components):
        raise ValueError("Un componente referencia un proyecto inexistente.")
    proposals = candidates()
    codes = {row["co"] for row in projects}
    if len(proposals) != 13 or any(code not in codes for row in proposals for code in row["codigos_candidatos"]):
        raise ValueError("La propuesta contiene codigos ausentes en el snapshot.")
    state_count = lambda rows: dict(Counter(str(row["es_registro"]) if row["es_registro"] is not None else "<NULL>" for row in rows))
    return {
        "fuente_mysql": {"archivo": source.name, "sha256": checksum.hexdigest(),
                         "schema": "SCH_EEP_INONE_MAPLINE", "dump_completed_raw": footer[1]},
        "alcance": {"proyectos": 40, "componentes": 120, "projectCandidates": 13,
                    "filtrado_por_estado": False, "nuevos_identificadores_generados": 0,
                    "correspondencias_validadas": 0, "ejecucion_sql": False},
        "campos_fuente": {
            "proyectos": {"id": "id_proyecto", "co": "co_proyecto", "no": "no_proyecto", "de": "de_proyecto", "es_registro": "es_registro"},
            "componentes": {"id": "id_proyecto_componente", "id_proyecto": "id_proyecto", "no": "no_componente",
                            "de": description, "es_registro": "es_registro", "zona_geografica": "no_zona_geografica", "departamento": "no_departamento"}},
        "observaciones": ["Se conservan todos los estados de registro y componentes con nombres repetidos.",
                          "Los candidatos se basan en nombres completos y carpetas inventariadas; no son aprobaciones ni demuestran correspondencia de geometria.",
                          "Un codigo de proyecto candidato no valida el identificador de componente.",
                          "El origen no contiene un campo de descripcion de componente." if description is None else "La descripcion del componente se conserva del campo indicado en campos_fuente."],
        "estados_registro_fuente": {"proyectos": state_count(projects), "componentes": state_count(components)},
        "proyectos": projects, "componentes": components, "projectCandidates": proposals,
    }


def main():
    here = Path(__file__).resolve()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=here.parents[4] / "01_fuentes" / "Mapline_20261030.sql")
    parser.add_argument("--output", type=Path, default=here.with_name("proyectos_mysql.json"))
    args = parser.parse_args()
    result = build(args.source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Extraidos 40 proyectos y 120 componentes, con 13 propuestas pendientes; sin ejecutar SQL ni filtrar historia.")


if __name__ == "__main__":
    main()
