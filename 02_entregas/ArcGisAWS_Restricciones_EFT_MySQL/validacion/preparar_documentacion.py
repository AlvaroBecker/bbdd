"""Generar trazabilidad del alcance SQL actual, sin acceder al servidor."""
from collections import Counter
from pathlib import Path
import json

BASE = Path(__file__).resolve().parents[1]
p = BASE / "modelo_restricciones.json"
m = json.loads(p.read_text(encoding="utf-8"))
names = {t["name"] for t in m["tables"]}
m.pop("rules_prefix", None)
m.pop("enforce_obsolete_null", None)
for r in m["relations"]:
    if r["parent"] in names and not r.get("obsolete"):
        r["treatment"] = "sql_foreign_key"
    elif r.get("obsolete"):
        r["treatment"] = "retirada_por_eft_no_recrear_fk"
m["scope"] = "PK/FK fisicas en ocho tablas gis existentes y registradas, SIN versionado ni archivado. No activa branch."
m["limitations"] = [
    "Las ocho PK impiden activar branch mientras existan; no se resuelve ese cambio de arquitectura en este paquete.",
    "Solo once FK vigentes tienen ambos extremos entre las ocho tablas actuales.",
    "No configura dominios, Portal ni las seis clases espaciales pendientes.",
    "No crea IDENTITY, secuencias, reglas Arcade, relationship classes ni nuevos campos.",
]
m["sources"] = {"eft": "EFT - ENGIE Mapline ArcGIS Enterprise y ArcGIS Pro_v2.4.docx",
                "mysql": "Mapline_20261030.sql",
                "eft_sections": ["5.8.2", "5.8.4", "5.8.10", "5.8.11"]}
p.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")

labels = {
    "sql_foreign_key": "Crear FK SQL (o conservar equivalente habilitada/confiable).",
    "retirada_por_eft_no_recrear_fk": "No recrear: referencia retirada por EFT 5.8.4; conservar campo, sin cambiar datos.",
    "coded_domain": "Pendiente de dominios conforme EFT 5.8.11; no crear tabla de parámetros para recuperar esta FK.",
    "pending_portal_field_mapping": "Pendiente de equivalencia Portal/campo conforme EFT; no inventar padre sustituto.",
    "pending_spatial_parent": "Pendiente de la clase espacial padre y su clave; no crear FK a un objeto todavía no integrado.",
}
counts = Counter(r["treatment"] for r in m["relations"])
assert counts == {"sql_foreign_key": 11, "retirada_por_eft_no_recrear_fk": 3,
                  "coded_domain": 8, "pending_portal_field_mapping": 2, "pending_spatial_parent": 3}, counts
lines = [
    "# Correspondencia de las restricciones: EFT y MySQL",
    "",
    "Selección: ocho tablas tabulares ya cargadas en `ArcGisAWS.gis`. El dump aporta las definiciones originales; el EFT determina qué objetos migran y qué referencias se retiran o reemplazan. Esri se consulta únicamente para la compatibilidad técnica.",
    "",
    "**Aplicación actual:** ocho PK físicas y once FK físicas entre estas ocho tablas, si continúan sin versionado ni archivado. Las PK impedirán activar branch mientras existan. Este paquete no deja resuelto el estado final branch del EFT.",
    "",
    "No hay `AUTO_INCREMENT` en estas ocho tablas del dump. Una PK no convierte su ID en autoincremental. No se crean `IDENTITY`, secuencias ni generadores de IDs.",
    "",
    "## Ocho claves primarias",
    "",
    "Todas son de una columna `INT NOT NULL`. Se agregan como `PRIMARY KEY NONCLUSTERED`, para conservar la organización clustered que pueda administrar ArcGIS. El nombre `PK_<tabla>` es el nombre técnico para SQL Server; MySQL llama `PRIMARY` a cada una.",
    "",
    "| Tabla | Clave de MySQL | Restricción SQL prevista |",
    "|---|---|---|",
]
for t in sorted(m["tables"], key=lambda t: t["name"]):
    lines.append(f"| `{t['name']}` | `{t['primary_key'][0]}` | `PK_{t['name']}` |")
