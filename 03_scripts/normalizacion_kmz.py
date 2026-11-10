"""Nombres y equivalencias conservadoras; sin ArcPy ni escritura de datos.

Las equivalencias se aplican por ruta. La comprobacion de valores debe usarse
antes de una carga: nunca resuelve un conflicto sobrescribiendo un atributo.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import Counter, defaultdict

# Lista vigente de Transact-SQL (no incluye palabras futuras ni ODBC).
# https://learn.microsoft.com/en-us/sql/t-sql/language-elements/reserved-keywords-transact-sql
# Revisada 2026-11-05. Se conserva aparte de snake_case: la sintaxis del nombre
# y su admisibilidad en el motor de base de datos son comprobaciones distintas.
SQLSERVER_RESERVED = frozenset('''
ADD ALL ALTER AND ANY AS ASC AUTHORIZATION BACKUP BEGIN BETWEEN BREAK BROWSE BULK BY
CASCADE CASE CHECK CHECKPOINT CLOSE CLUSTERED COALESCE COLLATE COLUMN COMMIT COMPUTE
CONSTRAINT CONTAINS CONTAINSTABLE CONTINUE CONVERT CREATE CROSS CURRENT CURRENT_DATE
CURRENT_TIME CURRENT_TIMESTAMP CURRENT_USER CURSOR DATABASE DBCC DEALLOCATE DECLARE
DEFAULT DELETE DENY DESC DISK DISTINCT DISTRIBUTED DOUBLE DROP DUMP ELSE END ERRLVL
ESCAPE EXCEPT EXEC EXECUTE EXISTS EXIT EXTERNAL FETCH FILE FILLFACTOR FOR FOREIGN
FREETEXT FREETEXTTABLE FROM FULL FUNCTION GOTO GRANT GROUP HAVING HOLDLOCK IDENTITY
IDENTITY_INSERT IDENTITYCOL IF IN INDEX INNER INSERT INTERSECT INTO IS JOIN KEY KILL
LEFT LIKE LINENO LOAD MERGE NATIONAL NOCHECK NONCLUSTERED NOT NULL NULLIF OF OFF
OFFSETS ON OPEN OPENDATASOURCE OPENQUERY OPENROWSET OPENXML OPTION OR ORDER OUTER OVER
PERCENT PIVOT PLAN PRECISION PRIMARY PRINT PROC PROCEDURE PUBLIC RAISERROR READ
READTEXT RECONFIGURE REFERENCES REPLICATION RESTORE RESTRICT RETURN REVERT REVOKE
RIGHT ROLLBACK ROWCOUNT ROWGUIDCOL RULE SAVE SCHEMA SECURITYAUDIT SELECT
SEMANTICKEYPHRASETABLE SEMANTICSIMILARITYDETAILSTABLE SEMANTICSIMILARITYTABLE SESSION_USER
SET SETUSER SHUTDOWN SOME STATISTICS SYSTEM_USER TABLE TABLESAMPLE TEXTSIZE THEN TO TOP
TRAN TRANSACTION TRIGGER TRUNCATE TRY_CONVERT TSEQUAL UNION UNIQUE UNPIVOT UPDATE
UPDATETEXT USE USER VALUES VARYING VIEW WAITFOR WHEN WHERE WHILE WITH WRITETEXT
'''.split())

# Restricciones adicionales comprobadas con ValidateFieldName en el SDE real
# del usuario (2026-11-05). COUNT no pertenece a la lista T-SQL anterior.
ARCGIS_SDE_REJECTED = frozenset({'COUNT'})


def snake_case(value):
    text = unicodedata.normalize('NFKD', str(value)).encode('ascii', 'ignore').decode()
    text = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1_\2', text)
    text = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', text)
    text = re.sub(r'[^a-zA-Z0-9]+', '_', text).strip('_').lower()
    if not text or not text[0].isalpha():
        text = 'atrib_' + text
    if len(text) > 55:
        text = text[:46].rstrip('_') + '_' + hashlib.sha256(text.encode()).hexdigest()[:8]
    return text


def spelling_index(rows):
    counts = defaultdict(Counter)
    for row in rows:
        counts[row['campo_normalizado']][snake_case(row['campo'])] += 1
    # Preferir separaciones presentes en los originales; desempate reproducible.
    return {key: sorted(variants, key=lambda n: (-n.count('_'), -variants[n], n))[0]
            for key, variants in counts.items()}


def is_name_100(row, layer):
    match = re.fullmatch(r'(.+?)\s*\(100(?:[.,]0+)?%\)', layer.get('nombre_viene_del_campo', '').strip())
    return bool(match and match[1].strip().casefold() == row['campo'].strip().casefold()
                and row.get('es_campo_del_nombre', '').casefold() in ('si', 'sí'))


def destination(row, layer, class_name, core, spellings):
    source = row['campo_normalizado']
    upper = source.upper()
    default = spellings.get(source, snake_case(row['campo']))
    if class_name == 'mline_td_proyecto_ltransmision':
        ddl = {'TENSION': 'me_nivel_tension', 'TENSION_NO': 'me_nivel_tension',
               'TENSION_NOMINAL_KV': 'me_nivel_tension', 'LONGITUD': 'me_longitud',
               'LONGITUD_DE_LINEA_DE_TRANSMISION_KM': 'me_longitud',
               'NOMBRE_DE_SUBESTACION_DE_SALIDA': 'no_subestacion_salida',
               'NOMBRE_DE_SUBESTACION_DE_LLEGADA': 'no_subestacion_llegada'}
        if upper in ddl:
            return ddl[upper], 'DDL_EFT', 'EFT 5.8.7; verificar tipo y unidad antes de cargar.'
    if upper in {'CODRUTA', 'ANP_CODI', 'CODIGOU', 'COD_PREDIO'} and 'id_origen' in core:
        return 'id_origen', 'IDENTIFICADOR_EFT', 'Identificador de fuente expresamente indicado en EFT 5.8.7; comparar si coexisten identificadores.'
    if upper in {'ALTERNATIV', 'ALTERNATIVA'} and 'alternativa' in core:
        return 'alternativa', 'ALIAS_ALTERNATIVA', 'Variantes truncada y completa del inventario; ejemplos Alternativa 1/2/3. Comprobar conflicto con el contexto.'
    # La bandera sola no basta: hay una capa Torre (16%).
    if upper in {'NOMBRE', 'NAME'} and 'nombre' in core and is_name_100(row, layer):
        return 'nombre', 'NOMBRE_KML_100', 'El inventario identifica este atributo como nombre del KML con coincidencia del 100% en esta ruta.'
    if upper in {'OBSERV', 'OBSERVACIO', 'OBSERVACION', 'OBSERVACIONES'}:
        return 'observaciones', 'ALIAS_OBSERVACIONES', 'Tabla de equivalencias de EFT 5.8.7; comparar valores si coexisten variantes.'
    if upper in {'TENSION_NO', 'TENSION_NOMINAL_KV'}:
        return 'tension_nominal_kv', 'ALIAS_TENSION_EFT', 'Equivalencia indicada en EFT 5.8.7; verificar kV, sin convertir por el nombre solamente.'
    if default in core:
        if core[default]['origen'].startswith('DDL MapLine'):
            return default, 'DDL_MISMO_NOMBRE', 'Campo del DDL migrado; validar tipo, longitud y significado.'
        return 'src_' + default, 'COLISION_CON_CAMPO_COMUN', 'Atributo original conservado: no hay evidencia suficiente de equivalencia con el campo comun en esta ruta.'
    if default.upper() in SQLSERVER_RESERVED:
        return 'src_' + default, 'PALABRA_RESERVADA_SQLSERVER', 'Atributo original conservado con prefijo src_ porque su nombre es una palabra reservada de Transact-SQL; no se agrega otro atributo.'
    if default.upper() in ARCGIS_SDE_REJECTED:
        return 'src_' + default, 'NOMBRE_RECHAZADO_ARCGIS_SDE', 'ValidateFieldName rechazo este nombre en el destino SDE del usuario. Se conserva el atributo original con prefijo src_; no se agrega otro atributo.'
    return default, 'NOMBRE_NORMALIZADO', 'Normalizacion de escritura del atributo original; no implica equivalencia semantica con otros atributos.'


def merge_values(pairs, initial=None):
    """Combinar destinos ya mapeados, deteniendo valores distintos (incluido 0).

    No convierte unidades/tipos, ni trata cadenas como <Null> como nulos sin
    una regla de origen: esos textos se conservan para no borrar informacion.
    """
    result = dict(initial or {})
    for target, value in pairs:
        if value is None or value == '':
            continue
        old = result.get(target)
        if old is not None and old != '' and (type(old) is not type(value) or old != value):
            raise ValueError(f'Valores diferentes para {target}; resolver la equivalencia antes de cargar.')
        result[target] = value
    return result


def normalize_record(attributes, mappings, initial=None):
    """Preparar nombres de UN contexto de inventario, sin insertar registros.

    Recibe pares (nombre original, valor), no un dict que pueda ocultar campos
    repetidos. El llamador sigue siendo responsable de tipos/unidades y llaves.
    """
    contexts = {tuple(r.get(k, '') for k in ('archivo', 'ruta', 'geometria', 'descripcion', 'clase_destino')) for r in mappings}
    if len(contexts) != 1:
        raise ValueError('Seleccione el mapeo de una sola ruta y clase.')
    by_original = {}
    for row in mappings:
        key = row['campo_original']
        if key in by_original and by_original[key]['campo_destino'] != row['campo_destino']:
            raise ValueError(f'Mapeo ambiguo para {key}.')
        by_original[key] = row
    pairs = []
    for source, value in attributes:
        if source not in by_original:
            raise ValueError(f'Atributo no inventariado: {source}; actualizar el mapeo.')
        row = by_original[source]
        if row['estado'] == 'OMITIR_CAMPO_SISTEMA':
            continue
        if not row['campo_destino']:
            raise ValueError(f'Atributo sin destino: {source}.')
        pairs.append((row['campo_destino'], value))
    return merge_values(pairs, initial)
