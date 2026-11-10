"""Consolida el esquema con reglas EFT por ruta y conserva todos los pendientes."""
from __future__ import annotations
import ast
import collections
import copy
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import zipfile

from normalizacion_kmz import snake_case, spelling_index, destination
from generar_esquema_kmz_descripcion import SYSTEM
from reglas_kmz_eft_corregido import classify, metadata, norm
from aplicar_nombres_clases import (load_baseline, apply_model_policy, retarget_rows,
                                   retarget_approval, save_mapping, retarget_existing_csv)
from nombres_clases_kmz import MAX_CLASS_NAME, NAMES
from aplicar_confirmacion_textos import load_verified_review, apply_text_confirmation
from fuentes_inventario_verificadas import read_inventory_bytes

ROOT=Path(__file__).resolve().parents[1]
SRC=ROOT/'inventario_kmz_resumen'
OLD=ROOT/'02_entregas/Esquema_KMZ_EFT'
OUT=ROOT/'02_entregas/Esquema_KMZ_EFT_Corregido'
GEOM={'Punto':'POINT','Línea':'POLYLINE','Polígono':'POLYGON'}
SUFFIX={'Punto':'punto','Línea':'linea','Polígono':'poligono'}
KEY=('archivo','ruta','geometria','descripcion')


def read(name):
    with io.StringIO(read_inventory_bytes(ROOT, name).decode('utf-8-sig'), newline='') as f:
        return list(csv.DictReader(f,delimiter=';'))


def write_csv(name,rows):
    assert rows, name
    with (OUT/name).open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]),delimiter=';');w.writeheader();w.writerows(rows)


def key(row): return tuple(row[k] for k in KEY)


def physical(base,role,g,multiple):
    # Identificador historico para enlazar el modelo 1.5.1 y sus decisiones de
    # tipos. La politica explicita 1.6 se aplica despues, antes de emitir archivos.
    if role=='migrada': return base
    suffix=('_'+SUFFIX[g] if multiple else '')+('_recorte' if role=='recorte' else '')
    name=base+suffix
    if len(name)>50:
        name=base[:50-len(suffix)-9].rstrip('_')+'_'+hashlib.sha256(name.encode()).hexdigest()[:8]+suffix
    return name


def field(name,typ='TEXT',length=4000,origin=None,nullable=True):
    if not origin:
        raise ValueError(f'El campo {name} requiere fundamento explicito; no se agregan extensiones.')
    return dict(nombre=name,tipo=typ,longitud=length,alias=name,dominio=None,nullable=nullable,origen=origin)


