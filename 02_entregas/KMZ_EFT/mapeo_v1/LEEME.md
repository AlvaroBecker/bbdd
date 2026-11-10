# Primer mapeo de los KMZ al EFT

El inventario recibido en `inventario_ArcGIS_20261103_114443` coincide por nombre y SHA-256 con los trece originales revisados. Se conservaron sus 3.655 filas y 279.623 Placemarks. La propuesta los organiza en **1.403 contextos de revisión**, sin fusionar entidades ni excluir registros.

El archivo principal es [Mapeo_KMZ_EFT_propuesta_v1.xlsx](../../../outputs/mapline_kmz_20261103_v1/Mapeo_KMZ_EFT_propuesta_v1.xlsx). Se abre en Excel; no se ejecuta en la ventana Python de ArcGIS.

## Continuación operativa: transferencia sin resolver el mapeo

Se autorizó avanzar con los trece KMZ, incluidos los contenidos ambiguos, dejando las preguntas para ENGIE. El [cargador a SDE](../carga_sde/LEEME.md) crea clases neutrales nuevas bajo `gis`, conserva los atributos y la procedencia de cada Placemark, y registra lo que ArcGIS no convierta. No exige completar este Excel para esa transferencia de conservación.

Esta transferencia no convierte las propuestas del Excel en aprobaciones ni asigna automáticamente los destinos EFT o las claves pendientes. Las decisiones siguientes se mantienen para la revisión posterior con ENGIE, sin bloquear el paso de las entidades convertibles.

## Orden de revisión

1. **Proyectos:** comprobar los códigos candidatos para los trece archivos. Los campos amarillos permiten indicar el proyecto y el `id_analisis` de la carga inicial cuando estén definidos. Los candidatos no están confirmados y el código de análisis no se inventa.
2. **Revisión:** filtrar por archivo, familia y geometría. Comparar la clase propuesta con el contenido y completar destino, inclusión y comentario únicamente cuando corresponda. Una exclusión requiere motivo.
3. **Detalle:** localizar el grupo y consultar las rutas y contenedores originales. Todas las filas del inventario se mantienen identificables.
4. **MySQL:** consultar los cuarenta proyectos y ciento veinte componentes del dump. Se conservan nombres repetidos y valores literales de `es_registro`, sin usarlos para filtrar ni interpretar automáticamente su vigencia.

Los campos vacíos permanecen pendientes. Incluso al indicar destino, proyecto y análisis, el estado solicita validar atributos y vínculos: el Excel no demuestra que la geometría, el componente o la alternativa estén resueltos.

La correspondencia de **Proyectos** es un punto de partida por archivo. Si un KMZ contiene elementos de más de un proyecto, no debe asignarse un único código a todo el archivo: dejarlo pendiente y documentar los grupos que necesitan una correspondencia más fina. Un nombre de localidad no demuestra identidad de proyecto.

## Propuestas y casos a resolver

Hay 311 filas de origen con una clase propuesta y 3.344 cuyo destino único todavía requiere interpretación. Los nombres conceptuales proceden del EFT; la geometría y el contexto de carpetas aportan evidencia para revisión, no una aprobación de carga.

- **Felam:** se conservan `PRY-00000010` y `PRY-00000027` como candidatos. Comparten circuitos y no se elige por similitud parcial.
- **Jaén Norte y Poroma:** no se encontró correspondencia nominal en los cuarenta proyectos del respaldo. Se necesita confirmar una equivalencia documentada o definir el alta correspondiente antes de asignar códigos. No se reservaron IDs nuevos.
- **Pucallpa:** la correspondencia principal con Aguaytía–Pucallpa debe distinguirse del proyecto Shipibo–Manantay y sus seccionamientos.
- **Componentes:** hay nombres repetidos, particularmente en Palián y Pariñas. Elegir un proyecto no valida automáticamente `id_proyecto_componente`.
- **Áreas de campo:** las áreas de FELAM bajo EBI01A y EBI01B se proponen como `AreaEstudioCampo`, aunque la hoja se llame solamente “ÁREA DE ESTUDIO”. No se sustituyen por el área general del proyecto.
- **Calicatas:** el tema se reconoce por el ancestro de la carpeta. Las hojas de Jaén que se llaman LT o Subestación no se convierten por eso en infraestructura eléctrica.
- **Recortes públicos:** ríos, vías, ANP, predios SUNARP y otros temas reconocibles se proponen como clases `_Recorte` de proyecto. La capa maestra completa se obtiene del servicio oficial.
- **Subestaciones y otros temas mixtos:** los nombres físicos para punto y polígono necesitan diferenciarse. El nombre conceptual `Subestacion` todavía no es un nombre SQL aprobado.
- **TORRES repetidas en Pariñas:** se mantienen todas las filas. Los nombres y conteos similares son una señal de revisión; no prueban duplicidad geométrica o equivalencia entre alternativas.

## PLS-CADD: revisión agrupada

Sus 2.271 filas se organizan en 49 contextos de raíz de modelo, rol y geometría. No se genera una clase por `Section #`.

Se ejecutó una prueba temporal de `KML To Layer` con Jaén Norte. Las 78 secciones conservan en `PopupInfo` sus extremos, tensión, cable y condición; los nombres de ambos extremos coinciden con puntos de `Structure locations`. Sin embargo, la geodatabase produjo 822 entidades bajo las secciones a partir de 847 Placemarks y 924 entidades para todo el modelo PLS-CADD frente a 950 Placemarks. Además, varias polilíneas representan tramos intermedios y no un único vano entre los extremos declarados.

La prueba confirma que ArcGIS sirve para inspección temporal, pero no concilia las entidades ni aprueba una estructura de negocio. No se debe convertir automáticamente cada línea de `Section` en un registro de `Vano`. El detalle del método, conteos y discrepancias está en [PRUEBA_PLS_CADD_JAENNORTE.md](PRUEBA_PLS_CADD_JAENNORTE.md). La granularidad sección/vano, el tratamiento de gráficos y sus destinos EFT permanecen pendientes de validación.

## Datos de apoyo

- `datos/01_mapeo_detallado_propuesto.csv`: copia íntegra del inventario recibido con columnas derivadas adicionales. Sus campos de aprobación originales permanecen vacíos.
- `datos/02_grupos_revision.csv`: los 1.403 grupos antes de cualquier edición manual en Excel.
- `datos/03_proyectos_candidatos.csv`: las trece correspondencias candidatas y su evidencia.

Las ediciones del Excel no se exportan automáticamente a esos CSV. Cuando se cierre la revisión, se deberá generar una versión de carga desde las decisiones acordadas y comprobar sus atributos, claves y geometrías.

Fuentes: EFT v2.4, secciones 5.8.4–5.8.11; inventario recibido de ArcGIS Pro; los trece KMZ con hashes coincidentes; y `Mapline_20261030.sql`, SHA-256 `ea9fc0fafa0f0f9cd1688cd4777901f45fbe9db307ee1d2e2272edefca0c63dd`.

La preparación no modifica SQL Server, los KMZ ni el inventario recibido. No se han aprobado filas, creado proyectos ni interpretado automáticamente los valores de borrado lógico. Las fórmulas y las vistas del Excel se comprueban durante su generación; queda pendiente la revisión de negocio y la validación GIS de la carga.
