"""Plan de rutas y reglas de valores. No escribe en KMZ, modelo ni geodatabase.

Los conteos de entidades se toman una vez por ruta y geometria. Los conteos
de atributos y conflictos nunca se suman como si fueran entidades distintas.
La identidad de las fuentes y la asociacion de proyectos se validan fuera de
este modulo antes de usar la evidencia archivada.
"""
from __future__ import annotations

from collections import defaultdict
import csv
from pathlib import Path

import validar_tipos_kmz as validation

HERE = Path(__file__).resolve().parent
NULL_FIELDS = frozenset({
    ('lineas_transmision_existentes_osinergmin_recorte', 'longitud_subterranea'),
    ('lineas_transmision_existentes_osinergmin_recorte', 'maxima_tension_operativa'),
    ('subestacion_poligono', 'src_area_ha'),
})
NULL_RULE = 'MARCADOR_LITERAL_NULL_A_NULO'
GEOMETRY = {'Punto': 'POINT', 'Línea': 'POLYLINE', 'Polígono': 'POLYGON'}
OFFICE_CLASS = 'predios_inscritos_sunarp_recorte'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def basename(value):
    return str(value).replace('\\', '/').rsplit('/', 1)[-1]


def route_key(row):
    return basename(row['archivo']), row['ruta'], row['geometria']


def read_csv(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream, delimiter=';'))


def convert_planned_null(clase, campo, value, spec):
    """Regla exacta y pura: devuelve (valor, regla); no convierte otros textos.

    El par debe estar autorizado, ser DOUBLE nullable y el valor debe ser el
    literal exacto '<Null>'. Ceros, vacios, 'null' y otros campos se conservan.
    Esta funcion no se ejecuta sobre los registros al generar el plan.
    """
    if (clase, campo) not in NULL_FIELDS or value != '<Null>':
        return value, None
    require(spec.get('tipo') == 'DOUBLE' and spec.get('nullable') is True,
            'La regla NULL requiere el campo DOUBLE nullable previsto: ' + clase + '.' + campo)
    return None, NULL_RULE


def null_decision(key, spec, stats):
    markers = stats.get('marcadores', {})
    if key not in NULL_FIELDS or not markers:
        return None
    valid = (spec.get('tipo') == 'DOUBLE' and spec.get('nullable') is True
             and set(markers) == {'<Null>'}
             and markers['<Null>'] == stats.get('validacion_valores', {}).get('marcadores', 0)
             and stats.get('cobertura') == 'COMPLETA_RUTAS_DEL_CAMPO'
             and not stats.get('conflictos'))
    return dict(clase=key[0], campo=key[1], regla=NULL_RULE,
                literal_origen='<Null>', valor_destino=None,
                tipo_destino=spec.get('tipo'), nullable=spec.get('nullable'),
                ocurrencias=int(markers.get('<Null>', 0)),
                otros_marcadores={k: v for k, v in markers.items() if k != '<Null>'},
                estado='DEFINIDA_PARA_PLAN' if valid else 'REGLA_NO_APLICABLE',
                aplicada=False, rutas=stats.get('rutas', []),
                alcance='Solo el literal exacto en este campo. No reemplaza ceros ni otros textos.')


