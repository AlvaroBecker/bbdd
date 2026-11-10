"""Plan de ingesta 1.10: fuentes actuales, proyectos y rutas; ninguna escritura GIS."""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
from types import SimpleNamespace
import uuid

import datos_proyecto as runner
import validar_tipos_kmz as validation
import fuentes_ingesta
import proyectos_ingesta
import plan_ingesta

HERE = Path(__file__).resolve().parent
require = runner.engine.require
NEW_REFERENCES = ('prevalidar_ingesta.py', 'fuentes_ingesta.py',
                  'proyectos_ingesta.py', 'plan_ingesta.py')


class ReadOnlyArcPy(validation.ReadOnlyArcPy):
    """Solo amplía la fachada de lectura con cursores de consulta y recuentos."""
    def __init__(self, wrapped):
        super().__init__(wrapped)
        self.da = SimpleNamespace(ListDomains=wrapped.da.ListDomains,
                                  SearchCursor=wrapped.da.SearchCursor)
        self.management = SimpleNamespace(GetCount=wrapped.management.GetCount)


def reference_hashes(model_dir):
    result = validation.input_hashes(model_dir)
    for name in NEW_REFERENCES + ('PERFIL_COMPLETO_KMZ_1_9.json',
                                  'PERFIL_COMPLETO_KMZ_1_9.sha256'):
        result[name] = validation.digest(model_dir / name)
    return result


def inspect_live(arcpy_module, workspace, database, owner, model, emit=print):
    """Comprueba el modelo cerrado y consulta el catálogo real, nunca lo crea."""
    a = ReadOnlyArcPy(arcpy_module)
    destination = validation.inspect_destination(a, workspace, database, owner, model)
    args = SimpleNamespace(workspace=os.path.abspath(workspace), database=database,
                           owner=owner, aplicar=False)
    inventory, _ = runner.engine.inspect(a, args, model, [])
    parent = inventory.get(model['tabla_proyecto'].casefold())
    catalog = proyectos_ingesta.read_projects(a, parent, model)
    counts, issues = [], []
    with a.EnvManager(overwriteOutput=False, extent=None):
        for cls in model['clases']:
            path = inventory.get(cls['nombre'].casefold())
            row = dict(clase=cls['nombre'], ruta=path, registros=None,
                       campos_ajenos=[], relaciones_observadas=[], versionada=None)
            try:
                require(path, 'No se encuentra la clase.')
                description = a.Describe(path)
                row['registros'] = int(a.management.GetCount(path).getOutput(0))
                row['campos_ajenos'] = runner.unexpected_fields(a.ListFields(path), description, cls)
                row['relaciones_observadas'] = list(getattr(description, 'relationshipClassNames', []) or [])
                row['versionada'] = bool(getattr(description, 'isVersioned', False))
                if row['registros']:
                    issues.append(dict(clase=cls['nombre'], motivo='DESTINO_CON_REGISTROS',
                        detalle='Definir una estrategia de carga y duplicados antes de insertar.',
                        registros=row['registros']))
                if row['campos_ajenos']:
                    issues.append(dict(clase=cls['nombre'], motivo='CAMPOS_FUERA_MODELO',
                        detalle=', '.join(row['campos_ajenos'])))
            except Exception as exc:
                issues.append(dict(clase=cls['nombre'], motivo='DESTINO_NO_LEIDO', detalle=str(exc)))
            counts.append(row)
    destination.update(recuentos=counts, incidencias_preingesta=issues,
        registros_existentes=sum(r['registros'] or 0 for r in counts),
        recuentos_completos=all(r['registros'] is not None for r in counts),
        relaciones_proyecto_certificadas=False)
    emit(f"DESTINO: {destination['campos_verificados']}/3340 campos; "
         f"{sum(r['registros'] is not None for r in counts)}/76 clases contadas.")
    return destination, catalog


def enrich_routes(plan, project_plan):
    associations = {r['archivo_kmz']: r for r in project_plan.get('asociaciones', [])}
    for row in plan['rutas']:
        association = associations.get(row['archivo'], {})
        row['co_proyecto'] = (association.get('co_proyecto') or '') if association.get('confirmado') else ''
        row['proyecto_confirmado'] = bool(association.get('confirmado'))
        row['estado_proyecto'] = association.get('estado', 'SIN_ASOCIACION')
        row['candidatos_proyecto'] = association.get('candidatos', [])
        row['cargable'] = False


