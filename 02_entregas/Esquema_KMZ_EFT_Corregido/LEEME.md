# Datos_Proyecto_Controlado 1.13

Use ahora **Preparar carga inicial de los KMZ**, dentro de `Datos_Proyecto.pyt`. Reúne reglas de proyecto/análisis, oficinas SUNARP, propuestas de cobertura, descripciones y lectura de las claves de negocio reales. Incluye las 13 asociaciones ya confirmadas. Es de lectura: no crea clases ni carga filas.

Los pasos vigentes están al inicio de [GUIA_DATOS_PROYECTO.md](GUIA_DATOS_PROYECTO.md). Las propuestas para `vanos` y Bofedales no se aplican automáticamente. El modelo sigue en 76 clases y 3.340 campos. Consulte [CAMBIOS_1_13.md](CAMBIOS_1_13.md).

La configuración y las altas descritas abajo son antecedentes de la versión 1.12, ya ejecutados en el flujo actual. No es necesario repetirlos.

## Referencia histórica de la versión 1.12

La nueva herramienta **Preparar catálogo de proyectos para altas** resuelve la preparación de `mline_tc_proyecto`: dos dominios completos y una propuesta de auditoría UTC separada de los campos históricos. Por defecto solo valida. La propuesta de cuatro campos administrados por ArcGIS requiere aprobación explícita porque el usuario pidió evitar columnas adicionales.

Comience en [GUIA_DATOS_PROYECTO.md](GUIA_DATOS_PROYECTO.md). Use su conexión SDE y carpeta de informes para revisar la configuración. Los campos propuestos son `created_user`, `created_date`, `last_edited_user` y `last_edited_date`. Los cuatro campos de auditoría heredada permanecen intactos: el origen no acredita su zona horaria. No se convierten fechas ni se agrega auditoría retrospectiva.

Esta versión conserva las once herramientas anteriores y el modelo 12, con 76 clases y 3.340 campos. La configuración propuesta afecta únicamente al catálogo padre y a los dos dominios; no modifica el esquema de esas 76 clases ni registra proyectos. Después de verificar la configuración, ejecute la herramienta 11 para validar y crear JAENNORTE/POROMA. El CSV incluido conserva las nueve asociaciones confirmadas; los códigos nuevos se calculan al aplicar el alta, no aquí.

El estado PLAN_INGESTA_CON_PENDIENTES es un plan revisable, no una autorización de carga. Sus informes conservan separadamente los atributos del inmueble y de la persona jurídica, las rutas sin destino, los candidatos de proyecto y los campos obligatorios por resolver.

Consulte [CAMBIOS_1_12.md](CAMBIOS_1_12.md) para alcance y evidencia. Los documentos y pruebas numerados de versiones anteriores son históricos; el manifiesto identifica los archivos vigentes y sus SHA-256. Las pruebas nativas son sobre una geodatabase local de ensayo, no sobre su SQL Server.
