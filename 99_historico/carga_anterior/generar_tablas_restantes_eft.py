"""Prepara siete tablas tabulares del EFT sin recrear el proyecto ya importado."""
from pathlib import Path
import hashlib
import json
import re

ROOT = Path(__file__).resolve().parent
BASE = ROOT / 'ArcGisAWS_Carga_Mapline'
MODEL = json.loads((BASE / 'modelo_eft.json').read_text(encoding='utf-8'))
VALIDATION = json.loads((BASE / 'validacion_conversion.json').read_text(encoding='utf-8'))
TABLES = {t['name']: t for t in MODEL['tables'] if t['geometry_type'] is None and t['name'] != 'mline_tc_proyecto'}
assert len(TABLES) == 7
SOURCE = BASE / '01_cargar_origen_en_ArcGisAWS.sql'
DEST = ROOT / 'Mapline_7_tablas_restantes_EFT_SQLServer.sql'
PREFIX = '[mapline_carga_20261030].'

ddl = {}
current = None
with SOURCE.open(encoding='utf-8-sig') as stream:
    for line in stream:
        found = re.match(r'^CREATE TABLE \[mapline_carga_20261030\]\.\[([^]]+)\]', line)
        if found:
            current = found[1] if found[1] in TABLES else None
            if current:
                ddl[current] = []
        if current:
            ddl[current].append(line.replace(PREFIX, '', 1) if line.startswith('CREATE TABLE ') else line)
            if line.strip() == ');':
                current = None
assert set(ddl) == set(TABLES)
for name, lines in ddl.items():
    key = TABLES[name]['primary_key']
    assert len(key) == 1
    original = ''.join(lines)
    transformed = re.sub(r',\n  PRIMARY KEY \(\[' + re.escape(key[0]) + r'\]\)', '', original)
    assert transformed != original and 'PRIMARY KEY' not in transformed
    assert 'FOREIGN KEY' not in transformed
    ddl[name] = transformed

hash_source = {n: hashlib.sha256() for n in TABLES}
counts = {n: 0 for n in TABLES}
batches = {n: 0 for n in TABLES}

with DEST.open('w', encoding='utf-8-sig', newline='\n') as out:
    out.write('''-- Siete tablas tabulares restantes del EFT, respaldo Mapline 2026-10-30.
-- mline_tc_proyecto ya importada NO se crea, modifica ni recarga.
-- Destino ArcGisAWS existente; se usa el esquema predeterminado del usuario.
-- No crea esquemas. No requiere modo SQLCMD. No sobrescribe objetos existentes.
-- Se conservan los valores e ID, salvo cuatro referencias obsoletas del EFT
-- que quedan NULL; sus valores originales permanecen en el respaldo MySQL.
-- No se imponen FK SQL a parametros, catalogos o clases espaciales pendientes.
-- Los indices de negocio son NO UNIQUE para la posterior configuracion branch.
-- Es una carga relacional: aun requiere registro, dominios, conversion de capas
-- y filtros, relaciones GIS y versionado mediante ArcGIS segun el EFT.
-- No ejecutar nuevamente sobre tablas ya cargadas o registradas con ArcGIS.
USE [ArcGisAWS];
GO
SET NOCOUNT ON;
SET XACT_ABORT ON;
SET ANSI_WARNINGS ON;
SET DATEFORMAT ymd;

IF @@TRANCOUNT <> 0
    THROW 51100, 'Ejecutar sin una transaccion previa abierta.', 1;

BEGIN TRY
    IF OBJECT_ID(N'mline_tc_proyecto', N'U') IS NULL
        THROW 51101, 'Primero debe existir mline_tc_proyecto en la conexion actual.', 1;
''')
    for name in TABLES:
        out.write(f"    IF OBJECT_ID(N'{name}') IS NOT NULL\n        THROW 51102, 'La tabla {name} ya existe. No se sobrescribio.', 1;\n")
    out.write('\n    BEGIN TRANSACTION;\n\n')
    for name in TABLES:
        out.write(ddl[name] + '\n')

    current = None
    with SOURCE.open(encoding='utf-8-sig') as stream:
        for line in stream:
            found = re.match(r'^INSERT INTO \[mapline_carga_20261030\]\.\[([^]]+)\]', line)
            if found:
                current = found[1] if found[1] in TABLES else None
                if current:
                    batches[current] += 1
            if current:
                if line.strip() == 'GO':
                    current = None
                    out.write('\n')
                else:
                    if line.startswith('INSERT INTO '):
                        out.write(line.replace(PREFIX, '', 1))
                    else:
                        hash_source[current].update(line.encode('utf-8'))
                        if line.startswith('('):
                            counts[current] += 1
                        out.write(line)

    out.write('''
    -- Referencias a capas de geometria sustituidas, segun EFT 5.8.4.
    UPDATE [mline_td_proyecto_componente]
       SET [id_proyecto_capa_componente] = NULL, [id_proyecto_capa_vertices] = NULL;
    UPDATE [mline_td_proyecto_alternativa]
       SET [id_proyecto_capa_alternativa] = NULL, [id_proyecto_capa_vertices] = NULL;
''')
    for name, meta in TABLES.items():
        assert counts[name] == meta['rows'], (name, counts[name], meta['rows'])
        key = meta['primary_key'][0]
        out.write(f"""
    IF (SELECT COUNT_BIG(*) FROM [{name}]) <> {meta['rows']}
        THROW 51103, 'Conteo de filas incorrecto en {name}.', 1;
    IF EXISTS (SELECT [{key}] FROM [{name}] GROUP BY [{key}] HAVING COUNT_BIG(*) > 1)
        THROW 51104, 'Claves de negocio duplicadas en {name}.', 1;
    CREATE NONCLUSTERED INDEX [ix_{name}_id] ON [{name}] ([{key}]);
""")
    out.write('''
    COMMIT TRANSACTION;
''')
    for name in TABLES:
        out.write(f"    SELECT N'{name}' AS tabla, COUNT_BIG(*) AS registros_importados FROM [{name}];\n")
    out.write('''END TRY
BEGIN CATCH
    IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;
GO
''')

