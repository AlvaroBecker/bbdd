# Versión 1.13: preparar la carga inicial

La preingesta ya comprobó los 13 KMZ y sus proyectos. Esta versión incorpora la herramienta **Preparar carga inicial de los KMZ**, dentro del mismo `Datos_Proyecto.pyt`, para reunir las reglas y obtener las correspondencias de negocio que aún no se habían leído del destino.

## Cambios

- Define las 76 reglas de `proyecto` a partir de las asociaciones confirmadas y las 76 de `id_analisis` con el literal del EFT `Carga inicial KMZ`. Quedan cuatro reglas de identidad que requieren conservar/cotejar las claves de negocio y el padre de los vértices.
- Implementa la separación de oficinas SUNARP: primera ocurrencia a `oficina_registral`, segunda a `oficina_1`, verificando archivo, hash, ruta, miembro KML, canal HTML, ocurrencia y contexto. No agrega columnas. Conserva ambos roles incluso cuando sus textos coinciden. La lectura de los originales comprobó 1.019 registros y 1.378 valores.
- Sustituye la propuesta antigua de cambiar el esquema SUNARP por reglas que reutilizan sus campos. Las otras propuestas no se eliminan.
- Conserva 3.638 rutas y propone destinos sustentados para 91 pendientes: 80 hacia cuatro clases existentes y 11 hacia una clase propia propuesta para Bofedales INAIGEM. Las propuestas requieren revisión; no se aplican al modelo ni a la SDE.
- Detalla el tratamiento PLS-CADD y propone `vanos` a partir del EFT y la conectividad de los nombres. Una carpeta Section no se convierte automáticamente en un vano. Copias y CAD siguen la excepción de revisión/exclusión del EFT.
- Distingue las 59 rutas con `description`: 23 ya representan sus pares HTML en atributos mapeados o reglas de campos de sistema; 36 requieren tratamiento. No descarta HTML en bloque ni pierde referencias a las 113 fotografías encontradas en POROMA.
- Lee proyecto, componente, alternativa, tres clases de negocio y vértices. Detecta duplicados, huérfanos, diferencias de proyecto e información incompleta. No deduce IDs desde OBJECTID ni reserva códigos a partir del máximo.
- Incluye el CSV de las 13 asociaciones confirmadas. FELAM usa PRY-00000027; PUCALLPA, PRY-00000001; JAENNORTE y POROMA, PRY-00000041/42. Su existencia se vuelve a comprobar contra el catálogo real.

## Uso y límites

Extraer en una carpeta nueva, agregar `Datos_Proyecto.pyt` y ejecutar **Preparar carga inicial de los KMZ**. Indicar conexión SDE, carpeta raíz de los 13 KMZ, DB `ArcGisAWS`, propietario `gis` e informes. Mantener el CSV incluido salvo cambio explícito de asociaciones.

La herramienta escribe únicamente informes. Conserva el modelo 12 (76 clases/3.340 campos) y las doce herramientas anteriores. `vanos` y `bofedales_inaigem_recorte` son propuestas, aún no clases creadas. Ninguna ruta se marca autorizada para cargar.

`PREPARACION_CON_PENDIENTES` significa que las lecturas requeridas terminaron, pero aún hay decisiones de carga. `PREPARACION_INCOMPLETA` identifica fuentes, destino, proyectos o tablas de negocio que no pudieron acreditarse. `ERROR_DETENIDO` conserva el error y el informe parcial. No es necesario repetir el cierre de tipos ni las altas ya ejecutadas.

La validación automatizada incluye pruebas unitarias, lectura de SUNARP original y ArcPy real en una copia local con catálogo sintético. No equivale a una prueba en la SDE de CT6788. No certifica publicación, branch versioning ni reparación geométrica.