def write_reports(folder, report):
    folder.mkdir(parents=True, exist_ok=False)
    report['archivo_resultado'] = str(folder / 'resultado.json')
    report['archivo_informe'] = str(folder / 'informe.md')
    sources, projects, plan = (report.get('fuentes', {}), report.get('proyectos', {}),
                               report.get('plan', {}))
    outputs = {
        'fuentes_kmz.csv': sources.get('inventario', []),
        'correspondencia_kmz.csv': sources.get('fuentes', []),
        'catalogo_proyectos.csv': report.get('catalogo_proyectos', {}).get('filas', []),
        'asociaciones_proyecto.csv': projects.get('asociaciones', []),
        'confirmar_proyectos.csv': projects.get('plantilla_csv', []),
        'plan_rutas.csv': plan.get('rutas', []),
        'rutas_sin_destino.csv': [r for r in plan.get('rutas', []) if not r['clase_destino']],
        'resumen_clases.csv': plan.get('resumen_clases', []),
        'reglas_valores.csv': plan.get('reglas_null', []),
        'ajustes_esquema_propuestos.csv': plan.get('ajustes_esquema_propuestos', []),
        'campos_obligatorios.csv': plan.get('pendientes_campos_comunes', []),
        'incidencias.csv': report.get('incidencias', []),
        'campos_destino.csv': (report.get('destino') or {}).get('campos', []),
        'recuentos_destino.csv': (report.get('destino') or {}).get('recuentos', []),
    }
    for name, rows in outputs.items():
        columns = ['archivo_kmz', 'co_proyecto', 'confirmado'] if name == 'confirmar_proyectos.csv' else None
        validation.csv_rows(folder / name, rows, columns)
    report['archivos_csv'] = {name: str(folder / name) for name in outputs}
    lines = ['# Prevalidación de ingesta 1.10', '', f"Estado: **{report['estado']}**", '',
        'Esta ejecución genera un plan; no inserta registros ni modifica la geodatabase.', '',
        f"KMZ esperados: {report.get('kmz_esperados', 0)}. "
        f"Fuentes actuales verificadas: {sources.get('verificado', False)}.",
        f"Esquema de destino verificado: {(report.get('destino') or {}).get('verificado', False)}.",
        f"Correspondencias de proyecto verificadas: {projects.get('verificado', False)}.", '',
        '## Cómo revisar el resultado', '',
        '1. Revise fuentes_kmz.csv y correspondencia_kmz.csv. Se buscan KMZ recursivamente y se '
        'comparan sus SHA-256 con las 13 fuentes del perfil completo. Un nombre distinto se documenta. '
        'Ausencias, duplicados, cambios de contenido y archivos adicionales quedan visibles.',
        '2. Revise asociaciones_proyecto.csv y catalogo_proyectos.csv. Complete confirmar_proyectos.csv '
        'con el código real y confirmado=si para cada asociación revisada. Los candidatos por nombre '
        'no se confirman automáticamente. Vuelva a ejecutar con ese CSV si quiere validar la asociación.',
        '3. Revise plan_rutas.csv, rutas_sin_destino.csv, reglas_valores.csv e incidencias.csv. '
        'Los recuentos son Placemarks agrupados por ruta/geometría del perfil, no filas prometidas '
        'para una carga que todavía debe resolver geometrías y correspondencias.',
        '4. Revise ajustes_esquema_propuestos.csv: las oficinas registrales del inmueble y de la persona '
        'jurídica son atributos distintos que el EFT 5.8.7 requiere conservar. El modelo actual tiene '
        'una sola columna; el ajuste se documenta para prepararlo y verificarlo antes de cargar. '
        'Complete también los atributos sin correspondencia y los campos obligatorios, incluido id_analisis.', '',
        '## Alcance de la evidencia', '',
        'Los valores se reutilizan del perfil completo 1.9 solo después de comprobar que los 13 archivos '
        'actuales tienen exactamente los mismos bytes. No se repite el análisis XML. Un cambio de '
        'contenido impide usar esa evidencia como comprobación de las fuentes actuales.',
        'El catálogo de proyectos, los tipos de campo y los recuentos del destino se consultan en vivo. '
        'Observar relaciones existentes no certifica FK, reglas de relación, publicación, branch ni permisos '
        'de un servicio. Tampoco se certifican geometrías reparadas ni los otros dos datasets.', '',
        'Ninguna ruta se declara lista para insertar en esta herramienta. El cierre de tipos 1.9 '
        'se conserva; los pendientes de este plan son de carga y correspondencia.', '']
    if report.get('error'):
        lines += ['## Error', '', report['error'], '']
    lines += ['## Resumen del plan', '', '```json',
              json.dumps(plan.get('resumen', {}), ensure_ascii=False, indent=2), '```', '']
    (folder / 'informe.md').write_text('\n'.join(lines), encoding='utf-8')
    with (folder / 'resultado.json').open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def run(workspace, kmz_dir, project_csv=None, database='ArcGisAWS', owner='gis',
        reports=None, arcpy_module=None, emit=print, model_dir=None):
    model_dir = Path(model_dir or HERE).resolve()
    parent = Path(reports or model_dir).resolve()
    require(parent.is_dir(), 'La carpeta de informes debe existir.')
    folder = parent / ('Preingesta_' + dt.datetime.now().strftime('%Y%m%d_%H%M%S_') + uuid.uuid4().hex[:12])
    emit('Informe: ' + str(folder))
    report = dict(version_paquete='1.10', version_modelo=12, estado='ERROR_DETENIDO',
        modo='SOLO_LECTURA', inicio_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
        workspace=str(workspace) if workspace else None, carpeta_kmz=str(kmz_dir),
        database=database, owner=owner, ingesta_autorizada=False, cambios_en_sde=False,
        registros_insertados=0, cambios_en_modelo=False, incidencias=[], destino=None)
    failure = None
    try:
        require(workspace, 'Indique la conexión o geodatabase existente.')
        require(kmz_dir and Path(kmz_dir).is_dir(), 'Indique la carpeta raíz de los KMZ actuales.')
        before = reference_hashes(model_dir)
        mapping_hash = validation.digest(project_csv) if project_csv else None
        report['proyectos_csv_sha256'] = mapping_hash
        model = validation.validated_model(model_dir,
            json.loads((model_dir / 'esquema.json').read_text(encoding='utf-8-sig')))
        require(model['version'] == 12, 'Se requiere el modelo cerrado 12 de la versión 1.9.')
        envelope, fingerprint = validation.read_profile_snapshot(model_dir)
        profile = envelope['perfil']
        require(len(profile['fuentes']) == 13, 'Se requieren las 13 fuentes del perfil completo.')
        report.update(referencias_sha256=before, perfil_sha256=fingerprint, kmz_esperados=13,
                      perfil_generado_utc=envelope.get('generado_utc'))
        sources = fuentes_ingesta.discover_sources(kmz_dir, profile['fuentes'], emit=emit)
        report['fuentes'] = sources
        if arcpy_module is None:
            import arcpy as arcpy_module
        destination, catalog = inspect_live(arcpy_module, workspace, database, owner, model, emit)
        report.update(destino=destination, catalogo_proyectos=catalog)
        projects = proyectos_ingesta.plan_projects(profile['fuentes'], catalog, mapping_csv=project_csv)
        report['proyectos'] = projects
        plan = plan_ingesta.build_plan(profile, model, model_dir=model_dir)
        report['plan'] = plan
        enrich_routes(plan, projects)
        report['evidencia_valores_actuales'] = bool(sources.get('completo'))
        if not report['evidencia_valores_actuales']:
            for row in plan['rutas']:
                row['evidencia_actual_verificada'] = False
            report['incidencias'].append(dict(motivo='FUENTES_ACTUALES_INCOMPLETAS_O_DISTINTAS',
                detalle='El plan muestra la referencia archivada; no acredita todos los archivos actuales.'))
        else:
            for row in plan['rutas']:
                row['evidencia_actual_verificada'] = True
        for group in (destination['incidencias'], destination['incidencias_preingesta'],
                      catalog.get('incidencias', []), projects.get('incidencias', []),
                      plan.get('incidencias_campos', []), plan.get('incidencias_fuente', [])):
            report['incidencias'].extend(group)
        # Segunda lectura de huellas: no aceptar un plan sobre archivos que cambiaron durante la consulta.
        after_sources = fuentes_ingesta.discover_sources(kmz_dir, profile['fuentes'], emit=lambda _: None)
        require(sources == after_sources, 'Los KMZ o su inventario cambiaron durante la prevalidación; repita.')
        require(reference_hashes(model_dir) == before, 'Las referencias cambiaron durante la prevalidación.')
        if project_csv:
            require(validation.digest(project_csv) == mapping_hash, 'El CSV de proyectos cambió durante la lectura.')
        structural_issues = [r for r in destination['incidencias_preingesta']
                             if r['motivo'] != 'DESTINO_CON_REGISTROS']
        complete = bool(sources.get('verificado') and destination['verificado']
                        and destination['recuentos_completos'] and catalog.get('verificado')
                        and not structural_issues)
        report['comprobaciones_lectura_completas'] = complete
        report['estado'] = 'PLAN_INGESTA_CON_PENDIENTES' if complete else 'PREVALIDACION_INGESTA_INCOMPLETA'
        report['correspondencias_proyecto_verificadas'] = bool(projects.get('verificado'))
        emit(f"PLAN: {len(plan['rutas'])} rutas; fuentes verificadas={sources.get('verificado')}; "
             f"proyectos verificados={projects.get('verificado')}.")
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
