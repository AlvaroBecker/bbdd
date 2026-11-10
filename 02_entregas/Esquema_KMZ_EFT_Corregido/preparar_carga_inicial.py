"""Preparación 1.13: reglas ejecutables y revisión de cobertura/negocio; solo lectura GIS."""
from __future__ import annotations

import copy
import datetime as dt
import json
import os
from pathlib import Path
from types import SimpleNamespace
import uuid

import prevalidar_ingesta as previous
import plan_ingesta
import proyectos_ingesta
import fuentes_ingesta
import validar_tipos_kmz as validation
import reglas_sunarp_ingesta as sunarp
import cobertura_ingesta
import inspeccionar_negocio_ingesta as business
import descripciones_ingesta

HERE = Path(__file__).resolve().parent
INITIAL_ANALYSIS = 'Carga inicial KMZ'
NEW_REFERENCES = ('preparar_carga_inicial.py', 'reglas_sunarp_ingesta.py',
    'reglas_sunarp_1_13.json', 'cobertura_ingesta.py', 'reglas_cobertura_1_13.json',
    'inspeccionar_negocio_ingesta.py', 'descripciones_ingesta.py', 'descripciones_1_13.json',
    'confirmar_proyectos_13_confirmados.csv')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def reference_hashes(base):
    result = previous.reference_hashes(base)
    result.update({name: validation.digest(base / name) for name in NEW_REFERENCES})
    return result


def common_rules(plan, projects, model, sources_verified):
    """Asigna las dos reglas ya fundamentadas; mantiene identidades de negocio pendientes."""
    result = copy.deepcopy(plan)
    associations = {r['archivo_kmz']: r for r in projects.get('asociaciones', [])}
    require(len(associations) == len(projects.get('asociaciones', [])), 'Asociaciones duplicadas.')
    specs = {(c['nombre'], f['nombre']): f for c in model['clases'] for f in c['campos']}
    resolved, pending = [], []
    for field in result['pendientes_campos_comunes']:
        item = dict(field)
        spec = specs[item['clase'], item['campo']]
        if item['campo'] == 'id_analisis':
            require(spec['tipo'] == 'TEXT' and spec.get('longitud', 0) >= len(INITIAL_ANALYSIS)
                    and spec.get('nullable') is False, 'Definicion incompatible de id_analisis.')
            item.update(regla='VALOR_RESERVADO_CARGA_INICIAL_EFT', valor=INITIAL_ANALYSIS,
                fundamento='EFT: campo Texto de analisis y ejemplo Carga inicial KMZ.',
                estado='REGLA_DEFINIDA', aplicada=False)
            resolved.append(item)
        elif item['campo'] == 'proyecto' and projects.get('verificado') and sources_verified:
            require(spec['tipo'] == 'TEXT' and spec.get('longitud', 0) >= 12,
                    'Definicion incompatible de proyecto.')
            item.update(regla='ASOCIACION_KMZ_PROYECTO_CONFIRMADA',
                estado='REGLA_DEFINIDA', aplicada=False)
            resolved.append(item)
        else:
            pending.append(item)
    resolved_keys = {(r['clase'], r['campo']) for r in resolved}
    for row in result['rutas']:
        association = associations.get(row['archivo'], {})
        confirmed = bool(association.get('confirmado') and sources_verified)
        row.update(proyecto_confirmado=confirmed,
            co_proyecto=association.get('co_proyecto', '') if confirmed else '',
            id_analisis=INITIAL_ANALYSIS,
            evidencia_actual_verificada=bool(sources_verified),
            cargable=False, autorizada_para_carga=False)
        row['campos_obligatorios_por_definir'] = [f for f in row['campos_obligatorios_por_definir']
            if (row['clase_destino'], f) not in resolved_keys]
        if not row['campos_obligatorios_por_definir']:
            row['incidencias'] = [v for v in row['incidencias']
                if v != 'CAMPOS_OBLIGATORIOS_SIN_REGLA_DE_CARGA']
        if not sources_verified:
            row['incidencias'].append('FUENTES_ACTUALES_NO_VERIFICADAS')
    result['reglas_campos_comunes'] = resolved
    result['pendientes_campos_comunes'] = pending
    result['resumen']['campos_obligatorios_con_regla_pendiente'] = len(pending)
    result['resumen']['campos_obligatorios_con_regla_definida'] = len(resolved)
    return result


