"""Registro de supuestos provisionales y preguntas de negocio del mapeo EFT."""
from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

SUPUESTOS = {
    "S-01": ("Estructura EFT", "Se respeta la estructura 5.8: tres datasets y geometria WGS84 con Z."),
    "S-02": ("Id de analisis", "La carga inicial se identifica como 'Carga inicial KMZ'."),
    "S-03": ("Codigo de proyecto", "El codigo se asigna por el nombre del archivo KMZ; los codigos PROV-* quedan pendientes de validacion."),
    "S-04": ("Disciplina", "La carpeta proveedora mas cercana a la raiz define disciplina; las inferencias por nombre de proveedor son provisionales."),
    "S-05": ("Componente y condicion", "Alternativa, componente y condicion se derivan de nombres de carpeta/archivo cuando son explicitos."),
    "S-06": ("Fuente", "Se usa la entidad oficial identificada por la ruta; si no existe, la fuente por defecto del EFT."),
    "S-07": ("Tema", "Se usa el dominio de tema del EFT para capas externas e internas."),
    "S-08": ("Capa publica", "Una capa publica se considera recorte del proyecto por el nombre de la capa y su geometria."),
    "S-09": ("Nombres fisicos", "Clases de geometria multiple usan sufijos Pto/Lin/Pol; los recortes terminan en _Recorte."),
    "S-10": ("Duplicados", "Se omiten duplicados geometricos exactos dentro del mismo destino; la copia Final prevalece sobre Prefinal."),
    "S-11": ("PLS-CADD", "Structure locations se propone como Estructuras y Section como Vanos segun geometria."),
    "S-12": ("Trazos migrados", "Los ejes/trazos de transmision destinados a clases migradas no se cargan en esta toolbox."),
    "S-13": ("Bofedales", "Bofedales se propone como EcosistemasFragiles_Recorte, pendiente de confirmacion de negocio."),
    "S-14": ("CUM", "CUM y catastro/concesion minera se proponen como CatastroMinero_Recorte."),
    "S-15": ("Calicatas", "Solo puntos de calicata se proponen como Calicatas; lineas y poligonos quedan pendientes."),
    "S-16": ("Estaciones", "Las areas de estudio de una estacion se proponen como AreaEstudioCampo; los puntos de muestreo como Muestreo."),
    "S-17": ("Predios", "Catastro rural y predios SUNARP se separan por el nombre de capa."),
    "S-18": ("Geometrias especiales", "Overlays, objetos sin geometria y multipatch se conservan en origen y no se cargan a clases vectoriales."),
    "S-19": ("Identificador de origen", "id_origen se extrae de CODRUTA, ANP_CODI, CODIGOU o COD_PREDIO cuando existe."),
    "S-20": ("Atributos KML", "Atributos KML/HTML que no tienen campo EFT equivalente se preservan como JSON en kz_atributos."),
    "S-21": ("Versionado", "Editor Tracking UTC y GlobalID se habilitan; Datos_Proyecto se versiona al final y solo con conexion branch."),
    "S-22": ("Condicion de recortes", "Un recorte sin condicion explicita recibe condicion Existente."),
    "S-23": ("Nombre vacio", "Si el Placemark no tiene nombre, se usa la carpeta hoja como nombre."),
    "S-24": ("Ancho de franja", "Franjas de hasta 60 m se proponen como FranjaServidumbre; anchos mayores quedan para revision."),
    "S-25": ("Registro de campo", "Waypoints, tracks y fotos/puntos de visita se proponen como RegistroCampo."),
    "S-26": ("Prefinal y Final", "Las rutas Prefinal se procesan despues de las demas para que sobreviva la copia Final ante duplicados exactos."),
}

