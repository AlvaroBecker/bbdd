"""Flujo EFT 5.8: propuesta editable, preparacion local y operaciones SDE."""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import json
import logging
import os
import shutil
import sqlite3
import tempfile
import time
from pathlib import Path

import eft_atributos as atributos
import eft_mapeo as mapeo
import eft_modelo as modelo
import eft_reglas as reglas

LOGGER = logging.getLogger("mapline_eft")
VERSION = "1.0"
MODOS = ("PROPONER", "PREPARAR_LOCAL", "ESTRUCTURA_SDE", "CARGAR_SDE", "VERSIONAR_SDE", "RETIRAR_KMZ")


def _log(mensaje):
    LOGGER.info(mensaje)


def _leer_json(path):
    with Path(path).open("r", encoding="utf-8-sig") as archivo:
        return json.load(archivo)


def _guardar_json(path, dato, intentos=5):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporal = path.with_name(path.name + f".{os.getpid()}.tmp")
    temporal.write_text(json.dumps(dato, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    error = None
    for intento in range(intentos):
        try:
            os.replace(str(temporal), str(path))
            return
        except PermissionError as exc:
            error = exc
            time.sleep(0.25 * (intento + 1))
    try:
        temporal.unlink()
    except FileNotFoundError:
        pass
    raise OSError(f"No se pudo reemplazar {path} despues de {intentos} intentos: {error}") from error


@contextlib.contextmanager
def _candado(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise RuntimeError(f"Hay otra ejecucion EFT activa o quedo un candado en {path}. Verifique antes de quitarlo.") from exc
    try:
        os.write(descriptor, f"pid={os.getpid()} utc={dt.datetime.now(dt.timezone.utc).isoformat()}".encode("ascii"))
        os.close(descriptor)
        yield
    finally:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def _fuentes(trabajo):
    info_path = Path(trabajo) / "informe.json"
    if not info_path.is_file():
        raise FileNotFoundError(f"No existe {info_path}; indique la carpeta de trabajo producida por la toolbox de transferencia.")
    info = _leer_json(info_path)
    ultimas = {}
    for fuente in info.get("sources") or []:
        sha = (fuente.get("sha256") or "").lower()
        if sha:
            ultimas[sha] = fuente
    if not ultimas:
        raise ValueError(f"{info_path} no contiene KMZ preparados.")
    return info, ultimas


def _seleccionar(fuentes, sha=None, kmz=None):
    sha = {str(valor).strip().lower() for valor in (sha or []) if str(valor).strip()}
    kmz = {Path(str(valor)).name.casefold() for valor in (kmz or []) if str(valor).strip()}
    resultado = []
    for codigo, fuente in fuentes.items():
        nombre = Path(fuente.get("file") or "").name
        if not sha and not kmz or codigo in sha or nombre.casefold() in kmz:
            resultado.append((codigo, fuente))
    no_encontrados = sha - {codigo for codigo, _ in resultado}
    no_encontrados |= {nombre for nombre in kmz
                       if nombre not in {Path(f.get("file") or "").name.casefold() for _, f in resultado}}
    if no_encontrados:
        raise ValueError("No se encontraron fuentes preparadas para: " + ", ".join(sorted(no_encontrados)))
    return sorted(resultado, key=lambda par: Path(par[1].get("file") or "").name.casefold())


def _ruta_local_fc(local, sha, trabajo, arcpy):
    local = str(local or "")
    if local and arcpy.Exists(local):
        return local
    raiz = Path(trabajo) / "intentos"
    normalizado = local.replace("/", "\\")
    indice = normalizado.casefold().find("\\intentos\\")
    if indice >= 0:
        resto = normalizado[indice + len("\\intentos\\"):]
        candidato = raiz.joinpath(*resto.split("\\"))
        if arcpy.Exists(str(candidato)):
            return str(candidato)
    sha12 = sha[:12]
    coincidencias = list(raiz.glob(f"*/{sha12}/preparado_{sha12}.gdb"))
    if coincidencias:
        candidato = max(coincidencias, key=lambda p: p.stat().st_mtime)
        # La clase suele ser la ruta despues de la geodatabase.
        nombre_clase = Path(local.replace("\\", "/")).name
        ruta_clase = str(candidato / nombre_clase)
        if arcpy.Exists(ruta_clase):
            return ruta_clase
    raise FileNotFoundError(f"No se encuentra la clase local preparada para {sha12}: {local}")


def _base_mapeo(trabajo):
    return Path(trabajo) / "eft"


def _seleccionar_mapeo(trabajo, path=None):
    elegido = Path(path) if path else _base_mapeo(trabajo) / "mapeo_eft.csv"
    filas = mapeo.leer(elegido)
    if not filas:
        raise ValueError(f"No existe un mapeo EFT con filas en {elegido}; ejecute PROPONER primero.")
    return elegido, filas


def _filas_sha(filas, fuentes):
    por_nombre = {Path(src.get("file") or "").name.casefold(): sha for sha, src in fuentes.items()}
    resultado = {}
    for fila in filas:
        sha = por_nombre.get(Path(fila.get("archivo_origen") or "").name.casefold())
        if sha:
            resultado.setdefault(sha, []).append(fila)
    return resultado


def _proponer(trabajo, seleccion, mapping_path=None, regenerar=False):
    info_path = Path(trabajo) / "trazabilidad.sqlite"
    if not info_path.is_file():
        raise FileNotFoundError(f"No existe la trazabilidad de origen: {info_path}")
    sha_archivo = {sha: Path(fuente.get("file") or "").name for sha, fuente in seleccion}
    grupos = reglas.leer_grupos(info_path, sha_archivo)
    destino = Path(mapping_path) if mapping_path else _base_mapeo(trabajo) / "mapeo_eft.csv"
    filas = mapeo.proponer(grupos, destino, regenerar=regenerar)
    balance_path = destino.with_name("balance_eft.csv")
    mapeo.escribir_balance(balance_path, filas)
    _log(f"PROPUESTA_EFT: {len(grupos)} grupos, {sum(g.objetos for g in grupos)} objetos; mapeo: {destino}")
    return {"estado": "PROPUESTA_EFT", "grupos": len(grupos), "objetos": sum(g.objetos for g in grupos),
            "mapeo": str(destino), "balance": str(balance_path)}


def _lookup_temporal(db_origen, ruta_lookup, sha, archivo, map_por_grupo):
    """Construir un indice en disco PM_ID -> grupo/orden, sin retener todos los payloads en RAM."""
    if os.path.exists(ruta_lookup):
        os.remove(ruta_lookup)
    salida = sqlite3.connect(ruta_lookup)
    salida.execute("CREATE TABLE lookup (id TEXT PRIMARY KEY, grupo_id TEXT, prioridad INTEGER)")
    entrada = sqlite3.connect(Path(db_origen).resolve().as_uri() + "?mode=ro", uri=True)
    consulta = (
        "SELECT o.id, json_extract(o.payload,'$.containers'), o.kind, s.class_name "
        "FROM originals o LEFT JOIN outputs s ON s.id=o.id WHERE o.sha=?")
    insertados = 0
    try:
        with salida:
            for pm_id, contenedores, kind, clase in entrada.execute(consulta, (sha,)):
                ruta = reglas._ruta_de(contenedores)
                geometria = reglas._geometria_de(kind, clase)
                gid = reglas.grupo_id(archivo, ruta, geometria)
                fila = map_por_grupo.get(gid)
                prioridad = reglas.prioridad_de_copia(ruta) if fila else 0
                salida.execute("INSERT OR REPLACE INTO lookup VALUES (?, ?, ?)", (pm_id, gid, prioridad))
                insertados += 1
        salida.execute("CREATE INDEX lookup_grupo ON lookup(grupo_id)")
    finally:
        entrada.close()
        salida.close()
    return insertados


def _valores_fila(geometria, spec, fila_mapeo, sha, grupo_id, nombre_original, ruta, payload, fecha, arcpy):
    nombre, usado_carpeta = atributos.nombre_de(nombre_original, ruta)
    atributos_kml = atributos.atributos_de(payload)
    sr_destino = arcpy.SpatialReference(modelo.WKID)
    sr = getattr(geometria, "spatialReference", None)
    if sr and getattr(sr, "factoryCode", None) not in (None, 0, modelo.WKID):
        geometria = geometria.projectAs(sr_destino)
    clase, _ = modelo.separar_destino(fila_mapeo.get("clase_destino"))
    valores = {
        "proyecto": fila_mapeo.get("proyecto") or None,
        "id_analisis": fila_mapeo.get("id_analisis") or "Carga inicial KMZ",
        "tema": fila_mapeo.get("tema") or None,
        "disciplina": fila_mapeo.get("disciplina") or None,
        "componente": fila_mapeo.get("componente") or None,
        "alternativa": fila_mapeo.get("alternativa") or None,
        "condicion": fila_mapeo.get("condicion") or None,
        "fuente": fila_mapeo.get("fuente") or None,
        "capa_origen": fila_mapeo.get("capa_origen") or None,
        "id_origen": atributos.id_origen(atributos_kml),
        "nombre": nombre,
        "archivo_origen": fila_mapeo.get("archivo_origen"),
        "ruta_kml": fila_mapeo.get("ruta_kml", "")[:modelo.LARGO_TEXTO_MAXIMO],
        "fecha_carga": fecha,
        "longitud_m": geometria.getLength("GEODESIC", "METERS") if spec.geometria == modelo.LINEA else None,
        "area_ha": geometria.getArea("GEODESIC", "HECTARES") if spec.geometria == modelo.POLIGONO else None,
        "codigo_estacion": atributos.codigo_estacion(ruta, nombre or "") if clase in ("AreaEstudioCampo", "Muestreo") else None,
        "kz_pm_id": payload.get("_eft_pm_id"),
        "kz_sha256": sha,
        "kz_grupo": grupo_id,
        "kz_supuestos": fila_mapeo.get("supuestos") or "",
        "kz_atributos": atributos.serializar(atributos_kml, modelo.LARGO_ATRIBUTOS),
    }
    if usado_carpeta:
        supuestos = [s for s in valores["kz_supuestos"].split(",") if s]
        if "S-23" not in supuestos:
            supuestos.append("S-23")
        valores["kz_supuestos"] = ",".join(supuestos)[:200]
    campos = modelo.campos_de(spec)
    return [valores.get(campo[0]) for campo in campos] + [geometria]


def _hash_duplicado(spec, valores):
    wkb = valores[-1].WKB
    campos = modelo.nombres_campos(spec)
    por_nombre = {nombre: valores[i] for i, nombre in enumerate(campos)}
    llaves = tuple(str(por_nombre.get(nombre) or "") for nombre in
                   ("nombre", "proyecto", "componente", "alternativa", "disciplina", "condicion", "kz_atributos"))
    h = hashlib.blake2b(digest_size=20)
    h.update(spec.fisico.encode("utf-8"))
    h.update(wkb)
    h.update(json.dumps(llaves, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    return h.hexdigest()


def _crear_stage(arcpy, base, specs, log):
    ruta = Path(tempfile.mkdtemp(prefix="eft_stage_", dir=str(base)))
    shutil.rmtree(ruta)
    gdb = str(ruta.with_suffix(".gdb"))
    arcpy.management.CreateFileGDB(str(Path(gdb).parent), Path(gdb).name)
    destinos = modelo.crear_estructura(gdb, specs, global_id=False, seguimiento=False, log=log)
    return gdb, destinos


def _conteo_sha(arcpy, fc, sha):
    campo = next((f.name for f in arcpy.ListFields(fc) if f.name.lower() == "kz_sha256"), None)
    if not campo:
        return 0
    where = f"{arcpy.AddFieldDelimiters(fc, campo)} = '{sha}'"
    return sum(1 for _ in arcpy.da.SearchCursor(fc, [campo], where_clause=where))


def _transformar_kmz(trabajo, sha, fuente, filas, db_path, stage_rutas, seen_db, informe, arcpy):
    archivo = Path(fuente.get("file") or "").name
    por_id = {fila["grupo_id"]: fila for fila in filas if
              Path(fila.get("archivo_origen") or "").name.casefold() == archivo.casefold()}
    candidatas = {}
    for gid, fila in por_id.items():
        estado, _ = mapeo.estado_efectivo(fila)
        if estado == reglas.CARGAR:
            candidatas[gid] = fila
    if not candidatas:
        _log(f"{archivo}: no hay grupos marcados para cargar; se conservan como pendientes/excluidos.")
        return 0, 0
    fd, lookup_path = tempfile.mkstemp(prefix="eft_lookup_", suffix=".sqlite", dir=str(Path(trabajo) / "eft"))
    os.close(fd)
    lookup = None
    try:
        n = _lookup_temporal(db_path, lookup_path, sha, archivo, por_id)
        _log(f"{archivo}: indice temporal para {n} originales.")
        lookup = sqlite3.connect(lookup_path)
        source_fcs = fuente.get("feature_classes") or []
        por_fc = []
        for clase_info in source_fcs:
            local = _ruta_local_fc(clase_info.get("local"), sha, trabajo, arcpy)
            if not arcpy.Exists(local):
                raise FileNotFoundError(f"No existe la feature class preparada: {local}")
            campos_fc = {f.name.lower(): f.name for f in arcpy.ListFields(local)}
            if "kz_pm_id" not in campos_fc:
                raise ValueError(f"La clase preparada no tiene KZ_PM_ID: {local}")
            nombre_campo = campos_fc.get("kz_nombre")
            campos_cursor = [campos_fc["kz_pm_id"]]
            campos_cursor.append(nombre_campo if nombre_campo else "SHAPE@")
            if nombre_campo:
                campos_cursor.append("SHAPE@")
            por_fc.append((local, campos_cursor, bool(nombre_campo)))
        specs_por_fisico = {spec.fisico.lower(): spec for spec in modelo.specs_de_destinos(
            {(fila["clase_destino"], fila["geometria"]) for fila in candidatas.values()})}
        cursor_state = {"target": None, "cursor": None}
        duplicados = 0
        cargadas = 0
        fecha = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
        batch_size = 100
        try:
            for prioridad in (0, 1):
                for local, cursor_fields, has_name in por_fc:
                    _log(f"{archivo}: transformando {Path(local).name}, prioridad {prioridad}.")
                    with arcpy.da.SearchCursor(local, cursor_fields) as cursor:
                        buffer = []
                        for item in cursor:
                            pm_id = item[0]
                            nombre = item[1] if has_name else ""
                            shape = item[-1]
                            buffer.append((pm_id, nombre, shape))
                            if len(buffer) >= batch_size:
                                duplicados, cargadas = _procesar_lote(
                                    buffer, prioridad, lookup, db_path, candidatas, specs_por_fisico,
                                    stage_rutas, cursor_state, seen_db, duplicados, cargadas, fecha, sha, arcpy)
                                buffer.clear()
                        if buffer:
                            duplicados, cargadas = _procesar_lote(
                                buffer, prioridad, lookup, db_path, candidatas, specs_por_fisico,
                                stage_rutas, cursor_state, seen_db, duplicados, cargadas, fecha, sha, arcpy)
            _log(f"{archivo}: {cargadas} entidades preparadas; {duplicados} duplicados exactos omitidos.")
        finally:
            cursor_state["cursor"] = None
            cursor_state["target"] = None
        informe.setdefault("sources", {})[sha] = {
            "file": archivo, "entities_prepared": cargadas, "exact_duplicates": duplicados,
            "completed_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        }
        return cargadas, duplicados
    finally:
        if lookup is not None:
            lookup.close()
        try:
            os.remove(lookup_path)
        except FileNotFoundError:
            pass


def _procesar_lote(buffer, prioridad, lookup, db_path, candidatas, specs_por_fisico, stage_rutas,
                    cursor_state, seen_db, duplicados, cargadas, fecha, sha, arcpy):
    ids = [str(x[0]) for x in buffer if x[0]]
    if not ids:
        return duplicados, cargadas
    marcadores = ",".join("?" * len(ids))
    indices = {r[0]: (r[1], r[2]) for r in lookup.execute(
        f"SELECT id, grupo_id, prioridad FROM lookup WHERE id IN ({marcadores})", ids)}
    original = sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True)
    try:
        payloads = {r[0]: json.loads(r[1]) for r in original.execute(
            f"SELECT id,payload FROM originals WHERE id IN ({marcadores})", ids)}
    finally:
        original.close()
    for pm_id, nombre, shape in buffer:
        if not pm_id or shape is None or shape.pointCount == 0:
            continue
        data = indices.get(str(pm_id))
        if not data:
            raise ValueError(f"El Placemark {pm_id} de la clase preparada no existe en trazabilidad.sqlite.")
        gid, orden = data
        if orden != prioridad or gid not in candidatas:
            continue
        fila = candidatas[gid]
        spec = specs_por_fisico[fila["clase_fisica"].lower()]
        payload = payloads.get(str(pm_id))
        if payload is None:
            raise ValueError(f"Falta el payload original del Placemark {pm_id}.")
        ruta = reglas._ruta_de(json.dumps(payload.get("containers") or [], ensure_ascii=False))
        payload["_eft_pm_id"] = str(pm_id)
        valores = _valores_fila(shape, spec, fila, sha, gid, nombre, ruta, payload, fecha, arcpy)
        clave = _hash_duplicado(spec, valores)
        nuevo = seen_db.execute("INSERT OR IGNORE INTO seen(key) VALUES (?)", (clave,))
        if nuevo.rowcount == 0:
            duplicados += 1
            continue
        key = spec.fisico.lower()
        if cursor_state["target"] != key:
            cursor_state["cursor"] = None
            cursor_state["cursor"] = arcpy.da.InsertCursor(
                stage_rutas[key], modelo.nombres_campos(spec) + ["SHAPE@"])
            cursor_state["target"] = key
        cursor_state["cursor"].insertRow(valores)
        cargadas += 1
    return duplicados, cargadas


def _preparar_local(trabajo, seleccion, mapping_path=None, id_analisis=None, arcpy=None):
    if arcpy is None:
        import arcpy
    destino, filas = _seleccionar_mapeo(trabajo, mapping_path)
    por_sha = _filas_sha(filas, dict(seleccion))
    relevantes = [fila for sha, _ in seleccion for fila in por_sha.get(sha, [])]
    errores = mapeo.validar(relevantes)
    if errores:
        raise ValueError("Corrija el mapeo antes de preparar:\n" + "\n".join(errores[:30]))
    specs = mapeo.specs(relevantes)
    if not specs:
        raise ValueError("No hay grupos cargables en la seleccion. Revise incluir, clase y proyecto en el mapeo.")
    base = _base_mapeo(trabajo)
    base.mkdir(parents=True, exist_ok=True)
    gdb_local = str(base / "EFT_local.gdb")
    if not arcpy.Exists(gdb_local):
        arcpy.management.CreateFileGDB(str(base), "EFT_local.gdb")
    for fila in filas:
        if fila.get("id_analisis"):
            continue
        fila["id_analisis"] = id_analisis or "Carga inicial KMZ"
    mapeo.escribir(destino, filas)
    seen_path = str(base / "deduplicacion.sqlite")
    if os.path.exists(seen_path):
        os.remove(seen_path)
    seen_db = sqlite3.connect(seen_path)
    seen_db.execute("CREATE TABLE seen(key TEXT PRIMARY KEY)")
    informe = {"version": VERSION, "mode": "PREPARAR_LOCAL", "started_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
               "sources": {}, "totals": {"prepared": 0, "duplicates": 0}}
    stage_gdb, stage_rutas = _crear_stage(arcpy, base, specs, _log)
    try:
        db_path = str(Path(trabajo) / "trazabilidad.sqlite")
        total_loaded = total_duplicates = 0
        for sha, fuente in seleccion:
            loaded, duplicates = _transformar_kmz(trabajo, sha, fuente, filas, db_path, stage_rutas,
                                                   seen_db, informe, arcpy)
            total_loaded += loaded
            total_duplicates += duplicates
        stage_count = 0
        for spec in specs:
            fc = stage_rutas.get(spec.fisico.lower())
            if fc:
                stage_count += int(arcpy.management.GetCount(fc)[0])
        if stage_count != total_loaded:
            raise RuntimeError(f"Conteo de preparacion inconsistente: stage={stage_count}, informe={total_loaded}.")
        # Replace only the selected SHA values in the local staging target; never touch the SDE here.
        rutas_local = modelo.crear_estructura(gdb_local, specs, log=_log)
        selected_sha = [sha for sha, _ in seleccion]
        inv = modelo.inventario(gdb_local)
        for fc in inv["clases"].values():
            names = {f.name.lower(): f.name for f in arcpy.ListFields(fc)}
            campo = names.get("kz_sha256")
            if not campo:
                continue
            for sha in selected_sha:
                where = f"{arcpy.AddFieldDelimiters(fc, campo)} = '{sha}'"
                with arcpy.da.UpdateCursor(fc, [campo], where_clause=where) as cursor:
                    for _ in cursor:
                        cursor.deleteRow()
        for spec in specs:
            src = stage_rutas[spec.fisico.lower()]
            count = int(arcpy.management.GetCount(src)[0])
            if not count:
                continue
            dest_fc = rutas_local[spec.fisico.lower()]
            arcpy.management.Append(src, dest_fc, "NO_TEST")
            _log(f"Preparacion local: {spec.fisico}, {count} entidades.")
        actual = sum(_conteo_sha(arcpy, fc, sha) for fc in modelo.inventario(gdb_local)["clases"].values()
                     for sha in selected_sha if any(f.name.lower() == "kz_sha256" for f in arcpy.ListFields(fc)))
        if actual != total_loaded:
            raise RuntimeError(f"Verificacion local fallo: {actual} entidades por SHA; se esperaban {total_loaded}.")
        informe["totals"] = {"prepared": total_loaded, "duplicates": total_duplicates}
        informe["local_gdb"] = gdb_local
        informe["completed_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
        _guardar_json(base / "informe_eft.json", informe)
        mapeo.escribir_balance(destino.with_name("balance_eft.csv"), filas)
        _log(f"PREPARADO_EFT_LOCAL: {len(seleccion)} KMZ, {total_loaded} entidades, "
             f"{total_duplicates} duplicados exactos. Geodatabase: {gdb_local}")
        return informe
    finally:
        seen_db.close()
        try:
            os.remove(seen_path)
        except FileNotFoundError:
            pass
        if arcpy.Exists(stage_gdb):
            try:
                arcpy.management.ClearWorkspaceCache(stage_gdb)
                arcpy.management.Delete(stage_gdb)
            except Exception as exc:
                LOGGER.warning("No se pudo limpiar la geodatabase temporal %s: %s", stage_gdb, exc)


def _estructura_sde(workspace, filas, completa=False, arcpy=None):
    if arcpy is None:
        import arcpy
    specs = modelo.specs_completas() if completa else mapeo.specs(filas)
    if not specs:
        raise ValueError("No hay clases en el mapeo. Ejecute PROPONER y revise el CSV.")
    rutas = modelo.crear_estructura(workspace, specs, log=_log)
    relacion = modelo.crear_relaciones(workspace, specs, log=_log)
    return {"specs": len(specs), "created": len(rutas), "relationships": relacion}


def _sha_en_fc(arcpy, fc, sha):
    return _conteo_sha(arcpy, fc, sha)


def _cargar_sde(workspace, trabajo, seleccion, filas, arcpy=None):
    if arcpy is None:
        import arcpy
    local = str(_base_mapeo(trabajo) / "EFT_local.gdb")
    if not arcpy.Exists(local):
        raise FileNotFoundError(f"No existe la geodatabase local preparada: {local}")
    specs = mapeo.specs([fila for sha, _ in seleccion for fila in _filas_sha(filas, dict(seleccion)).get(sha, [])])
    if not specs:
        raise ValueError("No hay clases cargables para la seleccion.")
    modelo.crear_estructura(workspace, specs, log=_log)
    modelo.crear_relaciones(workspace, specs, log=_log)
    local_inv = modelo.inventario(local)
    sde_inv = modelo.inventario(workspace)
    conteos_locales = {}
    for spec in specs:
        local_fc = local_inv["clases"].get(spec.fisico.lower())
        sde_fc = sde_inv["clases"].get(spec.fisico.lower())
        if not local_fc or not sde_fc:
            raise RuntimeError(f"No existe {spec.fisico} en el workspace local o SDE.")
        conteos_locales[spec.fisico] = {sha: _sha_en_fc(arcpy, local_fc, sha) for sha, _ in seleccion}
    total_local = sum(n for por_sha in conteos_locales.values() for n in por_sha.values())
    conteos_sde = {spec.fisico: {sha: _sha_en_fc(arcpy, sde_inv["clases"][spec.fisico.lower()], sha)
                                 for sha, _ in seleccion} for spec in specs}
    total_sde = sum(n for por_sha in conteos_sde.values() for n in por_sha.values())
    if total_sde:
        if total_sde == total_local and all(
                conteos_sde[spec.fisico][sha] == conteos_locales[spec.fisico][sha]
                for spec in specs for sha, _ in seleccion):
            _log("Los KMZ seleccionados ya estan cargados y los conteos coinciden; no se repite Append.")
            return {"status": "OMITIDO_YA_CARGADO", "local": total_local, "sde": total_sde}
        raise RuntimeError(f"Carga parcial o conteos distintos: SDE={total_sde}, local={total_local}. "
                           "Use RETIRAR_KMZ para retirar el SHA completo y vuelva a cargar.")
    for spec in specs:
        local_fc = local_inv["clases"][spec.fisico.lower()]
        sde_fc = sde_inv["clases"][spec.fisico.lower()]
        for sha, _ in seleccion:
            count = conteos_locales[spec.fisico][sha]
            if not count:
                continue
            campo = next(f.name for f in arcpy.ListFields(local_fc) if f.name.lower() == "kz_sha256")
            where = f"{arcpy.AddFieldDelimiters(local_fc, campo)} = '{sha}'"
            layer = f"eft_src_{spec.fisico[:22]}_{sha[:6]}"
            try:
                arcpy.management.MakeFeatureLayer(local_fc, layer, where)
                arcpy.management.Append(layer, sde_fc, "NO_TEST")
            finally:
                if arcpy.Exists(layer):
                    arcpy.management.Delete(layer)
            _log(f"Cargado SDE: {spec.fisico} / {sha[:12]}, {count} filas.")
    verificado = 0
    for spec in specs:
        sde_fc = sde_inv["clases"][spec.fisico.lower()]
        local_fc = local_inv["clases"][spec.fisico.lower()]
        for sha, _ in seleccion:
            esperado = conteos_locales[spec.fisico][sha]
            encontrado = _sha_en_fc(arcpy, sde_fc, sha)
            if esperado != encontrado:
                raise RuntimeError(f"Verificacion SDE fallo en {spec.fisico} / {sha[:12]}: "
                                   f"esperado={esperado}, encontrado={encontrado}.")
            verificado += encontrado
    return {"status": "CARGADO_SDE", "local": total_local, "sde": verificado}


def _versionar_sde(workspace, arcpy=None):
    if arcpy is None:
        import arcpy
    descripcion = arcpy.Describe(workspace)
    propiedades = getattr(descripcion, "connectionProperties", None)
    versionado = getattr(propiedades, "versioningType", None) if propiedades else None
    if not versionado or str(versionado).casefold() not in ("branch", "branch versioning"):
        raise RuntimeError("No se puede confirmar una conexion de versionado Branch. Configure la conexion SDE "
                           "como Branch y con usuario propietario de los datos antes de continuar.")
    return {"registered": modelo.registrar_versionado(workspace, log=_log), "versioningType": str(versionado)}


def _retirar_kmz(workspace, seleccion, confirmado=False, arcpy=None):
    if not confirmado:
        raise RuntimeError("Retirar es destructivo: marque la confirmacion explicita en la toolbox.")
    if arcpy is None:
        import arcpy
    if modelo.estado_versionado(workspace):
        raise RuntimeError("Datos_Proyecto esta versionado; no se eliminan filas mientras el dataset este versionado.")
    inv = modelo.inventario(workspace)
    retirados = {}
    for sha, fuente in seleccion:
        count = 0
        for fc in inv["clases"].values():
            nombres = {f.name.lower(): f.name for f in arcpy.ListFields(fc)}
            campo = nombres.get("kz_sha256")
            if not campo:
                continue
            where = f"{arcpy.AddFieldDelimiters(fc, campo)} = '{sha}'"
            with arcpy.da.UpdateCursor(fc, [campo], where_clause=where) as cursor:
                for _ in cursor:
                    cursor.deleteRow()
                    count += 1
        retirados[sha] = count
        _log(f"Retirado {Path(fuente.get('file') or '').name}: {count} entidades.")
    return retirados


def ejecutar(modo, trabajo, *, sde=None, sha=None, kmz=None, mapping_path=None, id_analisis=None,
             completa=False, confirmar=False, regenerar=False, arcpy=None):
    modo = str(modo).upper()
    if modo not in MODOS:
        raise ValueError(f"Modo desconocido: {modo}. Opciones: {', '.join(MODOS)}.")
    trabajo = str(Path(trabajo).resolve())
    Path(trabajo).mkdir(parents=True, exist_ok=True)
    if arcpy is None and modo != "PROPONER":
        import arcpy
    _, fuentes = _fuentes(trabajo)
    seleccion = _seleccionar(fuentes, sha, kmz)
    if modo == "RETIRAR_KMZ" and not sha and not kmz:
        raise RuntimeError("RETIRAR_KMZ requiere seleccionar al menos un KMZ de forma explicita.")
    base = _base_mapeo(trabajo)
    informe_path = base / "informe_eft.json"
    with _candado(base / "informe_eft.lock"):
        if modo == "PROPONER":
            resultado = _proponer(trabajo, seleccion, mapping_path, regenerar)
        elif modo == "PREPARAR_LOCAL":
            resultado = _preparar_local(trabajo, seleccion, mapping_path, id_analisis, arcpy)
        else:
            if not sde:
                raise ValueError(f"El modo {modo} requiere una conexion de geodatabase SDE.")
            _, filas = _seleccionar_mapeo(trabajo, mapping_path)
            if modo == "ESTRUCTURA_SDE":
                resultado = _estructura_sde(sde, filas, completa, arcpy)
            elif modo == "CARGAR_SDE":
                resultado = _cargar_sde(sde, trabajo, seleccion, filas, arcpy)
            elif modo == "VERSIONAR_SDE":
                resultado = _versionar_sde(sde, arcpy)
            else:
                resultado = _retirar_kmz(sde, seleccion, confirmar, arcpy)
        estado = {"version": VERSION, "mode": modo, "result": resultado,
                  "selection": [{"sha256": sh, "file": src.get("file")} for sh, src in seleccion],
                  "completed_utc": dt.datetime.now(dt.timezone.utc).isoformat()}
        _guardar_json(informe_path, estado)
    return estado


def _parser():
    parser = argparse.ArgumentParser(description="Preparacion EFT 5.8 para KMZ ya procesados por la toolbox de transferencia.")
    parser.add_argument("--modo", required=True, choices=MODOS)
    parser.add_argument("--trabajo", required=True, help="Carpeta que contiene informe.json y trazabilidad.sqlite")
    parser.add_argument("--sde", help="Conexion de geodatabase enterprise .sde")
    parser.add_argument("--sha", action="append", default=[], help="SHA-256 de un KMZ preparado (repetible)")
    parser.add_argument("--kmz", action="append", default=[], help="Nombre de KMZ preparado (repetible)")
    parser.add_argument("--mapeo", help="Ruta alternativa a mapeo_eft.csv")
    parser.add_argument("--id-analisis", default="Carga inicial KMZ")
    parser.add_argument("--estructura-completa", action="store_true")
    parser.add_argument("--confirmar", action="store_true", help="Confirmacion requerida por RETIRAR_KMZ")
    parser.add_argument("--regenerar", action="store_true", help="Respaldar y regenerar mapeo")
    return parser


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = _parser().parse_args(argv)
    try:
        resultado = ejecutar(args.modo, args.trabajo, sde=args.sde, sha=args.sha, kmz=args.kmz,
                             mapping_path=args.mapeo, id_analisis=args.id_analisis,
                             completa=args.estructura_completa, confirmar=args.confirmar, regenerar=args.regenerar)
    except Exception:
        LOGGER.exception("La ejecucion EFT fallo.")
        return 1
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
