# Generador de datos de prueba

Responsable: UMBI

## Alcance actual

Genera cinco contenedores con UUID propios y códigos de 11 caracteres.
El lote se conserva en `scripts/datos_generados/contenedores.json`.

Los códigos cumplen el largo exigido por el proyecto.
No se calcula el dígito verificador del estándar ISO 6346 completo.

## Generación

Ejecutar desde la carpeta principal del proyecto:

    python scripts/generar_datos.py

El programa no sobrescribe un archivo existente.
El lote incluido en el repositorio puede cargarse directamente,
sin volver a generarlo.

## Carga en PostgreSQL

Con el entorno virtual activo, PostgreSQL iniciado y el esquema creado:

    python scripts/cargar_contenedores.py

La conexión se obtiene del archivo `.env`.
La carga conserva los UUID del JSON y omite los identificadores
que ya existen en PostgreSQL.

## Verificación realizada

- Primera carga: cinco contenedores insertados.
- Segunda carga del mismo lote: cero inserciones nuevas.

## Pendientes

Ampliar el generador con las entidades relacionadas y los escenarios
necesarios para probar el sistema completo.