"""Migracion 1.4 limitada a siete campos de estructuras, sin cargar registros."""
from __future__ import annotations
import argparse
import copy
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
from types import SimpleNamespace
import uuid

import datos_proyecto as runner

HERE = Path(__file__).resolve().parent
FIELDS = ('este', 'norte', 'east', 'north', 'x', 'y', 'vano')


def properties(field):
    return dict(nombre=runner.engine.field_base_name(field), tipo=field.type,
                longitud=field.length, alias=getattr(field,'aliasName',''),
                nullable=field.isNullable, dominio=field.domain,
                defecto=repr(getattr(field,'defaultValue',None)),
                requerido=bool(getattr(field,'required',False)),
                precision=getattr(field,'precision',None), escala=getattr(field,'scale',None))


def snapshot(a, path):
    return {key:properties(field) for key,field in runner.engine.field_index(a.ListFields(path)).items()}


def require_preserved(before, after):
    runner.engine.require(before.keys()==after.keys(), 'Cambio inesperado en la lista de campos; detener para revision.')
    for name, original in before.items():
        current = dict(after[name])
        old = dict(original)
        if name in FIELDS:
            for prop in ('tipo','longitud','precision','escala'):
                old.pop(prop); current.pop(prop)
        runner.engine.require(old==current, f'{name}: cambio inesperado de propiedades; detener para revision.')


def ensure_empty(a, path):
    count = int(a.management.GetCount(path).getOutput(0))
    runner.engine.require(count==0, f'estructuras contiene {count} registros. El cambio de tipos requiere clase vacia.')


def plan(a, args, model):
    # Esta inspeccion valida conexion/propietario y dataset sin exigir todavia
    # los tipos nuevos sobre la clase que puede conservar TEXT de 1.3.3.
    inventory, _ = runner.engine.inspect(a,args,model,[])
    path = inventory.get('estructuras')
    runner.engine.require(path is not None, 'No existe estructuras; esta herramienta no crea clases.')
    actual = runner.engine.field_index(a.ListFields(path))
    compatible = copy.deepcopy(model)
    cls = compatible['clases'][0]
    expected = {f['nombre']:f for f in cls['campos']}
    runner.engine.require({n for n in FIELDS if expected.get(n,{}).get('tipo')=='DOUBLE'}==set(FIELDS), 'El modelo no contiene los siete DOUBLE aprobados.')
    rows = []
    for name in FIELDS:
        field = actual.get(name)
        runner.engine.require(field is not None, f'estructuras: falta {name}. No se agregan columnas automaticamente.')
        runner.engine.require(field.type in {'String','Double'}, f'{name}: tipo {field.type}; solo se admite TEXT anterior o DOUBLE objetivo.')
        runner.engine.require(not getattr(field,'required',False), f'{name}: es un campo requerido.')
        runner.engine.require(not field.domain and field.isNullable, f'{name}: dominio o nulabilidad incompatibles.')
        runner.engine.require(getattr(field,'defaultValue',None) is None, f'{name}: tiene un valor predeterminado; requiere revision previa.')
        if field.type=='String':
            expected[name].update(tipo='TEXT',longitud=4000)
        rows.append(dict(campo=name,tipo_actual=field.type,tipo_objetivo='Double',
                         accion='ALTERAR_TIPO' if field.type=='String' else 'YA_DOUBLE'))
    runner.preflight(a,args,compatible)
    ensure_empty(a,path)
    # Ninguno de los siete es clave en el modelo. Un indice externo necesita
    # revision para no quitarlo ni reconstruirlo silenciosamente.
    for index in a.ListIndexes(path) or []:
        affected={runner.engine.field_base_name(f).casefold() for f in index.fields} & set(FIELDS)
        runner.engine.require(not affected, f'Indice {index.name} usa {sorted(affected)}; requiere revision antes de alterar tipos.')
    return path, rows, bool(a.TestSchemaLock(path))


