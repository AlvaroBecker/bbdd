"""Emite lotes cortos y diagnosticos para las siete tablas pendientes."""
from pathlib import Path
import hashlib
import json
import re
import uuid
import zipfile

ROOT = Path(__file__).resolve().parent.parent / '02_entregas'
BASE = ROOT / 'ArcGisAWS_Carga_Mapline'
MODEL = json.loads((BASE / 'modelo_eft.json').read_text(encoding='utf-8'))
TABLES = {t['name']: t for t in MODEL['tables'] if not t['geometry_type'] and t['name'] != 'mline_tc_proyecto'}
SOURCE = BASE / '01_cargar_origen_en_ArcGisAWS.sql'
DEST = ROOT / 'Mapline_7_tablas_EFT_gis_v2.sql'
PREFIX = '[mapline_carga_20261030].'
RUN = str(uuid.uuid4())
TEMP = '#MaplineEFT7Control'

def dyn(text):
    return "EXEC sys.sp_executesql N'" + text.replace("'", "''") + "';\n"

def catch(phase):
    # La tabla de control se crea antes de la transaccion; Failed persiste tras rollback.
    return f"""END TRY
BEGIN CATCH
    DECLARE @numero int = ERROR_NUMBER(), @linea int = ERROR_LINE();
    DECLARE @mensaje nvarchar(2048) = ERROR_MESSAGE();
    IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
    UPDATE {TEMP} SET Failed=1, Ready=0, Phase=N'{phase}', ErrorNumber=@numero, ErrorText=@mensaje;
    SELECT N'{phase}' AS fase, @numero AS numero_error, @linea AS linea, @mensaje AS detalle;
    RAISERROR(N'FALLO %s: %s', 16, 1, N'{phase}', @mensaje) WITH NOWAIT;
END CATCH;
"""

ddl = {}
current = None
with SOURCE.open(encoding='utf-8-sig') as stream:
    for line in stream:
        m = re.match(r'^CREATE TABLE \[mapline_carga_20261030\]\.\[([^]]+)\]', line)
        if m:
            current = m[1] if m[1] in TABLES else None
            if current:
                ddl[current] = []
        if current:
            ddl[current].append(line.replace(PREFIX, '[gis].', 1) if line.startswith('CREATE TABLE ') else line)
            if line.strip() == ');':
                current = None
assert len(ddl) == 7
for name in ddl:
    key = TABLES[name]['primary_key'][0]
    ddl[name] = re.sub(r',\n  PRIMARY KEY \(\[' + re.escape(key) + r'\]\)', '', ''.join(ddl[name]))
    assert 'PRIMARY KEY' not in ddl[name] and 'FOREIGN KEY' not in ddl[name]

