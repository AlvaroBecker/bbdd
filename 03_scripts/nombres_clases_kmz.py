"""Nombres fisicos aprobados de las 76 clases KMZ de Datos_Proyecto (1.6).

El mapeo es explicito: no elimina palabras por heuristica ni produce hashes.
Los nombres migrados del modelo MapLine se conservan. Las descripciones de
origen permanecen completas en el inventario y alimentan los aliases legibles.
No renombra objetos ni modifica archivos al importar este modulo.
"""
from __future__ import annotations

import re


VERSION = '1.6'
MAX_CLASS_NAME = 63
PRESERVED_DDL = frozenset((
    'mline_td_proyecto_area_interes',
    'mline_td_proyecto_infraestructura',
    'mline_td_proyecto_ltransmision',
))
OMITTED_WORDS = frozenset(('a', 'de', 'del', 'la', 'las', 'el', 'los',
                           'en', 'por', 'para'))

# Incluye tambien las clases sin cambio: toda la coleccion tiene una decision
# trazable. Los nombres largos conservan palabras y siglas reconocibles;
# superar el antiguo limite autoimpuesto de 50 ya no introduce un hash.
NAMES = {
    'accesos': 'accesos',
    'acreditacion_de_disponibilidad_hidrica_ana_recorte': 'acreditacion_disponibilidad_hidrica_ana_recorte',
    'area_estudio_campo': 'area_estudio_campo',
    'area_urbana_recorte': 'area_urbana_recorte',
    'areas_de_conservacion_recorte': 'areas_conservacion_recorte',
    'areas_de_promocion_proinversion_recorte': 'areas_promocion_proinversion_recorte',
    'areas_naturales_protegidas_sernanp_recorte': 'areas_naturales_protegidas_sernanp_recorte',
    'autorizacion_de_ejecucion_de_obra_35f72e1f_recorte': 'autorizacion_obras_hidraulicas_ana_recorte',
    'calicatas': 'calicatas',
    'caminos_de_herradura_recorte': 'caminos_herradura_recorte',
    'canales_recorte': 'canales_recorte',
    'capacidad_de_uso_mayor_de_suelos_recorte': 'capacidad_uso_mayor_suelos_recorte',
    'catastro_minero_ingemmet_recorte': 'catastro_minero_ingemmet_recorte',
    'catastro_rural_midagri_sicar_recorte': 'catastro_rural_midagri_sicar_recorte',
    'centros_poblados_inei_recorte': 'centros_poblados_inei_recorte',
    'clasificacion_climatica_recorte': 'clasificacion_climatica_recorte',
    'clasificacion_hidrogeologica_recorte': 'clasificacion_hidrogeologica_recorte',
    'cobertura_agricola_midagri_recorte': 'cobertura_agricola_midagri_recorte',
    'cobertura_vegetal_minam_recorte': 'cobertura_vegetal_minam_recorte',
    'comunidades_campesinas_recorte': 'comunidades_campesinas_recorte',
    'concesiones_electricas_minem_recorte': 'concesiones_electricas_minem_recorte',
    'concesiones_forestales_serfor_recorte': 'concesiones_forestales_serfor_recorte',
    'cuencas_hidrograficas_ana_recorte': 'cuencas_hidrograficas_ana_recorte',
    'ecorregiones_recorte': 'ecorregiones_recorte',
    'ecosistemas_fragiles_serfor_recorte': 'ecosistemas_fragiles_serfor_recorte',
    'estaciones_de_bombeo_ana_recorte': 'estaciones_bombeo_ana_recorte',
    'estructuras': 'estructuras',
    'fajas_marginales_de_cuerpos_de_agua_ana_recorte': 'fajas_marginales_cuerpos_agua_ana_recorte',
    'fisiografia_recorte': 'fisiografia_recorte',
    'formalizacion_de_derechos_de_uso_01c8dd3e_recorte': 'formalizacion_derechos_uso_agua_ana_recorte',
    'franja_servidumbre': 'franja_servidumbre',
    'geologia_ingemmet_linea_recorte': 'geologia_ingemmet_linea_recorte',
    'geologia_ingemmet_poligono_recorte': 'geologia_ingemmet_poligono_recorte',
    'geomorfologia_recorte': 'geomorfologia_recorte',
    'habitats_criticos_recorte': 'habitats_criticos_recorte',
    'iba_eba_kba_recorte': 'iba_eba_kba_recorte',
    'instrumentos_de_gestion_74264739_poligono_recorte': 'instrumentos_gestion_ambiental_senace_poligono_recorte',
    'instrumentos_de_gestion_amb_9c432944_punto_recorte': 'instrumentos_gestion_ambiental_senace_punto_recorte',
    'instrumentos_de_gestion_amb_c6d70745_linea_recorte': 'instrumentos_gestion_ambiental_senace_linea_recorte',
    'lagunas_recorte': 'lagunas_recorte',
    'limite_departamento_recorte': 'limite_departamento_recorte',
    'limite_distrito_recorte': 'limite_distrito_recorte',
    'limite_provincia_recorte': 'limite_provincia_recorte',
    'lineas_de_transmision_existentes_64e6b9b1_recorte': 'lineas_transmision_existentes_osinergmin_recorte',
    'mapa_nacional_de_ecosistemas_minam_recorte': 'mapa_nacional_ecosistemas_minam_recorte',
    'mline_td_proyecto_area_interes': 'mline_td_proyecto_area_interes',
    'mline_td_proyecto_infraestructura': 'mline_td_proyecto_infraestructura',
    'mline_td_proyecto_ltransmision': 'mline_td_proyecto_ltransmision',
    'paleontologia_recorte': 'paleontologia_recorte',
    'plantaciones_forestales_en_predio_b9f4663d_recorte': 'plantaciones_forestales_predios_privados_serfor_recorte',
    'poseedores_posesionarios_b3ad0df0_poligono_recorte': 'poseedores_posesionarios_poligono_recorte',
    'poseedores_posesionarios_si_132bef96_punto_recorte': 'poseedores_posesionarios_punto_recorte',
    'predios_inscritos_en_sunarp_recorte': 'predios_inscritos_sunarp_recorte',
    'qhapaq_nan_red_vial_inca_minister_f6cbbcad_recorte': 'qhapaq_nan_red_vial_inca_mincul_recorte',
    'red_vial_departamental_mtc_recorte': 'red_vial_departamental_mtc_recorte',
    'red_vial_nacional_mtc_recorte': 'red_vial_nacional_mtc_recorte',
    'red_vial_vecinal_mtc_recorte': 'red_vial_vecinal_mtc_recorte',
    'redes_de_distribucion_en_media_tension_recorte': 'redes_distribucion_media_tension_recorte',
    'registro_campo_linea': 'registro_campo_linea',
    'registro_campo_punto': 'registro_campo_punto',
    'reservas_de_biosfera_unesco_recorte': 'reservas_biosfera_unesco_recorte',
    'rios_red_hidrografica_recorte': 'rios_red_hidrografica_recorte',
    'rios_secciones_transversales_ana_recorte': 'rios_secciones_transversales_ana_recorte',
    'sitios_arqueologicos_poligono_recorte': 'sitios_arqueologicos_poligono_recorte',
    'sitios_arqueologicos_punto_recorte': 'sitios_arqueologicos_punto_recorte',
    'subestacion_poligono': 'subestacion_poligono',
    'subestacion_punto': 'subestacion_punto',
    'subestaciones_osinergmin_recorte': 'subestaciones_osinergmin_recorte',
    'suelos_recorte': 'suelos_recorte',
    'susceptibilidad_a_movimientos_en_masa_recorte': 'susceptibilidad_movimientos_masa_recorte',
    'uso_actual_de_la_tierra_recorte': 'uso_actual_tierra_recorte',
    'vertices': 'vertices',
    'zonas_de_amortiguamiento_de_anp_sernanp_recorte': 'zonas_amortiguamiento_anp_sernanp_recorte',
    'zonas_de_vida_holdridge_recorte': 'zonas_vida_holdridge_recorte',
    'zonas_reservadas_sernanp_recorte': 'zonas_reservadas_sernanp_recorte',
    'zonas_restringidas_recorte': 'zonas_restringidas_recorte',
}

