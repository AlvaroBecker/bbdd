"""Inventario de identidad y relaciones de negocio: exclusivamente lectura ArcPy.

No consulta geometria, OBJECTID, celdas ni usuarios/IP de auditoria. No asigna
identificadores y no certifica su preservacion historica sin contrastar el origen.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime
import hashlib
import json
import math

import crear_esquema as engine


ID_ANALISIS_CARGA_INICIAL = 'Carga inicial KMZ'
MAX_SCAN_ROWS = 100000
MAX_REPORT_ROWS = 2000
MAX_EXAMPLES = 20
MAX_TEXT = 500

# Claves originales MapLine; los campos de las clases se cotejan ademas con el
# modelo aprobado. Vertices no tiene un PK de negocio nuevo que se pueda inventar.
SPECS = (
    ('mline_tc_proyecto', 'id_proyecto', ('co_proyecto',),
     ('no_proyecto', 'de_proyecto', 'id_estado_proyecto')),
    ('mline_td_proyecto_componente', 'id_proyecto_componente', ('id_proyecto',),
     ('no_componente', 'no_zona_geografica', 'id_estado_componente')),
    ('mline_td_proyecto_alternativa', 'id_proyecto_alternativa', ('id_proyecto_componente',),
     ('co_alternativa', 'nu_alternativa', 'id_alternativa_origen', 'id_estado_alternativa')),
    ('mline_td_proyecto_area_interes', 'id_proyecto_area_interes',
     ('id_proyecto_componente', 'proyecto', 'id_analisis'), ('id_proyecto_capa_area_interes',)),
    ('mline_td_proyecto_infraestructura', 'id_proyecto_infraestructura',
     ('id_proyecto_alternativa', 'proyecto', 'id_analisis'), ('co_infraestructura',)),
    ('mline_td_proyecto_ltransmision', 'id_proyecto_ltransmision',
     ('id_proyecto_componente', 'proyecto', 'id_analisis'),
     ('no_linea_transmision', 'no_subestacion_salida', 'no_subestacion_llegada')),
    ('vertices', None, ('id_proyecto_infraestructura', 'proyecto', 'id_analisis'),
     ('cod_vertice', 'vertice', 'vrtice')),
)
COMMON = ('es_registro', 'fe_eliminacion', 'nombre', 'archivo_origen', 'ruta_kml',
          'componente', 'alternativa')
LINKS = (
    ('mline_td_proyecto_componente', 'id_proyecto', 'mline_tc_proyecto', 'id_proyecto'),
    ('mline_td_proyecto_alternativa', 'id_proyecto_componente',
     'mline_td_proyecto_componente', 'id_proyecto_componente'),
    ('mline_td_proyecto_area_interes', 'id_proyecto_componente',
     'mline_td_proyecto_componente', 'id_proyecto_componente'),
    ('mline_td_proyecto_infraestructura', 'id_proyecto_alternativa',
     'mline_td_proyecto_alternativa', 'id_proyecto_alternativa'),
    ('mline_td_proyecto_ltransmision', 'id_proyecto_componente',
     'mline_td_proyecto_componente', 'id_proyecto_componente'),
    ('vertices', 'id_proyecto_infraestructura',
     'mline_td_proyecto_infraestructura', 'id_proyecto_infraestructura'),
)


def _normalized(value):
    return value.rstrip(' ').casefold() if isinstance(value, str) else value


def _inactive(row):
    return str(row.get('es_registro', '')).strip() == '0' or row.get('fe_eliminacion') is not None


def _serial(value):
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _public_row(row):
    result, truncated = {}, []
    for key, value in row.items():
        value = _serial(value)
        if isinstance(value, str) and len(value) > MAX_TEXT:
            value = value[:MAX_TEXT]
            truncated.append(key)
        result[key] = value
    if truncated:
        result['_campos_truncados_en_informe'] = truncated
    return result


def _add(report, code, message, severity='ERROR', **context):
    report['incidencias'].append(dict(codigo=code, mensaje=message, nivel=severity, **context))


def _index(rows, field):
    result = {}
    for row in rows:
        value = row.get(field)
        if value is not None:
            result.setdefault(_normalized(value), []).append(row)
    return result


def _check_keys(report, obj, rows, keys):
    for key in keys:
        counts, invalid = Counter(), 0
        numeric = []
        for row in rows:
            value = row.get(key)
            good = (isinstance(value, str) and bool(value.strip())
                    and value.rstrip(' ') == value.strip()) if key == 'co_proyecto' else (
                        isinstance(value, int) and not isinstance(value, bool))
            if not good:
                invalid += 1
                continue
            counts[_normalized(value)] += 1
            if isinstance(value, int):
                numeric.append(value)
        duplicates = [(value, count) for value, count in counts.items() if count > 1]
        obj['claves'][key] = dict(valores_distintos=len(counts), valores_invalidos=invalid,
            claves_duplicadas=len(duplicates),
            muestras_duplicadas=[dict(valor=v, repeticiones=n) for v, n in duplicates[:MAX_EXAMPLES]],
            maximo_observado=max(numeric) if numeric else None,
            minimo_observado=min(numeric) if numeric else None,
            maximo_autoriza_asignacion=False)
        if invalid:
            _add(report, 'CLAVE_NULA_O_INVALIDA', 'Hay claves de negocio nulas o incompatibles.',
                 objeto=obj['nombre'], campo=key, ocurrencias=invalid)
        if duplicates:
            _add(report, 'CLAVE_DUPLICADA', 'La identidad de negocio no es unica.',
                 objeto=obj['nombre'], campo=key, claves_duplicadas=len(duplicates))


def _read_object(a, path, name, pk, links, labels, model_classes, report):
    obj = dict(nombre=name, ruta=path, existe=bool(path), lectura_completa=False,
               lectura_datos_completa=False,
               campos_consultados=[], campos_ausentes=[], registros_leidos=0,
               registros=[], registros_informe_truncados=False, claves={},
               registros_inactivos_observados=0, geometria_consultada=False)
    report['objetos'].append(obj)
    if not path:
        _add(report, 'OBJETO_AUSENTE', 'No existe el objeto real; no se crea ni sustituye.', objeto=name)
        return obj, []
    try:
        description = a.Describe(path)
        obj.update(tipo_objeto=getattr(description, 'dataType', None),
                   tiene_oid=bool(getattr(description, 'hasOID', False)),
                   versionado=bool(getattr(description, 'isVersioned', False)),
                   branch=bool(getattr(description, 'isBranchVersioned', False)),
                   relaciones_observadas=sorted(getattr(description, 'relationshipClassNames', []) or []))
        fields = engine.field_index(a.ListFields(path))
    except Exception as exc:
        _add(report, 'METADATOS_NO_LEIDOS', str(exc), objeto=name)
        return obj, []
    if name in model_classes and obj['tipo_objeto'] != 'FeatureClass':
        _add(report, 'TIPO_OBJETO_DISTINTO_MODELO',
             'El nombre existe, pero el modelo exige una feature class. Se inventarian sus datos sin convertirlo.',
             objeto=name, observado=obj['tipo_objeto'], esperado='FeatureClass')
    required = ([pk] if pk else []) + list(links)
    obj['campos_ausentes'] = [f for f in required if f not in fields]
    if obj['campos_ausentes']:
        _add(report, 'CAMPOS_CLAVE_AUSENTES', 'Faltan campos para diagnosticar la identidad y referencias.',
             objeto=name, campos=obj['campos_ausentes'])
        return obj, []
    expected = {f['nombre'].casefold(): engine.TYPE[f['tipo']]
                for f in model_classes.get(name, {}).get('campos', []) if f['tipo'] in engine.TYPE}
    invalid_types = []
    for field in required:
        kind = expected.get(field, 'Integer' if field.startswith('id_') and field != 'id_analisis' else 'String')
        if fields[field].type != kind:
            invalid_types.append(dict(campo=field, observado=fields[field].type, esperado=kind))
    if invalid_types:
        _add(report, 'TIPOS_CLAVE_INCOMPATIBLES', 'No se convierten claves para forzar correspondencias.',
             objeto=name, campos=invalid_types)
        return obj, []
    selected = list(dict.fromkeys(required + [f for f in labels + COMMON if f in fields]))
    actual = [fields[f].name for f in selected]
    obj['campos_consultados'] = actual
    rows = []
    try:
        with a.da.SearchCursor(path, actual) as cursor:
            for values in cursor:
                if len(rows) >= MAX_SCAN_ROWS:
                    _add(report, 'LIMITE_LECTURA', 'Se alcanzo el limite de lectura; no se certifica integridad.',
                         objeto=name, limite=MAX_SCAN_ROWS)
                    break
                rows.append(dict(zip(selected, values)))
            else:
                obj['lectura_completa'] = True
                obj['lectura_datos_completa'] = True
    except Exception as exc:
        _add(report, 'LECTURA_DATOS_FALLIDA', str(exc), objeto=name)
    # SearchCursor no garantiza orden. Dos inventarios equivalentes deben tener
    # la misma representacion aunque el motor devuelva otro orden de filas.
    rows.sort(key=lambda row: json.dumps({k: _serial(v) for k, v in row.items()},
                                        sort_keys=True, ensure_ascii=True))
    digest = hashlib.sha256()
    for row in rows:
        digest.update(json.dumps({k: _serial(v) for k, v in row.items()}, sort_keys=True,
                                 ensure_ascii=True, separators=(',', ':')).encode('utf-8'))
        digest.update(b'\n')
    obj['huella_datos_leidos_sha256'] = digest.hexdigest()
    obj['registros_leidos'] = len(rows)
    obj['registros'] = [_public_row(row) for row in rows[:MAX_REPORT_ROWS]]
    obj['registros_informe_truncados'] = len(rows) > MAX_REPORT_ROWS
    if obj['registros_informe_truncados']:
        obj['lectura_completa'] = False
        _add(report, 'CATALOGO_INFORME_INCOMPLETO',
             'Se revisaron mas filas de las que caben en el informe. La muestra no basta para resolver identidades.',
             'PENDIENTE', objeto=name, filas_leidas=len(rows), filas_incluidas=MAX_REPORT_ROWS)
    obj['registros_inactivos_observados'] = sum(_inactive(row) for row in rows)
    if obj['registros_inactivos_observados']:
        _add(report, 'REGISTROS_INACTIVOS_CONSERVADOS',
             'Se conserva es_registro=0 o fecha de eliminacion; no se filtran filas historicas.',
             'ADVERTENCIA', objeto=name, ocurrencias=obj['registros_inactivos_observados'])
    if not rows and obj['lectura_completa']:
        _add(report, 'OBJETO_VACIO_SIN_EVIDENCIA',
             'No hay registros para contrastar identidades o relaciones; vacio no significa verificado.',
             'PENDIENTE', objeto=name)
    _check_keys(report, obj, rows, ([pk] if pk else []) + (['co_proyecto'] if name == 'mline_tc_proyecto' else []))
    if 'id_analisis' in selected:
        missing_analysis = sum(not isinstance(row.get('id_analisis'), str)
                               or not row['id_analisis'].strip() for row in rows)
        if missing_analysis:
            _add(report, 'ID_ANALISIS_SIN_VALOR', 'Hay registros sin identificador de analisis.',
                 objeto=name, ocurrencias=missing_analysis)
    return obj, rows


def _relationship(report, objects, rows, child, fk, parent, pk):
    result = dict(hijo=child, clave_hijo=fk, padre=parent, clave_padre=pk,
                  estado='NO_VERIFICADA', verificada=False, filas_hijas=0,
                  referencias_nulas=0, huerfanas=0, referencias_ambiguas=0,
                  referencias_inactivas=0, muestras_huerfanas=[])
    report['relaciones'].append(result)
    if not objects[child]['lectura_datos_completa'] or not objects[parent]['lectura_datos_completa']:
        result['motivo'] = 'Faltan objetos, campos o una lectura completa.'
        return
    cr, pr = rows[child], rows[parent]
    result['filas_hijas'] = len(cr)
    if not cr:
        result['estado'] = 'SIN_FILAS_HIJAS_NO_VERIFICADA'
        return
    if not pr:
        result['estado'] = 'PADRE_VACIO_NO_VERIFICADA'
    parent_index = _index(pr, pk)
    for row in cr:
        value = row.get(fk)
        if value is None or isinstance(value, str) and not value.strip():
            result['referencias_nulas'] += 1
            continue
        found = parent_index.get(_normalized(value), [])
        if not found:
            result['huerfanas'] += 1
            if len(result['muestras_huerfanas']) < MAX_EXAMPLES:
                result['muestras_huerfanas'].append(_serial(value))
        elif len(found) > 1:
            result['referencias_ambiguas'] += 1
        elif _inactive(found[0]):
            result['referencias_inactivas'] += 1
    for metric, code in [('referencias_nulas', 'FK_SIN_VALOR'), ('huerfanas', 'FK_HUERFANA'),
                         ('referencias_ambiguas', 'FK_AMBIGUA')]:
        if result[metric]:
            _add(report, code, 'La referencia de negocio necesita resolucion antes de cargar.',
                 objeto=child, campo=fk, padre=parent, ocurrencias=result[metric])
    result['verificada'] = bool(pr) and not any(result[k] for k in
        ('referencias_nulas', 'huerfanas', 'referencias_ambiguas'))
    result['estado'] = 'REFERENCIAS_EXISTENTES_VERIFICADAS' if result['verificada'] else 'REFERENCIAS_CON_INCIDENCIAS'
    if result['referencias_inactivas']:
        _add(report, 'FK_A_REGISTRO_INACTIVO', 'La referencia existe pero su padre conserva baja logica.',
             'ADVERTENCIA', objeto=child, campo=fk, padre=parent,
             ocurrencias=result['referencias_inactivas'])


def _crosswalk(report, objects, rows):
    """Correspondencias observadas por FK real, nunca por orden o similitud."""
    p = _index(rows['mline_tc_proyecto'], 'id_proyecto')
    c = _index(rows['mline_td_proyecto_componente'], 'id_proyecto_componente')
    alt = _index(rows['mline_td_proyecto_alternativa'], 'id_proyecto_alternativa')
    inf = _index(rows['mline_td_proyecto_infraestructura'], 'id_proyecto_infraestructura')
    def one(index, key):
        values = index.get(_normalized(key), [])
        return values[0] if len(values) == 1 else None
    for name, pk, _, _ in SPECS[1:]:
        if not objects[name]['lectura_completa']:
            continue
        for row in rows[name][:MAX_REPORT_ROWS]:
            component = alternative = infrastructure = None
            if name == 'mline_td_proyecto_componente':
                component = row
            elif name in {'mline_td_proyecto_alternativa', 'mline_td_proyecto_ltransmision', 'mline_td_proyecto_area_interes'}:
                component = one(c, row.get('id_proyecto_componente'))
                if name == 'mline_td_proyecto_alternativa':
                    alternative = row
            else:
                infrastructure = row if name == 'mline_td_proyecto_infraestructura' else one(inf, row.get('id_proyecto_infraestructura'))
                if infrastructure:
                    alternative = one(alt, infrastructure.get('id_proyecto_alternativa'))
                if alternative:
                    component = one(c, alternative.get('id_proyecto_componente'))
            project = one(p, component.get('id_proyecto')) if component else None
            inherited = project.get('co_proyecto') if project else None
            declared = row.get('proyecto')
            conflict = bool(inherited and declared and _normalized(inherited) != _normalized(declared))
            item = dict(objeto=name, clave=pk, id_observado=row.get(pk) if pk else None,
                        id_proyecto_infraestructura=row.get('id_proyecto_infraestructura'),
                        id_proyecto_componente=component.get('id_proyecto_componente') if component else None,
                        id_proyecto_alternativa=alternative.get('id_proyecto_alternativa') if alternative else None,
                        co_proyecto_por_cadena_fk=inherited, proyecto_declarado=declared,
                        cadena_completa=project is not None, conflicto_proyecto=conflict,
                        ruta_kml=row.get('ruta_kml'), archivo_origen=row.get('archivo_origen'),
                        nombre=row.get('nombre'), confirmada_para_ingesta=False)
            report['correspondencias_destino'].append(_public_row(item))
            if conflict:
                _add(report, 'PROYECTO_DISCREPA_CADENA_FK',
                     'El codigo de la clase difiere del proyecto obtenido por las claves de negocio.',
                     objeto=name, id_observado=row.get(pk) if pk else None,
                     proyecto_declarado=declared, proyecto_por_fk=inherited)


def inspect_business(a, args, model):
    """Inspeccionar siete objetos existentes y devolver solo datos serializables.

    ``args`` contiene workspace/database/owner, como crear_esquema. La lectura
    puede estar completa con clases vacias; eso no resuelve la correspondencia
    de KMZ ni la preservacion de IDs. No recibe fuentes KMZ para evitar proponer
    asociaciones sin evidencia. Los datos de correspondencia son del destino.
    """
    report = dict(estado='NEGOCIO_NO_INSPECCIONADO', modo='SOLO_LECTURA',
                  lectura_completa=False, lectura_datos_completa=False,
                  integridad_observada_sin_incidencias=False,
                  objetos=[], relaciones=[], incidencias=[], correspondencias_destino=[],
                  candidatos_cruce_kmz=[], ingesta_autorizada=False, cambios_en_sde=False,
                  ids_asignados=[], objetos_creados=[],
                  limites=dict(filas_leidas_por_objeto=MAX_SCAN_ROWS,
                               filas_informe_por_objeto=MAX_REPORT_ROWS, longitud_texto=MAX_TEXT),
                  preservacion_ids_origen=dict(estado='NO_VERIFICABLE_SOLO_DESTINO',
                      motivo='Se leen IDs de negocio existentes. Falta contrastarlos con el origen y los KMZ; los maximos no autorizan asignaciones.'),
                  id_analisis_carga_inicial=dict(valor=ID_ANALISIS_CARGA_INICIAL, tipo='TEXT',
                      evidencia='EFT 5.8.7: ejemplo Carga inicial KMZ; 5.8.8: id_analisis reservado para la carga inicial.',
                      tabla_cabecera_requerida_por_esta_regla=False, aplicado=False))
    try:
        if not a.Exists(args.workspace):
            raise ValueError('El workspace de destino no existe.')
        description = a.Describe(args.workspace)
        if args.workspace.lower().endswith('.sde'):
            cp = description.connectionProperties
            if str(cp.database).casefold() != args.database.casefold() or str(getattr(cp, 'user', '')).casefold() != args.owner.casefold():
                raise ValueError('La conexion no coincide con la base y propietario esperados.')
        inventory = engine.find_objects(a, args)
    except Exception as exc:
        _add(report, 'DESTINO_NO_INSPECCIONABLE', str(exc))
        return report
    # El nombre de proyecto aprobado forma parte del contrato del modelo actual.
    if model.get('tabla_proyecto', 'mline_tc_proyecto').casefold() != 'mline_tc_proyecto':
        _add(report, 'MODELO_PROYECTO_NO_ADMITIDO', 'El modelo no identifica la tabla original de proyectos esperada.')
        return report
    model_classes = {c['nombre'].casefold(): c for c in model.get('clases', [])}
    objects, rows = {}, {}
    for name, pk, links, labels in SPECS:
        objects[name], rows[name] = _read_object(a, inventory.get(name), name, pk, links,
                                                labels, model_classes, report)
    for child, fk, parent, pk in LINKS:
        _relationship(report, objects, rows, child, fk, parent, pk)
    for name, _, _, _ in SPECS[3:]:
        _relationship(report, objects, rows, name, 'proyecto', 'mline_tc_proyecto', 'co_proyecto')
    # Una lectura parcial no se utiliza como catalogo de correspondencias.
    if all(obj['lectura_completa'] for obj in objects.values()):
        _crosswalk(report, objects, rows)
    report['lectura_completa'] = all(obj['lectura_completa'] for obj in objects.values())
    report['lectura_datos_completa'] = all(obj['lectura_datos_completa'] for obj in objects.values())
    report['integridad_observada_sin_incidencias'] = report['lectura_completa'] and not any(
        i['nivel'] in {'ERROR', 'PENDIENTE'} for i in report['incidencias'])
    report['estado'] = 'NEGOCIO_INSPECCIONADO_CON_PENDIENTES' if report['lectura_completa'] else 'INSPECCION_NEGOCIO_INCOMPLETA'
    return report