def write_reports(folder, report):
    report['archivo_resultado'] = str(folder / 'resultado.json')
    report['archivo_informe'] = str(folder / 'informe.txt')
    plan = report.get('plan', {})
    coverage = report.get('cobertura', {})
    desc = report.get('descripciones', {})
    outputs = {
        'reglas_campos_comunes.csv': plan.get('reglas_campos_comunes', []),
        'identidades_pendientes.csv': plan.get('pendientes_campos_comunes', []),
        'rutas_carga_inicial.csv': plan.get('rutas', []),
        'mapeo_revisable.csv': coverage.get('rutas', []),
        'descripciones.csv': desc.get('rutas', []),
        'asociaciones_proyecto.csv': report.get('proyectos', {}).get('asociaciones', []),
        'incidencias_negocio.csv': report.get('negocio', {}).get('incidencias', []),
    }
    for name, rows in outputs.items():
        validation.csv_rows(folder / name, rows)
    report['archivos_csv'] = {name: str(folder / name) for name in outputs}
    with (folder / 'resultado.json').open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    summary = plan.get('resumen', {})
    text = [
        'PREPARACION DE CARGA INICIAL KMZ 1.13', '', 'Estado: ' + report['estado'], '',
        'Esta herramienta escribe informes. No crea clases, no modifica campos y no inserta registros.',
        'Las propuestas de cobertura no son cambios ya aplicados en la SDE.', '',
        'Fuentes actuales verificadas: ' + str(report.get('fuentes', {}).get('verificado', False)),
        'Proyectos verificados: ' + str(report.get('proyectos', {}).get('verificado', False)),
        'Reglas de campos obligatorios definidas: ' + str(summary.get('campos_obligatorios_con_regla_definida', 0)),
        'Reglas de identidad de negocio pendientes: ' + str(summary.get('campos_obligatorios_con_regla_pendiente', 0)),
        'Lectura de negocio: ' + str(report.get('negocio', {}).get('estado', 'NO_REALIZADA')), '',
        'REGLAS DE LA VERSION (SU VERIFICACION DEPENDE DEL RESULTADO)',
        'id_analisis: Carga inicial KMZ. proyecto: catalogo y CSV confirmado; vea reglas_campos_comunes.csv.',
        'Reglas SUNARP verificadas en esta ejecucion: ' + str(bool(report.get('sunarp'))),
        'La version propone separar las oficinas SUNARP en oficina_registral y oficina_1, ya existentes.',
        'La segunda oficina requiere la ruta, ocurrencia, contexto y fuente exactos de las reglas incluidas.',
        'El cierre de tipos y el modelo 12 permanecen intactos.', '',
        'REVISION DEL RESULTADO',
        'mapeo_revisable.csv separa destino actual, propuesta sustentada y tratamiento especial.',
        'Vanos y otros nuevos destinos figuran como propuestas; no se crean automaticamente.',
        'No se equipara una carpeta Section de PLS-CADD con un vano. Copias/CAD siguen la excepcion del EFT.',
        'descripciones.csv diferencia contenido ya representado en atributos y contenido que aun debe mapearse.',
        'negocio en resultado.json muestra los padres, claves, filas necesarias y relaciones leidas en destino.',
        'Un maximo de ID es informativo: no reserva codigos ni identifica por si mismo el padre de un vertice.', '',
        'Ninguna ruta queda autorizada para cargar: falta cerrar cobertura y correspondencias de negocio.',
        'Las lecturas no certifican branch, publicacion de servicios ni reparacion de geometria.',
    ]
    if report.get('error'):
        text += ['', 'ERROR: ' + report['error']]
    (folder / 'informe.txt').write_text('\n'.join(text) + '\n', encoding='utf-8')