# Estas etiquetas resuelven descripciones extensas o ambiguas sin modificar
# su clasificacion. Para una unica descripcion precisa se conserva su texto.
ALIASES = {
    'accesos': 'Accesos del proyecto',
    'area_estudio_campo': 'Área de estudio de campo',
    'areas_de_conservacion_recorte': 'Áreas de conservación privada y regional (SERNANP)',
    'canales_recorte': 'Canales de derivación, riego, trasvase y laterales',
    'capacidad_de_uso_mayor_de_suelos_recorte': 'Capacidad de uso mayor de suelos',
    'catastro_minero_ingemmet_recorte': 'Catastro minero (INGEMMET)',
    'estructuras': 'Torres y estructuras de líneas de transmisión del proyecto',
    'iba_eba_kba_recorte': 'Áreas importantes para aves y biodiversidad (IBA / EBA / KBA)',
    'limite_departamento_recorte': 'Límites departamentales (INEI)',
    'limite_distrito_recorte': 'Límites distritales (INEI)',
    'limite_provincia_recorte': 'Límites provinciales (INEI)',
    'rios_red_hidrografica_recorte': 'Ríos y red hidrográfica',
    'sitios_arqueologicos_poligono_recorte': 'Sitios y patrimonio arqueológico',
    'sitios_arqueologicos_punto_recorte': 'Sitios y patrimonio arqueológico',
    'subestacion_poligono': 'Subestación del proyecto',
    'subestacion_punto': 'Subestación del proyecto',
    'subestaciones_osinergmin_recorte': 'Subestaciones en operación y proyectadas (OSINERGMIN)',
    'uso_actual_de_la_tierra_recorte': 'Uso actual de la tierra',
    'vertices': 'Vértices del trazo de la línea de transmisión del proyecto',
}