lines += ["", "Si ya existe una PK equivalente se conserva. Si la PK actual está sobre ObjectID u otra clave, el script se detiene antes de hacer cambios: SQL Server permite una sola PK por tabla y no se autoriza eliminar la existente.",
          "", "## Las 27 FK originales, una por una", "",
          "Las once que se crean conservan la nulabilidad de las columnas, comprueban los datos existentes (`WITH CHECK`) y usan `NO ACTION` al borrar o actualizar. Eso conserva el comportamiento restrictivo de las FK de origen, que no declaran cascadas.",
          "", "| FK del dump | Hija.campo | Padre.campo | Tratamiento de este paquete |", "|---|---|---|---|"]
for r in sorted(m["relations"], key=lambda r: r["name"]):
    lines.append(f"| `{r['name']}` | `{r['child']}.{r['child_key']}` | `{r['parent']}.{r['parent_key']}` | {labels[r['treatment']]} |")
lines += ["", "De las once FK SQL, dos son autorreferencias: `mline_td_proyecto_alternativa.id_alternativa_origen` y `mline_td_proyecto_regla_cfg.id_proyecto_regla_cfg_origen`. SQL Server sí permite estas FK; se mantienen como relaciones a la propia tabla, sin cascada.",
          "", "Los campos `id_estado_componente` e `id_estado_regla_cfg` aparecen en el mapeo de dominios del EFT, pero no tienen FK física en el dump. No se les inventan FK nuevas.",
          "", "Los cuatro vínculos entrantes desde las futuras clases espaciales quedan fuera de este paso. No se agrega ninguna FK para ellos sin cargar y comprobar esas clases.",
          "", "## Los 27 índices secundarios originales", "",
          "El archivo `02_restaurar_indices_no_unicos.sql` conserva las columnas y nombres originales; crea únicamente los que falten y omite una cobertura equivalente. **Estos índices no son PK ni FK y no imponen unicidad.** Las PK del archivo 03 son restricciones distintas.",
          "", "| Tabla | Índice de MySQL | Columnas |", "|---|---|---|"]
for i in sorted(m["original_indexes"], key=lambda i: (i["table"], i["name"])):
    lines.append(f"| `{i['table']}` | `{i['name']}` | {', '.join('`'+c+'`' for c in i['columns'])} |")
lines += ["", "Los tres índices de referencias retiradas siguen en el inventario porque existen en MySQL; recrear su índice de búsqueda no recrea su FK ni vuelve a poblar el campo. No se eliminan índices previos ni se duplican los equivalentes.",
          "", "## Fuentes y límites", "",
          "- EFT v2.4, 5.8.2: migración de claves/relaciones compatibles; reemplazo de Parámetros y Maestros GIS por funciones nativas.",
          "- EFT v2.4, 5.8.4: referencias retiradas, conservando sus campos vacíos hasta completar la transición.",
          "- EFT v2.4, 5.8.10–5.8.11: vínculos del modelo futuro y parámetros que pasan a dominios.",
          f"- Dump MySQL: `Mapline_20261030.sql`; SHA-256 `{m['source_sha256']}`.",
          "- [Esri: requisitos de branch](https://doc.esri.com/en/arcgis-pro/latest/help/data/geodatabases/overview/register-a-dataset-as-branch-versioned.html): el versionado branch no admite índices únicos de usuario.",
          "- [Microsoft: PRIMARY KEY y FOREIGN KEY](https://learn.microsoft.com/en-us/sql/relational-databases/tables/primary-and-foreign-key-constraints): la PK crea un índice único; la FK exige una clave candidata única en el padre.",
          "", "La comprobación local valida archivos y correspondencia con el dump. No demuestra que se hayan aplicado restricciones a la base real; eso se confirma al ejecutar el SQL y consultar el diagnóstico.", ""]
(BASE / "04_correspondencia_EFT_MySQL.md").write_text("\n".join(lines), encoding="utf-8")
print(json.dumps({"tables": len(names), "fk_by_treatment": counts}, ensure_ascii=False))
