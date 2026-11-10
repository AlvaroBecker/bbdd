"""Prueba aislada de cuatro clases corregidas; no abre conexiones SDE."""
import argparse
import datetime
import gc
import json
from pathlib import Path

import arcpy
import crear_esquema
import relacionar_negocio


def main():
    p=argparse.ArgumentParser();p.add_argument('--reanudar');opts=p.parse_args()
    base=Path(__file__).resolve().parent/'_validacion';base.mkdir(exist_ok=True)
    gdb=base/(opts.reanudar or ('prueba_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S')+'.gdb'))
    assert gdb.resolve().parent==base.resolve() and gdb.name.startswith('prueba_') and gdb.suffix=='.gdb'
    names=['canales_recorte','mline_td_proyecto_infraestructura','mline_td_proyecto_ltransmision','vertices']
    args=['--workspace',str(gdb)]
    for name in names:args+=['--clase',name]
    crear_esquema.main(args+['--aplicar'])
    for table,key,typ,value in [('mline_tc_proyecto','co_proyecto','TEXT','PRY-00000005'),
                                 ('mline_td_proyecto_componente','id_proyecto_componente','LONG',1),
                                 ('mline_td_proyecto_alternativa','id_proyecto_alternativa','LONG',1)]:
        path=str(gdb/table)
        if not arcpy.Exists(path):
            arcpy.management.CreateTable(str(gdb),table)
            arcpy.management.AddField(path,key,typ,field_length=12 if typ=='TEXT' else None)
            with arcpy.da.InsertCursor(path,[key]) as cur:cur.insertRow([value])
    crear_esquema.main(args+['--accion','relacionar','--aplicar'])
    relargs=['--workspace',str(gdb),'--destino','mline_td_proyecto_infraestructura','--destino','mline_td_proyecto_ltransmision','--destino','vertices']
    relacionar_negocio.main(relargs+['--aplicar'])
    # La primera ejecucion en ArcGIS 3.7.1 fallo al releer campos tras crear
    # relaciones. Liberar referencias/cache antes de reinspeccionar.
    gc.collect()
    arcpy.management.ClearWorkspaceCache(str(gdb))
    crear_esquema.main(args+['--aplicar'])
    crear_esquema.main(args+['--accion','relacionar','--aplicar'])
    relacionar_negocio.main(relargs+['--aplicar'])
    # Entidad sintetica huerfana: debe ser rechazada por la prevalidacion del vinculo.
    path=str(gdb/'Datos_Proyecto'/'vertices')
    with arcpy.da.InsertCursor(path,['SHAPE@','proyecto','id_analisis','id_proyecto_infraestructura']) as cur:
        cur.insertRow([arcpy.PointGeometry(arcpy.Point(-75,-10,100),arcpy.SpatialReference(4326),True),'PRY-00000005','PRUEBA',999])
    rejected=False
    try:relacionar_negocio.main(['--workspace',str(gdb),'--destino','vertices'])
    except ValueError as exc:rejected='sin padre' in str(exc)
    assert rejected
    report=dict(arcgis=arcpy.GetInstallInfo()['Version'],clases=names,relaciones_proyecto=4,relaciones_negocio=3,
                segunda_ejecucion_sin_duplicacion=True,vertice_huerfano_rechazado=True,prueba_sde=False,prueba_branch=False,
                observacion='La primera ejecucion dio ERROR 999999 al reinspeccionar campos. Un proceso nuevo leyo las cuatro clases; la prueba libera cache antes de repetir operaciones.')
    (base/'resultado.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)


if __name__=='__main__':main()
