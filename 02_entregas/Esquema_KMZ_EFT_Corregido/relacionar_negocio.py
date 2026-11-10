"""Crea los vinculos componente/alternativa/trazado declarados en esquema.json.

Sin --aplicar solo comprueba datos y estructura. Nunca crea tablas padre ni FK SQL.
"""
import argparse
import json
import os
from pathlib import Path
import re

from crear_esquema import inspect,require,qualified,simple


def values(a,path,name,primary=False):
    fields={f.name.lower():f for f in a.ListFields(path)}
    require(name.lower() in fields,f'Falta la llave {path}.{name}')
    field=fields[name.lower()];found=set()
    with a.da.SearchCursor(path,[field.name]) as cursor:
        for (value,) in cursor:
            require(value is not None and (not isinstance(value,str) or value.strip()),f'Llave vacia en {path}.{name}')
            value=value.rstrip() if isinstance(value,str) else value
            if primary:require(value not in found,f'Llave padre duplicada en {path}.{name}: {value!r}')
            found.add(value)
    return field,found


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--workspace',required=True)
    p.add_argument('--database',default='ArcGisAWS')
    p.add_argument('--owner',default='gis')
    p.add_argument('--destino',action='append')
    p.add_argument('--aplicar',action='store_true')
    args=p.parse_args(argv)
    require(all(re.fullmatch('[A-Za-z_][A-Za-z0-9_]*',v) for v in (args.database,args.owner)),'Base/propietario invalidos.')
    model=json.loads((Path(__file__).parent/'esquema.json').read_text(encoding='utf-8'))
    all_rel=model['relaciones_negocio']
    require(not args.destino or set(args.destino)<={r['destino'] for r in all_rel},'Destino no declarado en las relaciones de negocio.')
    relations=[r for r in all_rel if not args.destino or r['destino'] in args.destino]
    selected=[c for c in model['clases'] if c['nombre'] in {r['destino'] for r in relations}]
    import arcpy as a
    with a.EnvManager(overwriteOutput=False):
        inv,_=inspect(a,args,model,selected)
        pending=[]
        for r in relations:
            require(r['origen'].lower() in inv and r['destino'].lower() in inv,
                    f'Faltan participantes: {r["origen"]} -> {r["destino"]}. Complete la migracion; no se crean sustitutos.')
            parent,child=inv[r['origen'].lower()],inv[r['destino'].lower()]
            pd,cd=a.Describe(parent),a.Describe(child)
            require(getattr(pd,'hasOID',False) and getattr(cd,'hasOID',False),'Ambos participantes deben estar registrados en la geodatabase.')
            require(bool(getattr(pd,'isVersioned',False))==bool(getattr(cd,'isVersioned',False)),'Versionado distinto entre participantes.')
            if getattr(pd,'isVersioned',False):
                require(getattr(pd,'isBranchVersioned',False) and getattr(cd,'isBranchVersioned',False),'Se requiere branch en ambos participantes.')
            pf,pk=values(a,parent,r['clave_origen'],True)
            cf,fk=values(a,child,r['clave_destino'])
            require(pf.type==cf.type and (pf.type!='String' or pf.length==cf.length),'Tipos/longitudes de llaves incompatibles.')
            require(fk<=pk,f'{r["destino"]}: hay referencias sin padre.')
            path=os.path.join(args.workspace,qualified(r['nombre'],args))
            if a.Exists(path):
                d=a.Describe(path)
                require(d.cardinality=='OneToMany' and not d.isComposite and not d.isAttributed,'Relacion existente de otro tipo.')
                require([simple(n).lower() for n in d.originClassNames]==[r['origen'].lower()] and
                        [simple(n).lower() for n in d.destinationClassNames]==[r['destino'].lower()],'Relacion existente con otros participantes.')
                keys={k[1]:k[0].lower() for k in d.originClassKeys}
                require(keys.get('OriginPrimary')==r['clave_origen'].lower() and keys.get('OriginForeign')==r['clave_destino'].lower(),'Relacion existente con otras llaves.')
            else:pending.append((r,parent,child,path))
        print(f'Relaciones de negocio validadas: {len(relations)}; nuevas: {len(pending)}',flush=True)
        if args.aplicar:
            for r,parent,child,path in pending:
                a.management.CreateRelationshipClass(parent,child,path,'SIMPLE',r['destino'],r['origen'],'NONE','ONE_TO_MANY','NONE',r['clave_origen'],r['clave_destino'])
                print('CREADA:',r['nombre'],flush=True)


if __name__=='__main__':main()