PREGUNTAS = {
    "Q-01": ("Proyecto, alternativa y componente", "Confirmar codigos PRY por KMZ, alternativas/componentes y reemplazo de los codigos PROV-* antes de cargar."),
    "Q-02": ("Disciplina de carpetas", "Confirmar disciplina de MyA, JP Planing, proveedores inferidos y carpetas mixtas."),
    "Q-03": ("Nombres fisicos", "Confirmar nombres fisicos y sufijos de las clases, especialmente las que admiten varias geometrias."),
    "Q-04": ("PLS-CADD", "Confirmar si Structure locations y Section se mapean a Estructuras y Vanos y como tratar el resto del modelo."),
    "Q-05": ("Trazos", "Definir clase o mecanismo de carga para ejes y trazos de transmision que hoy pertenecen a clases migradas."),
    "Q-06": ("Objetos no vectoriales", "Definir retencion/publicacion de GroundOverlay, ScreenOverlay y Placemarks sin entidad convertida."),
    "Q-07": ("Multipatch", "Definir si modelos 3D deben conservarse en otra estructura."),
    "Q-08": ("Duplicados y CAD", "Confirmar eliminacion de duplicados exactos y tratamiento de primitivas CAD."),
    "Q-09": ("Capas internas y publicas", "Confirmar precedencia cuando una capa podria ser interna del proyecto y tambien de referencia publica."),
    "Q-10": ("Equivalencia de atributos", "Confirmar si los atributos KML se conservan como JSON o requieren campos EFT dedicados."),
    "Q-11": ("Temas de ecosistemas y mineria", "Confirmar bofedales, ecosistemas, CUM y clases sin equivalencia inequívoca."),
    "Q-12": ("Patrimonio", "Confirmar la asignacion de capas arqueologicas y paleontologicas a las clases EFT."),
    "Q-13": ("Franja y corredor", "Definir el umbral entre servidumbre y corredor/area de estudio para franjas mayores de 60 m."),
    "Q-14": ("Calicatas no puntuales", "Definir el destino de lineas, poligonos y CAD dentro de carpetas de calicatas."),
    "Q-15": ("Id de origen", "Validar las claves usadas para llenar id_origen y las excepciones por fuente."),
    "Q-16": ("Z y tolerancia", "Confirmar preservacion de Z, tolerancias y tratamiento de coordenadas al cargar en SDE."),
    "Q-17": ("Campos kz_*", "Confirmar la permanencia de los campos de trazabilidad kz_* despues de validar la migracion."),
    "Q-18": ("Capas publicas completas", "Acordar si las capas de referencia se cargan completas o solo recortadas al area de proyecto."),
    "Q-19": ("Clases EFT faltantes", "Asignar capas sin clase evidente, categorias viales genericas y temas de referencia no catalogados."),
    "Q-20": ("RegistroCampo", "Confirmar que waypoints, tracks, imagenes y puntos de visita corresponden a RegistroCampo."),
}

COLUMNAS = (
    "grupo_id", "archivo_origen", "ruta_kml", "geometria", "entidades", "objetos",
    "tipo", "id", "descripcion", "grupos", "objetos_afectados", "comentario",
)


def _agregar(impacto, grupo):
    for codigo in (grupo.get("supuestos") or "").split(","):
        if codigo.strip():
            dato = impacto[codigo.strip()]
            dato["grupos"].add(grupo["grupo_id"])
            dato["objetos"] += int(grupo.get("objetos") or 0)
    for codigo in (grupo.get("preguntas") or "").split(","):
        if codigo.strip():
            dato = impacto[codigo.strip()]
            dato["grupos"].add(grupo["grupo_id"])
            dato["objetos"] += int(grupo.get("objetos") or 0)


def generar_registro(filas):
    """Construye filas de registro con el impacto acumulado por IDs usados en el mapeo."""
    impacto = defaultdict(lambda: {"grupos": set(), "objetos": 0})
    for fila in filas:
        _agregar(impacto, fila)
    resultado = []
    for codigo, (titulo, descripcion) in SUPUESTOS.items():
        dato = impacto[codigo]
        resultado.append({
            "tipo": "SUPUESTO", "id": codigo, "descripcion": descripcion,
            "grupos": len(dato["grupos"]), "objetos_afectados": dato["objetos"], "comentario": "",
        })
    for codigo, (titulo, descripcion) in PREGUNTAS.items():
        dato = impacto[codigo]
        resultado.append({
            "tipo": "PREGUNTA", "id": codigo, "descripcion": descripcion,
            "grupos": len(dato["grupos"]), "objetos_afectados": dato["objetos"], "comentario": "",
        })
    return resultado


def escribir_registro(filas, carpeta):
    """Escribe registro de preguntas/supuestos en CSV UTF-8 BOM y Markdown."""
    carpeta = Path(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    registro = generar_registro(filas)
    csv_path = carpeta / "supuestos_y_preguntas.csv"
    md_path = carpeta / "supuestos_y_preguntas.md"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as salida:
        escritor = csv.DictWriter(salida, fieldnames=COLUMNAS, delimiter=";", extrasaction="ignore")
        escritor.writeheader()
        for fila in registro:
            escritor.writerow(fila)
    with md_path.open("w", encoding="utf-8", newline="\n") as salida:
        salida.write("# Supuestos y preguntas de negocio\n\n")
        salida.write("Los supuestos son decisiones provisionales de migracion. Las preguntas deben confirmarse con ENGIE; ")
        salida.write("editar el CSV de mapeo no altera este registro hasta volver a generar la propuesta.\n\n")
        salida.write("| Tipo | ID | Descripcion | Grupos | Objetos afectados |\n")
        salida.write("|---|---|---|---:|---:|\n")
        for fila in registro:
            descripcion = fila["descripcion"].replace("|", "\\|")
            salida.write(f"| {fila['tipo']} | {fila['id']} | {descripcion} | {fila['grupos']} | "
                         f"{fila['objetos_afectados']} |\n")
    return csv_path, md_path