hashes = {n: hashlib.sha256() for n in TABLES}
rows = {n: 0 for n in TABLES}
batches = 0
with DEST.open('w', encoding='utf-8-sig', newline='\n') as out:
    out.write(f"""-- Version 2: siete tablas EFT, esquema GIS existente, lotes <=500 filas.
-- Ejecutar COMPLETO en una ventana nueva de SSMS conectada a ArcGisAWS.
-- No requiere modo SQLCMD. No crea esquemas ni modifica gis.mline_tc_proyecto.
-- No sobrescribe tablas. El COMMIT requiere todos los lotes y conteos correctos.
-- Si se cancela, cerrar esa conexion antes de volver a iniciar.
USE [ArcGisAWS];
GO
SET NOCOUNT ON;
SET XACT_ABORT ON;
SET ANSI_WARNINGS ON;
SET DATEFORMAT ymd;
RAISERROR(N'INICIO Mapline EFT7 v2: comprobando conexion y permisos', 10, 1) WITH NOWAIT;
SELECT @@SERVERNAME AS servidor, DB_NAME() AS base_actual, USER_NAME() AS usuario;
IF @@TRANCOUNT <> 0
BEGIN
    RAISERROR(N'Hay una transaccion previa. Abra una ventana nueva; no se modifico nada.',16,1) WITH NOWAIT;
    RETURN;
END;
IF OBJECT_ID(N'tempdb..{TEMP}') IS NOT NULL
BEGIN
    RAISERROR(N'Existe control de otro intento. Abra una ventana nueva.',16,1) WITH NOWAIT;
    RETURN;
END;
SET IMPLICIT_TRANSACTIONS OFF;
CREATE TABLE {TEMP} (RunId uniqueidentifier NOT NULL, Ready bit NOT NULL, Failed bit NOT NULL,
    LastBatch int NOT NULL, Phase nvarchar(128), ErrorNumber int NULL, ErrorText nvarchar(2048) NULL);
INSERT INTO {TEMP} VALUES ('{RUN}',0,0,0,N'preparacion',NULL,NULL);
BEGIN TRY
    IF SCHEMA_ID(N'gis') IS NULL THROW 51200, 'El esquema gis no existe; no se crea automaticamente.',1;
    IF OBJECT_ID(N'gis.mline_tc_proyecto', N'U') IS NULL THROW 51201, 'No se encuentra gis.mline_tc_proyecto.',1;
""")
    for name in TABLES:
        out.write(f"    IF OBJECT_ID(N'gis.{name}') IS NOT NULL THROW 51202, 'Ya existe gis.{name}; no se sobrescribe.',1;\n")
    out.write('    BEGIN TRANSACTION;\n')
    out.write(dyn('\n'.join(ddl.values())))
    out.write(f"    UPDATE {TEMP} SET Ready=1, Phase=N'tablas creadas';\n")
    out.write("    RAISERROR(N'Las 7 tablas GIS fueron creadas. Iniciando carga por lotes...',10,1) WITH NOWAIT;\n")
    out.write(catch('crear tablas') + 'GO\n')

    def emit(name, chunk):
        global batches
        batches += 1
        text = ''.join(chunk).replace(PREFIX, '[gis].', 1)
        original_values = ''.join(chunk[1:])
        hashes[name].update(original_values.encode('utf-8'))
        count = sum(1 for line in chunk[1:] if line.startswith('('))
        rows[name] += count
        assert 0 < count <= 500
        phase = f'{name} lote {batches}'
        out.write(f"""IF OBJECT_ID(N'tempdb..{TEMP}') IS NOT NULL
BEGIN
IF EXISTS (SELECT 1 FROM {TEMP} WHERE RunId='{RUN}' AND Ready=1 AND Failed=0)
BEGIN
BEGIN TRY
    IF @@TRANCOUNT <> 1 OR XACT_STATE() <> 1 THROW 51203, 'La transaccion de carga no esta disponible.',1;
    IF (SELECT LastBatch FROM {TEMP}) <> {batches-1} THROW 51204, 'Se omitio o repitio un lote. No se confirmara la carga.',1;
""")
        out.write(dyn(text))
        out.write(f"    UPDATE {TEMP} SET LastBatch={batches}, Phase=N'{phase}';\n")
        if batches == 1 or batches % 50 == 0 or count < 500:
            out.write(f"    RAISERROR(N'Procesado: {phase}',10,1) WITH NOWAIT;\n")
        out.write(catch(phase) + 'END;\nEND;\nGO\n')

    current, chunk = None, []
    with SOURCE.open(encoding='utf-8-sig') as stream:
        for line in stream:
            m = re.match(r'^INSERT INTO \[mapline_carga_20261030\]\.\[([^]]+)\]', line)
            if m:
                current = m[1] if m[1] in TABLES else None
                chunk = []
            if current:
                if line.strip() == 'GO':
                    emit(current, chunk)
                    current, chunk = None, []
                else:
                    chunk.append(line)

    finish = '''UPDATE [gis].[mline_td_proyecto_componente]
SET [id_proyecto_capa_componente]=NULL, [id_proyecto_capa_vertices]=NULL;
UPDATE [gis].[mline_td_proyecto_alternativa]
SET [id_proyecto_capa_alternativa]=NULL, [id_proyecto_capa_vertices]=NULL;
'''
    for name, meta in TABLES.items():
        assert rows[name] == meta['rows']
        key = meta['primary_key'][0]
        finish += f"""IF (SELECT COUNT_BIG(*) FROM [gis].[{name}]) <> {meta['rows']} THROW 51205, 'Conteo incorrecto: {name}',1;
IF EXISTS (SELECT [{key}] FROM [gis].[{name}] GROUP BY [{key}] HAVING COUNT_BIG(*)>1)
    THROW 51206, 'Claves duplicadas: {name}',1;
CREATE NONCLUSTERED INDEX [ix_{name}_id] ON [gis].[{name}] ([{key}]);
"""
    out.write(f"""IF OBJECT_ID(N'tempdb..{TEMP}') IS NULL
BEGIN
    RAISERROR(N'No existe control de carga. Ejecute el archivo completo en una ventana nueva.',16,1) WITH NOWAIT;
END
ELSE IF EXISTS (SELECT 1 FROM {TEMP} WHERE RunId='{RUN}' AND Ready=1 AND Failed=0)
BEGIN
BEGIN TRY
    IF @@TRANCOUNT <> 1 OR XACT_STATE() <> 1 THROW 51207, 'No se puede confirmar la transaccion.',1;
    IF (SELECT LastBatch FROM {TEMP}) <> {batches} THROW 51208, 'Faltan lotes por ejecutar.',1;
""")
    out.write(dyn(finish))
    out.write(f"""    UPDATE {TEMP} SET Ready=0, Phase=N'COMPLETADO';
    COMMIT TRANSACTION;
""")
    out.write(catch('validar y confirmar') + 'END\n')
    out.write(f"""ELSE
BEGIN
    SELECT Phase AS ultima_fase, Failed AS fallo, ErrorNumber AS numero_error, ErrorText AS detalle
    FROM {TEMP};
    RAISERROR(N'CARGA NO COMPLETADA. Revisar el primer mensaje de error anterior.',16,1) WITH NOWAIT;
END;
GO
""")
    # Un error de presentacion posterior no convierte en fallida una carga confirmada.
    out.write(f"""IF OBJECT_ID(N'tempdb..{TEMP}') IS NOT NULL
BEGIN
IF EXISTS (SELECT 1 FROM {TEMP} WHERE RunId='{RUN}' AND Phase=N'COMPLETADO' AND Failed=0)
BEGIN
    RAISERROR(N'COMPLETADO: 7 tablas en GIS; COMMIT ejecutado y conteos validados.',10,1) WITH NOWAIT;
BEGIN TRY
""")
    for name in TABLES:
        out.write(dyn(f"SELECT N'gis.{name}' AS tabla, COUNT_BIG(*) AS registros FROM [gis].[{name}];"))
    out.write("""END TRY
BEGIN CATCH
    DECLARE @error_reporte nvarchar(2048)=ERROR_MESSAGE();
    RAISERROR(N'La carga YA fue confirmada; fallo solamente el reporte: %s',10,1,@error_reporte) WITH NOWAIT;
END CATCH;
END;
END;
GO
""")

