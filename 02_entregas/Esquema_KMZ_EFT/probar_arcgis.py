"""Prueba local aislada; nunca usa conexiones SDE ni tablas reales del usuario."""
import datetime
import argparse
import json
from pathlib import Path

import arcpy
import crear_esquema


def main():
    base=Path(__file__).resolve().parent / '_validacion'
    base.mkdir(exist_ok=True)
    parser=argparse.ArgumentParser()
    parser.add_argument('--reanudar',help='Nombre de una fixture creada antes, sin ruta.')
    opts=parser.parse_args()
    gdb=base / (opts.reanudar or ('prueba_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S')+'.gdb'))
    assert gdb.resolve().parent==base.resolve() and gdb.name.startswith('prueba_') and gdb.suffix=='.gdb'
    classes=['PredioSUNARP_Recorte','ViasNacional_Recorte','Estructuras','mline_td_proyecto_ltransmision']
    args=['--workspace',str(gdb)]
    for name in classes: args+=['--clase',name]
    crear_esquema.main(args+['--aplicar'])
    # Padre sintetico exclusivamente dentro de esta fixture; no se exporta al paquete.
    parent=arcpy.management.CreateTable(str(gdb),'mline_tc_proyecto').getOutput(0)
    arcpy.management.AddField(parent,'co_proyecto','TEXT',field_length=12)
    with arcpy.da.InsertCursor(parent,['co_proyecto']) as cursor:
        cursor.insertRow(['PRY-00000005'])
    crear_esquema.main(args+['--accion','relacionar','--aplicar'])
    # Repetir sobre objetos existentes debe validar, no duplicar clases o relaciones.
    crear_esquema.main(args+['--aplicar'])
    crear_esquema.main(args+['--accion','relacionar','--aplicar'])
    evidence=[]
    for name in classes:
        path=str(gdb/'Datos_Proyecto'/name)
        d=arcpy.Describe(path)
        rel=arcpy.Describe(str(gdb/('rel_proyecto_'+name)))
        evidence.append(dict(clase=name,campos=len(arcpy.ListFields(path)),wkid=d.spatialReference.factoryCode,
                             z=d.hasZ,globalid=d.hasGlobalID,editor_tracking_utc=d.isTimeInUTC,
                             cardinalidad=rel.cardinality,llaves=rel.originClassKeys))
    # Una llave padre duplicada tiene que detenerse antes de cualquier DDL nuevo.
    with arcpy.da.InsertCursor(parent,['co_proyecto']) as cursor:
        cursor.insertRow(['PRY-00000005'])
    duplicate_rejected=False
    try:
        crear_esquema.main(args+['--accion','relacionar','--aplicar'])
    except ValueError as exc:
        duplicate_rejected='duplicado' in str(exc)
    assert duplicate_rejected
    report=dict(arcgis=arcpy.GetInstallInfo()['Version'],workspace=str(gdb),clases=evidence,
                repeticion_sin_duplicacion=True,codigo_padre_duplicado_rechazado=True,
                prueba_sde=False,prueba_branch=False)
    (base/'resultado.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)


if __name__=='__main__': main()