def reconcile_plan_issues(plan, rules, descriptions, sources_verified):
    """Cierra solo las incidencias cuya correspondencia tiene evidencia exacta.

Se conserva el diagnóstico original del perfil y la regla que lo sustituye.
Resolver una correspondencia no equivale a verificar una inserción.
"""
    plan['resoluciones_incidencias'] = []
    if not sources_verified:
        return
    office_keys = {(r['archivo'], r['ruta'], r['geometria']) for r in rules['equivalencias']
        if r['cambio_de_mapeo'] and r['ocurrencia'] == 2}
    description_keys = {(r['archivo'], r['ruta'], r['geometria']) for r in descriptions['rutas']
        if r['estado_efectivo'] == 'CONTENIDO_EN_ATRIBUTOS_MAS_REGLAS_SISTEMA'}
    for issue in plan['incidencias_fuente']:
        route = issue.get('ruta') or {}
        key = (route.get('archivo'), route.get('ruta'), route.get('geometria'))
        rule = None
        if key in office_keys and issue.get('codigo') == 'VALORES_CONFLICTIVOS':
            # El perfil identifica el campo; no resolver cualquier conflicto de la ruta.
            if issue.get('detalle') == 'predios_inscritos_sunarp_recorte.oficina_registral':
                rule = 'SUNARP_DOS_ROLES_EN_CAMPOS_EXISTENTES'
        elif (key in description_keys and issue.get('codigo') == 'ATRIBUTO_SIN_MAPEO'
                and issue.get('detalle') == 'description'):
            rule = 'DESCRIPTION_YA_REPRESENTADA_EN_ATRIBUTOS'
        if rule:
            issue.update(requiere_decision=False, nivel='RESUELTO_EN_PLAN', regla=rule,
                motivo='Correspondencia sustentada en fuentes identicas; no se han insertado valores.')
            plan['resoluciones_incidencias'].append(dict(ruta=route, codigo=issue['codigo'], regla=rule))
    for item in plan['campos_verificados']:
        if (item['clase'], item['campo']) == ('predios_inscritos_sunarp_recorte', 'oficina_registral'):
            require(item['registros_conflictivos'] == rules['evidencia']['distintos'],
                    'La evidencia de conflictos SUNARP cambio.')
            if 'CONFLICTO_MAPEO_VALORES' in item['incidencias']:
                item['incidencias'].remove('CONFLICTO_MAPEO_VALORES')
                item['incidencias_resueltas_por_regla_del_plan'].append('CONFLICTO_MAPEO_VALORES')
                item['regla_resolucion'] = 'SUNARP_DOS_ROLES_EN_CAMPOS_EXISTENTES'
    plan['incidencias_campos'] = [r for r in plan['campos_verificados'] if r['incidencias']]
    plan['resumen']['campos_con_incidencias'] = len(plan['incidencias_campos'])
    # Recalcular los códigos de ruta sin suprimir otras incidencias del mismo código.
    for row in plan['rutas']:
        key = row['archivo'], row['ruta'], row['geometria']
        remaining_source = {i['codigo'] for i in plan['incidencias_fuente']
            if i.get('requiere_decision') and i.get('ruta')
            and plan_ingesta.route_key(i['ruta']) == key}
        if key in office_keys:
            row['incidencias'] = [i for i in row['incidencias']
                if i != 'CONFLICTO_MAPEO_VALORES' and (i != 'VALORES_CONFLICTIVOS' or i in remaining_source)]
        if key in description_keys and 'ATRIBUTO_SIN_MAPEO' not in remaining_source:
            row['incidencias'] = [i for i in row['incidencias'] if i != 'ATRIBUTO_SIN_MAPEO']