def validate_policy():
    if len(NAMES) != 76 or len({name.casefold() for name in NAMES.values()}) != 76:
        raise ValueError('La politica debe contener exactamente 76 nombres unicos.')
    for old, new in NAMES.items():
        if not re.fullmatch(r'[a-z][a-z0-9]*(?:_[a-z0-9]+)*', new):
            raise ValueError(f'Nombre fuera de snake_case: {new}')
        if len(new) > MAX_CLASS_NAME or re.search(r'_[0-9a-f]{8}(?:_|$)', new):
            raise ValueError(f'Nombre largo o con hash no aprobado: {new}')
        if old in PRESERVED_DDL:
            if old != new:
                raise ValueError(f'El nombre DDL debe conservarse: {old}')
        elif set(new.split('_')) & OMITTED_WORDS:
            raise ValueError(f'Nombre con palabras prescindibles: {new}')
        if old.endswith('_recorte') != new.endswith('_recorte'):
            raise ValueError(f'El sufijo recorte no coincide: {old}')
        for suffix in ('punto', 'linea', 'poligono'):
            for ending in ('_' + suffix, '_' + suffix + '_recorte'):
                if old.endswith(ending) and not new.endswith(ending):
                    raise ValueError(f'La geometria no se conserva: {old}')


def final_name(old):
    """Nombre de una clase conocida; rechaza temas nuevos sin decision explicita."""
    if old in NAMES:
        return NAMES[old]
    if old in NAMES.values():
        return old
    raise ValueError(f'Clase sin nombre aprobado en la politica 1.6: {old}')


def _alias(old, cls):
    if old in PRESERVED_DDL:
        return None
    if old in ALIASES:
        title = ALIASES[old]
    else:
        descriptions = cls.get('descripciones', [])
        if len(descriptions) != 1 or not descriptions[0].strip():
            raise ValueError(f'La clase requiere un alias tematico explicito: {old}')
        title = descriptions[0].strip()
    new = NAMES[old]
    for suffix, text in (('punto', 'puntos'), ('linea', 'líneas'), ('poligono', 'polígonos')):
        if new.endswith('_' + suffix) or new.endswith('_' + suffix + '_recorte'):
            title += ' — ' + text
            break
    if cls['rol'] == 'recorte':
        title += ' — recorte'
    if len(title) > 255:
        raise ValueError(f'Alias demasiado largo: {old}')
    return title


def policy_rows(model):
    """Devuelve las decisiones completas a partir del modelo anterior o final.

    Mantiene nombre_anterior siempre ligado al esquema 1.5.1 para reanudar una
    migracion parcial. No altera el modelo recibido ni sus descripciones.
    """
    validate_policy()
    classes = model['clases']
    names = {cls['nombre'] for cls in classes}
    if len(classes) != 76 or names not in (set(NAMES), set(NAMES.values())):
        raise ValueError('El modelo no coincide con las 76 clases de la politica 1.6.')
    reverse = {new: old for old, new in NAMES.items()}
    rows = []
    for cls in classes:
        name = cls['nombre']
        old = name if name in NAMES else reverse[name]
        new = NAMES[old]
        if cls['rol'] == 'migrada' and old not in PRESERVED_DDL:
            raise ValueError(f'Clase migrada sin excepcion DDL documentada: {old}')
        if old in PRESERVED_DDL:
            reason = 'Conservar nombre oficial del modelo MapLine migrado.'
        elif re.search(r'_[0-9a-f]{8}(?:_|$)', old):
            reason = 'Sustituir truncamiento y hash por tema, fuente y geometria legibles.'
        elif old != new:
            reason = 'Omitir articulos y preposiciones prescindibles; conservar significado.'
        else:
            reason = 'El nombre ya cumple la convencion; conservarlo.'
        rows.append(dict(nombre_anterior=old, nombre_nuevo=new,
                         alias=_alias(old, cls), rol=cls['rol'],
                         geometria=cls['geometria'], renombrar=old != new,
                         motivo=reason))
    return sorted(rows, key=lambda row: row['nombre_anterior'])


validate_policy()
