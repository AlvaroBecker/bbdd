"""Genera la revision de nombres solicitada: descripcion CSV -> snake_case.

Solo genera archivos locales. No renombra ni conecta a una geodatabase.
"""
from __future__ import annotations
import ast
import collections
import copy
import csv
import hashlib
import json
from pathlib import Path
import re
import shutil
import unicodedata
import zipfile

from generar_esquema_kmz_eft import nombre_campo

ROOT=Path(__file__).resolve().parents[1]
SRC=ROOT/'inventario_kmz_resumen'
PREV=ROOT/'02_entregas/Esquema_KMZ_EFT'
OUT=ROOT/'02_entregas/Esquema_KMZ_CSV'
GEOM={'Punto':'POINT','Línea':'POLYLINE','Polígono':'POLYGON'}
SUFFIX={'Punto':'punto','Línea':'linea','Polígono':'poligono','Mixta':'mixta'}
MAX_NAME=50  # deja espacio para rel_proyecto_ dentro de 64 caracteres
SYSTEM=re.compile(r'^(?:FID(?:_.*)?|OBJECTID(?:_.*)?|OID|GLOBALID|SHAPE(?:_.*)?|ST_AREA_SH(?:APE)?|ST_LENGTH(?:_SHAPE)?)$',re.I)


def snake(value):
    s=unicodedata.normalize('NFKD',value).encode('ascii','ignore').decode().lower()
    s=re.sub('[^a-z0-9]+','_',s).strip('_')
    if not s: raise ValueError('Descripcion sin caracteres utilizables.')
    return ('c_'+s) if s[0].isdigit() else s


def physical_name(description,geometry,multiple):
    base=snake(description)
    suffix='_'+SUFFIX[geometry] if multiple else ''
    full=base+suffix
    if len(full)>MAX_NAME:
        digest=hashlib.sha256(full.encode()).hexdigest()[:8]
        return base[:MAX_NAME-len(suffix)-9].rstrip('_')+'_'+digest+suffix,full
    return full,full


def read(name):
    with (SRC/name).open(encoding='utf-8-sig',newline='') as f:
        return list(csv.DictReader(f,delimiter=';'))


def write_csv(name,rows):
    with (OUT/name).open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]),delimiter=';')
        w.writeheader(); w.writerows(rows)


