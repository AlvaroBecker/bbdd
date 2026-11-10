"""Lee exclusivamente los cuatro CSV de inventario aprobados, sin sobrescribirlos.

Los SHA-256 proceden de VALIDACION_NORMALIZACION.json del paquete historico
1.6.2. Si el archivo de trabajo cambio, se admite solamente su copia integra en
inventario_kmz_resumen.zip. Nunca se extrae el ZIP ni se reemplaza el CSV actual.
"""

import hashlib
from pathlib import Path, PurePosixPath
import zipfile


EXPECTED_SHA256 = {
    'inventario_kmz_campos.csv': 'e81c05ed81b35b998b6b10ee39911807ffeaa0eec740bf14dfaa40c1eb62af8c',
    'inventario_kmz_capas.csv': 'a17043bd8f500a6e05f95594abdaa6763c59da5f860b57c030f06d6f530dff14',
    'inventario_kmz_matriz_campos.csv': 'fcea4243bca9875ceb9a92ee8ef7e65b0f9b85fb54211c717c1a6ef5dd10d495',
    'inventario_kmz_resumen.csv': '42fa9466bc4b45184877719a6b895cda7a484f676505936bc29eb5b22ce85ae2',
}


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _read(root, name):
    if name not in EXPECTED_SHA256:
        raise ValueError(f'Fuente de inventario no autorizada: {name!r}.')
    root = Path(root).resolve()
    current = root / 'inventario_kmz_resumen' / name
    if not current.resolve().is_relative_to(root):
        raise ValueError('La fuente de inventario debe permanecer dentro del proyecto.')
    expected = EXPECTED_SHA256[name]
    raw = current.read_bytes() if current.is_file() else None
    current_sha = _sha(raw) if raw is not None else None
    metadata = {
        'nombre': name,
        'sha256': expected,
        'ruta_actual': str(current),
        'sha256_actual': current_sha,
        'archivo_actual_modificado': False,
        'ruta_zip': None,
        'miembro_zip': None,
    }
    if current_sha == expected:
        metadata.update(origen='CSV_ACTUAL_VERIFICADO', bytes=len(raw))
        return raw, metadata

    archive_path = root / 'inventario_kmz_resumen.zip'
    if not archive_path.resolve().is_relative_to(root) or not archive_path.is_file():
        raise ValueError(f'{name}: el CSV actual no coincide con la referencia y falta el ZIP original verificado.')
    with zipfile.ZipFile(archive_path) as archive:
        candidates = [info for info in archive.infolist() if not info.is_dir()
                      and PurePosixPath(info.filename.replace('\\', '/')).name == name]
        if len(candidates) != 1:
            raise ValueError(f'{name}: debe existir un unico miembro con ese nombre en el ZIP original; encontrados {len(candidates)}.')
        member = candidates[0]
        raw = archive.read(member)
    if _sha(raw) != expected:
        raise ValueError(f'{name}: el SHA-256 del miembro del ZIP no coincide con la referencia aprobada.')
    metadata.update(origen='ZIP_ORIGINAL_VERIFICADO', bytes=len(raw),
                    ruta_zip=str(archive_path), miembro_zip=member.filename)
    return raw, metadata


def read_inventory_bytes(root, name):
    """Devuelve bytes aprobados del CSV actual o del unico miembro ZIP valido."""
    return _read(root, name)[0]


def source_metadata(root, name):
    """Informa origen y hashes tras volver a verificar la fuente; no modifica nada."""
    return _read(root, name)[1]
