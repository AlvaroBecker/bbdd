# Prueba técnica PLS-CADD: Jaén Norte

**Fecha:** 3 de noviembre de 2026  
**Resultado:** conversión temporal ejecutada; mapeo de negocio pendiente.

## Alcance y método

Se convirtió `kmz/Proyecto JAENNORTE.kmz` con `KML To Layer` de ArcGIS Pro 3.7.1 a una geodatabase temporal. El origen no se modificó y no se ejecutó ninguna carga a SQL Server, SDE ni ArcGIS Enterprise.

La geodatabase de esta sesión quedó en:

`C:\Users\aibecker\.copilot\session-state\c0d3f30e-fca8-404f-b5a0-55d100685bf6\files\jaen_pls_test\JaenNortePLS.gdb`

La comparación de extremos es un diagnóstico exploratorio: se compararon las coordenadas inicial y final de cada polilínea con las ubicaciones de las estructuras nombradas en los metadatos de la sección, usando distancia horizontal aproximada sobre WGS84. No es un umbral de aceptación ni una validación topológica de ArcGIS.

## Conteos

| Salida de KML To Layer | Elementos |
|---|---:|
| Points | 2.444 |
| Polylines | 3.157 |
| Polygons | 1.623 |
| Multipatches | 221 |
| **Total convertido** | **7.445** |

El inventario registra 7.005 Placemarks para este KMZ. La salida contiene 440 entidades más que los Placemarks de origen; por ello, el conteo de entidades resultante no debe usarse como conteo de registros de negocio.

En las ubicaciones PLS-CADD examinadas:

| Contexto | Inventario KML | Geodatabase temporal |
|---|---:|---:|
| `Structure locations` | 42 Placemarks | 42 puntos |
| `Section #...` | 847 Placemarks | 822 entidades: 78 puntos, 525 polilíneas y 219 multipatches |
| Resto de `PLS-CADD Model` | 103 Placemarks | 102 entidades: 100 polilíneas y 2 multipatches |
| **Modelo PLS-CADD** | **950 Placemarks** | **924 entidades** |

La diferencia entre el origen y la salida no está conciliada. La conversión sí genera geometrías separadas por tipo, pero la expansión o agrupación de geometrías KML no conserva una equivalencia simple de conteos. Las cuatro clases resultantes reportan WKID 4326 y geometría Z.

## Atributos y vínculos observados

- Los 42 puntos de `Structure locations` conservan nombre y `PopupInfo`.
- Las 78 secciones tienen un punto con nombre `Section #...` y `PopupInfo` con tensión, cable, estructura inicial, estructura final y condición de disposición.
- Se pudieron extraer ambos nombres de extremo en las 78 secciones. Los 78 extremos iniciales y los 78 finales coinciden por nombre con uno de los 42 puntos de estructura.
- Las polilíneas y multipatches bajo las secciones son principalmente representación geométrica: en las muestras examinadas sus nombres son genéricos (`Placemark`) y no tienen `PopupInfo` propio.

La coincidencia de nombres confirma que el vínculo está disponible como atributo en esta muestra; no valida por sí sola el identificador de negocio ni demuestra que cada geometría de línea sea un `Vano`.

## Geometría: resultado no concluyente para carga automática

Al comparar los extremos de polilíneas con los extremos declarados en la sección, el mejor candidato geométrico quedó a más de 100 m en 16 de las 78 secciones. En varios casos, esos extremos de línea están cerca de estructuras intermedias: por ejemplo, una sección declarada entre T01 y T05 tiene una polilínea cuyos extremos quedan cerca de T02 y T03. Esto es consistente con una sección que agrupa varias representaciones o vanos, no con una única línea de negocio de extremo a extremo.

Por tanto:

1. No convertir cada polilínea de una `Section` directamente en un registro `Vano`.
2. No usar el nombre `Section #...` como clave de negocio aprobada.
3. Mantener el punto con `PopupInfo` separado de las geometrías de visualización hasta definir la granularidad y los vínculos con el responsable del modelo.
4. Antes de una carga, conciliar los 950 Placemarks de origen con las 924 entidades temporales y revisar las 16 discrepancias espaciales, incluidos los tramos intermedios y las alternativas/set.

## Conclusión

La conversión sirve para inspección GIS y recupera metadatos útiles de las secciones, pero no entrega por sí sola una estructura de entidades de negocio lista para el EFT. El siguiente paso requiere acordar la granularidad de sección/vano, el tratamiento de los gráficos y los campos de destino. Esta prueba no aprueba filas ni cambia la propuesta de mapeo.

## Decisión operativa posterior

Se autorizó transferir también los contenidos ambiguos sin esperar esas respuestas. El [cargador neutral a SDE](../carga_sde/LEEME.md) conserva las entidades convertibles y los atributos, sin clasificarlas como `Vanos` ni inventar claves de negocio. Las preguntas anteriores se mantienen para ENGIE y no bloquean esa transferencia de conservación.
