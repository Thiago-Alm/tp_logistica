# Registro de decisiones de diseño

Cada decisión de diseño que tomamos queda acá, con el motivo. No es burocracia:
la nota sale de una **defensa individual** donde cualquiera puede ser preguntado
sobre cualquier parte, y este archivo es la fuente del informe técnico y de la
justificación de persistencia políglota (entregables 1 y 2 del enunciado).

Formato de cada entrada: **qué se decidió**, **por qué**, **qué consecuencias
tiene** y **a quién le cambia el trabajo**.

---

## D1 — Los estados son `Enum`, no `str`

**Fecha:** 11/10/2026 · **Alcance:** todo el dominio

Todo campo que represente un estado o una categoría cerrada se modela como un
`Enum` de Python (`EstadoEnvio`, `PrioridadEnvio`, `EstadoContenedor`), no como
un `str` libre.

**Por qué:** el enunciado pide "controles de integridad" entre los requisitos de
calidad. Un `str` acepta `"EN_TRANISTO"` sin chistar y el error aparece semanas
después en un reporte que devuelve menos filas de las que debería. Además, la
lista de valores válidos tiene que existir en un solo lugar, porque el DDL de
Postgres la repite en un `CHECK (estado IN (...))` o en un tipo `ENUM`.

**Consecuencias:** la fuente de verdad de los valores válidos es el dominio. Si
se agrega un estado, se agrega primero acá y después en el DDL.

**Le cambia el trabajo a:** Fran (los `CHECK` del DDL salen de estos enums).

---

## D2 — `Enum` puro, no `(str, Enum)`

**Fecha:** 11/10/2026 · **Alcance:** todo el dominio

Los enums heredan de `Enum` y no de `(str, Enum)`. Convertir a string al escribir
(`envio.estado.value`) y reconstruir al leer (`EstadoEnvio(fila["estado"])`) es
responsabilidad del repositorio.

**Por qué:** el dominio no conoce la persistencia. Es coherente con la
arquitectura en capas, que es lo que el enunciado pide en "Restricciones
Técnicas". Con `(str, Enum)` la conversión queda implícita y el día que Mongo
devuelva el string crudo nadie se entera de que se perdió el tipo.

**Consecuencias:** cada repositorio necesita un mapeo explícito dominio ↔ fila.
Eso no es costo perdido: ese mismo mapeo se reusa en el Outbox, donde la misma
entidad tiene que salir hacia Neo4j y Mongo.

**Le cambia el trabajo a:** todos los que escriban un repositorio.

---

## D3 — Dónde van las validaciones

**Fecha:** 11/10/2026 · **Alcance:** dominio y servicios

El criterio es uno solo: **¿puedo verificar esta regla con los campos del objeto,
sin consultar ninguna base?**

- **Sí** → va en el dominio, en `__post_init__` / `_validar()`.
  Ejemplo: `origen_id != destino_id`.
- **No** → va en el servicio.
  Ejemplo: que `cliente_id` exista, o que un contenedor no esté en dos envíos
  activos a la vez.

**Por qué:** sin un criterio explícito, la misma validación termina duplicada en
el dominio, en el servicio y en el repositorio, y las tres versiones se
desincronizan.

**Consecuencias:** el dominio queda sin dependencias de infraestructura y se
puede testear sin levantar ninguna base (los 16 tests actuales corren en 0,05 s).

---

## D4 — Las transiciones de estado viven en el dominio

**Fecha:** 11/10/2026 · **Alcance:** `domain/envio.py`

Las transiciones permitidas entre estados de un envío son un diccionario
(`_TRANSICIONES_ENVIO`) consultado desde métodos del propio enum
(`puede_pasar_a`, `es_final`). El cambio de estado se hace con `Envio.pasar_a()`,
no asignando `envio.estado` directo.

**Por qué va en el dominio:** por D3 — para saber si `CREADO → ENTREGADO` es
válido no hace falta consultar nada.

**Por qué un diccionario y no el patrón State:** cinco clases para cinco estados
que casi no tienen comportamiento propio es sobreingeniería. El profesor pidió
simplificar. Un mapa da el mismo control y se lee de un vistazo.

**Por qué `pasar_a()` y no asignación directa:** sin ese método el mapa es
decorativo, porque cualquiera lo esquiva asignando el campo. `pasar_a()` además
revierte el cambio si la validación posterior falla, con el mismo razonamiento
que una transacción: el objeto queda consistente en el estado nuevo o como
estaba, nunca a mitad de camino.

**Transiciones definidas:**

| Desde | Hacia |
|---|---|
| `CREADO` | `EN_TRANSITO`, `CANCELADO` |
| `EN_TRANSITO` | `EN_PUERTO`, `ENTREGADO`, `CANCELADO` |
| `EN_PUERTO` | `EN_TRANSITO`, `ENTREGADO`, `CANCELADO` |
| `ENTREGADO` | — (final) |
| `CANCELADO` | — (final) |

