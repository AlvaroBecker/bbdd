"""Reglas de propuesta por tema, geometria y ruta. Nunca aprueban una carga."""
import re
import unicodedata


def norm(text):
    return unicodedata.normalize('NFKD',text).encode('ascii','ignore').decode().lower()


def snake(text):
    return re.sub('[^a-z0-9]+','_',norm(text)).strip('_')


def result(base='',role='pendiente',reason='',master='',eft=''):
    return dict(base=base,rol=role,motivo=reason,maestro_dataset=master,clase_eft=eft)


def classify(row):
    desc=norm(row['descripcion']); path=norm(row['ruta']); g=row['geometria']
    parts=[x.strip() for x in path.split('/')]
    if g not in ('Punto','Línea','Polígono'):
        return result(reason='Separar geometria mixta o revisar objeto no vectorial; no descartar.')
    if any(x in desc for x in ('pls-cadd','click on a structure')) or desc in ('area features','line features','point features') or 'pls-cadd' in path:
        return result(reason='PLS-CADD/graficos: reconstruir estructuras y vanos con conectividad; no tratar cada grafico como entidad de negocio.')
    if any(x in desc for x in ('cad exportad','textos / anotaciones','created with sketchup')):
        return result(reason='CAD/texto/modelo: revisar manualmente tema y duplicados segun EFT 5.8.9.')

    # La ruta tiene prioridad en descripciones que mezclan varios objetos.
    mixed_label=desc in ('linea de transmision del proyecto','trazo / alternativas de ruta de la lt')
    if mixed_label:
        if any('acceso' in p for p in parts) and g=='Línea':
            return result('accesos','proyecto','La carpeta identifica accesos, no el eje de transmision.',eft='Accesos')
        if any('vertice' in p for p in parts) and g=='Punto':
            return result('vertices','proyecto','Vertices explicitos; cotejar con los vertices generados del trazado y resolver su llave.',eft='Vertices')
        if any('estructura' in p or 'torres' in p for p in parts) and g=='Punto':
            return result('estructuras','proyecto','La carpeta identifica estructuras de la LT.',eft='Estructuras')
        is_substation=any('subestacion' in p or re.match(r'^(?:s\.?e\.?)(?:\s|$)',p) for p in parts)
        if is_substation and g in ('Punto','Polígono'):
            if any(p=='predio' for p in parts):
                return result(reason='Predio de una subestacion: distinguir terreno de la instalacion.')
            return result('subestacion','proyecto','La ruta identifica una subestacion; la etiqueta de alternativa no cambia su tema.',eft='Subestacion')
        if g=='Línea':
            alternative=desc.startswith('trazo /') or any(re.search(r'\b(?:alt\s*_?\s*\d|alternativa|opcion|caso base|trazo)',p) for p in parts)
            if alternative:
                return result('mline_td_proyecto_infraestructura','migrada','Trazo de ruta/alternativa: completar la clase migrada y resolver id_proyecto_alternativa.',eft='td_proyecto_infraestructura')
            if 'lineas de transmision' in path or 'linea de transmision' in path:
                return result('mline_td_proyecto_ltransmision','migrada','Linea del componente: completar clase migrada; confirmar componente y distinguir alternativas.',eft='td_proyecto_ltransmision')
        return result(reason='Descripcion de LT/alternativa insuficiente para esta geometria; revisar nombre, atributos y funcion del objeto.')

    if desc=='area de estudio':
        if g!='Polígono':
            return result(reason='Area de estudio no poligonal; revisar clasificacion, no convertir geometria automaticamente.')
        station=any(re.fullmatch(r'(?:ebi|f|soc|iba|pl)\d+[a-z]?',p,re.I) for p in parts)
        if 'estudio de campo' in path or station:
            return result('area_estudio_campo','proyecto','Area de campo asociada a estacion; conservar codigo_estacion.',eft='AreaEstudioCampo')
        return result('mline_td_proyecto_area_interes','migrada','Area general propuesta: confirmar el componente y completar la clase migrada.',eft='td_proyecto_area_interes')

    direct={
        'accesos del proyecto':('accesos',('Línea',),'Accesos'),
        'torres / estructuras de la lt del proyecto':('estructuras',('Punto',),'Estructuras'),
        'vertices del trazo de la lt del proyecto':('vertices',('Punto',),'Vertices'),
        'subestacion del proyecto':('subestacion',('Punto','Polígono'),'Subestacion'),
        'franja de servidumbre de la lt':('franja_servidumbre',('Polígono',),'FranjaServidumbre'),
        'calicatas / investigacion geotecnica':('calicatas',('Punto',),'Calicatas'),
        'recorridos y registros de campo (gps)':('registro_campo',('Punto','Línea'),'RegistroCampo'),
    }
    if desc.startswith(('acceso existente','acceso nuevo')):
        direct[desc]=('accesos',('Línea',),'Accesos')
    if desc in direct:
        base,allowed,eft=direct[desc]
        if g not in allowed: return result(reason=f'{eft}: geometria no prevista para el objeto; revisar antes de crear otra clase.')
        return result(base,'proyecto','Tema de proyecto identificado; mantener categoria, componente y alternativa como atributos.',eft=eft)
    if desc=='estacion de muestreo – componente biologico' or desc=='estacion de muestreo - componente biologico':
        return result(reason='Poligonos rotulados como estacion de muestreo: distinguir area de campo de punto de muestreo.')
    if desc.startswith('estacion de muestreo'):
        return result(reason='Confirmar si el poligono representa area de campo; Muestreo del EFT es puntual.')

    # Grupos semanticos del EFT: no separar clases por categorias.
    merged={
        'canales de derivacion (ana)':('canales','Canales'),
        'canales de riego':('canales','Canales'),
        'canales de trasvase (ana)':('canales','Canales'),
        'canales laterales (ana)':('canales','Canales'),
        'areas de conservacion privada (sernanp)':('areas_de_conservacion','AreaConservacion'),
        'areas de conservacion regional (sernanp)':('areas_de_conservacion','AreaConservacion'),
        'areas importantes para las aves (iba)':('iba_eba_kba','IBA_EBA_KBA'),
        'areas clave para la biodiversidad (kba)':('iba_eba_kba','IBA_EBA_KBA'),
        'lugares mas importantes para la conservacion basada en el habitat de las aves':('iba_eba_kba','IBA_EBA_KBA'),
        'red de sitios que son importantes para la viabilidad a largo plazo de las poblaciones de aves presentes en la naturaleza':('iba_eba_kba','IBA_EBA_KBA'),
        'sitios arqueologicos declarados (ministerio de cultura)':('sitios_arqueologicos','SitioArqueologico'),
        'sitios arqueologicos delimitados (ministerio de cultura)':('sitios_arqueologicos','SitioArqueologico'),
        'patrimonio arqueologico':('sitios_arqueologicos','SitioArqueologico'),
        'rios / red hidrografica':('rios_red_hidrografica','Rios'),
        'subestaciones en operacion (osinergmin)':('subestaciones_osinergmin','SE_Existente'),
        'subestaciones proyectadas (osinergmin)':('subestaciones_osinergmin','SE_Existente'),
    }
    if desc.startswith('elementos de la red hidrografica'):
        merged[desc]=('rios_red_hidrografica','Rios')
    if desc.startswith('informacion del catastro minero'):
        merged[desc]=('catastro_minero_ingemmet','CatastroMinero')
    if desc in merged:
        base,eft=merged[desc]
        allowed=('Línea',) if eft in ('Canales','Rios') else ('Punto',) if eft=='SE_Existente' else ('Punto','Polígono') if eft=='SitioArqueologico' else ('Polígono',)
        if g not in allowed: return result(reason=f'{eft}: revisar geometria incompatible con la clase del EFT.')
        return result(base,'recorte','Consolidar tema; conservar descripcion/categoria original en tipo_tema.','Datos_Externos',eft)

    # Recortes publicos reconocibles, con controles para geometrias sospechosas.
    sources=('(ana)','(sernanp)','(serfor)','(minam)','(ingemmet)','(midagri','(inei)',
             '(minem)','(os inergmin)','(osinergmin)','(mtc)','(senace)','(unesco)',
             '(ministerio de cultura)','(proinversion)')
    special={
        'predios inscritos en sunarp':('Polígono',),
        'lineas de transmision existentes (osinergmin)':('Línea',),
        'redes de distribucion en media tension':('Línea',),
        'concesiones electricas (minem)':('Polígono',),
        'fajas marginales de cuerpos de agua (ana)':('Punto',),
        'paleontologia':('Punto',),
        'geologia (ingemmet)':('Línea','Polígono'),
        'red vial (mtc)':('Línea',),
    }
    if desc in special and g not in special[desc]:
        return result(reason='Geometria distinta de la prevista en el EFT; revisar el contenido antes de ampliar la clase.')
    if desc=='limites politico-administrativos (inei)':
        for text,label in [('departament','limite_departamento'),('provinc','limite_provincia'),('distrit','limite_distrito')]:
            if text in path and g=='Polígono': return result(label,'recorte','Nivel administrativo identificado por ruta.','Datos_Externos',label)
        return result(reason='Separar limites departamentales, provinciales y distritales segun la ruta/atributos.')
    if desc=='red vial (mtc)':
        for text,label in [('nacional','red_vial_nacional_mtc'),('departamental','red_vial_departamental_mtc'),('regional','red_vial_departamental_mtc'),('vecinal','red_vial_vecinal_mtc')]:
            if text in path: return result(label,'recorte','Categoria vial identificada por ruta.','Datos_Externos',label)
        return result(reason='Determinar categoria nacional, regional o vecinal; no duplicar la red vial generica.')
    if any(source in desc for source in sources) or desc in ('predios inscritos en sunarp','redes de distribucion en media tension','comunidades campesinas'):
        return result(snake(row['descripcion']),'recorte','Conservar recorte del KMZ; la capa maestra se obtiene de su fuente oficial.','Datos_Externos')

    internal=('poseedores / posesionarios (sin titulo inscrito)','uso actual','uso actual de la tierra','caminos de herradura')
    if desc in internal or desc.startswith('para identificar las unidades de uso actual'):
        base='uso_actual_de_la_tierra' if 'uso actual' in desc else snake(row['descripcion'])
        return result(base,'recorte','Instantanea inicial del proyecto; confirmar entrega maestra interna y prevalencia segun EFT 5.8.9.','Datos_Internos')

    reference={'capacidad de uso mayor de suelos','clasificacion climatica','clasificacion hidrogeologica','ecorregiones',
               'fisiografia','geomorfologia','habitats criticos','lagunas','paleontologia','suelos',
               'susceptibilidad a movimientos en masa','zonas de vida (holdridge)','zonas restringidas','area urbana'}
    if desc.startswith('mapa de capacidad de uso mayor'):
        return result('capacidad_de_uso_mayor_de_suelos','recorte','Mismo tema CUM; confirmar fuente maestra.','POR_CONFIRMAR')
    if desc in reference:
        return result(snake(row['descripcion']),'recorte','Capa tematica de referencia; confirmar fuente maestra externa/interna.','POR_CONFIRMAR')
    return result(reason='Tema no resuelto con descripcion y ruta; conservar en revision, sin crear tabla generica.')


