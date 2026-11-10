"""Creacion de esquema por herramientas nativas ArcGIS. Sin --aplicar solo consulta.

No carga datos, no borra objetos y no agrega PK/UNIQUE/FK SQL. Las relaciones
de geodatabase se crean en una fase separada despues de verificar las llaves.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
TYPE = {'TEXT':'String', 'LONG':'Integer', 'SHORT':'SmallInteger', 'DOUBLE':'Double', 'DATE':'Date'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def simple(name):
    return name.rsplit('.',1)[-1]


def qualified(name, args):
    return f'{args.database}.{args.owner}.{name}' if args.workspace.lower().endswith('.sde') else name


def find_objects(a, args):
    result = {}
    with a.EnvManager(workspace=args.workspace):
        datasets = a.ListDatasets(feature_type='Feature') or []
        for ds in [''] + datasets:
            if ds:
                result_key(a, args, result, ds, os.path.join(args.workspace,ds))
            for fc in a.ListFeatureClasses(feature_dataset=ds) or []:
                result_key(a,args,result,fc,os.path.join(args.workspace,ds,fc))
        for table in a.ListTables() or []:
            result_key(a,args,result,table,os.path.join(args.workspace,table))
    return result


def result_key(a,args,result,name,path):
    if args.workspace.lower().endswith('.sde'):
        parts=name.split('.')
        if len(parts)<2 or parts[-2].lower()!=args.owner.lower():
            return
    key=simple(name).lower()
    require(key not in result or result[key]==path, f'Nombre ambiguo: {name}')
    result[key]=path


def field_base_name(field):
    """ArcGIS puede calificar AREA con base/esquema/tabla en SDE."""
    base = getattr(field, 'baseName', None)
    return base if isinstance(base, str) and base else simple(field.name)


def field_index(fields):
    result = {}
    for field in fields:
        key = field_base_name(field).casefold()
        require(key not in result, f'Nombre base de campo ambiguo: {key}. No se elige una columna automaticamente.')
        result[key] = field
    return result


def validate_fields(a,path,fields):
    listed = a.ListFields(path)
    actual = field_index(listed)
    missing = [f['nombre'] for f in fields if f['nombre'].casefold() not in actual]
    require(not missing, f'{path}: faltan campos: {", ".join(missing)}. No se modifica el objeto existente. '
            + 'Campos observados (nombre -> base): '
            + '; '.join(f'{x.name} -> {field_base_name(x)}' for x in listed))
    for f in fields:
        x=actual[f['nombre'].casefold()]
        require(x.type==TYPE[f['tipo']], f'{path}.{x.name}: tipo {x.type}, esperado {TYPE[f["tipo"]]}.')
        if f['tipo']=='TEXT':
            require(x.length>=f['longitud'], f'{path}.{x.name}: longitud insuficiente ({x.length}).')
        if not f['nullable']:
            require(not x.isNullable, f'{path}.{x.name}: el esquema requiere NOT NULL.')
        if f.get('dominio'):
            require(x.domain==f['dominio'], f'{path}.{x.name}: dominio distinto de {f["dominio"]}.')


def parent_keys(a,path,key):
    f=field_index(a.ListFields(path)).get(key.casefold())
    require(f is not None and f.type=='String', f'{path}.{key} debe existir y ser Texto.')
    keys=set()
    folded=set()
    with a.da.SearchCursor(path,[key]) as cursor:
        for (value,) in cursor:
            require(value is not None and value.strip(), f'{path}: codigo de proyecto vacio.')
            # nchar puede devolver relleno derecho. No modificar el dato fuente.
            normalized=value.rstrip()
            require(normalized.casefold() not in folded, f'{path}: codigo duplicado {normalized!r}.')
            keys.add(normalized)
            folded.add(normalized.casefold())
    return f,keys


def validate_names(a, workspace, classes):
    """Revisar todos los nombres del lote y reportar juntos los incompatibles."""
    invalid = []
    cache = {}
    for c in classes:
        proposed = a.ValidateTableName(c['nombre'], workspace)
        if proposed != c['nombre']:
            invalid.append(f'Clase {c["nombre"]}; ArcGIS propone {proposed!r}')
        for f in c['campos']:
            name = f['nombre']
            if name not in cache:
                cache[name] = a.ValidateFieldName(name, workspace)
            if cache[name] != name:
                invalid.append(f'{c["nombre"]}.{name}; ArcGIS propone {cache[name]!r}')
    require(not invalid, 'Nombres no validos en el destino (sin cambios):\n' + '\n'.join(invalid))


def inspect(a,args,model,classes):
    exists=a.Exists(args.workspace)
    remote=args.workspace.lower().endswith('.sde')
    require(exists or args.workspace.lower().endswith('.gdb'), 'Se requiere una conexion .sde existente o una ruta .gdb.')
    if not exists:
        require(Path(args.workspace).parent.is_dir(), 'La carpeta padre de la geodatabase no existe.')
        return {},[]
    wd=a.Describe(args.workspace)
    require(wd.workspaceType==('RemoteDatabase' if remote else 'LocalDatabase'), 'Tipo de workspace no admitido.')
    if remote:
        cp=wd.connectionProperties
        require(str(cp.database).lower()==args.database.lower(), 'La conexion apunta a otra base de datos.')
        user=str(getattr(cp,'user',''))
        require(user.lower()==args.owner.lower(), 'Use la conexion del propietario indicado en --owner.')
    validate_names(a, args.workspace, classes)
    inv=find_objects(a,args)
    naming_path=HERE/'nombres_clases_1_6.json'
    if naming_path.exists():
        selected={c['nombre'] for c in classes}
        for row in json.loads(naming_path.read_text(encoding='utf-8'))['clases']:
            if row['nombre_nuevo'] in selected and row['nombre_anterior']!=row['nombre_nuevo']:
                require(row['nombre_anterior'].casefold() not in inv,
                    f"{row['nombre_anterior']}: ejecute primero Normalizar nombres de Datos_Proyecto; "
                    'no se crea una clase duplicada con el nombre nuevo.')
    for ds in model['datasets']:
        if ds.lower() in inv:
            d=a.Describe(inv[ds.lower()])
            require(d.spatialReference.factoryCode==4326, f'{ds}: referencia distinta de EPSG:4326.')
    for c in classes:
        path=inv.get(c['nombre'].lower())
        if not path:
            ds=inv.get(c['dataset'].lower())
            require(not ds or not getattr(a.Describe(ds),'isVersioned',False),
                    'Agregar clases a un dataset ya versionado requiere un procedimiento de administracion especifico.')
            continue
        d=a.Describe(path)
        require(d.dataType=='FeatureClass', f'{c["nombre"]} existe como tabla; completar su migracion a feature class.')
        require(simple(Path(d.path).name).lower()==c['dataset'].lower(), f'{c["nombre"]} esta fuera de {c["dataset"]}.')
        require(d.shapeType.lower()==c['geometria'].lower() and d.spatialReference.factoryCode==4326,
                f'{c["nombre"]}: geometria o referencia incompatible.')
        require(d.hasZ, f'{c["nombre"]}: falta soporte Z.')
        validate_fields(a,path,c['campos'])
        require(d.hasGlobalID, f'{c["nombre"]}: falta GlobalID.')
        if c['relacion_proyecto']:
            require(d.editorTrackingEnabled and getattr(d,'isTimeInUTC',False), f'{c["nombre"]}: falta Editor Tracking UTC.')
    domains={x.name:x for x in a.da.ListDomains(args.workspace)}
    for name,spec in model['dominios'].items():
        if name in domains:
            d=domains[name]
            require(d.domainType=='CodedValue' and d.type=='Text', f'Dominio incompatible: {name}')
            require(all(d.codedValues.get(v)==v for v in spec['valores']), f'Dominio {name}: faltan valores o sus descripciones difieren.')
    return inv,domains


def create(a,args,model,classes,inv,domains):
    if not a.Exists(args.workspace):
        a.management.CreateFileGDB(str(Path(args.workspace).parent),Path(args.workspace).name)
    for name,spec in model['dominios'].items():
        if name not in domains:
            a.management.CreateDomain(args.workspace,name,spec['descripcion'],'TEXT','CODED')
            for value in spec['valores']:
                a.management.AddCodedValueToDomain(args.workspace,name,value,value)
    for ds in model['datasets']:
        if ds.lower() not in inv:
            inv[ds.lower()]=a.management.CreateFeatureDataset(args.workspace,ds,a.SpatialReference(4326)).getOutput(0)
    for c in classes:
        if c['nombre'].lower() in inv:
            print('VALIDADA existente:',c['nombre'],flush=True)
            continue
        ds=inv[c['dataset'].lower()]
        require(not getattr(a.Describe(ds),'isVersioned',False), 'Agregar clases a un dataset ya versionado requiere un procedimiento de administracion especifico.')
        result=a.management.CreateFeatureclass(ds,c['nombre'],c['geometria'],has_z='ENABLED',spatial_reference=a.SpatialReference(4326))
        path=result.getOutput(0)
        # Algunos resultados GP devuelven una salida vacia pese a crear la clase.
        # Resolver el objeto real antes de agregar campos, sin repetir la creacion.
        if not path:
            path=find_objects(a,args).get(c['nombre'].lower())
        require(path and a.Exists(path), f'{c["nombre"]}: ArcGIS no devolvio una clase existente tras crearla.')
        nullable=[f for f in c['campos'] if f['nullable']]
        if nullable:
            a.management.AddFields(path,[[f['nombre'],f['tipo'],f['alias'],f['longitud'],None,f['dominio']] for f in nullable])
        for f in c['campos']:
            if not f['nullable']:
                a.management.AddField(path,f['nombre'],f['tipo'],field_length=f['longitud'],
                                      field_alias=f['alias'],field_is_nullable='NON_NULLABLE',field_domain=f['dominio'] or '')
        a.management.AddGlobalIDs(path)
        if c['relacion_proyecto']:
            a.management.EnableEditorTracking(path,'created_user','created_date','last_edited_user','last_edited_date','ADD_FIELDS','UTC')
        if c.get('alias'):
            a.AlterAliasName(path,c['alias'])
        print('CREADA:',c['dataset']+'/'+c['nombre'],flush=True)


def relations(a,args,model,classes,inv):
    parent=inv.get(model['tabla_proyecto'].lower())
    require(parent is not None, 'Falta mline_tc_proyecto en el mismo workspace y propietario. Este paquete no crea una tabla de proyectos vacia.')
    parent_desc=a.Describe(parent)
    require(getattr(parent_desc,'hasOID',False), 'Registre la tabla padre en la geodatabase antes de relacionarla.')
    pk,keys=parent_keys(a,parent,model['clave_proyecto'])
    pending=[]
    for c in classes:
        if not c['relacion_proyecto']:
            continue
        child=inv.get(c['nombre'].lower())
        require(child is not None, f'Falta la clase {c["nombre"]}; ejecute crear primero.')
        d=a.Describe(child)
        require(bool(getattr(d,'isVersioned',False))==bool(getattr(parent_desc,'isVersioned',False)), 'Padre e hija deben tener el mismo versionado.')
        if getattr(d,'isVersioned',False):
            require(getattr(d,'isBranchVersioned',False) and getattr(parent_desc,'isBranchVersioned',False), 'El EFT requiere branch en ambos lados.')
        fk=field_index(a.ListFields(child))['proyecto']
        require(fk.type==pk.type and fk.length==pk.length, 'Iguale longitud/tipo de proyecto con co_proyecto antes de relacionar.')
        with a.da.SearchCursor(child,['proyecto','id_analisis']) as cursor:
            for code,analysis in cursor:
                require(code is not None and code.rstrip() in keys, f'{c["nombre"]}: proyecto inexistente o codigo no exacto {code!r}.')
                require(analysis is not None and analysis.strip(), f'{c["nombre"]}: id_analisis vacio.')
        spec = next((r for r in model.get('relaciones', [])
                     if r['destino'] == c['nombre'] and r['origen'] == model['tabla_proyecto']), None)
        require(spec is not None, f'{c["nombre"]}: falta definicion de relacion en el modelo.')
        name=spec['nombre']
        path=os.path.join(args.workspace,qualified(name,args))
        if a.Exists(path):
            rd=a.Describe(path)
            require(rd.cardinality=='OneToMany' and not rd.isComposite and not rd.isAttributed,
                    f'{name}: relacion existente incompatible.')
            require([simple(n).lower() for n in rd.originClassNames]==[model['tabla_proyecto'].lower()] and
                    [simple(n).lower() for n in rd.destinationClassNames]==[c['nombre'].lower()], f'{name}: participantes diferentes.')
            rk={str(k[1]):str(k[0]).lower() for k in rd.originClassKeys}
            require(rk.get('OriginPrimary')=='co_proyecto' and rk.get('OriginForeign')=='proyecto',f'{name}: llaves diferentes.')
        else:
            pending.append((parent,child,path,c['nombre']))
    print(f'Relaciones nuevas: {len(pending)}',flush=True)
    if args.aplicar:
        for parent,child,path,label in pending:
            a.management.CreateRelationshipClass(parent,child,path,'SIMPLE',label,'Proyecto','NONE','ONE_TO_MANY','NONE','co_proyecto','proyecto')
            print('RELACION CREADA:',label,flush=True)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace',help='Geodatabase .gdb o conexion propietaria .sde')
    parser.add_argument('--database',default='ArcGisAWS')
    parser.add_argument('--owner',default='gis')
    parser.add_argument('--clase',action='append',help='Repetible. Sin este parametro, todas las clases.')
    parser.add_argument('--accion',choices=['crear','relacionar'],default='crear')
    parser.add_argument('--aplicar',action='store_true')
    args=parser.parse_args(argv)
    model=json.loads((HERE/'esquema.json').read_text(encoding='utf-8'))
    names={c['nombre'] for c in model['clases']}
    require(not args.clase or set(args.clase)<=names, 'Nombre de clase desconocido.')
    classes=[c for c in model['clases'] if not args.clase or c['nombre'] in args.clase]
    require(all(re.fullmatch('[A-Za-z_][A-Za-z0-9_]*',v) for v in (args.database,args.owner)), 'Base/propietario invalidos.')
    print(f'Accion: {args.accion}; clases: {len(classes)}; aplicar: {args.aplicar}',flush=True)
    if not args.workspace:
        require(not args.aplicar, 'Indique --workspace para aplicar.')
        for c in classes:
            print(c['dataset']+'/'+c['nombre'],c['geometria'],len(c['campos']),'campos')
        return
    import arcpy as a
    with a.EnvManager(overwriteOutput=False):
        inv,domains=inspect(a,args,model,classes)
        # La longitud depende del padre real, si ya esta disponible.
        parent=inv.get(model['tabla_proyecto'].lower())
        if parent:
            pk,_=parent_keys(a,parent,model['clave_proyecto'])
            require(pk.length==12, f'co_proyecto tiene longitud {pk.length}; ajustar el esquema a la tabla real antes de crear.')
        if args.accion=='relacionar':
            relations(a,args,model,classes,inv)
        elif args.aplicar:
            create(a,args,model,classes,inv,domains)
            inspect(a,args,model,classes)
        else:
            print('Prevalidacion terminada; no se hicieron cambios.',flush=True)


if __name__=='__main__':
    main()