`EN_PUERTO → EN_TRANSITO` es intencional: un envío marítimo pasa por varios
puertos antes de llegar.

---

## D5 — `Tramo` es una tabla propia en PostgreSQL

**Fecha:** 12/10/2026 · **Alcance:** modelo físico de Postgres

`Tramo` es una tabla con clave primaria propia y FK a `envio`, `vehiculo` y
`ubicacion` (origen y destino). **No** es una columna `JSONB` dentro de `envio`.

**Por qué:**

1. **Integridad referencial.** Tramo tiene tres claves foráneas
   (`vehiculo_id`, `origen_id`, `destino_id`). Dentro de un `JSONB`, Postgres no
   puede imponer ninguna: se podría borrar un vehículo y los tramos quedarían
   apuntando a un registro inexistente. Perderíamos exactamente la capacidad por
   la que elegimos un motor relacional para esta parte del sistema.
2. **Agregación.** Los reportes "Costos por tipo de transporte" y "Tiempos
   promedio de entrega" agrupan sobre campos del tramo
   (`medio_transporte`, `costo`). Con tabla propia es un `GROUP BY` indexable;
   con `JSONB` hay que desarmar el array de cada envío con `jsonb_array_elements`
   antes de poder agrupar, escaneando todos los envíos.
3. **Sincronización.** El Outbox propaga cada tramo a Neo4j como una relación
   entre dos `Ubicacion`. Un tramo embebido en un JSON no tiene id propio
   estable, y sin ese id no se puede hacer un `MERGE` idempotente en Cypher.

**Le cambia el trabajo a:** Fran (tabla `tramo` con tres FK en el DDL) y a
Umbi (la relación en el grafo sale de esta tabla).

---

## D6 — `Envio` no carga sus tramos; el servicio los compone

**Fecha:** 12/10/2026 · **Alcance:** dominio, repositorios y servicios

`Tramo` tiene su propio repositorio (`TramoRepository`). El dataclass `Envio`
**no** tiene un campo `tramos: list[Tramo]`. Cuando una consulta necesita el
envío con sus tramos ("ruta completa de un envío", "seguimiento temporal"), el
**servicio** llama a los dos repositorios y compone el resultado.

**Por qué:**

1. El reporte "Costos por tipo de transporte" agrupa tramos de *todos* los
   envíos. Si los tramos solo se alcanzaran a través de un `Envio`, habría que
   levantar todos los envíos a memoria y sumar en Python, teniendo Postgres al
   lado: lo contrario de elegir el motor según el proceso.
2. Coherencia: la arquitectura ya es un repositorio por entidad con interfaces
   `ABC`. `TramoRepository` encaja sin inventar un patrón nuevo.
3. Simplicidad, que es lo que pidió el profesor.
4. El Outbox propaga tramos individuales; con repositorio propio el evento lleva
   el tramo y no hace falta levantar el envío entero.

**Objeción prevista y su respuesta:** *¿quién garantiza que el origen del primer
tramo coincida con el origen del envío, o que los tramos no se pisen en el
tiempo?* El **servicio** (`EnvioService`), por el criterio de D3: son reglas que
necesitan consultar otras entidades.

---

## D7 — `fecha_llegada_estimada` se deriva, no se denormaliza

**Fecha:** 12/10/2026 · **Alcance:** `domain/envio.py`, reportes

`Envio` **no** tiene `fecha_llegada_estimada`. El reporte "Envíos demorados" se
calcula como: *el envío no está entregado y el máximo de
`fecha_llegada_estimada` entre sus tramos ya pasó*.

**Por qué:** denormalizar la estimada en `Envio` haría el reporte trivial, pero
crearía un dato que hay que mantener sincronizado cada vez que cambia un tramo
— un problema de consistencia **dentro de una sola base**, justamente en un TP
cuyo tema es la consistencia entre bases. Derivarlo cuesta un `MAX ... GROUP BY`
y no cuesta nada de defender.

**Le cambia el trabajo a:** Fran (el reporte sale de un `GROUP BY ... HAVING`,
no de una columna).

---

## D8 — `codigo_iso` se valida con 11 caracteres (ISO 6346)

**Fecha:** 11/10/2026 · **Alcance:** `domain/contenedor.py`, datos de prueba

El código internacional de contenedor se valida con largo exacto 11, que es el
formato ISO 6346 (4 letras de dueño y categoría + 7 dígitos), por ejemplo
`MSKU1234567`.

**Por qué:** es un control de integridad barato sobre un identificador que es
único por contenedor y que se usa para buscarlo
(`ContenedorRepository.obtener_por_codigo`).

**Le cambia el trabajo a: Umbi.** El generador de datos de prueba **tiene que
producir códigos de 11 caracteres** o va a fallar la construcción de todo
`Contenedor`. Hay un test que lo verifica
(`test_el_codigo_iso_debe_tener_once_caracteres`). Si el generador no puede
cumplirlo, hay que relajar la validación antes, no después.
