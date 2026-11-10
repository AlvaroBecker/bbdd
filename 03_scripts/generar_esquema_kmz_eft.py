"""Genera definiciones ArcGIS desde el EFT y el inventario; no conecta a SDE."""
from __future__ import annotations

import collections
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import unicodedata

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '02_entregas' / 'Esquema_KMZ_EFT'
SRC = ROOT / 'inventario_kmz_resumen'


def leer(nombre):
    with (SRC / nombre).open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f, delimiter=';'))


def escribir_csv(nombre, filas, columnas):
    with (OUT / nombre).open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=columnas, delimiter=';')
        w.writeheader()
        w.writerows(filas)


def nombre_campo(valor):
    limpio = unicodedata.normalize('NFKD', valor).encode('ascii', 'ignore').decode()
    limpio = re.sub('[^A-Za-z0-9_]', '_', limpio).strip('_')
    if not limpio or not limpio[0].isalpha():
        limpio = 'atrib_' + limpio
    # Nombres de campos cortos, estables y distinguibles aun al truncar.
    if len(limpio) > 55:
        limpio = limpio[:46] + '_' + hashlib.sha256(valor.encode()).hexdigest()[:8]
    return limpio


# Equivalencias semanticas conservadoras. Una descripcion no sustituye la
# revision de la ruta/capa requerida por 5.8.8. No se aprueban filas de carga.
EQUIVALENCIAS = {
    'Accesos del proyecto': 'Accesos',
    'Calicatas / investigación geotécnica': 'Calicatas',
    'Canales de derivación (ANA)': 'Canales_Recorte',
    'Canales de riego': 'Canales_Recorte',
    'Canales de trasvase (ANA)': 'Canales_Recorte',
    'Canales laterales (ANA)': 'Canales_Recorte',
    'Catastro minero (INGEMMET)': 'CatastroMinero_Recorte',
    'Centros poblados (INEI)': 'CentroPoblado_Recorte',
    'Cobertura vegetal (MINAM)': 'CoberturaVegetal_Recorte',
    'Comunidades campesinas': 'ComunidadCampesina_Recorte',
    'Concesiones eléctricas (MINEM)': 'ConcesionElectrica_Recorte',
    'Ecosistemas frágiles (SERFOR)': 'EcosistemasFragiles_Recorte',
    'Fajas marginales de cuerpos de agua (ANA)': 'FajasMarginales_Recorte',
    'Franja de servidumbre de la LT': 'FranjaServidumbre',
    'Geología (INGEMMET)': 'Geologia_Recorte',
    'Geomorfología': 'Geomorfologia_Recorte',
    'Lagunas': 'Lagunas_Recorte',
    'Líneas de transmisión existentes (OSINERGMIN)': 'LT_Existente_Recorte',
    'Paleontología': 'Paleontologia_Recorte',
    'Predios inscritos en SUNARP': 'PredioSUNARP_Recorte',
    'Qhapaq Ñan – red vial inca (Ministerio de Cultura)': 'QhapaqNan_Recorte',
    'Recorridos y registros de campo (GPS)': 'RegistroCampo',
    'Red vial departamental (MTC)': 'ViasRegional_Recorte',
    'Red vial nacional (MTC)': 'ViasNacional_Recorte',
    'Red vial vecinal (MTC)': 'ViasVecinal_Recorte',
    'Redes de distribución en media tensión': 'RedesMT_Recorte',
    'Ríos / red hidrográfica': 'Rios_Recorte',
    'Sitios arqueológicos declarados (Ministerio de Cultura)': 'SitioArqueologico_Recorte',
    'Sitios arqueológicos delimitados (Ministerio de Cultura)': 'SitioArqueologico_Recorte',
    'Subestaciones en operación (OSINERGMIN)': 'SE_Existente_Recorte',
    'Subestación del proyecto': 'Subestacion',
    'Torres / estructuras de la LT del proyecto': 'Estructuras',
    'Vértices del trazo de la LT del proyecto': 'Vertices',
    'Zonas de amortiguamiento de ANP (SERNANP)': 'ZonaAmortiguamiento_Recorte',
    'Zonificación ecológica económica (ZEE)': 'ZEE_Recorte',
    'Áreas clave para la biodiversidad (KBA)': 'IBA_EBA_KBA_Recorte',
    'Áreas importantes para las aves (IBA)': 'IBA_EBA_KBA_Recorte',
    'Áreas de conservación privada (SERNANP)': 'AreaConservacion_Recorte',
    'Áreas de conservación regional (SERNANP)': 'AreaConservacion_Recorte',
    'Áreas naturales protegidas (SERNANP)': 'ANPNacional_Recorte',
}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    spec = importlib.util.spec_from_file_location('catalogo_eft_base', ROOT / '02_entregas/KMZ_EFT/carga_eft/eft_modelo.py')
    eft = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = eft
    spec.loader.exec_module(eft)
    matriz = leer('inventario_kmz_matriz_campos.csv')
    capas = leer('inventario_kmz_capas.csv')
    grupos = collections.defaultdict(list)
    for row in matriz:
        grupos[row['descripcion'], row['geometria']].append(row)
    numero_grupos_matriz = len(grupos)
    specs = eft.specs_completas()
    classes = {}
    for s in specs:
        campos = []
        for n, t, length, alias, domain in eft.campos_de(s):
            if n.startswith('kz_'):
                continue  # La trazabilidad pedida por el EFT ya tiene campos propios.
            campos.append(dict(nombre=n, tipo=t, longitud=12 if n == 'proyecto' else length,
                               alias=alias, dominio=domain, nullable=n not in ('proyecto', 'id_analisis'),
                               origen='EFT 5.8.7'))
        # Identificador fuente disponible tambien para clases de diseno/campo.
        if not any(x['nombre'] == 'id_origen' for x in campos):
            campos.append(dict(nombre='id_origen', tipo='TEXT', longitud=255,
                               alias='Identificador en la fuente', dominio=None, nullable=True,
                               origen='Trazabilidad de identificadores de fuente, EFT 5.8.7'))
        classes[s.fisico] = dict(nombre=s.fisico, dataset=s.dataset,
                                 geometria=eft.ARC_GEOMETRIA[s.geometria], campos=campos,
                                 origen='EFT 5.8.6', relacion_proyecto=s.dataset == 'Datos_Proyecto',
                                 tipo='nueva', descripciones=[])

    # Las seis clases migradas mantienen los campos y nombres del DDL existente.
    modelo = json.loads((ROOT / '02_entregas/ArcGisAWS_Carga_Mapline/modelo_eft.json').read_text(encoding='utf-8'))
    for tabla in modelo['tables']:
        if not tabla.get('geometry_type'):
            continue
        base_spec = eft.spec_de('Accesos' if tabla['geometry_type'] == 'POLYLINE' else 'AreaEstudioCampo',
                               'LINEA' if tabla['geometry_type'] == 'POLYLINE' else 'POLIGONO')
        comunes = [dict(c) for c in classes[base_spec.fisico]['campos'] if c['nombre'] != 'codigo_estacion']
        fields = []
        for f in tabla['fields']:
            sql = f['sql_type'].lower()
            t = 'TEXT' if 'char' in sql else 'DATE' if 'date' in sql else 'DOUBLE' if any(k in sql for k in ('decimal','float','double')) else 'LONG'
            fields.append(dict(nombre=f['name'], tipo=t, longitud=f.get('length'),
                               alias=f['name'], dominio=None, nullable=f['nullable'], origen='DDL MapLine: '+sql))
        used = {f['nombre'].lower() for f in fields}
        fields += [f for f in comunes if f['nombre'].lower() not in used]
        classes[tabla['name']] = dict(nombre=tabla['name'], dataset='Datos_Proyecto', geometria=tabla['geometry_type'],
                                      campos=fields, origen='EFT 5.8.3 / DDL MapLine', relacion_proyecto=True,
                                      tipo='migrada', descripciones=[])

    geom = {'Punto':'PUNTO', 'Línea':'LINEA', 'Polígono':'POLIGONO'}
    all_groups = set(grupos) | {(r['descripcion'],r['geometria']) for r in capas}
    mapping = {}
    for desc, g in sorted(all_groups):
        dest = EQUIVALENCIAS.get(desc)
        reason = 'Tema sin equivalencia univoca en la lista EFT; revisar rutas y atributos.'
        physical = ''
        if g not in geom:
            reason = 'Separar geometria mixta o revisar objeto no vectorial; no crear clase mixta.'
        elif dest:
            ok, msg = eft.validar_destino(dest, geom[g])
            if ok:
                physical = eft.nombre_fisico(dest, geom[g])
                reason = 'Correspondencia tematica propuesta; revisar la tabla de carga por ruta (EFT 5.8.8).'
            else:
                reason = msg + ' Requiere definir clase/geometria adicional con INDRA.'
        elif desc in ('Poseedores / posesionarios (sin título inscrito)', 'Uso actual', 'Uso actual de la tierra', 'Caminos de herradura'):
            reason = 'Resolver Datos_Internos frente a recorte de proyecto: EFT 5.8.8 y ultimo parrafo de 5.8.9.'
        elif desc in ('Línea de transmisión del proyecto','Trazo / alternativas de ruta de la LT','Área de estudio'):
            reason = 'Distinguir componente, alternativa, area general y campo por ruta. Usar las clases mline_* del DDL cuando corresponda.'
        elif 'PLS-CADD' in desc or desc in ('Area Features','Line Features','Point Features','Click on a structure to jump to it'):
            reason = 'Procesamiento PLS-CADD/contexto de carpeta requerido; cada grafico no equivale a un vano o estructura.'
        if physical:
            classes[physical]['descripciones'].append(desc)
        mapping[desc,g] = (physical,reason)

    field_map = []
    # Solo campos de sistema explicitos; ID y auditoria heredada se conservan.
    system = re.compile(r'^(?:FID(?:_.*)?|OBJECTID(?:_.*)?|OID|GLOBALID|SHAPE(?:_.*)?|ST_AREA_SH(?:APE)?|ST_LENGTH(?:_SHAPE)?)$', re.I)
    for row in matriz:
        dest,reason = mapping[row['descripcion'],row['geometria']]
        original = row['campo_normalizado']
        state = 'PENDIENTE_DESTINO'
        target = ''
        if system.fullmatch(original):
            state = 'OMITIR_CAMPO_SISTEMA'
        elif dest:
            base = nombre_campo(original)
            fields = classes[dest]['campos']
            common = {x['nombre'].lower() for x in fields if x['origen'] != 'Matriz KMZ: valor textual'}
            if base.lower() in common:
                base = 'src_' + base  # No confundir medida original con calculo geodesico ni codigo fuente con FK.
            target = base
            occupied = {x['nombre'].lower():x for x in fields}
            if target.lower() in occupied and occupied[target.lower()].get('campo_fuente') != original:
                target = base[:46] + '_' + hashlib.sha256(original.encode()).hexdigest()[:8]
            if target.lower() not in {x['nombre'].lower() for x in fields}:
                fields.append(dict(nombre=target, tipo='TEXT', longitud=4000, alias=original[:255], dominio=None,
                                   nullable=True, origen='Matriz KMZ: valor textual', campo_fuente=original))
            state = 'CAMPO_TEXTUAL'
        field_map.append(dict(descripcion=row['descripcion'], geometria=row['geometria'],
                              campo_fuente=original, variantes=row['variantes_del_nombre'],
                              tecnico_inventario=row['tecnico'], clase_destino=dest, campo_destino=target,
                              tipo='TEXT' if target else '', longitud=4000 if target else '', estado=state))

    counts = collections.Counter()
    review = []
    for idx,row in enumerate(capas,1):
        dest,reason = mapping[row['descripcion'],row['geometria']]
        project = Path(row['archivo'].replace('\\','/')).stem
        n = int(row['elementos'])
        counts[dest,project] += n
        review.append(dict(fila_capas=idx, archivo=row['archivo'], ruta=row['ruta'], descripcion=row['descripcion'],
                           geometria=row['geometria'], elementos=n, clase_propuesta=dest,
                           dataset_propuesto='Datos_Proyecto' if dest else '',
                           incluir='', clase_confirmada='', co_proyecto='', id_analisis='',
                           estado='REVISAR_MAPEO' if dest else 'PENDIENTE_DESTINO', motivo=reason))

    domains = {k:dict(descripcion=v[0], valores=list(v[1])) for k,v in eft.DOMINIOS.items()}
    relations = [dict(nombre='rel_proyecto_'+c['nombre'], origen='mline_tc_proyecto', destino=c['nombre'],
                      clave_origen='co_proyecto', clave_destino='proyecto') for c in classes.values() if c['relacion_proyecto']]
    manifest = dict(version=1, referencia_espacial=4326, tabla_proyecto='mline_tc_proyecto', clave_proyecto='co_proyecto',
                    datasets=list(eft.DATASETS), dominios=domains, clases=list(classes.values()), relaciones=relations,
                    tablas_migradas=[t['name'] for t in modelo['tables'] if not t.get('geometry_type')],
                    fuentes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in SRC.glob('*.csv')})
    (OUT/'esquema.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    escribir_csv('campos_matriz_a_esquema.csv',field_map,list(field_map[0]))
    escribir_csv('mapeo_capas_revision.csv',review,list(review[0]))
    projects = sorted({p for _,p in counts})
    summary=[]
    for c in classes.values():
        row=dict(dataset=c['dataset'],clase=c['nombre'],geometria=c['geometria'],tipo=c['tipo'],
                 campos=len(c['campos']),relacion='co_proyecto -> proyecto' if c['relacion_proyecto'] else '',
                 elementos_propuestos=sum(counts[c['nombre'],p] for p in projects))
        row.update({p:counts[c['nombre'],p] for p in projects})
        summary.append(row)
    escribir_csv('catalogo_clases.csv',summary,list(summary[0]))
    pending=[dict(descripcion=d,geometria=g,motivo=why,campos_matriz=len(grupos.get((d,g),[])))
             for (d,g),(dest,why) in mapping.items() if not dest]
    escribir_csv('temas_pendientes.csv',pending,list(pending[0]))
    scripts=OUT/'por_clase'
    scripts.mkdir(exist_ok=True)
    for c in classes.values():
        (scripts/(c['nombre']+'.py')).write_text(
            '"""Definicion ArcGIS: '+c['dataset']+'/'+c['nombre']+'."""\n'
            'import sys\nfrom pathlib import Path\n'
            'sys.path.insert(0, str(Path(__file__).resolve().parents[1]))\n'
            'from crear_esquema import main\n\n'
            'if __name__ == "__main__":\n'
            '    main(["--clase", '+repr(c['nombre'])+'] + sys.argv[1:])\n',encoding='utf-8')
    stats=dict(filas_matriz=len(matriz),grupos_matriz=numero_grupos_matriz,filas_capas=len(capas),
               elementos_origen=sum(int(r['elementos']) for r in capas),clases=len(classes),relaciones=len(relations),
               campos_matriz_por_estado=dict(collections.Counter(x['estado'] for x in field_map)),
               elementos_con_destino_propuesto=sum(v for (d,p),v in counts.items() if d),
               elementos_pendientes=sum(v for (d,p),v in counts.items() if not d),
               grupos_pendientes=len(pending))
    assert stats['elementos_con_destino_propuesto']+stats['elementos_pendientes']==stats['elementos_origen']
    assert len(field_map)==len(matriz)
    for c in classes.values():
        names=[f['nombre'].lower() for f in c['campos']]
        assert len(names)==len(set(names)), c['nombre']
    (OUT/'validacion_inventario.json').write_text(json.dumps(stats,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(stats,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