def run(workspace, apply=False, database='ArcGisAWS', owner='gis', reports=None,
        arcpy_module=None, emit=print, model_path=None):
    runner.engine.require(all(re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',v) for v in (database,owner)), 'Base o propietario invalido.')
    raw=Path(model_path or HERE/'esquema.json').read_bytes()
    model=runner.scoped_model(json.loads(raw),['estructuras'])
    args=SimpleNamespace(workspace=os.path.abspath(workspace),database=database,owner=owner,aplicar=apply)
    folder=Path(reports or HERE)/('Tipos_Estructuras_'+dt.datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8])
    report=dict(estado='INICIADO',modo='APLICAR_TIPOS' if apply else 'VALIDAR_TIPOS',workspace=args.workspace,
                modelo_sha256=hashlib.sha256(raw).hexdigest(),version_paquete='1.4',completadas=[],campo_en_curso=None,
                clase_en_curso=None,clases=[dict(nombre='estructuras',geometria='POINT',campos=32,tipos_pendientes=0,accion='POR_VALIDAR')],
                advertencias=['Cambio exclusivo de siete tipos en una clase vacia. Los 14 atributos TEXT conservan sus longitudes.',
                              'No carga datos ni convierte unidades, coordenadas o marcadores <Null>.',
                              'Los cambios DDL no forman una transaccion atomica. Un error puede dejar tipos parcialmente actualizados; la siguiente ejecucion reconoce los DOUBLE ya aplicados.'])
    runner.report_files(folder,report,model)
    emit(f'Informe: {folder}')
    try:
        if arcpy_module is None:
            import arcpy as arcpy_module
        a=arcpy_module
        report['arcgis']=a.GetInstallInfo().get('Version')
        with a.EnvManager(overwriteOutput=False):
            path, rows, lock=plan(a,args,model)
            report.update(clase=path,plan=rows,bloqueo_disponible=lock)
            before=snapshot(a,path)
            report['campos_antes']=before
            report['clases'][0]['accion']='VALIDADA_PARA_TIPOS'
            if not lock and any(r['accion']=='ALTERAR_TIPO' for r in rows):
                report['advertencias'].append('No hay bloqueo de esquema disponible sobre estructuras. Cierre tablas/capas o procesos que la usen antes de aplicar.')
            report['estado']='PREVALIDADO'
            runner.report_files(folder,report,model)
            for row in rows:
                emit(f'{row["campo"]}: {row["tipo_actual"]} -> Double ({row["accion"]})')
            if apply:
                for row in rows:
                    if row['accion']=='YA_DOUBLE':
                        continue
                    # Volver a validar todo el estado permitido antes de cada
                    # mutacion, incluido cero registros y bloqueo en la clase.
                    _, current, available=plan(a,args,model)
                    require_preserved(before,snapshot(a,path))
                    now=next(r for r in current if r['campo']==row['campo'])
                    if now['accion']=='YA_DOUBLE':
                        row['accion']='YA_DOUBLE'
                        continue
                    runner.engine.require(available, 'No hay bloqueo de esquema disponible sobre estructuras; cierre su uso y reintente.')
                    report.update(campo_en_curso=row['campo'],clase_en_curso='estructuras')
                    runner.report_files(folder,report,model)
                    # Un error se propaga y detiene. No se repite la escritura
                    # ni se declara exito sin una comprobacion posterior.
                    a.management.AlterField(path,row['campo'],field_type='DOUBLE')
                    after=snapshot(a,path)
                    runner.engine.require(after[row['campo']]['tipo']=='Double', f'{row["campo"]}: ArcGIS no confirma Double despues de AlterField.')
                    require_preserved(before,after)
                    ensure_empty(a,path)
                    report['completadas'].append(row['campo'])
                    row['accion']='ALTERADA_VERIFICADA'
                    report.update(campo_en_curso=None,clase_en_curso=None)
                    runner.report_files(folder,report,model)
                    emit(f'TIPO actualizado y verificado: {row["campo"]}')
                # El modelo normal vuelve a validar la clase sin relajar tipos.
                if report['completadas']:
                    runner.preflight(a,args,model)
                ensure_empty(a,path)
                after=snapshot(a,path)
                require_preserved(before,after)
                runner.engine.require(all(after[n]['tipo']=='Double' for n in FIELDS), 'Persisten campos sin Double.')
                report['campos_despues']=after
                report['clases'][0]['accion']='TIPOS_VERIFICADOS'
            report['estado']='TIPOS_VERIFICADOS' if apply else 'VALIDACION_OK_SIN_CAMBIOS'
    except Exception as exc:
        report.update(estado='ERROR_DETENIDO',error=str(exc))
        if 'path' in locals() and 'a' in locals():
            try:
                report['campos_observados_al_detener']=snapshot(a,path)
            except Exception as diagnostic_error:
                report['error_al_leer_estado']=str(diagnostic_error)
        raise
    finally:
        report['fin_utc']=dt.datetime.now(dt.timezone.utc).isoformat()
        try:
            runner.report_files(folder,report,model)
        except OSError as error:
            if not report.get('error'):
                raise
            emit(f'No se pudo guardar el estado final: {error}. Error original: {report["error"]}')
        else:
            emit(f'Estado: {report["estado"]}')
            emit(f'Resultado JSON: {report["archivo_resultado"]}')
    return folder,report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--workspace',required=True)
    p.add_argument('--aplicar',action='store_true')
    p.add_argument('--database',default='ArcGisAWS');p.add_argument('--owner',default='gis')
    p.add_argument('--informes')
    v=p.parse_args()
    run(v.workspace,v.aplicar,v.database,v.owner,v.informes)


if __name__=='__main__':
    main()
