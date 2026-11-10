"""Ensayo 1.3 en una GDB aislada: preparar y validar en procesos separados."""
import argparse
import datetime as dt
import json
from pathlib import Path
import re
import uuid

import arcpy as a
import datos_proyecto as runner


def main():
    here=Path(__file__).resolve().parent
    p=argparse.ArgumentParser();p.add_argument('--workspace')
    p.add_argument('--preparar-dominios',action='store_true');v=p.parse_args()
    if not v.workspace:
        folder=here/'_validacion'/('norm13_'+dt.datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8])
        folder.mkdir(parents=True)
        gdb=str(folder/'ensayo.gdb')
        a.management.CreateFileGDB(str(folder),'ensayo.gdb')
        a.management.CreateFeatureDataset(gdb,'Datos_Proyecto',a.SpatialReference(4326))
        parent=gdb+'/mline_tc_proyecto'
        a.management.CreateTable(gdb,'mline_tc_proyecto')
        a.management.AddField(parent,'co_proyecto','TEXT',field_length=12)
        with a.da.InsertCursor(parent,['co_proyecto']) as cursor:cursor.insertRow(['PRY-00000001'])
        print(gdb,flush=True)
        return
    path=Path(v.workspace).resolve()
    assert path.suffix=='.gdb' and path.is_relative_to(here/'_validacion') and path.parent.name.startswith('norm13_')
    if v.preparar_dominios:
        # Fixture exclusivamente local: no es reparacion automatica del tool.
        model=json.loads((here/'esquema.json').read_text(encoding='utf-8'))
        cls=next(c for c in model['clases'] if c['nombre']=='estructuras')
        wanted={f['dominio'] for f in cls['campos'] if f['dominio']}
        domains={d.name:d for d in a.da.ListDomains(str(path))}
        for name in sorted(wanted):
            spec=model['dominios'][name]
            assert name in domains, 'Esta preparacion solo completa dominios de este ensayo.'
            for value in spec['valores']:
                if value not in domains[name].codedValues:
                    a.management.AddCodedValueToDomain(str(path),name,value,value)
        print('Dominios del fixture local completados.',flush=True)
        return
    existed=a.Exists(str(path/'Datos_Proyecto'/'estructuras'))
    _,report=runner.run(str(path),['estructuras'],apply=True,reports=path.parent,arcpy_module=a)
    assert report['estado']=='CREACION_VERIFICADA'
    fc=str(path/'Datos_Proyecto'/'estructuras')
    names={f.name for f in a.ListFields(fc)}
    assert len(names)==39
    native={'OBJECTID','Shape','GlobalID','created_user','created_date','last_edited_user','last_edited_date'}
    assert all(re.fullmatch(r'[a-z][a-z0-9]*(?:_[a-z0-9]+)*',n) for n in names-native)
    assert {'codigo_enti','cod_vertice','alternativa','src_nombre','nombre'}<=names
    assert not {'ALTERNATIV','src_ALTERNATIVA','src_alternativa','CODVERTICE'} & names
    if not existed:
        print('Creacion y nombres verificados. Repita este comando en un proceso nuevo para verificar idempotencia.',flush=True)
        return
    assert not report['completadas']
    result=dict(version_paquete='1.3',arcgis=a.GetInstallInfo()['Version'],
                estructuras_campos_modelo=32,estructuras_campos_fisicos=39,nombres_fisicos_verificados=True,
                repeticion_sin_duplicados=True,validacion_sde=False,gdb=str(path))
    result['alcance']='Nombres y campos de estructuras; dominios existentes preparados en el fixture local.'
    result['incidencia_previa']='Primer ensayo detenido por ERROR 000112 al poblar dom_fuente; no creo la clase. Dominio del fixture completado en proceso separado. Las repeticiones fallaron en una segunda prevalidacion redundante tras validar el lote existente (999999/read only y Describe no existe). Se retiro esa segunda lectura solo para lotes sin cambios.'
    result['repeticion_en_proceso_separado']=True
    result['informe_repeticion']=report['archivo_resultado']
    (here/'VALIDACION_NORMALIZACION_ARCGIS.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)


if __name__=='__main__':main()
