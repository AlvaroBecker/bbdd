"""Creacion robusta de la estructura VACIA de Datos_Proyecto con ArcPy.

Acciones:
  diagnosticar  Lee la geodatabase y clasifica cada clase. No modifica nada (por defecto).
  crear         Muestra el plan; con --aplicar crea dominios, clases, campos, GlobalID y Editor Tracking UTC.
  verificar     Igual que diagnosticar; termina con error si alguna clase no esta completa.
  relacionar    Crea las relationship classes con mline_tc_proyecto (fase separada, usa crear_esquema.py).

Garantias: no carga datos, no borra ni renombra objetos y no modifica clases con registros.
Es idempotente: si se interrumpe, volver a ejecutar completa solo lo que falta en clases vacias.
Cada ejecucion escribe un log y un informe (JSON y CSV) en la carpeta informes/.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import crear_esquema as base  # noqa: E402

TRACKING = ('created_user', 'created_date', 'last_edited_user', 'last_edited_date')
SYSTEM_FIELDS = {'objectid', 'oid', 'fid', 'shape', 'globalid', 'shape_length', 'shape_area', *TRACKING}
GEOMETRIES = {'POINT', 'POLYLINE', 'POLYGON'}
CHUNK = 40
LOG = logging.getLogger('datos_proyecto')


def lint_spec(model, classes):
    """Valida la definicion sin necesitar ArcGIS."""
    problems = []
    seen = set()
    for c in classes:
        name = c['nombre']
        if name.lower() in seen:
            problems.append(f'Clase duplicada: {name}')
        seen.add(name.lower())
        if not re.fullmatch('[A-Za-z_][A-Za-z0-9_]{0,127}', name):
            problems.append(f'Nombre de clase invalido: {name}')
        if c['geometria'] not in GEOMETRIES:
            problems.append(f'{name}: geometria no admitida {c["geometria"]}')
        fields = {}
        for f in c['campos']:
            key = f['nombre'].lower()
            if key in fields:
                problems.append(f'{name}: campo duplicado {f["nombre"]}')
            fields[key] = f
            if key in SYSTEM_FIELDS:
                problems.append(f'{name}: {f["nombre"]} colisiona con un campo de sistema')
            if not re.fullmatch('[A-Za-z_][A-Za-z0-9_]{0,127}', f['nombre']):
                problems.append(f'{name}: nombre de campo invalido {f["nombre"]}')
            if f['tipo'] not in base.TYPE:
                problems.append(f'{name}.{f["nombre"]}: tipo no admitido {f["tipo"]}')
            if f['tipo'] == 'TEXT' and not 1 <= (f.get('longitud') or 0) <= 4000:
                problems.append(f'{name}.{f["nombre"]}: longitud de texto fuera de 1-4000')
            if f.get('dominio') and f['dominio'] not in model['dominios']:
                problems.append(f'{name}.{f["nombre"]}: dominio inexistente {f["dominio"]}')
        if c['relacion_proyecto']:
            for needed in ('proyecto', 'id_analisis'):
                f = fields.get(needed)
                if f is None or f['nullable'] or f['tipo'] != 'TEXT':
                    problems.append(f'{name}: {needed} debe ser Texto obligatorio')
            if fields.get('proyecto', {}).get('longitud') != 12:
                problems.append(f'{name}: proyecto debe tener longitud 12')
    return problems


def refresh(a, ws):
    """ArcGIS 3.7 puede devolver lecturas obsoletas justo despues de crear objetos."""
    try:
        a.management.ClearWorkspaceCache(ws)
    except Exception:
        a.management.ClearWorkspaceCache()


def open_workspace(a, args):
    ws = args.workspace
    remote = ws.lower().endswith('.sde')
    base.require(remote or ws.lower().endswith('.gdb'), 'Indique una conexion .sde o una ruta .gdb.')
    if not a.Exists(ws):
        base.require(not remote, f'No existe la conexion {ws}.')
        base.require(Path(ws).parent.is_dir(), 'La carpeta padre de la geodatabase no existe.')
        return {}
    wd = a.Describe(ws)
    base.require(wd.workspaceType == ('RemoteDatabase' if remote else 'LocalDatabase'), 'Tipo de workspace no admitido.')
    if remote:
        cp = wd.connectionProperties
        base.require(str(cp.database).lower() == args.database.lower(), f'La conexion apunta a {cp.database}, no a {args.database}.')
        user = str(getattr(cp, 'user', ''))
        base.require(user.lower() == args.owner.lower(), f'La conexion usa el usuario {user!r}; se requiere el propietario {args.owner!r}.')
    return base.find_objects(a, args)


def dataset_problems(a, model, classes, inv):
    problems = []
    for ds in sorted({c['dataset'] for c in classes}):
        path = inv.get(ds.lower())
        if not path:
            continue
        d = a.Describe(path)
        if d.spatialReference.factoryCode != 4326:
            problems.append(f'{ds}: referencia espacial distinta de EPSG:4326.')
        if getattr(d, 'isVersioned', False) or getattr(d, 'isBranchVersioned', False):
            problems.append(f'{ds}: ya esta versionado; agregar clases requiere un procedimiento de administracion especifico.')
    return problems


def check_domains(a, args, model):
    if not a.Exists(args.workspace):
        return list(model['dominios']), []
    existing = {d.name: d for d in a.da.ListDomains(args.workspace)}
    missing, conflicts = [], []
    for name, spec in model['dominios'].items():
        d = existing.get(name)
        if d is None:
            missing.append(name)
        elif d.domainType != 'CodedValue' or d.type != 'Text':
            conflicts.append(f'Dominio {name}: tipo incompatible.')
        elif not all(d.codedValues.get(v) == v for v in spec['valores']):
            conflicts.append(f'Dominio {name}: faltan valores o sus descripciones difieren.')
    return missing, conflicts


def create_domains(a, args, model, missing):
    for name in missing:
        spec = model['dominios'][name]
        a.management.CreateDomain(args.workspace, name, spec['descripcion'], 'TEXT', 'CODED')
        for value in spec['valores']:
            a.management.AddCodedValueToDomain(args.workspace, name, value, value)
        LOG.info('Dominio creado: %s (%d valores)', name, len(spec['valores']))


def diagnose(a, args, c, inv):
    r = {'clase': c['nombre'], 'dataset': c['dataset'], 'geometria': c['geometria'], 'estado': 'NUEVA',
         'campos_esperados': len(c['campos']), 'conflictos': [], 'faltan_campos': [], 'faltan_dominios': [],
         'falta_globalid': False, 'falta_tracking': False}
    path = inv.get(c['nombre'].lower())
    if not path:
        return r
    d = a.Describe(path)
    conflicts = r['conflictos']
    if d.dataType != 'FeatureClass':
        conflicts.append('existe como tabla y no como clase de entidades; resolver su migracion con el administrador')
        r['estado'] = 'CONFLICTO'
        return r
    if base.simple(Path(d.path).name).lower() != c['dataset'].lower():
        conflicts.append(f'esta fuera de {c["dataset"]}')
    if d.shapeType.lower() != c['geometria'].lower():
        conflicts.append(f'geometria {d.shapeType}, esperada {c["geometria"]}')
    if d.spatialReference.factoryCode != 4326:
        conflicts.append('referencia espacial distinta de EPSG:4326')
    if not d.hasZ:
        conflicts.append('sin soporte Z')
    if d.hasM:
        conflicts.append('tiene valores M')
    actual = {f.name.lower(): f for f in a.ListFields(path)}
    for f in c['campos']:
        x = actual.get(f['nombre'].lower())
        if x is None:
            r['faltan_campos'].append(f)
            continue
        if x.type != base.TYPE[f['tipo']]:
            conflicts.append(f'{x.name}: tipo {x.type}, esperado {base.TYPE[f["tipo"]]}')
            continue
        if f['tipo'] == 'TEXT' and (x.length < f['longitud'] or (f['nombre'] == 'proyecto' and x.length != f['longitud'])):
            conflicts.append(f'{x.name}: longitud {x.length}, esperada {f["longitud"]}')
        if bool(x.isNullable) != bool(f['nullable']):
            conflicts.append(f'{x.name}: permite nulos={x.isNullable}, esperado {f["nullable"]}')
        want, have = f.get('dominio') or '', x.domain or ''
        if want != have:
            if want and not have:
                r['faltan_dominios'].append((f['nombre'], want))
            else:
                conflicts.append(f'{x.name}: dominio {have or "ninguno"}, esperado {want or "ninguno"}')
    r['falta_globalid'] = not d.hasGlobalID
    tracking = bool(getattr(d, 'editorTrackingEnabled', False))
    if tracking and not getattr(d, 'isTimeInUTC', False):
        conflicts.append('Editor Tracking no esta en UTC')
    r['falta_tracking'] = not tracking
    pending = bool(r['faltan_campos'] or r['faltan_dominios'] or r['falta_globalid'] or r['falta_tracking'])
    if pending and not conflicts and int(a.management.GetCount(path)[0]) > 0:
        conflicts.append('tiene registros e incompleta: no se modifica automaticamente')
    r['estado'] = 'CONFLICTO' if conflicts else ('INCOMPLETA' if pending else 'OK')
    return r


def add_fields(a, path, fields):
    nullable = [f for f in fields if f['nullable']]
    for i in range(0, len(nullable), CHUNK):
        a.management.AddFields(path, [[f['nombre'], f['tipo'], f['alias'], f['longitud'], None, f['dominio']]
                                      for f in nullable[i:i + CHUNK]])
    for f in fields:
        if not f['nullable']:
            a.management.AddField(path, f['nombre'], f['tipo'], field_length=f['longitud'], field_alias=f['alias'],
                                  field_is_nullable='NON_NULLABLE', field_domain=f['dominio'] or '')


def apply_class(a, args, c, inv, r):
    if r['estado'] == 'NUEVA':
        ds = inv[c['dataset'].lower()]
        inv[c['nombre'].lower()] = a.management.CreateFeatureclass(
            ds, c['nombre'], c['geometria'], has_z='ENABLED', has_m='DISABLED',
            spatial_reference=a.SpatialReference(4326)).getOutput(0)
        refresh(a, args.workspace)
        r = diagnose(a, args, c, inv)
        base.require(r['estado'] == 'INCOMPLETA', f'{c["nombre"]}: estado inesperado tras crear la clase: {r["estado"]} {r["conflictos"]}')
    path = inv[c['nombre'].lower()]
    if r['faltan_campos']:
        add_fields(a, path, r['faltan_campos'])
    for field, domain in r['faltan_dominios']:
        a.management.AssignDomainToField(path, field, domain)
    if r['falta_globalid']:
        a.management.AddGlobalIDs(path)
    if r['falta_tracking']:
        a.management.EnableEditorTracking(path, *TRACKING, 'ADD_FIELDS', 'UTC')


def summarize(results):
    counts = {}
    for r in results:
        counts[r['estado']] = counts.get(r['estado'], 0) + 1
    return counts


def detail(r):
    parts = list(r.get('conflictos', []))
    if r.get('error'):
        parts.append('ERROR: ' + r['error'])
    if r['estado'] == 'INCOMPLETA':
        parts.append(f'faltan {len(r["faltan_campos"])} campos, {len(r["faltan_dominios"])} dominios'
                     + (', GlobalID' if r['falta_globalid'] else '') + (', tracking' if r['falta_tracking'] else ''))
    return '; '.join(parts)


def write_report(args, model, classes, results, global_problems, started):
    out = Path(args.informe_dir) if args.informe_dir else HERE / 'informes'
    out.mkdir(parents=True, exist_ok=True)
    stamp = started.strftime('%Y%m%d_%H%M%S')
    clean = [{k: v for k, v in r.items() if k not in ('faltan_campos', 'faltan_dominios')} |
             {'faltan_campos': [f['nombre'] for f in r['faltan_campos']],
              'faltan_dominios': [f'{f}:{d}' for f, d in r['faltan_dominios']]} for r in results]
    payload = {'fecha': started.isoformat(timespec='seconds'), 'accion': args.accion, 'aplicar': args.aplicar,
               'workspace': args.workspace, 'clases_evaluadas': len(classes), 'resumen': summarize(results),
               'problemas_globales': global_problems, 'clases': clean}
    (out / f'informe_{stamp}.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    with open(out / f'informe_{stamp}.csv', 'w', newline='', encoding='utf-8-sig') as fh:
        writer = csv.writer(fh, delimiter=';')
        writer.writerow(['clase', 'dataset', 'geometria', 'campos_esperados', 'estado', 'detalle'])
        for r in results:
            writer.writerow([r['clase'], r['dataset'], r['geometria'], r['campos_esperados'], r['estado'], detail(r)])
    return out / f'informe_{stamp}.csv'


def run(args, model, classes, started):
    import arcpy as a
    ws = args.workspace
    results_error = {}
    with a.EnvManager(overwriteOutput=False):
        inv = open_workspace(a, args)
        missing_domains, domain_conflicts = check_domains(a, args, model)
        global_problems = dataset_problems(a, model, classes, inv) + domain_conflicts
        for c in classes:
            base.require(a.ValidateTableName(c['nombre'], ws) == c['nombre'], f'Nombre de clase no valido en este workspace: {c["nombre"]}')
            for f in c['campos']:
                base.require(a.ValidateFieldName(f['nombre'], ws) == f['nombre'],
                             f'Nombre de campo no valido en este workspace: {c["nombre"]}.{f["nombre"]}')
        results = [diagnose(a, args, c, inv) for c in classes]
        LOG.info('Diagnostico: %s; dominios por crear: %d', summarize(results), len(missing_domains))
        for r in results:
            if r['estado'] != 'OK':
                LOG.info('%-12s %s %s', r['estado'], r['clase'], detail(r))
        for p in global_problems:
            LOG.error('PROBLEMA GLOBAL: %s', p)

        if args.accion == 'crear' and args.aplicar:
            base.require(not global_problems, 'Resuelva los problemas globales antes de aplicar.')
            conflicted = [r['clase'] for r in results if r['estado'] == 'CONFLICTO']
            base.require(not conflicted or args.omitir_conflictos,
                         f'{len(conflicted)} clases en conflicto; revise el informe o use --omitir-conflictos: {conflicted[:5]}')
            if not a.Exists(ws):
                a.management.CreateFileGDB(str(Path(ws).parent), Path(ws).name)
            create_domains(a, args, model, missing_domains)
            for ds in sorted({c['dataset'] for c in classes}):
                if ds.lower() not in inv:
                    inv[ds.lower()] = a.management.CreateFeatureDataset(ws, ds, a.SpatialReference(4326)).getOutput(0)
                    LOG.info('Dataset creado: %s', ds)
            todo = [(c, r) for c, r in zip(classes, results) if r['estado'] in ('NUEVA', 'INCOMPLETA')]
            for n, (c, r) in enumerate(todo, 1):
                t0 = time.time()
                try:
                    apply_class(a, args, c, inv, r)
                    LOG.info('[%d/%d] %s listo (%.0f s)', n, len(todo), c['nombre'], time.time() - t0)
                except Exception as exc:
                    msg = str(exc)
                    try:
                        msg += ' | ' + a.GetMessages(2).replace('\n', ' ')
                    except Exception:
                        pass
                    LOG.error('[%d/%d] %s FALLO: %s', n, len(todo), c['nombre'], msg)
                    results_error[c['nombre']] = msg
                    if args.detener_en_error:
                        break
            refresh(a, ws)
            inv = base.find_objects(a, args)
            results = [diagnose(a, args, c, inv) for c in classes]
            for r in results:
                if r['clase'] in results_error:
                    r['error'] = results_error[r['clase']]
                    if r['estado'] != 'OK':
                        r['estado'] = 'ERROR'
        report = write_report(args, model, classes, results, global_problems, started)
        counts = summarize(results)
        LOG.info('RESUMEN: %s', counts)
        LOG.info('Informe: %s', report)
        ok = set(counts) <= {'OK'} and not global_problems
        if args.accion == 'diagnosticar' or (args.accion == 'crear' and not args.aplicar):
            return 0
        return 0 if ok else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--workspace', help='Conexion propietaria .sde o geodatabase .gdb')
    parser.add_argument('--accion', choices=['diagnosticar', 'crear', 'verificar', 'relacionar'], default='diagnosticar')
    parser.add_argument('--aplicar', action='store_true', help='Permite modificar la geodatabase')
    parser.add_argument('--clase', action='append', help='Repetible. Sin este parametro, todas las clases.')
    parser.add_argument('--sin-migradas', action='store_true', help='Omite las tres clases mline_td_proyecto_*')
    parser.add_argument('--omitir-conflictos', action='store_true', help='Aplica las demas clases aunque otras esten en conflicto')
    parser.add_argument('--detener-en-error', action='store_true')
    parser.add_argument('--database', default='ArcGisAWS')
    parser.add_argument('--owner', default='gis')
    parser.add_argument('--esquema', default=str(HERE / 'esquema.json'))
    parser.add_argument('--informe-dir')
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    started = datetime.now()
    out = Path(args.informe_dir) if args.informe_dir else HERE / 'informes'
    out.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s', handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(out / f'log_{started:%Y%m%d_%H%M%S}.txt', encoding='utf-8')])

    model = json.loads(Path(args.esquema).read_text(encoding='utf-8'))
    names = {c['nombre'] for c in model['clases']}
    base.require(not args.clase or set(args.clase) <= names, f'Clase desconocida: {sorted(set(args.clase or []) - names)}')
    base.require(all(re.fullmatch('[A-Za-z_][A-Za-z0-9_]*', v) for v in (args.database, args.owner)), 'Base/propietario invalidos.')
    classes = [c for c in model['clases']
               if (not args.clase or c['nombre'] in args.clase) and not (args.sin_migradas and c['tipo'] == 'migrada')]
    base.require(classes, 'No hay clases seleccionadas.')
    problems = lint_spec(model, classes)
    base.require(not problems, 'Esquema invalido: ' + ' | '.join(problems[:10]))
    LOG.info('Accion: %s; clases: %d; aplicar: %s', args.accion, len(classes), args.aplicar)

    if args.accion == 'relacionar':
        base.require(args.workspace, 'Indique --workspace.')
        delegated = ['--workspace', args.workspace, '--accion', 'relacionar', '--database', args.database, '--owner', args.owner]
        for c in classes:
            delegated += ['--clase', c['nombre']]
        base.main(delegated + (['--aplicar'] if args.aplicar else []))
        return 0
    if not args.workspace:
        base.require(not args.aplicar, 'Indique --workspace para aplicar.')
        LOG.info('Esquema valido sin conectar: %d clases, %d campos.', len(classes), sum(len(c['campos']) for c in classes))
        return 0
    return run(args, model, classes, started)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except ValueError as exc:
        logging.getLogger('datos_proyecto').error('%s', exc)
        sys.exit(2)