# Volver a leer el archivo emitido y comprobar que cada linea de VALUES es identica.
hash_output = {n: hashlib.sha256() for n in TABLES}
seen_tables = []
current = None
with DEST.open(encoding='utf-8-sig') as stream:
    for line in stream:
        found = re.match(r'^INSERT INTO \[([^]]+)\]', line)
        if found:
            current = found[1]
            assert current in TABLES
        elif current and line.startswith('('):
            hash_output[current].update(line.encode('utf-8'))
            if line.rstrip().endswith(';'):
                current = None
        elif line.startswith('CREATE TABLE '):
            seen_tables.append(re.match(r'CREATE TABLE \[([^]]+)\]', line)[1])
        assert not re.match(r'^\s*(CREATE SCHEMA|CREATE DATABASE|DROP|DELETE|TRUNCATE|:)', line)
        assert not line.startswith('INSERT INTO [mline_tc_proyecto]')
assert set(seen_tables) == set(TABLES) and len(seen_tables) == 7
report = []
for name, meta in TABLES.items():
    a, b = hash_source[name].hexdigest(), hash_output[name].hexdigest()
    assert a == b
    assert batches[name] == next(t['batches'] for t in VALIDATION['tables'] if t['table'] == name)
    report.append({'table': name, 'rows': counts[name], 'columns': len(meta['fields']),
                   'batches': batches[name], 'values_sha256': a, 'source_values_unchanged': True})
summary = {'file': DEST.name, 'total_rows': sum(counts.values()), 'tables': report,
           'after_insert_transformations': {
               'mline_td_proyecto_componente': {'id_proyecto_capa_componente': None, 'id_proyecto_capa_vertices': None},
               'mline_td_proyecto_alternativa': {'id_proyecto_capa_alternativa': None, 'id_proyecto_capa_vertices': None}},
           'creates_schemas': False, 'sqlcmd_required': False,
           'recreates_project_table': False, 'executed_on_sql_server': False}
(ROOT / 'Mapline_7_tablas_restantes_EFT_validacion.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
print(json.dumps({'file': DEST.name, 'tables': len(TABLES), 'rows': sum(counts.values()),
                  'values_match': True, 'bytes': DEST.stat().st_size}))