def metadata(row):
    parts=[p.strip() for p in row['ruta'].split('/')]
    n=norm(row['ruta']); d=norm(row['descripcion'])
    discipline=''
    if 'consultor predial' in n: discipline='Predial'
    elif 'consultor ambiental' in n or 'ambiental/' in n: discipline='Ambiental'
    elif 'ingenieria' in n or '1. lineas de transmision' in n: discipline='Ingeniería'
    alternatives=[p for p in parts if re.search(r'\b(?:alt[_\s]*\d|alternativa|opcion|caso base)',norm(p))]
    components=[p for p in parts if re.match(r'^(?:lt\s+\d|se\s+|s\.e\.|seccionamiento)',norm(p))]
    station=next((p for p in reversed(parts) if re.fullmatch(r'(?:EBI|F|SOC|IBA|PL)\d+[A-Z]?',p,re.I)),'')
    condition='Existente' if 'existente' in d or 'existente' in n or 'en operacion' in d else 'Nuevo' if 'nuevo' in d or 'nuevos' in n else 'Proyectado' if 'proyectad' in n or 'proyectad' in d else ''
    agencies={'ana':'ANA','sernanp':'SERNANP','serfor':'SERFOR','minam':'MINAM','ingemmet':'INGEMMET',
              'sunarp':'SUNARP','midagri':'MIDAGRI','minem':'MINEM','osinergmin':'OSINERGMIN','mtc':'MTC','inei':'INEI','senace':'SENACE'}
    source=next((label for term,label in agencies.items() if re.search(r'\b'+term+r'\b',d)), '')
    if 'ministerio de cultura' in d: source='Ministerio de Cultura'
    return dict(disciplina_propuesta=discipline,componente_propuesto=components[-1] if components else '',
                alternativa_propuesta=alternatives[-1] if alternatives else '',condicion_propuesta=condition,
                codigo_estacion_propuesto=station,fuente_propuesta=source,tipo_tema_propuesto=row['descripcion'])
