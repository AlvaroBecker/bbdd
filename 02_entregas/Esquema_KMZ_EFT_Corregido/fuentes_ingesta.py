"""Inventario recursivo de KMZ por identidad SHA-256; solo lectura.

El nombre canónico identifica la fuente en el perfil. Su contenido, y no una
aproximación del nombre, acredita que el archivo local es esa fuente. Este
módulo no abre conexiones de base de datos ni escribe archivos.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import stat


def digest(path):
    """Calcula SHA-256 y rechaza un archivo que cambió durante la lectura."""
    path = Path(path)
    before = path.stat()
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (
            after.st_size, after.st_mtime_ns, after.st_ino):
        raise OSError('El archivo cambió durante la lectura.')
    return value.hexdigest(), after.st_size


def _references(expected_archivos):
    by_name, by_hash = {}, {}
    for source in expected_archivos:
        name = source.get('archivo')
        sha = str(source.get('sha256', '')).lower()
        if (not isinstance(name, str) or not name or '/' in name or '\\' in name
                or not name.casefold().endswith('.kmz')
                or not re.fullmatch('[0-9a-f]{64}', sha)):
            raise ValueError('Referencia KMZ inválida: se requieren archivo y SHA-256.')
        if name.casefold() in by_name:
            raise ValueError('Nombre de referencia duplicado: ' + name)
        if sha in by_hash:
            raise ValueError('Dos referencias comparten SHA-256: ' + name)
        item = dict(archivo=name, sha256=sha)
        by_name[name.casefold()] = item
        by_hash[sha] = item
    if not by_name:
        raise ValueError('El inventario de referencia no puede estar vacío.')
    return by_name, by_hash


def _is_link(path):
    info = path.lstat()
    return (path.is_symlink() or bool(getattr(info, 'st_file_attributes', 0)
                                     & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0)))


def discover_sources(root, expected_archivos, emit=print):
    """Devuelve un informe JSON serializable sin modificar las fuentes.

    ``expected_archivos`` es la lista ``perfil['fuentes']`` (archivo/sha256).
    ``completo`` acredita que todos los hashes esperados fueron encontrados y
    que la exploración no sufrió errores. ``verificado`` exige además ausencia
    de copias duplicadas, archivos inesperados y conflictos de nombre.

    ``archivos_por_referencia`` contiene solamente correspondencias de hash con
    una única ruta. En duplicados, ``fuentes[].ruta_elegida`` es informativa;
    no se incorpora esa ruta al mapa ni se autoriza una carga automática.
    """
    by_name, by_hash = _references(expected_archivos)
    folder = Path(root).expanduser().resolve()
    report = dict(carpeta=str(folder), criterio='SHA256_EXACTO', inventario=[],
                  fuentes=[], archivos_por_referencia={}, ausentes=[],
                  inesperados=[], duplicados=[], conflictos_nombre=[], errores=[],
                  completo=False, verificado=False, cambios_en_fuentes=False,
                  cambios_en_sde=False, ingesta_autorizada=False)
    matches = {sha: [] for sha in by_hash}

    def error(path, message):
        report['errores'].append(dict(ruta=str(path), mensaje=str(message)))

    if not folder.is_dir():
        error(folder, 'La carpeta de KMZ no existe o no es un directorio accesible.')
    else:
        paths = []

        def walk_error(exception):
            error(getattr(exception, 'filename', folder), exception)

        for directory, dirs, names in os.walk(folder, topdown=True, onerror=walk_error,
                                              followlinks=False):
            safe_dirs = []
            for name in sorted(dirs, key=lambda value: (value.casefold(), value)):
                path = Path(directory) / name
                try:
                    if _is_link(path):
                        error(path, 'Subcarpeta enlazada omitida; no se sigue fuera del inventario.')
                    else:
                        safe_dirs.append(name)
                except OSError as exc:
                    error(path, exc)
            dirs[:] = safe_dirs
            for name in names:
                if name.casefold().endswith('.kmz'):
                    paths.append(Path(directory) / name)
        for path in sorted(paths, key=lambda value: (str(value).casefold(), str(value))):
            item = dict(ruta=str(path), ruta_relativa=str(path.relative_to(folder)),
                        nombre=path.name, sha256=None, bytes=None,
                        archivo_referencia=None, estado='ERROR_LECTURA')
            report['inventario'].append(item)
            try:
                if _is_link(path):
                    raise OSError('Archivo enlazado omitido; se requiere una copia local verificable.')
                if not path.is_file():
                    raise OSError('El elemento KMZ no es un archivo regular.')
                sha, size = digest(path)
                item.update(sha256=sha, bytes=size)
                reference = by_hash.get(sha)
                named_reference = by_name.get(path.name.casefold())
                if named_reference is not None and named_reference['sha256'] != sha:
                    report['conflictos_nombre'].append(dict(
                        ruta=str(path), nombre=path.name,
                        archivo_referencia=named_reference['archivo'],
                        sha256_esperado=named_reference['sha256'], sha256_observado=sha))
                if reference is None:
                    item['estado'] = 'CONTENIDO_NO_INCLUIDO_EN_REFERENCIA'
                    report['inesperados'].append(dict(item))
                else:
                    item['archivo_referencia'] = reference['archivo']
                    item['estado'] = ('IDENTICO_NOMBRE_Y_CONTENIDO'
                                      if path.name == reference['archivo']
                                      else 'IDENTICO_CONTENIDO_NOMBRE_DISTINTO')
                    matches[sha].append(str(path))
                if emit is not None:
                    emit('FUENTE: ' + path.name + '; ' + item['estado'] + '.')
            except OSError as exc:
                item['estado'] = 'ERROR_LECTURA'
                item['mensaje'] = str(exc)
                error(path, exc)

    for reference in sorted(by_hash.values(), key=lambda value: value['archivo']):
        name, sha = reference['archivo'], reference['sha256']
        paths = matches[sha]
        paths.sort(key=lambda value: (Path(value).name != name, value.casefold(), value))
        row = dict(archivo=name, sha256=sha, rutas=paths,
                   ruta_elegida=paths[0] if paths else None, copias=len(paths),
                   estado='AUSENTE' if not paths else 'DUPLICADO_IDENTICO' if len(paths) > 1
                   else 'VERIFICADO_POR_SHA256')
        report['fuentes'].append(row)
        if not paths:
            report['ausentes'].append(dict(archivo=name, sha256=sha))
        elif len(paths) > 1:
            report['duplicados'].append(dict(archivo=name, sha256=sha, rutas=list(paths)))
        else:
            report['archivos_por_referencia'][name] = paths[0]
    report['conteos'] = dict(esperados=len(by_hash), encontrados=len(report['inventario']),
                            referencias_cubiertas=sum(bool(paths) for paths in matches.values()),
                            ausentes=len(report['ausentes']), inesperados=len(report['inesperados']),
                            referencias_duplicadas=len(report['duplicados']),
                            conflictos_nombre=len(report['conflictos_nombre']),
                            errores=len(report['errores']))
    report['completo'] = not report['ausentes'] and not report['errores']
    report['verificado'] = bool(report['completo'] and not report['inesperados']
                                and not report['duplicados'] and not report['conflictos_nombre'])
    report['estado'] = 'FUENTES_VERIFICADAS' if report['verificado'] else 'FUENTES_CON_INCIDENCIAS'
    return report
