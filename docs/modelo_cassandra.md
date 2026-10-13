# Modelo de Cassandra

Responsable: MATI

## Objetivo

Cassandra se utilizará para:

- Registrar de forma continua las lecturas de los sensores IoT.
- Reconstruir el recorrido GPS de un contenedor.
- Guardar el historial de eventos logísticos de envíos y contenedores.

Son datos masivos, de solo agregar, con consultas conocidas de antemano.
Cassandra no hace JOIN ni agregaciones (SUM, AVG): los promedios y análisis
se calculan en la aplicación leyendo por partición, o se resuelven en
MongoDB y PostgreSQL.

Script de creación: `scripts/cassandra/cassandra_modelo.cql`.

## Convenciones

- Keyspace: `logistica`.
- Nombres en español, `snake_case`, sin tildes.
- Todo id es `uuid` y es el mismo que en las demás bases.
- Fechas en UTC.
- `SimpleStrategy` con factor de replicación 1 solo para desarrollo. En un
  entorno real se usaría `NetworkTopologyStrategy` con factor 3.

## Fuente de datos

PostgreSQL conserva los datos maestros (envíos, contenedores, sensores).
Cassandra no tiene claves foráneas: la validez de `envio_id`, `sensor_id` y
`contenedor_id` la garantiza la capa de aplicación y el chequeo de
consistencia de la sincronización.

## Consultas que debe responder

El modelo se diseñó a partir de las consultas, una tabla por cada una.

| Consulta | Tabla |
|---|---|
| Q1. Lecturas históricas de un sensor en un rango de fechas | lecturas_por_sensor |
| Q2. Última lectura de un sensor | lecturas_por_sensor (LIMIT 1) |
| Q3. Recorrido GPS de un contenedor | recorrido_por_contenedor |
| Q4. Eventos de un envío en orden cronológico | eventos_por_envio |
| Q5. Historial de movimientos de un contenedor | eventos_por_contenedor |

## Tablas

### lecturas_por_sensor

| Campo | Tipo | Descripción |
|---|---|---|
| sensor_id | uuid | Sensor que emite la lectura (partition key) |
| dia | date | Día de la lectura (partition key) |
| momento | timestamp | Fecha y hora (clustering key, descendente) |
| contenedor_id | uuid | Contenedor asociado |
| temperatura | double | |
| humedad | double | |
| vibracion | double | |
| latitud | double | Posición GPS |
| longitud | double | Posición GPS |
| bateria | int | Nivel de batería |

- Clave primaria: `((sensor_id, dia), momento)`.
- La partición agrupa un sensor y un día. Sin el día, la partición de un sensor
  crecería sin límite. Con una lectura por minuto son 1.440 filas por partición,
  muy por debajo del tamaño recomendado (alrededor de 100.000 filas).
- El orden descendente deja la última lectura primera, por eso Q2 es un `LIMIT 1`.
- `momento` corresponde al campo `momento` de la clase `Lectura`. El campo `dia`
  no existe en la clase: la aplicación lo calcula a partir de `momento` (en UTC)
  al escribir la lectura.
- Compactación `TimeWindowCompactionStrategy` por día, pensada para series de tiempo.

### recorrido_por_contenedor

| Campo | Tipo | Descripción |
|---|---|---|
| contenedor_id | uuid | Contenedor (partition key) |
| dia | date | Día (partition key) |
| momento | timestamp | Fecha y hora (clustering key, ascendente) |
| sensor_id | uuid | Sensor que reporta (clustering key) |
| envio_id | uuid | Envío en curso |
| latitud | double | |
| longitud | double | |

- Clave primaria: `((contenedor_id, dia), momento, sensor_id)`.
- Es una tabla desnormalizada: cada lectura con posición se escribe también
  acá. Un contenedor puede tener varios sensores, por eso la partición se arma
  por contenedor y no por sensor.
- `sensor_id` en la clave desempata dos sensores que reportan en el mismo instante.
- El orden ascendente permite reconstruir el recorrido cronológicamente.
- La doble escritura es idempotente: repetirla pisa la misma fila.

### eventos_por_envio

| Campo | Tipo | Descripción |
|---|---|---|
| envio_id | uuid | Envío (partition key) |
| momento | timestamp | Fecha y hora del evento (clustering key) |
| evento_id | uuid | Id del evento (clustering key) |
| tipo | text | carga_iniciada, en_transito, aduana, retraso, descarga, entregado |
| contenedor_id | uuid | Contenedor asociado |
| ubicacion_nombre | text | Nombre del lugar |
| latitud, longitud | double | Posición |
| descripcion | text | Texto libre |

- Clave primaria: `((envio_id), momento, evento_id)`, orden ascendente.
- Un envío tiene decenas o cientos de eventos: la partición es chica y acotada,
  y todo el historial sale de una sola partición.
- Se agregó `contenedor_id` al evento (propiedad no incluida en la consigna)
  para poder responder Q5.

### eventos_por_contenedor

| Campo | Tipo | Descripción |
|---|---|---|
| contenedor_id | uuid | Contenedor (partition key) |
| anio_mes | text | Mes en formato `YYYY-MM` (partition key) |
| momento | timestamp | Fecha y hora (clustering key, descendente) |
| evento_id | uuid | Id del evento (clustering key) |
| envio_id | uuid | Envío al que pertenece |
| tipo, ubicacion_nombre, latitud, longitud, descripcion | | Igual que en eventos_por_envio |

- Clave primaria: `((contenedor_id, anio_mes), momento, evento_id)`.
- Un contenedor se reutiliza en muchos envíos durante años y su historial no
  tiene límite, por eso la partición lleva un tramo mensual.
- Para consultar varios meses, la aplicación hace una consulta por mes.

## Relaciones

No hay relaciones entre tablas. Los datos que se consultan juntos se
desnormalizan: un mismo evento se escribe en `eventos_por_envio` y en
`eventos_por_contenedor`, y una misma lectura con posición en
`lecturas_por_sensor` y `recorrido_por_contenedor`.

## Índices

Se usa únicamente el índice primario (la clave de cada tabla). No se crean
índices secundarios: toda consulta se apoya en la partition key completa.

## Restricciones

No hay claves foráneas ni restricciones de integridad referencial. Cada
consulta debe incluir toda la partition key en el `WHERE`; si falta alguna
columna, Cassandra rechaza la consulta.

## Particionamiento y consistencia

- El particionamiento es parte del modelo: cada tabla define su partition key
  y Cassandra reparte las particiones entre los nodos con el particionador
  Murmur3 (hash).
- Los tramos por día o mes evitan particiones demasiado grandes.
- Niveles de consistencia sugeridos con factor de replicación 3: lecturas con
  `ONE` (alto volumen, se tolera perder una) y eventos con `QUORUM`
  (trazabilidad, no se pueden perder; con W=2 y R=2 se cumple R+W>N).

## Pendiente de acordar con el grupo

- Frecuencia de envío de las lecturas, para confirmar el tamaño de partición
  (si supera una por segundo, el tramo pasa a ser por hora).
- Tiempo de retención de las lecturas (TTL), si se decide limitarlo.
- Lista definitiva de tipos de evento logístico.
