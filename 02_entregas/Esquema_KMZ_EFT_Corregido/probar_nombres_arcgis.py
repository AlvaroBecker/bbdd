"""Validacion de nombres 1.5 en GDB de ensayo existente; no crea objetos."""
import argparse
import hashlib
import json
from pathlib import Path
import arcpy
import crear_esquema as engine
from normalizacion_kmz import SQLSERVER_RESERVED, ARCGIS_SDE_REJECTED


def main():
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', required=True)
    args = parser.parse_args()
    path = Path(args.workspace).resolve()
    assert path.suffix == '.gdb' and path.is_relative_to(here / '_validacion')
    assert arcpy.Exists(str(path))
    raw = (here / 'esquema.json').read_bytes()
    model = json.loads(raw)
    names = {f['nombre'] for c in model['clases'] for f in c['campos']}
    assert not {n.upper() for n in names} & (SQLSERVER_RESERVED | ARCGIS_SDE_REJECTED)
    engine.validate_names(arcpy, str(path), model['clases'])
    report = dict(version_paquete='1.5', version_modelo=model['version'],
                  arcgis=arcpy.GetInstallInfo()['Version'],
                  clases=len(model['clases']), campos=sum(len(c['campos']) for c in model['clases']),
                  nombres_campo_distintos=len(names), nombres_validos_en_gdb_local=True,
                  palabras_reservadas_sqlserver_en_modelo=[], nombres_rechazados_sde_en_modelo=[],
                  operaciones_de_escritura_en_geodatabase=0, validacion_sde=False,
                  alcance='ValidateTableName y ValidateFieldName sobre GDB local; cotejo estatico contra palabras reservadas actuales de Transact-SQL. No demuestra validez en SDE.',
                  esquema_sha256=hashlib.sha256(raw).hexdigest())
    (here / 'VALIDACION_NOMBRES_SQLSERVER.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