def office_reconciliation(profile, classes):
    """Conservar las dos oficinas sin elegir un valor ni decidir aun el DDL.

    La separacion semantica requiere revisar tambien oficina/oficina_re/
    oficina_1 ya existentes. Una propuesta no justifica columnas duplicadas.
    """
    stats = next((row for row in profile.get('campos_destino', [])
                  if (row['clase'], row['campo']) == (OFFICE_CLASS, 'oficina_registral')), None)
    if not stats or not stats.get('conflictos') or OFFICE_CLASS not in classes:
        return []
    fields = [dict(nombre=f['nombre'], tipo=f['tipo'], longitud=f.get('longitud'),
                   nullable=f.get('nullable'), campos_fuente=f.get('campos_fuente', []))
              for f in classes[OFFICE_CLASS]['campos']
              if f['nombre'] in {'oficina', 'oficina_re', 'oficina_1', 'oficina_registral'}]
    raw = [row for row in profile.get('campos_fuente', [])
           if row.get('clase_destino') == OFFICE_CLASS and row.get('campo_destino') in
           {'oficina', 'oficina_re', 'oficina_1', 'oficina_registral'}]
    evidence = [dict(archivo=row['archivo'], ruta=row['ruta'], geometria=row['geometria'],
                     campo_original=row['campo_original'], ocurrencia=row.get('ocurrencia'),
                     canal=row.get('canal'), campo_destino_actual=row['campo_destino'],
                     registros=row.get('registros', 0), ejemplos=row.get('ejemplos', []))
                for row in raw]
    current = next(f for f in fields if f['nombre'] == 'oficina_registral')
    proposed = []
    for name, occurrence, context in [
        ('oficina_registral_inmueble', 1, ['PARTIDA REGISTRAL', 'ANTECEDENTE REGISTRAL']),
        ('oficina_registral_persona_juridica', 2, ['PARTIDA JURÍDICA', 'JUNTA DIRECTIVA']),
    ]:
        proposed.append(dict(nombre_propuesto=name, tipo=current['tipo'],
            longitud=current['longitud'], nullable=current['nullable'],
            campo_original='OFICINA REGISTRAL', ocurrencia=occurrence, canal='HTML',
            contexto_a_verificar=context,
            operacion_fisica='POR_DEFINIR_TRAS_RECONCILIAR_CAMPOS_EXISTENTES'))
    return [dict(codigo='RECONCILIAR_ATRIBUTOS_OFICINA', clase=OFFICE_CLASS,
        operacion='RECONCILIAR_ATRIBUTOS_OFICINA',
        estado='PROPUESTA_CONSERVACION_ATRIBUTOS',
        requisito='REQUIERE_AJUSTE_ESQUEMA_Y_MAPEO',
        siguiente_control='VERIFICAR_FUENTES_EXISTENTES_ANTES_DE_MIGRACION_FISICA',
        fundamento_eft=dict(seccion='5.8.7 Campos comunes / Atributos propios',
            extractos=['Cada capa conserva todos sus atributos',
                       'Los nombres se unifican con una tabla de equivalencias']),
        motivo='Conservar por separado las dos ocurrencias. No seleccionar una ni concatenar sus valores.',
        campos_actuales_a_reconciliar=fields, campos_semanticos_propuestos=proposed,
        evidencia_fuentes=evidence, rutas=stats.get('rutas', []),
        registros_perfilados=stats['registros'], registros_conflictivos=stats['conflictos'],
        aprobado_ddl=False, aplicado=False, tipos_pendientes_nuevos=0,
        cambios_en_modelo=False, cambios_en_sde=False,
        criterio_implementacion='Reutilizar o renombrar campos existentes si la equivalencia se demuestra; agregar solo lo necesario para conservar ambos atributos sin colisiones. La operacion fisica no se decide en esta prevalidacion.')]


