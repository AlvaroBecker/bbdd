from pathlib import Path
import json
import re

root = Path(__file__).resolve().parent.parent / '02_entregas'
model = json.loads((root / 'ArcGisAWS_Carga_Mapline/modelo_eft.json').read_text(encoding='utf-8'))
meta = next(t for t in model['tables'] if t['name'] == 'mline_tc_proyecto')
assert meta['rows'] == 40 and meta['geometry_type'] is None
ddl, inserts = [], []
capturing = None
with (root / 'ArcGisAWS_Carga_Mapline/01_cargar_origen_en_ArcGisAWS.sql').open(encoding='utf-8') as stream:
    for line in stream:
        if line.startswith('CREATE TABLE [mapline_carga_20261030].[mline_tc_proyecto] '):
            capturing = 'ddl'
        elif line.startswith('INSERT INTO [mapline_carga_20261030].[mline_tc_proyecto] '):
            capturing = 'insert'
        if capturing == 'ddl':
            ddl.append(line)
            if line.strip() == ');':
                capturing = None
        elif capturing == 'insert':
            if line.strip() == 'GO':
                capturing = None
            else:
                inserts.append(line)

create = ''.join(ddl).replace('[mapline_carga_20261030].', '', 1)
create = create.replace(',\n  PRIMARY KEY ([id_proyecto])', '')
assert create and 'PRIMARY KEY' not in create and 'FOREIGN KEY' not in create
data = ''.join(inserts).replace('[mapline_carga_20261030].', '', 1)
assert data and len(re.findall(r'^\(', data, re.M)) == 40

output = f"""-- Carga independiente de mline_tc_proyecto, una de las 14 tablas migradas del EFT.
-- Destino existente: ArcGisAWS. Estructura y 40 registros del respaldo 2026-10-30.
-- No requiere modo SQLCMD. No borra ni sobrescribe tablas existentes.
-- Los ID de tipo y estado se conservan; sus dominios se configuran en ArcGIS.
-- No se crean FK hacia mline_tp_parametro porque se reemplaza por dominios.
-- id_proyecto mantiene su funcion de clave de negocio y se valida su unicidad.
-- Se crea un indice NO UNIQUE para el posterior registro branch desde ArcGIS.
-- SQL no registra la tabla en geodatabase ni configura ObjectID, GlobalID,
-- dominios, relaciones GIS, Editor Tracking o branch. Esos pasos usan ArcGIS Pro.
-- No crea ni especifica esquema: SQL Server usa el predeterminado del usuario.
USE [ArcGisAWS];
GO
SET NOCOUNT ON;
SET XACT_ABORT ON;
SET ANSI_WARNINGS ON;
SET DATEFORMAT ymd;

BEGIN TRY
    IF OBJECT_ID(N'mline_tc_proyecto') IS NOT NULL
        THROW 51010, 'La tabla mline_tc_proyecto ya existe. No se sobrescribio.', 1;

    BEGIN TRANSACTION;

{create}
{data}
    IF (SELECT COUNT_BIG(*) FROM [mline_tc_proyecto]) <> 40
        THROW 51011, 'El conteo no coincide con los 40 proyectos del respaldo.', 1;
    IF EXISTS (SELECT [id_proyecto] FROM [mline_tc_proyecto]
               GROUP BY [id_proyecto] HAVING COUNT_BIG(*) > 1)
        THROW 51013, 'Se encontraron identificadores de proyecto duplicados.', 1;

    CREATE NONCLUSTERED INDEX [ix_mline_tc_proyecto_id]
        ON [mline_tc_proyecto] ([id_proyecto]);
    CREATE NONCLUSTERED INDEX [ix_mline_tc_proyecto_tipo]
        ON [mline_tc_proyecto] ([id_tipo_proyecto]);
    CREATE NONCLUSTERED INDEX [ix_mline_tc_proyecto_estado]
        ON [mline_tc_proyecto] ([id_estado_proyecto]);

    COMMIT TRANSACTION;
    SELECT N'mline_tc_proyecto' AS tabla, COUNT_BIG(*) AS registros_importados
    FROM [mline_tc_proyecto];
END TRY
BEGIN CATCH
    IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;
GO
"""
path = root / 'Mapline_una_tabla_mline_tc_proyecto_SQLServer.sql'
path.write_text(output, encoding='utf-8-sig')
saved = path.read_text(encoding='utf-8-sig')
assert saved.count('\nCREATE TABLE ') == 1
assert data in saved and 'USE [ArcGisAWS];' in saved
assert 'CREATE SCHEMA' not in saved and 'SCHEMA_ID' not in saved
assert '[dbo].' not in saved and '[mapline].' not in saved
assert '\nCREATE TABLE [mline_tc_proyecto] (' in saved
assert not re.search(r'^\s*(DROP|DELETE|TRUNCATE|CREATE DATABASE)\b', saved, re.M)
assert not re.search(r'^\s*:', saved, re.M)
old = root / 'Mapline_una_tabla_mline_tc_proceso_SQLServer.sql'
if old.exists():
    old.unlink()
print(json.dumps({'file': path.name, 'rows': meta['rows'], 'columns': len(meta['fields']),
                  'foreign_keys': 0, 'source_insert_payload_unchanged': True,
                  'old_file_removed': not old.exists(), 'bytes': path.stat().st_size}))