# Releer cada literal dinamico y verificar su desescape antes de aceptar el archivo.
out_hash = {n: hashlib.sha256() for n in TABLES}
current = None
buffer = []
with DEST.open(encoding='utf-8-sig') as stream:
    for line in stream:
        if line.startswith("EXEC sys.sp_executesql N'"):
            current = True
            buffer = [line[len("EXEC sys.sp_executesql N'"):]]
        elif current:
            buffer.append(line)
        if current and line.rstrip().endswith("';"):
            literal = ''.join(buffer).rstrip()[:-2]
            decoded = literal.replace("''", "'")
            found = re.match(r'^INSERT INTO \[gis\]\.\[([^]]+)\]', decoded)
            if found:
                lines = decoded.splitlines(keepends=True)
                values = ''.join(lines[1:])
                # El texto original del bloque acaba en un salto de linea.
                if not values.endswith('\n'):
                    values += '\n'
                out_hash[found[1]].update(values.encode('utf-8'))
            current = None
for name in TABLES:
    assert hashes[name].digest() == out_hash[name].digest(), name

report = {'file': DEST.name, 'schema': 'gis', 'rows': sum(rows.values()), 'batches': batches,
          'run_id': RUN, 'creates_schema': False, 'sqlcmd_required': False,
          'source_insert_values_preserved': True, 'executed_on_sql_server': False,
          'tables': [{'table': n, 'rows': rows[n], 'values_sha256': hashes[n].hexdigest()} for n in TABLES],
          'transformations_after_load': ['EFT: cuatro referencias obsoletas quedan NULL']}
(ROOT / 'Mapline_7_tablas_EFT_gis_v2_validacion.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
print(json.dumps({'file': DEST.name, 'rows': report['rows'], 'batches': batches,
                  'values_verified': True, 'bytes': DEST.stat().st_size}))