def build_plan(profile, model, model_dir=None, *, catalog=None, field_mappings=None):
    """Construye un plan diagnosticable; nunca declara autorizada la ingesta.

    profile es el objeto envelope['perfil'], no una muestra. El llamador debe
    comprobar los hashes de todos los KMZ antes de reutilizarlo. catalog y
    field_mappings opcionales permiten ensayos con referencias controladas.
    """
    model_dir = Path(model_dir or HERE)
    if catalog is None:
        catalog = read_csv(model_dir / 'mapeo_capas_revision.csv')
    if field_mappings is None:
        field_mappings = read_csv(model_dir / 'campos_por_ruta.csv')
    expected = {route_key(row): row for row in catalog}
    observed = {route_key(row): row for row in profile['rutas']}
    require(len(expected) == len(catalog), 'Catalogo de rutas duplicado; no se elige una fila.')
    require(len(observed) == len(profile['rutas']), 'Perfil con rutas duplicadas; evita contar entidades dos veces.')
    require(set(expected) == set(observed), 'El perfil y el catalogo no tienen las mismas rutas esperadas.')
    classes = {row['nombre']: row for row in model['clases']}
    require(len(classes) == len(model['clases']), 'Modelo con nombres de clases duplicados.')
    specs = {(c['nombre'], f['nombre']): f for c in model['clases'] for f in c['campos']}
    maps = defaultdict(list)
    for row in field_mappings:
        key = route_key(row)
        require(key in expected, 'Mapeo de campo fuera del catalogo: ' + repr(key))
        dest = row.get('clase_destino', ''), row.get('campo_destino', '')
        if all(dest):
            require(dest in specs, 'Campo de destino inexistente en el modelo: ' + '.'.join(dest))
            require(dest[0] == expected[key].get('clase_propuesta', ''),
                    'Clase de campo distinta del destino de ruta: ' + repr(key))
        maps[key].append(row)

    field_issues, null_rules, checks = [], [], []
    route_issues, route_rules = defaultdict(set), defaultdict(set)
    seen_fields = set()
    for stats in profile.get('campos_destino', []):
        key = stats['clase'], stats['campo']
        require(key not in seen_fields, 'Perfil de campo duplicado: ' + '.'.join(key))
        seen_fields.add(key)
        require(key in specs, 'Perfil para un campo ajeno al modelo: ' + '.'.join(key))
        checked = validation.evaluate_field(specs[key], stats)
        remaining = list(checked['incidencias'])
        decision = null_decision(key, specs[key], stats)
        resolved = []
        if decision:
            null_rules.append(decision)
            if decision['estado'] == 'DEFINIDA_PARA_PLAN':
                if 'MARCADORES_REQUIEREN_REGLA_NULL' in remaining:
                    remaining.remove('MARCADORES_REQUIEREN_REGLA_NULL')
                    resolved.append('MARCADORES_REQUIEREN_REGLA_NULL')
                for route in stats.get('rutas', []):
                    route_rules[route_key(route)].add('.'.join(key))
        item = dict(clase=key[0], campo=key[1], tipo_destino=specs[key]['tipo'],
                    registros_perfilados=stats.get('registros', 0),
                    valores_perfilados=sum(stats.get('validacion_valores', {}).get(n, 0)
                                          for n in ('utiles', 'vacios', 'marcadores')),
                    registros_conflictivos=stats.get('conflictos', 0),
                    incidencias=remaining, incidencias_resueltas_por_regla_del_plan=resolved,
                    incidencias_declaracion_origen=checked.get('incidencias_declaracion_origen', []),
                    rutas=stats.get('rutas', []), cambios_en_datos=False)
        checks.append(item)
        if remaining:
            field_issues.append(item)
            for route in stats.get('rutas', []):
                route_issues[route_key(route)].update(remaining)

    source_issues = []
    for issue in profile.get('incidencias', []):
        item = dict(issue)
        key = route_key(issue['ruta']) if issue.get('ruta') else None
        mapped = bool(key in expected and expected[key].get('clase_propuesta'))
        code = issue['codigo']
        if code == 'CONTENEDOR_XML_SIN_DESTINO':
            item.update(nivel='OBSERVACION', requiere_decision=False,
                        motivo='El contenedor HTML presenta atributos interiores; no se agrega como columna.')
        elif code == 'OBJETO_NO_PLACEMARK':
            item.update(nivel='OBSERVACION', requiere_decision=False,
                        motivo='Objeto KML fuera del conteo de Placemarks; se conserva en el informe.')
        else:
            item.update(nivel='PENDIENTE', requiere_decision=True,
                        motivo='Revisar la correspondencia o el valor sin descartar contenido de la fuente.')
            if mapped:
                route_issues[key].add(code)
        item['ruta_con_destino'] = mapped
        source_issues.append(item)
    # Las declaraciones de origen siguen siendo evidencia, aunque TEXT sea
    # una capacidad fisica valida. No confundir su cierre con resolver el dato.
    for raw in profile.get('campos_fuente', []):
        checked = validation.evaluate_source_declaration(raw)
        if checked['incidencias_tipo_origen']:
            key = route_key(raw)
            mapped = bool(key in expected and expected[key].get('clase_propuesta'))
            source_issues.append(dict(codigo='DECLARACION_TIPO_ORIGEN',
                ruta=dict(archivo=raw['archivo'], ruta=raw['ruta'], geometria=raw['geometria']),
                campo_original=raw['campo_original'], canal=raw.get('canal'),
                ocurrencia=raw.get('ocurrencia'), incidencias=checked['incidencias_tipo_origen'],
                detalle_tipos_origen=checked['detalle_tipos_origen'],
                nivel='PENDIENTE', requiere_decision=True,
                ruta_con_destino=mapped,
                motivo='Conservar el valor y decidir su lectura; no se modifica el tipo confirmado.'))
            if mapped:
                route_issues[key].add('DECLARACION_TIPO_ORIGEN')

    rows, common = [], {}
    for key, route in sorted(observed.items()):
        entry = expected[key]
        destination = entry.get('clase_propuesta', '')
        require(route.get('clase', '') == destination, 'El destino de una ruta difiere entre perfil y catalogo.')
        require(int(route['esperados']) == int(entry['elementos']), 'El conteo esperado difiere del catalogo.')
        count = int(route['observados'])
        require(count >= 0, 'Conteo de entidades negativo.')
        issues = set(route_issues[key])
        geometry = dataset = ''
        missing_required = []
        mapped_fields = sorted({r['campo_destino'] for r in maps[key] if r.get('campo_destino')})
        if destination:
            require(destination in classes, 'Clase de ruta inexistente: ' + destination)
            cls = classes[destination]
            geometry, dataset = cls['geometria'], cls['dataset']
            if GEOMETRY.get(key[2]) != geometry:
                issues.add('GEOMETRIA_INCOMPATIBLE')
            for spec in cls['campos']:
                if not spec.get('nullable', True) and spec['nombre'] not in mapped_fields:
                    name = spec['nombre']
                    missing_required.append(name)
                    common[(destination, name)] = dict(clase=destination, campo=name,
                        tipo=spec['tipo'], nullable=False, origen=spec.get('origen', ''),
                        estado='REGLA_DE_CARGA_PENDIENTE',
                        motivo='Definir su valor o generacion y comprobar sus referencias antes de insertar.')
        else:
            issues.add('RUTA_SIN_DESTINO')
        coverage_matches = route['estado'] == 'COINCIDE' or (
            not destination and route['estado'] == 'SIN_DESTINO_COINCIDE')
        if not coverage_matches or count != int(route['esperados']):
            issues.add('COBERTURA_RUTA_INCOMPLETA')
        if missing_required:
            issues.add('CAMPOS_OBLIGATORIOS_SIN_REGLA_DE_CARGA')
        rows.append(dict(archivo=key[0], ruta=key[1], geometria=key[2],
            clase_destino=destination, dataset_destino=dataset, geometria_destino=geometry,
            descripcion=entry.get('descripcion', ''), elementos=count,
            elementos_esperados=int(route['esperados']), estado_cobertura=route['estado'],
            estado_plan='DESTINO_PENDIENTE' if not destination else 'PREPARACION_PENDIENTE',
            incidencias=sorted(issues), reglas_null=sorted(route_rules[key]),
            campos_mapeados=mapped_fields, campos_obligatorios_por_definir=sorted(missing_required),
            co_proyecto='', proyecto_confirmado=False,
            autorizada_para_carga=False))
    extras = profile.get('rutas_no_inventariadas', [])
    extra_keys = [route_key(row) for row in extras]
    require(len(extra_keys) == len(set(extra_keys)), 'Rutas extra duplicadas en el perfil.')
    require(not set(extra_keys) & set(expected), 'Una ruta extra tambien figura en el catalogo.')
    for extra in extras:
        require(int(extra['observados']) >= 0, 'Conteo de entidades negativo en ruta extra.')
        rows.append(dict(archivo=basename(extra['archivo']), ruta=extra['ruta'], geometria=extra['geometria'],
            clase_destino='', dataset_destino='', geometria_destino='', descripcion='',
            elementos=int(extra['observados']), elementos_esperados=0,
            estado_cobertura='NO_INVENTARIADA', estado_plan='DESTINO_PENDIENTE',
            incidencias=['RUTA_NO_INVENTARIADA'], reglas_null=[], campos_mapeados=[],
            campos_obligatorios_por_definir=[], co_proyecto='', proyecto_confirmado=False,
            autorizada_para_carga=False))
    counts = dict(rutas=len(rows), rutas_inventariadas=len(observed), rutas_no_inventariadas=len(extras),
        elementos=sum(row['elementos'] for row in rows),
        rutas_con_destino=sum(bool(row['clase_destino']) for row in rows),
        rutas_sin_destino=sum(not row['clase_destino'] for row in rows),
        elementos_con_destino=sum(row['elementos'] for row in rows if row['clase_destino']),
        elementos_sin_destino=sum(row['elementos'] for row in rows if not row['clase_destino']),
        campos_con_incidencias=len(field_issues),
        reglas_null_definidas=sum(row['estado'] == 'DEFINIDA_PARA_PLAN' for row in null_rules),
        ocurrencias_null_con_regla=sum(row['ocurrencias'] for row in null_rules if row['estado'] == 'DEFINIDA_PARA_PLAN'),
        campos_obligatorios_con_regla_pendiente=len(common),
        observaciones_fuente=len(source_issues))
    if 'elementos_observados' in profile.get('conteos', {}):
        require(counts['elementos'] == profile['conteos']['elementos_observados'],
                'El total por rutas no coincide con los Placemarks observados; no se publica un conteo ambiguo.')
    grouped = defaultdict(list)
    for row in rows:
        if row['clase_destino']:
            grouped[row['clase_destino']].append(row)
    class_summary = [dict(clase=name, dataset=classes[name]['dataset'],
        geometria=classes[name]['geometria'], rutas=len(grouped[name]),
        elementos=sum(row['elementos'] for row in grouped[name]),
        archivos=sorted({row['archivo'] for row in grouped[name]}),
        estado='PREPARACION_PENDIENTE', autorizada_para_carga=False)
        for name in sorted(classes)]
    return dict(estado='PLAN_INGESTA_CON_PENDIENTES', rutas=rows,
        resumen_clases=class_summary, reglas_null=null_rules, campos_verificados=checks,
        incidencias_campos=field_issues, incidencias_fuente=source_issues,
        pendientes_campos_comunes=[common[key] for key in sorted(common)], resumen=counts,
        ajustes_esquema_propuestos=office_reconciliation(profile, classes),
        ingesta_autorizada=False, cambios_en_modelo=False, cambios_en_sde=False,
        alcance='Conteos de Placemarks por ruta y geometria. No comprueba aun reparacion geometrica, duplicados entre KMZ ni reglas completas de carga.')