def build():
    current_path = OUT / 'esquema.json'
    if current_path.exists() and json.loads(current_path.read_text(encoding='utf-8-sig')).get('version', 0) >= 12:
        raise ValueError('El modelo vigente ya tiene cierre 1.9. Este generador historico llega al modelo 11 '
                         'y no puede sobrescribirlo. Use preparar_cierre_tipos_1_9.py para reproducir el cierre aprobado.')
    OUT.mkdir(exist_ok=True)
    previous_names=set()
    if (OUT/'esquema.json').exists():
        previous_names={c['nombre'] for c in json.loads((OUT/'esquema.json').read_text(encoding='utf-8'))['clases']}
    matrix=read('inventario_kmz_matriz_campos.csv');layers=read('inventario_kmz_capas.csv');occurrences=read('inventario_kmz_campos.csv')
    spellings=spelling_index(occurrences)
    previous=json.loads((OLD/'esquema.json').read_text(encoding='utf-8'))
    migration=json.loads((ROOT/'02_entregas/ArcGisAWS_Carga_Mapline/modelo_eft.json').read_text(encoding='utf-8'))
    lookup={key(r):r for r in layers}; assert len(lookup)==len(layers)
    decisions={k:classify(r) for k,r in lookup.items()}
    geometries=collections.defaultdict(set)
    for k,d in decisions.items():
        if d['base']: geometries[d['base'],d['rol']].add(k[2])
    names={k:physical(d['base'],d['rol'],k[2],len(geometries[d['base'],d['rol']])>1) if d['base'] else '' for k,d in decisions.items()}
    reference=next(c for c in previous['clases'] if c['nombre']=='PredioSUNARP_Recorte')
    common=[copy.deepcopy(f) for f in reference['campos'] if f['origen']!='Matriz KMZ: valor textual' and f['nombre']!='area_ha']
    classes={}
    for k,d in decisions.items():
        name=names[k]
        if not name or name in classes: continue
        if d['rol']=='migrada':
            c=copy.deepcopy(next(c for c in previous['clases'] if c['nombre']==name))
            c['campos']=[f for f in c['campos'] if f['nombre'] not in ('tema','id_origen','capa_origen') or f['origen'].startswith('DDL MapLine')]
            c['tipo']='migrada';c['rol']='migrada';c['descripciones']=[]
        else:
            fields=copy.deepcopy(common)
            if d['rol']!='recorte': fields=[f for f in fields if f['nombre'] not in ('capa_origen','tema','id_origen')]
            if k[2] in ('Línea','Polígono'):
                fields.append(field('longitud_m' if k[2]=='Línea' else 'area_ha','DOUBLE',None,'EFT 5.8.7'))
            c=dict(nombre=name,dataset='Datos_Proyecto',geometria=GEOM[k[2]],campos=fields,relacion_proyecto=True,
                   tipo='nueva',rol=d['rol'],origen='Matriz CSV revisada por tema y ruta conforme EFT',descripciones=[])
        # EFT 5.8.6 requiere el codigo de estacion en AreaEstudioCampo,
        # no en el bloque comun ni en Estructuras.
        if name=='area_estudio_campo':
            c['campos'].append(field('codigo_estacion','TEXT',80,'EFT 5.8.6: codigo de estacion en AreaEstudioCampo'))
        c['clase_eft']=d['clase_eft'];c['maestro_dataset']=d['maestro_dataset']
        classes[name]=c
    for k,name in names.items():
        if name and k[3] not in classes[name]['descripciones']: classes[name]['descripciones'].append(k[3])

    # Atributos por ocurrencia/ruta, para no trasladar campos de accesos a trazados.
    occurrence_map=[];matrix_targets=collections.defaultdict(set);examples=collections.defaultdict(list)
    core={n:{f['nombre']:f for f in c['campos']} for n,c in classes.items()}
    origins={}
    for row in occurrences:
        k=key(row); assert k in lookup
        dest=names[k];source=row['campo_normalizado'];target='';conversion='';state='PENDIENTE_DESTINO';rule='SIN_DESTINO'
        if SYSTEM.fullmatch(source): state='OMITIR_CAMPO_SISTEMA';rule='SISTEMA_OMITIDO'
        elif dest:
            target,rule,conversion=destination(row,lookup[k],dest,core[dest],spellings)
            target=snake_case(target)
            existing={f['nombre'].lower():f for f in classes[dest]['campos']}
            is_ddl=target.lower() in existing and existing[target.lower()]['origen'].startswith('DDL MapLine')
            if is_ddl: target=existing[target.lower()]['nombre']
            field_key=(dest,target.lower())
            signature=target if rule.startswith('ALIAS_') else spellings.get(source,snake_case(row['campo']))
            if target not in core[dest] and field_key in origins and origins[field_key]!=signature:
                target=target[:46]+'_'+hashlib.sha256(source.encode()).hexdigest()[:8];field_key=(dest,target.lower())
                rule='COLISION_NORMALIZACION';conversion+=' Colision de nombres distinguida con sufijo estable; no se fusionan atributos diferentes.'
            origins[field_key]=signature
            if target.lower() not in {f['nombre'].lower() for f in classes[dest]['campos']}:
                f=field(target,origin='Atributo KMZ; texto conservador pendiente de revision de tipo')
                f['campo_fuente']=source;classes[dest]['campos'].append(f)
            spec=next(f for f in classes[dest]['campos'] if f['nombre']==target)
            source_names=spec.setdefault('campos_fuente',[])
            if source not in source_names:source_names.append(source)
            state='MAPEADO_DDL_REVISAR_CONVERSION' if is_ddl else 'MAPEADO_COMUN_VALIDAR_VALORES' if target in core[dest] else 'MAPEADO_REVISAR_TIPO'
            if row['ejemplo_valor'] and row['ejemplo_valor'] not in examples[dest,target]: examples[dest,target].append(row['ejemplo_valor'])
        matrix_targets[row['descripcion'],row['geometria'],source].add((dest,target,state,conversion))
        occurrence_map.append(dict(archivo=row['archivo'],ruta=row['ruta'],descripcion=row['descripcion'],geometria=row['geometria'],
                                   campo_fuente=source,campo_original=row['campo'],clase_destino=dest,campo_destino=target,estado=state,regla=rule,conversion=conversion,
                                   evidencia_nombre=lookup[k]['nombre_viene_del_campo'],ejemplo_valor=row['ejemplo_valor'],ejemplo_nombre=lookup[k]['ejemplo_nombre']))
    approved=json.loads((ROOT/'03_scripts/tipos_estructuras_aprobados.json').read_text(encoding='utf-8'))
    profile_path=ROOT/'02_entregas/Revision_Tipos_Estructuras/resultado.json'
    assert hashlib.sha256(profile_path.read_bytes()).hexdigest()==approved['perfil_sha256'], 'El perfil cambio: revisar de nuevo la decision de tipos.'
    for source in approved['fuentes']:
        assert hashlib.sha256((ROOT/'01_fuentes/kmz'/source['archivo']).read_bytes()).hexdigest()==source['sha256'], 'Cambio un KMZ del perfil aprobado.'
    target_class=classes[approved['clase']]
    own={f['nombre']:f for f in target_class['campos'] if f.get('campo_fuente')}
    assert set(own)==set(approved['campos'])
    for name,definition in approved['campos'].items():
        own[name].update(tipo=definition['tipo'],longitud=definition['longitud'],
                         origen='Atributo KMZ; tipo confirmado mediante perfil de valores y decision del usuario',
                         tipo_confirmado=True,evidencia_tipo='tipos_estructuras_aprobados.json')
    for row in occurrence_map:
        if row['clase_destino']==approved['clase'] and row['campo_destino'] in own:
            row['estado']='MAPEADO_TIPO_CONFIRMADO'
    general=json.loads((ROOT/'03_scripts/campos_aprobados_1_5.json').read_text(encoding='utf-8'))
    profile_general=ROOT/'02_entregas/Revision_Tipos_Datos_Proyecto/resultado.json'
    assert hashlib.sha256(profile_general.read_bytes()).hexdigest()==general['perfil_sha256'], 'Cambio el perfil general; revisar la decision de tipos.'
    for source in general['fuentes']:
        assert hashlib.sha256((ROOT/source['ruta_relativa']).read_bytes()).hexdigest()==source['sha256'], 'Cambio un KMZ del perfil general.'
    confirmed=set()
    for change in general['cambios']:
        spec=next(f for f in classes[change['clase']]['campos'] if f['nombre']==change['campo'])
        assert spec.get('campo_fuente') and spec['tipo']==change['tipo_anterior'] and spec['longitud']==change['longitud_anterior']
        spec.update(tipo=change['tipo_objetivo'],longitud=change['longitud_objetivo'],
                    origen='Atributo KMZ; tipo y capacidad confirmados mediante perfil completo y decision del usuario',
                    tipo_confirmado=True,evidencia_tipo='campos_aprobados_1_5.json')
        confirmed.add((change['clase'],change['campo']))
    for row in occurrence_map:
        if (row['clase_destino'],row['campo_destino']) in confirmed:
            row['estado']='MAPEADO_TIPO_CONFIRMADO'
    field_map=[]
    for i,row in enumerate(matrix,1):
        targets=matrix_targets.get((row['descripcion'],row['geometria'],row['campo_normalizado'])) or {('','','SIN_OCURRENCIA_LOCALIZADA','Revisar matriz frente al detalle de campos.')}
        for dest,target,state,conversion in sorted(targets):
            spec=next((f for f in classes[dest]['campos'] if f['nombre']==target),None) if dest and target else None
            if spec and spec.get('tipo_confirmado'):
                state='MAPEADO_TIPO_CONFIRMADO'
            field_map.append(dict(fila_matriz=i,descripcion=row['descripcion'],geometria=row['geometria'],campo_fuente=row['campo_normalizado'],
                                  variantes=row['variantes_del_nombre'],clase_destino=dest,campo_destino=target,
                                  tipo=spec['tipo'] if spec else '',longitud=spec['longitud'] if spec else '',estado=state,conversion=conversion))

    review=[];counts=collections.Counter()
    for i,row in enumerate(layers,1):
        k=key(row);d=decisions[k];dest=names[k];meta=metadata(row)
        project=Path(row['archivo'].replace('\\','/')).stem;counts[dest,project]+=int(row['elementos'])
        ref_origin=d['base'] if d['rol']=='recorte' else ''
        if d['rol']=='recorte' and len(geometries[d['base'],d['rol']])>1: ref_origin+='_'+SUFFIX[row['geometria']]
        review.append(dict(fila_capas=i,archivo=row['archivo'],ruta=row['ruta'],descripcion=row['descripcion'],geometria=row['geometria'],
                           elementos=int(row['elementos']),clase_propuesta=dest,rol=d['rol'],dataset_propuesto='Datos_Proyecto' if dest else '',
                           clase_eft=d['clase_eft'],maestro_dataset=d['maestro_dataset'],capa_origen_propuesta=ref_origin,
                           **meta,co_proyecto='',id_analisis='',id_proyecto_componente='',id_proyecto_alternativa='',id_proyecto_infraestructura='',
                           incluir='',clase_confirmada='',estado='REVISAR_MAPEO' if dest else 'PENDIENTE_DESTINO',motivo=d['motivo']))
    projects=sorted({p for _,p in counts});catalog=[]
    for name,c in sorted(classes.items()):
        row=dict(clase=name,dataset=c['dataset'],rol=c['rol'],geometria=c['geometria'],
                 descripciones_origen=' | '.join(sorted(c['descripciones'])),campos=len(c['campos']),
                 elementos_propuestos=sum(counts[name,p] for p in projects))
        row.update({p:counts[name,p] for p in projects});catalog.append(row)
    group_targets=collections.defaultdict(set)
    for r in review: group_targets[r['descripcion'],r['geometria']].add(r['clase_propuesta'])
    before=json.loads((ROOT/'02_entregas/Esquema_KMZ_CSV/esquema.json').read_text(encoding='utf-8'))
    changes=[]
    for c in before['clases']:
        desc=c['descripciones'][0];g=next(k for k,v in GEOM.items() if v==c['geometria'])
        targets=group_targets[desc,g]
        changes.append(dict(clase_anterior=c['nombre'],descripcion=desc,geometria=g,
                            clases_corregidas=' | '.join(sorted(t for t in targets if t)),
                            tiene_rutas_pendientes='SI' if '' in targets else 'NO',
                            criterio='Destino por tema y ruta; ver mapeo_capas_revision.csv para cada asignacion.'))
    # Vinculos de negocio migrados: declarar dependencias, sin crear tablas padre ficticias.
    business=[]
    for rel in migration['relations']:
        if rel['child'] in classes and not rel['obsolete'] and rel['parent']!=rel['child'] and rel['parent']!='mline_td_proyecto_capa':
            business.append(dict(nombre='rel_'+rel['name'],origen=rel['parent'],destino=rel['child'],
                                 clave_origen=rel['parent_key'],clave_destino=rel['child_key']))
    if 'vertices' in classes:
        classes['vertices']['campos'].append(field('id_proyecto_infraestructura','LONG',None,'Llave del trazado, EFT 5.8.10',False))
        business.append(dict(nombre='rel_trazado_vertices',origen='mline_td_proyecto_infraestructura',destino='vertices',
                             clave_origen='id_proyecto_infraestructura',clave_destino='id_proyecto_infraestructura'))
    model=dict(version=9,politica_nombres='snake_case; nombres nativos de ArcGIS, datasets EFT y DDL conservados',politica_campos='EFT v2.4: campos aplicables, atributos de origen y DDL; sin extensiones',referencia_espacial=4326,tabla_proyecto='mline_tc_proyecto',clave_proyecto='co_proyecto',
               datasets=previous['datasets'],dominios=previous['dominios'],clases=list(classes.values()),
               relaciones=[dict(nombre='rel_proyecto_'+name,origen='mline_tc_proyecto',destino=name,
                                 clave_origen='co_proyecto',clave_destino='proyecto') for name in classes],
               relaciones_negocio=business,tablas_migradas=previous['tablas_migradas'],
               fuentes={n:hashlib.sha256(read_inventory_bytes(ROOT, n)).hexdigest() for n in ('inventario_kmz_matriz_campos.csv','inventario_kmz_capas.csv','inventario_kmz_campos.csv')})
    # Recalcular conteos de campos tras agregar las llaves de negocio.
    for r in catalog:r['campos']=len(classes[r['clase']]['campos'])
    type_review=[]
    for (dest,target),samples in sorted(examples.items()):
        spec=next(f for f in classes[dest]['campos'] if f['nombre']==target)
        type_review.append(dict(clase=dest,campo=target,tipo_actual=spec['tipo'],longitud_actual=spec['longitud'],
                                ejemplos=json.dumps(samples[:3],ensure_ascii=False),estado='TIPO_CONFIRMADO_PERFIL' if spec.get('tipo_confirmado') else 'REVISAR_VALORES_Y_UNIDADES' if spec['origen'].startswith('DDL') else 'REVISAR_TIPO_Y_LONGITUD' if spec['origen'].startswith('Atributo KMZ') else 'VALIDAR_CORRESPONDENCIA_Y_VALORES',
                                tipo_confirmado=spec['tipo'] if spec.get('tipo_confirmado') else '',longitud_confirmada=spec['longitud'] if spec.get('tipo_confirmado') else '',observacion='Ver perfil completo y decision en tipos_estructuras_aprobados.json' if spec.get('tipo_confirmado') else 'Ejemplos, no perfil completo; no inferir tipo definitivo solo con estos valores.'))
    baseline, baseline_raw = load_baseline(ROOT, OUT)
    assert model == baseline, 'El modelo base cambio mas alla de los nombres; revisar antes de generar la version 1.6.'
    model, naming_rows = apply_model_policy(model)
    model, text_confirmation = apply_text_confirmation(model, load_verified_review(ROOT))
    classes = {c['nombre']: c for c in model['clases']}
    catalog = retarget_rows(catalog, ('clase',))
    aliases = {row['nombre_nuevo']: row['alias'] for row in naming_rows}
    for row in catalog:
        row['alias'] = aliases[row['clase']]
    changes = retarget_rows(changes, (), ('clases_corregidas',))
    review = retarget_rows(review, ('clase_propuesta', 'clase_confirmada'))
    field_map = retarget_rows(field_map, ('clase_destino',))
    occurrence_map = retarget_rows(occurrence_map, ('clase_destino',))
    type_review = retarget_rows(type_review, ('clase',))
    confirmed_text = {(row['clase'], row['campo']) for row in text_confirmation['campos']}
    for row in field_map + occurrence_map:
        if (row['clase_destino'], row['campo_destino']) in confirmed_text:
            row['estado'] = 'MAPEADO_TIPO_CONFIRMADO'
    for row in type_review:
        if (row['clase'], row['campo']) in confirmed_text:
            row.update(estado='TIPO_CONFIRMADO_PERFIL', tipo_confirmado='TEXT',
                longitud_confirmada=4000, observacion='Texto confirmado; ver textos_confirmados_1_7.json. Sin cambio fisico.')
    business = model['relaciones_negocio']
    model_raw = json.dumps(model,ensure_ascii=False,indent=2).encode('utf-8')
    (OUT/'esquema.json').write_bytes(model_raw)
    save_mapping(OUT, naming_rows, baseline_raw, model_raw, model_version=11)
    (OUT/'textos_confirmados_1_7.json').write_text(
        json.dumps(text_confirmation,ensure_ascii=False,indent=2),encoding='utf-8')
    for name,rows in [('catalogo_clases.csv',catalog),('cambios_respecto_csv.csv',changes),('mapeo_capas_revision.csv',review),
                      ('campos_matriz_a_esquema.csv',field_map),('campos_por_ruta.csv',occurrence_map),('revision_tipos.csv',type_review),
                      ('rutas_pendientes.csv',[r for r in review if not r['clase_propuesta']]),('relaciones_negocio.csv',business)]:write_csv(name,rows)
    shutil.copyfile(ROOT/'03_scripts/motor_esquema_arcgis.py',OUT/'crear_esquema.py')
    shutil.copyfile(ROOT/'03_scripts/normalizacion_kmz.py',OUT/'normalizacion_kmz.py')
    shutil.copyfile(ROOT/'03_scripts/tipos_estructuras_aprobados.json',OUT/'tipos_estructuras_aprobados.json')
    (OUT/'campos_aprobados_1_5.json').write_text(
        json.dumps(retarget_approval(general, model_version=11),ensure_ascii=False,indent=2),encoding='utf-8')
    for filename in ('plan_actualizacion_1_5.csv', 'PROPUESTA_MAPEO_OFICINAS.csv'):
        retarget_existing_csv(OUT/filename, ('clase',))
    scripts=OUT/'por_clase';scripts.mkdir(exist_ok=True)
    for name in classes:
        (scripts/(name+'.py')).write_text('import sys\nfrom pathlib import Path\nsys.path.insert(0,str(Path(__file__).resolve().parents[1]))\nfrom crear_esquema import main\nif __name__=="__main__":\n    main(["--clase",'+repr(name)+']+sys.argv[1:])\n',encoding='utf-8')
    for name in previous_names-set(classes):
        path=scripts/(name+'.py')
        assert path.resolve().parent==scripts.resolve()
        if path.exists():
            history=OUT/'_historico_scripts';history.mkdir(exist_ok=True)
            target=history/path.name
            if target.exists():
                # Otra generacion historica puede tener el mismo nombre; guardar
                # en la subcarpeta de esta migracion sin sobrescribir evidencia.
                history=history/'nombres_1_6';history.mkdir(exist_ok=True)
                target=history/path.name
            assert target.resolve().parent==history.resolve() and not target.exists()
            path.rename(target)
    assert {p.stem for p in scripts.glob('*.py')}==set(classes)
    validate(model,matrix,layers,occurrences,review,field_map,occurrence_map,catalog)
    stats=dict(version=11,version_paquete='1.7',clases_anteriores=len(before['clases']),clases_corregidas=len(classes),
                textos_confirmados=1356,campos_tipo_provisional=730,
                clases_renombradas=sum(row['renombrar'] for row in naming_rows),
                clases_nombre_conservado=sum(not row['renombrar'] for row in naming_rows),
                clases_por_rol=dict(collections.Counter(c['rol'] for c in classes.values())),
                relaciones_proyecto=len(classes),relaciones_negocio=len(business),
                filas_matriz=len(matrix),filas_matriz_representadas=len({r['fila_matriz'] for r in field_map}),
                ocurrencias_atributos=len(occurrence_map),grupos_origen=len(review),
                elementos_origen=sum(r['elementos'] for r in review),elementos_con_destino_propuesto=sum(r['elementos'] for r in review if r['clase_propuesta']),
                elementos_pendientes=sum(r['elementos'] for r in review if not r['clase_propuesta']),
                rutas_pendientes=sum(not r['clase_propuesta'] for r in review),campos_para_revision_tipo=len(type_review),
                verificacion_estatica='OK',ejecutado_en_sde=False,clasificacion_aprobada=False)
    (OUT/'VALIDACION.json').write_text(json.dumps(stats,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(stats,ensure_ascii=False,indent=2))


def validate(model,matrix,layers,occurrences,review,field_map,occurrence_map,catalog):
    classes={c['nombre']:c for c in model['clases']}
    assert len(classes)==len(model['clases'])
    assert len(review)==len(layers)==3638 and sum(r['elementos'] for r in review)==279623
    assert len(occurrence_map)==len(occurrences)==9934
    assert {r['fila_matriz'] for r in field_map}==set(range(1,len(matrix)+1))
    assert sum(r['elementos_propuestos'] for r in catalog)==sum(r['elementos'] for r in review if r['clase_propuesta'])
    for c in classes.values():
        assert re.fullmatch('[a-z][a-z0-9_]*',c['nombre']) and len(c['nombre'])<=MAX_CLASS_NAME
        assert c['nombre'] in NAMES.values() and not re.search(r'_[0-9a-f]{8}(?:_|$)',c['nombre'])
        assert c['rol']!='recorte' or c['nombre'].endswith('_recorte')
        assert len({f['nombre'].lower() for f in c['campos']})==len(c['campos'])
        assert all(re.fullmatch('[a-z][a-z0-9]*(?:_[a-z0-9]+)*',f['nombre']) for f in c['campos'])
        assert c['geometria'] in GEOM.values()
    for r in field_map:
        if r['campo_destino']: assert r['campo_destino'] in {f['nombre'] for f in classes[r['clase_destino']]['campos']}
    for path in OUT.rglob('*.py'):ast.parse(path.read_text(encoding='utf-8'))


if __name__=='__main__':build()