def main():
    OUT.mkdir(exist_ok=True)
    matrix=read('inventario_kmz_matriz_campos.csv')
    layers=read('inventario_kmz_capas.csv')
    old=json.loads((PREV/'esquema.json').read_text(encoding='utf-8'))
    groups=collections.defaultdict(list)
    geoms=collections.defaultdict(set)
    for row in matrix:
        key=(row['descripcion'],row['geometria'])
        groups[key].append(row); geoms[key[0]].add(key[1])
    names={}
    occupied=set()
    catalog=[]
    for desc,g in sorted(groups):
        name,full=physical_name(desc,g,len(geoms[desc])>1)
        if name in occupied:
            name=name[:41].rstrip('_')+'_'+hashlib.sha256((desc+'|'+g).encode()).hexdigest()[:8]
        assert name not in occupied
        occupied.add(name); names[desc,g]=name
        catalog.append(dict(descripcion=desc,geometria=g,nombre_normalizado_completo=full,
                            nombre_clase=name,dataset='Datos_Proyecto',
                            estado='DEFINIDA' if g in GEOM else 'PENDIENTE_SEPARAR_GEOMETRIAS',
                            nombre_abreviado='SI' if name!=full else 'NO',
                            filas_campos=len(groups[desc,g])))

    # Conserva el bloque comun anterior y la politica de campos propios.
    template=next(c for c in old['clases'] if c['nombre']=='PredioSUNARP_Recorte')
    common=[copy.deepcopy(f) for f in template['campos'] if f['origen']!='Matriz KMZ: valor textual' and f['nombre']!='area_ha']
    classes=[]
    field_map=[]
    for (desc,g),rows in sorted(groups.items()):
        name=names[desc,g]
        fields=copy.deepcopy(common)
        if g in ('Línea','Polígono'):
            fields.append(dict(nombre='longitud_m' if g=='Línea' else 'area_ha',tipo='DOUBLE',longitud=None,
                               alias='Longitud geodesica (m)' if g=='Línea' else 'Area geodesica (ha)',
                               dominio=None,nullable=True,origen='EFT 5.8.7'))
        commons={f['nombre'].lower() for f in fields}
        for row in rows:
            original=row['campo_normalizado']; target=''; state='PENDIENTE_GEOMETRIA'
            if SYSTEM.fullmatch(original): state='OMITIR_CAMPO_SISTEMA'
            elif g in GEOM:
                target=nombre_campo(original)
                if target.lower() in commons: target='src_'+target
                existing={f['nombre'].lower():f for f in fields}
                if target.lower() in existing and existing[target.lower()].get('campo_fuente')!=original:
                    target=target[:46]+'_'+hashlib.sha256(original.encode()).hexdigest()[:8]
                if target.lower() not in {f['nombre'].lower() for f in fields}:
                    fields.append(dict(nombre=target,tipo='TEXT',longitud=4000,alias=original[:255],
                                       dominio=None,nullable=True,origen='Matriz KMZ: valor textual',campo_fuente=original))
                state='CAMPO_TEXTUAL'
            field_map.append(dict(descripcion=desc,geometria=g,campo_fuente=original,
                                  variantes=row['variantes_del_nombre'],tecnico_inventario=row['tecnico'],
                                  clase_destino=name,campo_destino=target,tipo='TEXT' if target else '',
                                  longitud=4000 if target else '',estado=state))
        if g in GEOM:
            classes.append(dict(nombre=name,dataset='Datos_Proyecto',geometria=GEOM[g],campos=fields,
                                origen='descripcion + geometria de la matriz CSV',relacion_proyecto=True,
                                tipo='nueva_desde_csv',descripciones=[desc]))

    counts=collections.Counter(); review=[]
    for i,row in enumerate(layers,1):
        key=row['descripcion'],row['geometria']; name=names.get(key,'')
        usable=bool(name and row['geometria'] in GEOM)
        project=Path(row['archivo'].replace('\\','/')).stem
        counts[name,project]+=int(row['elementos'])
        review.append(dict(fila_capas=i,archivo=row['archivo'],ruta=row['ruta'],descripcion=key[0],geometria=key[1],
                           elementos=row['elementos'],clase_propuesta=name,dataset_propuesto='Datos_Proyecto' if usable else '',
                           incluir='',clase_confirmada='',co_proyecto='',id_analisis='',
                           estado='REVISAR_MAPEO' if usable else 'PENDIENTE_GEOMETRIA' if name else 'NO_FIGURA_EN_MATRIZ'))
    projects=sorted({p for _,p in counts})
    for row in catalog:
        row['elementos_inventariados']=sum(counts[row['nombre_clase'],p] for p in projects)
        row.update({p:counts[row['nombre_clase'],p] for p in projects})
    model=dict(version=2,criterio_nombres='descripcion CSV en snake_case ASCII; sufijo geometrico solo para descripciones repetidas',
               referencia_espacial=4326,tabla_proyecto='mline_tc_proyecto',clave_proyecto='co_proyecto',
               datasets=old['datasets'],dominios=old['dominios'],clases=classes,
               relaciones=[dict(nombre='rel_proyecto_'+c['nombre'],origen='mline_tc_proyecto',destino=c['nombre'],
                                 clave_origen='co_proyecto',clave_destino='proyecto') for c in classes],
               tablas_migradas=old['tablas_migradas'],
               fuentes={n:hashlib.sha256((SRC/n).read_bytes()).hexdigest() for n in ('inventario_kmz_matriz_campos.csv','inventario_kmz_capas.csv')})
    (OUT/'esquema.json').write_text(json.dumps(model,ensure_ascii=False,indent=2),encoding='utf-8')
    write_csv('catalogo_nombres.csv',catalog)
    write_csv('campos_matriz_a_esquema.csv',field_map)
    write_csv('mapeo_capas_revision.csv',review)
    shutil.copyfile(PREV/'crear_esquema.py',OUT/'crear_esquema.py')
    scripts=OUT/'por_clase'; scripts.mkdir(exist_ok=True)
    for c in classes:
        (scripts/(c['nombre']+'.py')).write_text(
            '"""Creacion de la clase '+c['nombre']+'."""\n'
            'import sys\nfrom pathlib import Path\n'
            'sys.path.insert(0,str(Path(__file__).resolve().parents[1]))\n'
            'from crear_esquema import main\n'
            'if __name__ == "__main__":\n'
            '    main(["--clase",'+repr(c['nombre'])+']+sys.argv[1:])\n',encoding='utf-8')
    # Pruebas de la regla pedida, cobertura y referencias generadas.
    assert snake('Áreas naturales protegidas (SERNANP)')=='areas_naturales_protegidas_sernanp'
    assert snake('Qhapaq Ñan – red vial inca (Ministerio de Cultura)')=='qhapaq_nan_red_vial_inca_ministerio_de_cultura'
    assert len(catalog)==len(groups)==125 and len(field_map)==len(matrix)==3507
    assert len(classes)==124 and len(model['relaciones'])==124
    assert all(re.fullmatch('[a-z][a-z0-9_]*',x['nombre']) and len(x['nombre'])<=MAX_NAME for x in classes)
    assert len({c['nombre'] for c in classes})==len(classes)
    lookup={c['nombre']:{f['nombre'] for f in c['campos']} for c in classes}
    for c in classes: assert len(lookup[c['nombre']])==len(c['campos'])
    for row in field_map:
        if row['campo_destino']: assert row['campo_destino'] in lookup[row['clase_destino']]
    assert sum(int(r['elementos']) for r in review)==279623
    assert sum(r['elementos_inventariados'] for r in catalog)==sum(int(r['elementos']) for r in review if r['clase_propuesta'])
    for p in OUT.rglob('*.py'): ast.parse(p.read_text(encoding='utf-8'))
    report=dict(filas_matriz=3507,descripciones=len(geoms),grupos=125,clases_generadas=124,
                relaciones=124,grupos_geometria_mixta=1,
                nombres_abreviados=sum(r['nombre_abreviado']=='SI' for r in catalog),
                campos_por_estado=dict(collections.Counter(r['estado'] for r in field_map)),
                comprobaciones_estaticas='OK',ejecutado_en_geodatabase=False,
                observacion='Las pruebas ArcGIS del paquete anterior validan el motor, no este nuevo catalogo.')
    (OUT/'VALIDACION.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    output=OUT.with_suffix('.zip')
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(OUT.rglob('*')):
            if p.is_file() and '__pycache__' not in p.parts: z.write(p,Path(OUT.name)/p.relative_to(OUT))
    with zipfile.ZipFile(output) as z: assert z.testzip() is None
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__': main()