def run(workspace, kmz_dir, project_csv=None, database='ArcGisAWS', owner='gis',
        reports=None, arcpy_module=None, emit=print, model_dir=None):
    base = Path(model_dir or HERE).resolve()
    parent = Path(reports or base).resolve()
    require(parent.is_dir(), 'La carpeta de informes debe existir.')
    require(not any(p.suffix.lower() == '.gdb' for p in (parent,) + tuple(parent.parents)),
            'Los informes deben guardarse fuera de una geodatabase.')
    folder = parent / ('Carga_Inicial_' + dt.datetime.now().strftime('%Y%m%d_%H%M%S_') + uuid.uuid4().hex[:12])
    folder.mkdir(exist_ok=False)
    report = dict(version_paquete='1.13', estado='ERROR_DETENIDO', modo='SOLO_LECTURA',
        inicio_utc=dt.datetime.now(dt.timezone.utc).isoformat(), workspace=str(workspace),
        carpeta_kmz=str(kmz_dir), database=database, owner=owner, ingesta_autorizada=False,
        cambios_en_sde=False, cambios_en_modelo=False, registros_insertados=0)
    emit('Informe: ' + str(folder))
    failure = None
    try:
        require(workspace, 'Indique la conexion/geodatabase existente.')
        require(kmz_dir and Path(kmz_dir).is_dir(), 'Indique la carpeta raiz de los 13 KMZ.')
        before = reference_hashes(base)
        selected_csv = Path(project_csv or base / 'confirmar_proyectos_13_confirmados.csv').resolve()
        csv_hash = validation.digest(selected_csv)
        report.update(referencias_sha256=before, proyectos_csv=str(selected_csv), proyectos_csv_sha256=csv_hash)
        model = validation.validated_model(base, json.loads((base / 'esquema.json').read_text(encoding='utf-8-sig')))
        require(model['version'] == 12, 'Se requiere el modelo cerrado 12; esta herramienta no lo modifica.')
        envelope, fingerprint = validation.read_profile_snapshot(base)
        profile = envelope['perfil']
        report['perfil_sha256'] = fingerprint
        sources = fuentes_ingesta.discover_sources(kmz_dir, profile['fuentes'], emit=emit)
        report['fuentes'] = sources
        if arcpy_module is None:
            import arcpy as arcpy_module
        readonly = previous.ReadOnlyArcPy(arcpy_module)
        destination, catalog = previous.inspect_live(readonly, workspace, database, owner, model, emit)
        report.update(destino=destination, catalogo_proyectos=catalog)
        projects = proyectos_ingesta.plan_projects(profile['fuentes'], catalog, mapping_csv=selected_csv)
        report['proyectos'] = projects
        plan = common_rules(plan_ingesta.build_plan(profile, model, model_dir=base),
                            projects, model, sources['verificado'])
        # Sustituir expresamente la propuesta antigua de DDL SUNARP por equivalencias sin DDL.
        plan['ajustes_esquema_propuestos'] = [r for r in plan.get('ajustes_esquema_propuestos', [])
            if not (r.get('clase') == 'predios_inscritos_sunarp_recorte'
                    and r.get('codigo') == 'RECONCILIAR_ATRIBUTOS_OFICINA')]
        report['plan'] = plan
        rules = sunarp.load_rules(base / 'reglas_sunarp_1_13.json')
        checked = sunarp.validate_references(rules, base_dir=base)
        report['sunarp'] = dict(validacion=checked, reglas=rules,
            evidencia_actual_verificada=bool(sources['verificado']), cambios_ddl=0,
            resolucion='Separacion de roles en campos existentes; resolve_record comprueba cada registro.',
            aplicada=False)
        report['cobertura'] = cobertura_ingesta.generar_plan(base=base)
        report['descripciones'] = descripciones_ingesta.load_plan(base,
            current_sources_verified=sources['verificado'])
        reconcile_plan_issues(plan, rules, report['descripciones'], sources['verificado'])
        args = SimpleNamespace(workspace=os.path.abspath(workspace), database=database, owner=owner, aplicar=False)
        report['negocio'] = business.inspect_business(readonly, args, model)
        for row in report['cobertura'].get('rutas', []):
            row['evidencia_actual_verificada'] = bool(sources['verificado'])
        # Relectura: no publicar como actuales referencias, fuentes o identidades que cambiaron.
        require(business.inspect_business(readonly, args, model) == report['negocio'],
                'Las claves de negocio cambiaron durante la lectura; repita la preparacion.')
        require(fuentes_ingesta.discover_sources(kmz_dir, profile['fuentes'], emit=lambda _: None) == sources,
                'Los KMZ cambiaron durante la preparacion.')
        require(reference_hashes(base) == before, 'Las referencias cambiaron durante la preparacion.')
        require(validation.digest(selected_csv) == csv_hash, 'El CSV de proyectos cambio durante la lectura.')
        structural_issues = [i for i in destination['incidencias_preingesta'] if i['motivo'] != 'DESTINO_CON_REGISTROS']
        complete = bool(sources['verificado'] and projects['verificado'] and destination['verificado']
            and destination['recuentos_completos'] and not structural_issues
            and report['negocio'].get('lectura_completa'))
        report['comprobaciones_lectura_completas'] = complete
        report['estado'] = 'PREPARACION_CON_PENDIENTES' if complete else 'PREPARACION_INCOMPLETA'
        report['version_modelo'] = model['version']
        emit('REGLAS: ' + str(len(plan['reglas_campos_comunes'])) + ' definidas; '
             + str(len(plan['pendientes_campos_comunes'])) + ' identidades pendientes.')
        emit('NEGOCIO: ' + report['negocio']['estado'])
    except Exception as exc:
        failure = exc
        report['error'] = str(exc)
    report['fin_utc'] = dt.datetime.now(dt.timezone.utc).isoformat()
    write_reports(folder, report)
    emit('Estado: ' + report['estado'])
    emit('Resultado JSON: ' + report['archivo_resultado'])
    if failure is not None:
        raise failure
    return folder, report
