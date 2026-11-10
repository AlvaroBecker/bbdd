"""Ejecuta reglas SUNARP sobre todos los registros reales de sus ocho KMZ."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
from zipfile import ZipFile

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'02_entregas/Esquema_KMZ_EFT_Corregido'
sys.path.insert(0,str(OUT))
import inspeccion_kmz as kml
import reglas_sunarp_ingesta as sunarp
import fuentes_ingesta


def sha(path):return fuentes_ingesta.digest(path)[0]


def main():
    rules=sunarp.load_rules()
    checked=sunarp.validate_references(rules,OUT)
    keys={(r['archivo'],r['ruta'],r['geometria']) for r in rules['equivalencias']}
    sources={p.name:p for p in (ROOT/'01_fuentes').rglob('*.kmz')}
    count=Counter();values=Counter();routes=Counter();different=equal=0
    for source in rules['fuentes']:
        path=sources[source['archivo']]
        assert sha(path)==source['sha256']
        with ZipFile(path) as archive:
            members=sorted(n for n in archive.namelist() if n.lower().endswith('.kml'))
            schemas,paths,_=kml._schemas_and_routes(archive,members,lambda *args:None)
            for member in members:
                stack=[];containers=[];next_id=0
                with archive.open(member) as stream:
                    for event,elem in ET.iterparse(kml.NamespaceStream(stream),events=('start','end')):
                        tag=kml.local(elem.tag)
                        if event=='start':
                            stack.append(elem)
                            if tag in {'Document','Folder'}:
                                next_id+=1;containers.append(next_id)
                            continue
                        parent=stack[-2] if len(stack)>1 else None
                        if tag=='Placemark':
                            route=paths[member][containers[-1]] if containers else ''
                            geometry=kml.geometry(elem)
                            key=(source['archivo'],route,geometry)
                            if key in keys:
                                identity=dict(archivo=source['archivo'],miembro=member,ruta=route,
                                              geometria=geometry,sha256=source['sha256'])
                                result=sunarp.resolve_record(rules,identity,kml.attributes(elem,member,schemas,lambda *args:None))
                                count[source['archivo']]+=1;routes[key]+=1
                                for field in result['asignaciones']:values[field]+=1
                                pairs=result['asignaciones']
                                if 'oficina_registral' in pairs and 'oficina_1' in pairs:
                                    if pairs['oficina_registral']==pairs['oficina_1']:equal+=1
                                    else:different+=1
                        if tag in {'Placemark','Style','StyleMap','Schema','Document','Folder'}:
                            if tag in {'Document','Folder'}:containers.pop()
                            if parent is not None:parent.remove(elem)
                            elem.clear()
                        stack.pop()
        assert sha(path)==source['sha256']
        print(source['archivo']+': '+str(count[source['archivo']]),flush=True)
    assert sum(count.values())==1019 and sum(values.values())==1378 and len(routes)==12
    assert different==253 and equal==35
    names=['reglas_sunarp_ingesta.py','reglas_sunarp_1_13.json','inspeccion_kmz.py','esquema.json',
           'PERFIL_COMPLETO_KMZ_1_9.json','campos_por_ruta.csv','mapeo_capas_revision.csv']
    result=dict(version_paquete='1.13',estado='VERIFICACION_KMZ_REAL_OK',referencias=checked,
        registros=1019,valores=1378,rutas=12,pares_distintos=different,pares_iguales=equal,
        por_fuente=dict(count),por_campo=dict(values),errores=[],ddl=False,carga_ejecutada=False,
        fuentes_inalteradas=True,archivos_sha256={n:sha(OUT/n) for n in names})
    result['archivos_sha256']['03_scripts/probar_reglas_sunarp_1_13.py']=sha(__file__)
    (OUT/'VALIDACION_REGLAS_SUNARP_1_13.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('SUNARP: 1019 registros y ambos roles verificados.',flush=True)


if __name__=='__main__':main()
