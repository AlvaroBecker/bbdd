"""Generador local: DDL de PK/FK originales para ocho tablas existentes."""
from pathlib import Path
import json

BASE = Path(__file__).resolve().parents[1]
manifest = json.loads((BASE / "modelo_restricciones.json").read_text(encoding="utf-8"))
tables = sorted(manifest["tables"], key=lambda t: t["name"])
names = {t["name"] for t in tables}
relations = sorted((r for r in manifest["relations"]
                    if r["parent"] in names and not r.get("obsolete")), key=lambda r: r["name"])
assert len(tables) == 8 and len(relations) == 11
assert all(len(t["primary_key"]) == 1 for t in tables)
assert all(r["on_delete"] == r["on_update"] == "NO_ACTION" for r in relations)

def lit(value):
    return "N'" + value.replace("'", "''") + "'"

pk_values = ",\n".join("    (" + ", ".join(map(lit, [t["name"], t["primary_key"][0], "PK_" + t["name"]])) + ")" for t in tables)
fk_values = ",\n".join("    (" + ", ".join(map(lit, [r["name"], r["child"], r["child_key"], r["parent"], r["parent_key"]])) + ")" for r in relations)

sql = r"""-- PK/FK FISICAS: ArcGisAWS.gis, ocho tablas ya existentes y registradas.
-- Fuente: Mapline_20261030.sql; seleccion de objetos y excepciones: EFT v2.4.
-- Ocho PK y once FK vigentes entre estas ocho tablas. Sin restricciones inventadas.
-- NO ejecuta cargas, no cambia columnas ni IDs, no crea esquemas ni reglas ArcGIS.
-- IMPORTANTE: estas PK impiden activar posteriormente BRANCH mientras existan.
-- Solo sirve SIN VERSIONADO NI ARCHIVADO. Registrar no equivale a versionar.
-- 00_verificar_estado_arcgis.py verifica ese estado SIN modificar la geodatabase
-- y produce 03_agregar_PK_FK_VERIFICADO.sql listo para SSMS, SIN modo SQLCMD.
-- Este archivo base se detiene al aplicar hasta contar con esa verificacion.
-- Cerrar sesiones de edicion/servicios que afecten estas tablas antes de ejecutar.

USE [ArcGisAWS];
SET NOCOUNT ON;
SET XACT_ABORT ON;
IF @@TRANCOUNT <> 0
    THROW 51400, N'Ejecutar en una ventana sin transacciones previas abiertas.', 1;
SET IMPLICIT_TRANSACTIONS OFF;
SET LOCK_TIMEOUT 15000;

DECLARE @Aplicar bit = 1; -- 1: crear restricciones faltantes; 0: solo mostrar plan.
DECLARE @EstadoArcGISVerificado bit = 0; -- ACTIVAR_SOLO_TRAS_VERIFICACION_ARCGIS
DECLARE @ServidorVerificado nvarchar(256) = N'__PENDIENTE__';
DECLARE @FechaVerificacion datetime2(0) = NULL;
DECLARE @Esquema sysname = N'gis';

IF DB_NAME() <> N'ArcGisAWS'
    THROW 51401, N'Base incorrecta: se requiere ArcGisAWS.', 1;
IF @Aplicar = 1 AND (
    @EstadoArcGISVerificado <> 1 OR @FechaVerificacion IS NULL
    OR @ServidorVerificado <> CONVERT(nvarchar(256), SERVERPROPERTY('ServerName'))
    OR DATEDIFF(MINUTE, @FechaVerificacion, SYSUTCDATETIME()) NOT BETWEEN -1 AND 15)
    THROW 51402, N'Falta verificacion ArcGIS vigente del mismo servidor. Ejecutar 00_verificar_estado_arcgis.py y usar el SQL VERIFICADO. No modificar el indicador manualmente.', 1;

DECLARE @PK TABLE (tabla sysname PRIMARY KEY, columna sysname, nombre sysname);
INSERT INTO @PK VALUES
__PK_VALUES__;
DECLARE @FK TABLE (nombre sysname PRIMARY KEY, hija sysname, columna_hija sysname,
                  padre sysname, columna_padre sysname);
INSERT INTO @FK VALUES
__FK_VALUES__;

-- Validaciones globales antes de cualquier DDL persistente.
IF EXISTS (SELECT 1 FROM @PK p
           WHERE OBJECT_ID(QUOTENAME(@Esquema)+N'.'+QUOTENAME(p.tabla),'U') IS NULL)
    THROW 51403, N'Falta alguna tabla gis o no es visible. No se crearon restricciones.', 1;
IF EXISTS (SELECT 1 FROM @PK p
           WHERE ISNULL(HAS_PERMS_BY_NAME(QUOTENAME(@Esquema)+N'.'+QUOTENAME(p.tabla),'OBJECT','VIEW DEFINITION'),0) <> 1)
    THROW 51404, N'Falta VIEW DEFINITION sobre las tablas; no se puede verificar su estructura.', 1;
IF EXISTS (SELECT 1 FROM @PK p JOIN sys.columns c
           ON c.object_id=OBJECT_ID(QUOTENAME(@Esquema)+N'.'+QUOTENAME(p.tabla),'U')
           WHERE c.name IN (N'GDB_BRANCH_ID',N'GDB_FROM_DATE',N'GDB_TO_DATE',N'GDB_IS_DELETE',N'GDB_ARCHIVE_OID'))
    THROW 51405, N'Hay marcadores de versionado o archivado. Este script no admite esos estados.', 1;
IF EXISTS (SELECT 1 FROM @PK p WHERE NOT EXISTS (
    SELECT 1 FROM sys.columns c
    WHERE c.object_id=OBJECT_ID(QUOTENAME(@Esquema)+N'.'+QUOTENAME(p.tabla),'U')
      AND c.name=p.columna AND c.system_type_id=56 AND c.is_nullable=0 AND c.is_computed=0))
    THROW 51406, N'La clave de origen debe existir como INT NOT NULL no calculado. No se alteran columnas automaticamente.', 1;
IF EXISTS (SELECT 1 FROM @FK f WHERE NOT EXISTS (
    SELECT 1 FROM sys.columns h JOIN sys.columns p
      ON p.object_id=OBJECT_ID(QUOTENAME(@Esquema)+N'.'+QUOTENAME(f.padre),'U') AND p.name=f.columna_padre
    WHERE h.object_id=OBJECT_ID(QUOTENAME(@Esquema)+N'.'+QUOTENAME(f.hija),'U')
      AND h.name=f.columna_hija AND h.system_type_id=56 AND p.system_type_id=56
      AND h.user_type_id=p.user_type_id AND h.is_computed=0 AND p.is_computed=0))
    THROW 51407, N'Falta un campo de relacion o sus tipos INT no coinciden. No se alteran columnas automaticamente.', 1;

DECLARE @Conflictos TABLE (objeto nvarchar(400), detalle nvarchar(600));
-- Una tabla admite una sola PK. No eliminar ni reemplazar una PK de ObjectID/otra clave.
INSERT INTO @Conflictos
SELECT p.tabla, N'PK existente diferente o deshabilitada: '+k.name
FROM @PK p JOIN sys.key_constraints k
  ON k.parent_object_id=OBJECT_ID(QUOTENAME(@Esquema)+N'.'+QUOTENAME(p.tabla),'U') AND k.type='PK'
JOIN sys.indexes i ON i.object_id=k.parent_object_id AND i.index_id=k.unique_index_id
WHERE i.is_disabled=1 OR i.is_unique<>1 OR i.has_filter=1 OR i.is_hypothetical=1
  OR (SELECT COUNT(*) FROM sys.index_columns ic WHERE ic.object_id=i.object_id AND ic.index_id=i.index_id AND ic.key_ordinal>0)<>1
  OR NOT EXISTS (SELECT 1 FROM sys.index_columns ic JOIN sys.columns c
                 ON c.object_id=ic.object_id AND c.column_id=ic.column_id
                 WHERE ic.object_id=i.object_id AND ic.index_id=i.index_id AND ic.key_ordinal=1 AND c.name=p.columna);
INSERT INTO @Conflictos
SELECT p.tabla, N'Nombre previsto de PK ocupado: '+p.nombre FROM @PK p
WHERE NOT EXISTS (SELECT 1 FROM sys.key_constraints k WHERE k.parent_object_id=OBJECT_ID(QUOTENAME(@Esquema)+N'.'+QUOTENAME(p.tabla),'U') AND k.type='PK')
  AND (EXISTS (SELECT 1 FROM sys.objects o WHERE o.schema_id=SCHEMA_ID(@Esquema) AND o.name=p.nombre)
       OR EXISTS (SELECT 1 FROM sys.indexes i
                  WHERE i.object_id=OBJECT_ID(QUOTENAME(@Esquema)+N'.'+QUOTENAME(p.tabla),'U') AND i.name=p.nombre));

-- Detectar relaciones existentes sobre las mismas claves con estado/acciones distintos.
INSERT INTO @Conflictos
SELECT f.hija, N'FK existente no confiable, deshabilitada o con acciones distintas: '+k.name
FROM @FK f JOIN sys.foreign_keys k
  ON k.parent_object_id=OBJECT_ID(QUOTENAME(@Esquema)+N'.'+QUOTENAME(f.hija),'U')
 AND k.referenced_object_id=OBJECT_ID(QUOTENAME(@Esquema)+N'.'+QUOTENAME(f.padre),'U')
JOIN sys.foreign_key_columns x ON x.constraint_object_id=k.object_id
JOIN sys.columns h ON h.object_id=x.parent_object_id AND h.column_id=x.parent_column_id
JOIN sys.columns p ON p.object_id=x.referenced_object_id AND p.column_id=x.referenced_column_id
WHERE h.name=f.columna_hija AND p.name=f.columna_padre
  AND (SELECT COUNT(*) FROM sys.foreign_key_columns x2 WHERE x2.constraint_object_id=k.object_id)=1
  AND (k.is_disabled=1 OR k.is_not_trusted=1 OR k.is_not_for_replication=1
       OR k.delete_referential_action<>0 OR k.update_referential_action<>0);
INSERT INTO @Conflictos
SELECT f.hija, N'Nombre previsto de FK ocupado por otra definicion: '+f.nombre
FROM @FK f JOIN sys.objects o ON o.schema_id=SCHEMA_ID(@Esquema) AND o.name=f.nombre
WHERE NOT EXISTS (
    SELECT 1 FROM sys.foreign_keys k JOIN sys.foreign_key_columns x ON x.constraint_object_id=k.object_id
    JOIN sys.columns h ON h.object_id=x.parent_object_id AND h.column_id=x.parent_column_id
    JOIN sys.columns p ON p.object_id=x.referenced_object_id AND p.column_id=x.referenced_column_id
    WHERE k.object_id=o.object_id AND k.parent_object_id=OBJECT_ID(QUOTENAME(@Esquema)+N'.'+QUOTENAME(f.hija),'U')
      AND k.referenced_object_id=OBJECT_ID(QUOTENAME(@Esquema)+N'.'+QUOTENAME(f.padre),'U')
      AND h.name=f.columna_hija AND p.name=f.columna_padre
      AND (SELECT COUNT(*) FROM sys.foreign_key_columns x2 WHERE x2.constraint_object_id=k.object_id)=1
      AND k.is_disabled=0 AND k.is_not_trusted=0 AND k.is_not_for_replication=0
      AND k.delete_referential_action=0 AND k.update_referential_action=0);
IF EXISTS (SELECT 1 FROM @Conflictos)
BEGIN
    SELECT * FROM @Conflictos ORDER BY objeto,detalle;
    THROW 51408, N'Conflictos con restricciones existentes. No se eliminan ni reemplazan automaticamente.', 1;
END;

DECLARE @Plan TABLE (orden int, clase varchar(2), tabla sysname, restriccion sysname,
                     existente sysname NULL, accion nvarchar(50), ddl nvarchar(max));
INSERT INTO @Plan
SELECT 1,'PK',p.tabla,p.nombre,k.name,
    CASE WHEN k.name IS NULL THEN N'CREAR' ELSE N'CONSERVAR_EQUIVALENTE' END,
    N'ALTER TABLE '+QUOTENAME(@Esquema)+N'.'+QUOTENAME(p.tabla)+N' ADD CONSTRAINT '+QUOTENAME(p.nombre)+
    N' PRIMARY KEY NONCLUSTERED ('+QUOTENAME(p.columna)+N');'
FROM @PK p LEFT JOIN sys.key_constraints k
  ON k.parent_object_id=OBJECT_ID(QUOTENAME(@Esquema)+N'.'+QUOTENAME(p.tabla),'U') AND k.type='PK';
INSERT INTO @Plan
SELECT 2,'FK',f.hija,f.nombre,e.nombre,
    CASE WHEN e.nombre IS NULL THEN N'CREAR' ELSE N'CONSERVAR_EQUIVALENTE' END,
    N'ALTER TABLE '+QUOTENAME(@Esquema)+N'.'+QUOTENAME(f.hija)+N' WITH CHECK ADD CONSTRAINT '+QUOTENAME(f.nombre)+
    N' FOREIGN KEY ('+QUOTENAME(f.columna_hija)+N') REFERENCES '+QUOTENAME(@Esquema)+N'.'+QUOTENAME(f.padre)+
    N' ('+QUOTENAME(f.columna_padre)+N') ON DELETE NO ACTION ON UPDATE NO ACTION;'
FROM @FK f OUTER APPLY (
    SELECT TOP(1) k.name AS nombre FROM sys.foreign_keys k
    JOIN sys.foreign_key_columns x ON x.constraint_object_id=k.object_id
    JOIN sys.columns h ON h.object_id=x.parent_object_id AND h.column_id=x.parent_column_id
    JOIN sys.columns p ON p.object_id=x.referenced_object_id AND p.column_id=x.referenced_column_id
    WHERE k.parent_object_id=OBJECT_ID(QUOTENAME(@Esquema)+N'.'+QUOTENAME(f.hija),'U')
      AND k.referenced_object_id=OBJECT_ID(QUOTENAME(@Esquema)+N'.'+QUOTENAME(f.padre),'U')
      AND h.name=f.columna_hija AND p.name=f.columna_padre
      AND (SELECT COUNT(*) FROM sys.foreign_key_columns x2 WHERE x2.constraint_object_id=k.object_id)=1
      AND k.is_disabled=0 AND k.is_not_trusted=0 AND k.is_not_for_replication=0
      AND k.delete_referential_action=0 AND k.update_referential_action=0
    ORDER BY CASE WHEN k.name=f.nombre THEN 0 ELSE 1 END,k.name) e;

-- Revisar todos los datos antes de crear la primera restriccion. No se corrigen datos.
DECLARE @Datos TABLE (clase varchar(2), objeto sysname, nulos bigint, duplicados bigint, huerfanos bigint);
DECLARE @Tabla sysname,@Columna sysname,@Nombre sysname,@Padre sysname,@CampoPadre sysname,
        @SQL nvarchar(max),@Nulos bigint,@Duplicados bigint,@Huerfanos bigint;
DECLARE pk_datos CURSOR LOCAL FAST_FORWARD FOR SELECT tabla,columna FROM @PK;
OPEN pk_datos; FETCH NEXT FROM pk_datos INTO @Tabla,@Columna;
WHILE @@FETCH_STATUS=0
BEGIN
    SET @SQL=N'SELECT @n=COUNT_BIG(*) FROM '+QUOTENAME(@Esquema)+N'.'+QUOTENAME(@Tabla)+
        N' WHERE '+QUOTENAME(@Columna)+N' IS NULL; SELECT @d=COUNT_BIG(*) FROM (SELECT '+QUOTENAME(@Columna)+
        N' FROM '+QUOTENAME(@Esquema)+N'.'+QUOTENAME(@Tabla)+N' GROUP BY '+QUOTENAME(@Columna)+N' HAVING COUNT_BIG(*)>1) q;';
    EXEC sys.sp_executesql @SQL,N'@n bigint OUTPUT,@d bigint OUTPUT',@n=@Nulos OUTPUT,@d=@Duplicados OUTPUT;
    INSERT INTO @Datos VALUES ('PK',@Tabla,@Nulos,@Duplicados,NULL);
    FETCH NEXT FROM pk_datos INTO @Tabla,@Columna;
END;
CLOSE pk_datos; DEALLOCATE pk_datos;
DECLARE fk_datos CURSOR LOCAL FAST_FORWARD FOR SELECT nombre,hija,columna_hija,padre,columna_padre FROM @FK;
OPEN fk_datos; FETCH NEXT FROM fk_datos INTO @Nombre,@Tabla,@Columna,@Padre,@CampoPadre;
WHILE @@FETCH_STATUS=0
BEGIN
    SET @SQL=N'SELECT @h=COUNT_BIG(*) FROM '+QUOTENAME(@Esquema)+N'.'+QUOTENAME(@Tabla)+N' h WHERE h.'+
        QUOTENAME(@Columna)+N' IS NOT NULL AND NOT EXISTS (SELECT 1 FROM '+QUOTENAME(@Esquema)+N'.'+QUOTENAME(@Padre)+
        N' p WHERE p.'+QUOTENAME(@CampoPadre)+N'=h.'+QUOTENAME(@Columna)+N');';
    EXEC sys.sp_executesql @SQL,N'@h bigint OUTPUT',@h=@Huerfanos OUTPUT;
    INSERT INTO @Datos VALUES ('FK',@Nombre,NULL,NULL,@Huerfanos);
    FETCH NEXT FROM fk_datos INTO @Nombre,@Tabla,@Columna,@Padre,@CampoPadre;
END;
CLOSE fk_datos; DEALLOCATE fk_datos;
SELECT * FROM @Datos ORDER BY clase,objeto;
IF EXISTS (SELECT 1 FROM @Datos WHERE nulos>0 OR duplicados>0 OR huerfanos>0)
    THROW 51409, N'Hay claves nulas, duplicadas o referencias huerfanas. No se modificaron datos ni restricciones.', 1;
SELECT @Aplicar AS aplicar,clase,tabla,restriccion,existente,accion,ddl FROM @Plan ORDER BY orden,tabla,restriccion;
IF @Aplicar=0
BEGIN
    PRINT N'Solo plan: no se modificaron restricciones.';
    RETURN;
END;
IF EXISTS (SELECT 1 FROM @Plan WHERE accion=N'CREAR' AND
    ISNULL(HAS_PERMS_BY_NAME(QUOTENAME(@Esquema)+N'.'+QUOTENAME(tabla),'OBJECT','ALTER'),0)<>1)
    THROW 51410, N'Falta permiso ALTER sobre alguna tabla. No se crearon restricciones.', 1;
IF EXISTS (SELECT 1 FROM @FK f WHERE
    ISNULL(HAS_PERMS_BY_NAME(QUOTENAME(@Esquema)+N'.'+QUOTENAME(f.padre),'OBJECT','REFERENCES'),0)<>1)
    THROW 51411, N'Falta permiso REFERENCES sobre alguna tabla padre. No se crearon restricciones.', 1;

-- Una sola transaccion: cualquier fallo de PK/FK o de verificacion revierte todo este paso.
BEGIN TRY
    BEGIN TRANSACTION;
    DECLARE crear_restricciones CURSOR LOCAL FAST_FORWARD FOR
        SELECT ddl FROM @Plan WHERE accion=N'CREAR' ORDER BY orden,tabla,restriccion;
    OPEN crear_restricciones; FETCH NEXT FROM crear_restricciones INTO @SQL;
    WHILE @@FETCH_STATUS=0
    BEGIN
        EXEC sys.sp_executesql @SQL;
        FETCH NEXT FROM crear_restricciones INTO @SQL;
    END;
    CLOSE crear_restricciones; DEALLOCATE crear_restricciones;
    IF EXISTS (SELECT 1 FROM @PK p WHERE NOT EXISTS (
        SELECT 1 FROM sys.key_constraints k JOIN sys.indexes i ON i.object_id=k.parent_object_id AND i.index_id=k.unique_index_id
        JOIN sys.index_columns x ON x.object_id=i.object_id AND x.index_id=i.index_id AND x.key_ordinal=1
        JOIN sys.columns c ON c.object_id=x.object_id AND c.column_id=x.column_id
        WHERE k.type='PK' AND k.parent_object_id=OBJECT_ID(QUOTENAME(@Esquema)+N'.'+QUOTENAME(p.tabla),'U')
          AND c.name=p.columna AND i.is_unique=1 AND i.is_disabled=0 AND i.has_filter=0 AND i.is_hypothetical=0
          AND (SELECT COUNT(*) FROM sys.index_columns x2 WHERE x2.object_id=i.object_id AND x2.index_id=i.index_id AND x2.key_ordinal>0)=1))
        THROW 51412, N'No se confirmaron las ocho PK. Se revierte este paso completo.', 1;
    IF EXISTS (SELECT 1 FROM @FK f WHERE NOT EXISTS (
        SELECT 1 FROM sys.foreign_keys k JOIN sys.foreign_key_columns x ON x.constraint_object_id=k.object_id
        JOIN sys.columns h ON h.object_id=x.parent_object_id AND h.column_id=x.parent_column_id
        JOIN sys.columns p ON p.object_id=x.referenced_object_id AND p.column_id=x.referenced_column_id
        WHERE k.parent_object_id=OBJECT_ID(QUOTENAME(@Esquema)+N'.'+QUOTENAME(f.hija),'U')
          AND k.referenced_object_id=OBJECT_ID(QUOTENAME(@Esquema)+N'.'+QUOTENAME(f.padre),'U')
          AND h.name=f.columna_hija AND p.name=f.columna_padre
          AND (SELECT COUNT(*) FROM sys.foreign_key_columns x2 WHERE x2.constraint_object_id=k.object_id)=1
          AND k.is_disabled=0 AND k.is_not_trusted=0 AND k.is_not_for_replication=0
          AND k.delete_referential_action=0 AND k.update_referential_action=0))
        THROW 51413, N'No se confirmaron las once FK habilitadas y confiables. Se revierte este paso completo.', 1;
    COMMIT TRANSACTION;
    SELECT clase,accion,COUNT(*) AS cantidad FROM @Plan GROUP BY clase,accion ORDER BY clase,accion;
    PRINT N'Finalizado: ocho PK y once FK fisicas verificadas. No se cambiaron datos, columnas, ObjectID ni GlobalID.';
END TRY
BEGIN CATCH
    IF CURSOR_STATUS('local','crear_restricciones')>=0 CLOSE crear_restricciones;
    IF CURSOR_STATUS('local','crear_restricciones')>=-1 DEALLOCATE crear_restricciones;
    IF XACT_STATE()<>0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;
"""
sql = sql.replace("__PK_VALUES__", pk_values).replace("__FK_VALUES__", fk_values)
(BASE / "03_agregar_PK_FK_SQLServer.sql").write_text(sql, encoding="utf-8-sig")
print("Generado 03: ocho PK, once FK NO ACTION, sin cambios en la base.")
