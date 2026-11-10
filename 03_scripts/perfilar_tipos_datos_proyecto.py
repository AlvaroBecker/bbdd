"""Perfil de las 75 clases restantes; solo lectura de KMZ, sin ArcPy/SDE.

Las propuestas NO modifican el modelo. La cobertura se verifica por archivo,
ruta y geometria; las fuentes ausentes y formatos ambiguos siguen pendientes.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
from decimal import Decimal
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile

import perfilar_estructuras_kmz as base
from normalizacion_kmz import snake_case

ROOT=Path(__file__).resolve().parents[1]
MODEL=ROOT/'02_entregas/Esquema_KMZ_EFT_Corregido'
GEOM={'Point':'Punto','LineString':'Línea','Polygon':'Polígono'}
DATE_NAME=re.compile(r'(?:^|_)(?:fecha\w*|fec\w*|fecreg|fecleg|date|time_stamp|time_span)(?:_|$)')
IDENTIFIER=re.compile(r'(?:^|_)(?:id|cod\w*|codigo\w*|ubigeo|ruc|dni|partida\w*|expediente\w*|resolucion\w*|telefono\w*|zona\w*|zone|gridcode|codi\w*)(?:_|$)')
LABEL=re.compile(r'(?:nombre|name|descripcion|description|observ|titular|direccion|fuente|tipo|clase|categoria|estado|situacion|condicion|material|uso|color|sigla|simbolo|simbolo|popup|style|carpeta|folder|path|ruta|posicion|position|utm|lat_lon)')
MEASURE=re.compile(r'(?:^|_)(?:este|norte|east|north|x|y|z|latitud|latitude|longitud|longitude|altitud|altitude|elevacion|elevation|altura|ancho|largo|perimetro|perimeter|caudal|potencia|tension|voltaje|distancia|diametro|profundidad|pendiente)(?:_|$)|(?:^|_)(?:area|superficie)_(?:ha|has|m2|km2)(?:_|$)|(?:^|_)(?:hectareas|hectarea)(?:_|$)')
COUNT_NAME={'poblacion','poblacion_total','n_habitantes','numero_habitantes','nro_habitantes',
            'n_carriles','nro_carriles','numero_carriles','num_carriles','n_transformadores','numero_transformadores'}


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):
            h.update(chunk)
    return h.hexdigest()


def fresh():
    return dict(kinds=Counter(),records=0,max_length=0,max_utf16=0,min=None,max=None,
                decimals=False,max_significant=0,leading_zeros=0,samples=[],text_examples=[],markers=Counter())


def observe(s,value):
    kind,number=base.value_kind(value)
    s['kinds'][kind]+=1
    s['max_length']=max(s['max_length'],len(value))
    s['max_utf16']=max(s['max_utf16'],len(value.encode('utf-16-le'))//2)
    if len(s['samples'])<5 and value not in s['samples']:
        s['samples'].append(value[:250])
    if kind=='MARCADOR_LITERAL':
        s['markers'][value]+=1
    if kind=='TEXTO' and len(s['text_examples'])<5 and value not in s['text_examples']:
        s['text_examples'].append(value[:250])
    if number is not None:
        s['min']=number if s['min'] is None else min(s['min'],number)
        s['max']=number if s['max'] is None else max(s['max'],number)
        s['decimals'] |= number != number.to_integral_value()
        s['max_significant']=max(s['max_significant'],len(number.as_tuple().digits))
        s['leading_zeros']+=bool(re.fullmatch(r'[+-]?0\d+',value.strip()))


def recommend(name,s):
    useful=s['kinds']['TEXTO']+s['kinds']['NUMERICO_DECIMAL']
    if DATE_NAME.search(name):
        return 'REVISAR_FECHA','Revisar formatos y significado por fuente; no se convierte automaticamente a DATE.'
    if IDENTIFIER.search(name) or LABEL.search(name):
        return 'MANTENER_TEXT_IDENTIFICADOR_O_ETIQUETA','Conservar significado, ceros iniciales, codigos y texto original.'
    if not useful:
        return 'SIN_VALORES_UTILES_CONSERVAR_TEXT','No hay valores utiles suficientes para justificar otro tipo.'
    if s['kinds']['TEXTO']:
        return 'MANTENER_TEXT_CONTENIDO','Contiene valores que no son numeros decimales de formato inequívoco.'
    if s['leading_zeros']:
        return 'REVISAR_CEROS_INICIALES','Valores con ceros iniciales; no convertir sin determinar si son codigos.'
    if name in COUNT_NAME and not s['decimals'] and s['min']>=0 and s['max']<=2147483647:
        return 'CANDIDATO_LONG','Nombre de conteo explicito y todos los valores utiles son enteros en rango LONG.'
    if re.search(r'_[xyz]$',name) and not re.search(r'^(?:coor|coord|coordenada|near|punto|pnt|inicio|fin)_',name):
        return 'REVISAR_NUMERICO_SIN_SEMANTICA','Un sufijo x/y/z no demuestra que sea una coordenada o magnitud.'
    if MEASURE.search(name) and s['max_significant']<=15:
        return 'CANDIDATO_DOUBLE','Magnitud potencial; valores numericos sin formatos ambiguos. Confirmar significado y unidades sin convertir valores.'
    return 'REVISAR_NUMERICO_SIN_SEMANTICA','Todos los valores utiles son numericos, pero el nombre/rango no demuestra que deban tratarse como magnitudes.'


def raw_attributes(elem, mapping):
    """Preservar tambien una clave envolvente HTML cuando esta mapeada."""
    pairs=[(k,v) for k,v in base.attributes(elem) if not (
        snake_case(k)=='field_name' and snake_case(v)=='field_value' and 'field_name' not in mapping)]
    for node in elem.iter():
        kind=base.local(node.tag)
        name=node.get('name')
        if kind in {'Data','SimpleData'} and name and snake_case(name) in mapping:
            text=(node.text or '') if kind=='SimpleData' else next((v.text or '' for v in node if base.local(v.tag)=='value'),'')
            if re.search(r'<table\b',text,re.I):
                pairs.append((name,text))
        elif kind=='description' and 'description' in mapping and not re.search(r'<table\b',node.text or '',re.I):
            pairs.append(('description',node.text or ''))
    return pairs


def run(roots,output):
    output=Path(output)
    output.mkdir(parents=True,exist_ok=True)
    model=json.loads((MODEL/'esquema.json').read_text(encoding='utf-8'))
    classes={c['nombre']:c for c in model['clases'] if c['nombre']!='estructuras'}
    pending={(c['nombre'],f['nombre']):f for c in classes.values() for f in c['campos'] if 'pendiente' in f['origen'].lower()}
    assert len(pending)==2185, 'Cambio el alcance del modelo: revisar antes de continuar.'
    rows=[r for r in base.read(MODEL/'mapeo_capas_revision.csv') if r['clase_propuesta'] in classes]
    key=lambda r:(Path(r['archivo'].replace('\\','/')).name,r['ruta'],r['geometria'])
    expected={key(r):r for r in rows}
    assert len(expected)==len(rows)
    maps=defaultdict(dict)
    field_routes=defaultdict(set)
    for row in base.read(MODEL/'campos_por_ruta.csv'):
        if row['clase_destino'] not in classes:
            continue
        k=key(row)
        name=snake_case(row['campo_original'])
        target=row['campo_destino']
        if name in maps[k]:
            assert maps[k][name]==target
        maps[k][name]=target
        if (row['clase_destino'],target) in pending:
            field_routes[row['clase_destino'],target].add(k)
    files=defaultdict(list)
    for root in roots:
        for p in Path(root).rglob('*'):
            if p.is_file() and p.suffix.casefold()=='.kmz':
                if p.resolve() not in files[p.name]:files[p.name].append(p.resolve())
    for name,paths in files.items():
        assert len(paths)==1, f'Dos KMZ con el mismo nombre: {name}. Elegir la fuente correcta.'
    missing=sorted({k[0] for k in expected}-files.keys())
    stats={k:fresh() for k in pending}
    found=Counter()
    conflicts=Counter()
    issues=Counter()
    issue_examples={}
    sources=[]
    issue=lambda k,m,d:(issues.update([(k,m,d)]),issue_examples.setdefault((k,m,d),''))
    spec=importlib.util.spec_from_file_location('kmz_inventory',ROOT/'02_entregas/KMZ_EFT/01_inventariar_kmz.py')
    inv=importlib.util.module_from_spec(spec);spec.loader.exec_module(inv)
    for filename in sorted({k[0] for k in expected}-set(missing)):
        path=files[filename][0]
        before=digest(path)
        repaired=[]
        with zipfile.ZipFile(path) as archive:
            for member in archive.namelist():
                if not member.lower().endswith('.kml'):continue
                stack=[];frames=[]
                with archive.open(member) as stream:
                    reader=inv.NamespaceStream(stream)
                    for event,elem in ET.iterparse(reader,events=('start','end')):
                        tag=base.local(elem.tag)
                        if event=='start':
                            stack.append(elem)
                            if tag in {'Document','Folder'}:frames.append({'name':''})
                            continue
                        parent=stack[-2] if len(stack)>1 else None
                        if tag=='name' and parent is not None and base.local(parent.tag) in {'Document','Folder'}:
                            frames[-1]['name']=(elem.text or '').strip()
                        if tag=='Placemark':
                            route=' / '.join(f['name'] for f in frames)
                            geometries={GEOM[base.local(x.tag)] for x in elem.iter() if base.local(x.tag) in GEOM}
                            for geometry in geometries:
                                k=(filename,route,geometry)
                                if k not in expected:continue
                                found[k]+=1
                                cls=expected[k]['clase_propuesta']
                                values=defaultdict(list)
                                originals=defaultdict(list)
                                for original,value in raw_attributes(elem,maps[k]):
                                    source=snake_case(original)
                                    if source not in maps[k]:
                                        issue(k,'ATRIBUTO_NO_MAPEADO',original)
                                        continue
                                    target=maps[k][source]
                                    if (cls,target) in pending and value not in values[target]:
                                        values[target].append(value)
                                    if (cls,target) in pending:
                                        originals[target].append((original,value))
                                for target,raw in values.items():
                                    s=stats[cls,target];s['records']+=1
                                    # El normalizador de carga omite la cadena
                                    # vacia; vacio + valor no es un conflicto.
                                    if len([v for v in raw if v!=''])>1:
                                        conflicts[cls,target]+=1
                                        issue(k,'VALORES_CONFLICTIVOS',target)
                                        issue_examples[k,'VALORES_CONFLICTIVOS',target]=json.dumps(originals[target][:5],ensure_ascii=False)
                                    for value in raw:observe(s,value)
                            if parent is not None:parent.remove(elem)
                            elem.clear()
                        elif tag in {'Document','Folder'}:
                            frames.pop()
                            if parent is not None:parent.remove(elem)
                            elem.clear()
                        elif tag in {'Style','StyleMap','Schema'}:
                            if parent is not None:parent.remove(elem)
                            elem.clear()
                        stack.pop()
                    if reader.repaired:repaired.append(member)
        assert before==digest(path), 'Cambio un KMZ durante su lectura.'
        sources.append(dict(archivo=filename,ruta_lectura=str(path),sha256=before,xsi_declarado_en_copia_lectura=repaired))
        print(filename,sum(n for k,n in found.items() if k[0]==filename),'asignaciones observadas',flush=True)
    coverage=[]
    for k,r in expected.items():
        state='FUENTE_AUSENTE' if k[0] in missing else 'COINCIDE' if found[k]==int(r['elementos']) else 'DIFERENCIA'
        coverage.append(dict(archivo=k[0],ruta=k[1],geometria=k[2],clase=r['clase_propuesta'],esperados=int(r['elementos']),observados=found[k],estado=state))
    coverage_by_key={key(r):r['estado'] for r in coverage}
    report_rows=[]
    for (cls,name),s in sorted(stats.items()):
        proposal,why=recommend(name,s)
        required=field_routes[cls,name]
        absent={k[0] for k in required if k[0] in missing}
        bad=[k for k in required if coverage_by_key.get(k)!='COINCIDE']
        reasons=[]
        if absent:reasons.append('FALTAN_KMZ')
        if bad and not absent:reasons.append('DIFERENCIA_CONTEO')
        if conflicts[cls,name]:reasons.append('CONFLICTO_VALORES')
        if s['max_utf16']>pending[cls,name]['longitud']:reasons.append('SUPERA_LONGITUD_ACTUAL')
        if not required:reasons.append('SIN_RUTAS_INVENTARIADAS')
        report_rows.append(dict(clase=cls,campo=name,tipo_actual=pending[cls,name]['tipo'],propuesta=proposal,
            cobertura='COMPLETA_RUTAS_DEL_CAMPO' if not bad and required else 'INCOMPLETA',
            bloqueos=' | '.join(reasons),fuentes_ausentes=' | '.join(sorted(absent)),registros_con_campo=s['records'],
            numericos=s['kinds']['NUMERICO_DECIMAL'],otros_textos=s['kinds']['TEXTO'],vacios=s['kinds']['VACIO'],marcadores_literales=s['kinds']['MARCADOR_LITERAL'],
            longitud_maxima_caracteres=s['max_length'],longitud_maxima_utf16=s['max_utf16'],
            ceros_iniciales=s['leading_zeros'],digitos_significativos_max=s['max_significant'],
            minimo=str(s['min']) if s['min'] is not None else '',maximo=str(s['max']) if s['max'] is not None else '',
            ejemplos=json.dumps(s['samples'],ensure_ascii=False),ejemplos_no_numericos=json.dumps(s['text_examples'],ensure_ascii=False),
            fundamento=why,aprobado='NO'))
    def write(filename,data,columns=None):
        import csv
        with (output/filename).open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fieldnames=columns or list(data[0]),delimiter=';');w.writeheader();w.writerows(data)
    write('revision_2185_campos.csv',report_rows)
    write('cobertura_rutas.csv',coverage)
    issue_rows=[dict(archivo=k[0],ruta=k[1],geometria=k[2],motivo=m,detalle=d,ejemplo=issue_examples[k,m,d],ocurrencias=n) for (k,m,d),n in issues.items()]
    write('incidencias.csv',issue_rows,['archivo','ruta','geometria','motivo','detalle','ejemplo','ocurrencias'])
    class_rows=[]
    for cls in sorted(classes):
        rr=[r for r in report_rows if r['clase']==cls]
        cc=[r for r in coverage if r['clase']==cls]
        class_rows.append(dict(clase=cls,campos_provisionales=len(rr),campos_cobertura_completa=sum(r['cobertura'].startswith('COMPLETA') for r in rr),
            candidatos_double=sum(r['propuesta']=='CANDIDATO_DOUBLE' for r in rr),candidatos_long=sum(r['propuesta']=='CANDIDATO_LONG' for r in rr),
            fuentes_ausentes=' | '.join(sorted({r['archivo'] for r in cc if r['estado']=='FUENTE_AUSENTE'})),
            rutas_con_diferencias=sum(r['estado']=='DIFERENCIA' for r in cc),asignaciones_observadas=sum(r['observados'] for r in cc)))
    write('resumen_75_clases.csv',class_rows)
    report=dict(modelo_sha256=digest(MODEL/'esquema.json'),fuentes=sources,fuentes_ausentes=missing,
        clases=len(classes),definiciones_perfiladas=len(report_rows),rutas_inventariadas=len(coverage),
        rutas_fuente_ausente=sum(r['estado']=='FUENTE_AUSENTE' for r in coverage),rutas_con_diferencias=sum(r['estado']=='DIFERENCIA' for r in coverage),
        asignaciones_esperadas=sum(r['esperados'] for r in coverage),asignaciones_observadas=sum(found.values()),
        propuestas=dict(Counter(r['propuesta'] for r in report_rows)),campos_cobertura_incompleta=sum(r['cobertura']=='INCOMPLETA' for r in report_rows),
        campos_superan_longitud_actual=sum('SUPERA_LONGITUD_ACTUAL' in r['bloqueos'] for r in report_rows),
        campos_con_conflictos=len(conflicts),incidencias_agrupadas=len(issues),incidencias_por_tipo=dict(Counter({m:sum(n for (k,x,d),n in issues.items() if x==m) for _,m,_ in issues})),
        cambios_en_modelo=False,cambios_en_sde=False,alcance='Borrador de tipos de atributos propios pendientes. No aprueba mapeos, fechas, unidades ni conversiones. No deduplica entidades, no elimina atributos ni trunca datos de origen. Ejemplos del informe se limitan a250caracteres; longitudes se miden completas.')
    (output/'resultado.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='fuentes'},ensure_ascii=True,indent=2))
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--kmz-dir',action='append',default=[])
    p.add_argument('--salida',default=str(ROOT/'02_entregas/Revision_Tipos_Datos_Proyecto'))
    args=p.parse_args()
    run(args.kmz_dir or [ROOT/'01_fuentes'],args.salida)
