-- =====================================================================
-- Cassandra - Modelo fisico | TP Persistencia Poliglota (Logistica IoT)
-- Ejecutar:  cqlsh -f cassandra_modelo.cql
--   (con Docker: docker cp cassandra_modelo.cql <contenedor>:/tmp/ &&
--                docker exec -it <contenedor> cqlsh -f /tmp/cassandra_modelo.cql)
--
-- Convenciones: espanol, snake_case, sin tildes. Todo id es uuid (el mismo id
-- que en Postgres, Mongo, Neo4j y Redis). Fechas en UTC.
--
-- Que vive aca (y por que): datos MASIVOS, de solo agregar y con consultas
-- conocidas de antemano: lecturas de sensores y eventos logisticos.
-- Cassandra escribe barato, escala horizontal y se particiona por tiempo.
-- NO hace agregaciones (SUM/AVG) ni JOIN: los promedios/analiticas se calculan
-- en la app leyendo por particion, o salen de Mongo/Postgres.
--
-- Modelado QUERY-FIRST. Consultas que debe responder:
--   Q1  Lecturas historicas de un sensor en un rango de fechas      -> lecturas_por_sensor
--   Q2  Ultima lectura de un sensor (estado del sensor)             -> lecturas_por_sensor (LIMIT 1)
--   Q3  Recorrido GPS de un contenedor (reconstruccion de ruta)     -> recorrido_por_contenedor
--   Q4  Historial de eventos de un envio, en orden cronologico      -> eventos_por_envio
--   Q5  Historial de movimientos de un contenedor                   -> eventos_por_contenedor
--
-- Integridad: Cassandra no tiene FK ni JOIN. La validez de envio_id,
-- sensor_id, contenedor_id la garantiza la capa de aplicacion (la fuente de
-- verdad es Postgres) y el chequeo de consistencia del Outbox.
-- =====================================================================

-- SimpleStrategy / RF=1 solo para desarrollo (Docker de un nodo).
-- En produccion: NetworkTopologyStrategy con RF=3 por datacenter.
CREATE KEYSPACE IF NOT EXISTS logistica
  WITH replication = {'class': 'SimpleStrategy', 'replication_factor': 1};

USE logistica;

-- ---------------------------------------------------------------------
-- Q1 y Q2: lecturas por sensor
--  Partition key = (sensor_id, dia): un "bucket" por sensor y por dia.
--    Sin el dia, la particion de un sensor crece para siempre (particion gigante).
--    Con 1 lectura/min son 1.440 filas/dia por particion: muy por debajo del limite
--    recomendado (~100.000 filas / ~100 MB). Si la frecuencia fuera de 1/seg
--    (86.400 filas/dia) todavia entra; mas que eso, bucket por hora.
--  Clustering key = momento DESC: la ultima lectura queda primera (Q2 = LIMIT 1) y no
--    hace falta ORDER BY en la consulta.
--  Posicion GPS en dos columnas (latitud/longitud) para poder seleccionarlas.
--  TWCS: estrategia de compactacion pensada para series temporales.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS lecturas_por_sensor (
  sensor_id     uuid,
  dia           date,
  momento       timestamp,
  contenedor_id uuid,
  temperatura   double,
  humedad       double,
  vibracion     double,
  latitud       double,
  longitud      double,
  bateria       int,
  PRIMARY KEY ((sensor_id, dia), momento)
) WITH CLUSTERING ORDER BY (momento DESC)
  AND compaction = {'class': 'TimeWindowCompactionStrategy',
                    'compaction_window_unit': 'DAYS',
                    'compaction_window_size': 1};

-- ---------------------------------------------------------------------
-- Q3: recorrido de un contenedor (solo lo necesario para dibujar la ruta)
--  Tabla DESNORMALIZADA: cada lectura se escribe tambien aca. Un contenedor puede
--  tener varios sensores, por eso la clave es contenedor_id (no sensor_id).
--  Clustering (momento, sensor_id) ASC: orden cronologico para reconstruir el recorrido;
--  sensor_id desempata si dos sensores reportan en el mismo instante.
--  La doble escritura es el costo de no tener JOIN; es idempotente (misma PK).
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS recorrido_por_contenedor (
  contenedor_id uuid,
  dia           date,
  momento       timestamp,
  sensor_id     uuid,
  envio_id      uuid,
  latitud       double,
  longitud      double,
  PRIMARY KEY ((contenedor_id, dia), momento, sensor_id)
) WITH CLUSTERING ORDER BY (momento ASC, sensor_id ASC)
  AND compaction = {'class': 'TimeWindowCompactionStrategy',
                    'compaction_window_unit': 'DAYS',
                    'compaction_window_size': 1};

-- ---------------------------------------------------------------------
-- Q4: eventos de un envio (Carga iniciada, En transito, Aduana, Retraso, Descarga, Entregado)
--  Partition key = envio_id: un envio tiene decenas o cientos de eventos, la
--  particion es chica y acotada. Todo el historial sale de UNA particion.
--  Clustering (momento, evento_id) ASC: seguimiento temporal, de lo mas viejo a lo nuevo.
--  contenedor_id agregado al evento (propiedad extra, justificada): permite Q5.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS eventos_por_envio (
  envio_id         uuid,
  momento          timestamp,
  evento_id        uuid,
  tipo             text,
  contenedor_id    uuid,
  ubicacion_nombre text,
  latitud          double,
  longitud         double,
  descripcion      text,
  PRIMARY KEY ((envio_id), momento, evento_id)
) WITH CLUSTERING ORDER BY (momento ASC, evento_id ASC);

-- ---------------------------------------------------------------------
-- Q5: movimientos de un contenedor
--  Un contenedor se reutiliza en muchos envios durante anios: su historial NO
--  esta acotado, por eso la particion lleva un bucket mensual (anio_mes 'YYYY-MM').
--  Para pedir varios meses la app hace una consulta por mes (o IN sobre anio_mes).
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS eventos_por_contenedor (
  contenedor_id    uuid,
  anio_mes         text,
  momento          timestamp,
  evento_id        uuid,
  envio_id         uuid,
  tipo             text,
  ubicacion_nombre text,
  latitud          double,
  longitud         double,
  descripcion      text,
  PRIMARY KEY ((contenedor_id, anio_mes), momento, evento_id)
) WITH CLUSTERING ORDER BY (momento DESC, evento_id DESC);

-- ---------------------------------------------------------------------
-- NIVELES DE CONSISTENCIA sugeridos (parametros N/R/W vistos en la materia)
--  Con RF=3:
--   - lecturas (escritura masiva, se tolera perder una):  CONSISTENCY ONE
--   - eventos logisticos (trazabilidad, no se pueden perder): CONSISTENCY QUORUM
--     (W=2, R=2 -> R+W > N, lectura fuertemente consistente)
--  En cqlsh:  CONSISTENCY QUORUM;
-- ---------------------------------------------------------------------

-- ---------------------------------------------------------------------
-- DATOS DE PRUEBA minimos (las claves se pisan si se corre de nuevo)
-- ---------------------------------------------------------------------
INSERT INTO lecturas_por_sensor (sensor_id, dia, momento, contenedor_id, temperatura, humedad, vibracion, latitud, longitud, bateria)
VALUES (11111111-1111-4111-8111-111111111111, '2026-10-12', '2026-10-12 10:00:00+0000', dddddddd-0000-4000-8000-000000000001, 4.2, 60.0, 0.1, -34.60, -58.38, 95);
INSERT INTO lecturas_por_sensor (sensor_id, dia, momento, contenedor_id, temperatura, humedad, vibracion, latitud, longitud, bateria)
VALUES (11111111-1111-4111-8111-111111111111, '2026-10-12', '2026-10-12 10:01:00+0000', dddddddd-0000-4000-8000-000000000001, 4.4, 61.0, 0.2, -34.61, -58.39, 95);
INSERT INTO lecturas_por_sensor (sensor_id, dia, momento, contenedor_id, temperatura, humedad, vibracion, latitud, longitud, bateria)
VALUES (11111111-1111-4111-8111-111111111111, '2026-10-12', '2026-10-12 10:02:00+0000', dddddddd-0000-4000-8000-000000000001, 12.5, 62.0, 0.3, -34.62, -58.40, 94);

INSERT INTO recorrido_por_contenedor (contenedor_id, dia, momento, sensor_id, envio_id, latitud, longitud)
VALUES (dddddddd-0000-4000-8000-000000000001, '2026-10-12', '2026-10-12 10:00:00+0000', 11111111-1111-4111-8111-111111111111, aaaaaaaa-0000-4000-8000-000000000001, -34.60, -58.38);
INSERT INTO recorrido_por_contenedor (contenedor_id, dia, momento, sensor_id, envio_id, latitud, longitud)
VALUES (dddddddd-0000-4000-8000-000000000001, '2026-10-12', '2026-10-12 10:01:00+0000', 11111111-1111-4111-8111-111111111111, aaaaaaaa-0000-4000-8000-000000000001, -34.61, -58.39);

INSERT INTO eventos_por_envio (envio_id, momento, evento_id, tipo, contenedor_id, ubicacion_nombre, latitud, longitud, descripcion)
VALUES (aaaaaaaa-0000-4000-8000-000000000001, '2026-10-12 08:00:00+0000', 5eb00000-0000-4000-8000-000000000001, 'carga_iniciada', dddddddd-0000-4000-8000-000000000001, 'Puerto Buenos Aires', -34.60, -58.37, 'Inicio de carga');
INSERT INTO eventos_por_envio (envio_id, momento, evento_id, tipo, contenedor_id, ubicacion_nombre, latitud, longitud, descripcion)
VALUES (aaaaaaaa-0000-4000-8000-000000000001, '2026-10-12 12:00:00+0000', 5eb00000-0000-4000-8000-000000000002, 'en_transito', dddddddd-0000-4000-8000-000000000001, 'Rio de la Plata', -34.70, -58.20, 'Zarpo el buque');

INSERT INTO eventos_por_contenedor (contenedor_id, anio_mes, momento, evento_id, envio_id, tipo, ubicacion_nombre, latitud, longitud, descripcion)
VALUES (dddddddd-0000-4000-8000-000000000001, '2026-10', '2026-10-12 08:00:00+0000', 5eb00000-0000-4000-8000-000000000001, aaaaaaaa-0000-4000-8000-000000000001, 'carga_iniciada', 'Puerto Buenos Aires', -34.60, -58.37, 'Inicio de carga');

-- ---------------------------------------------------------------------
-- CONSULTAS DE VERIFICACION (cada una usa la partition key completa)
-- ---------------------------------------------------------------------
-- Q1: SELECT * FROM lecturas_por_sensor
--       WHERE sensor_id = 11111111-1111-4111-8111-111111111111 AND dia = '2026-10-12'
--         AND momento >= '2026-10-12 10:00:00+0000' AND momento < '2026-10-12 11:00:00+0000';
-- Q2: SELECT * FROM lecturas_por_sensor
--       WHERE sensor_id = 11111111-1111-4111-8111-111111111111 AND dia = '2026-10-12' LIMIT 1;
--     (si hoy no hay lecturas, la app prueba con el dia anterior; la deteccion de
--      sensores inactivos la resuelve Redis con la marca de "ultimo visto")
-- Q3: SELECT latitud, longitud, momento FROM recorrido_por_contenedor
--       WHERE contenedor_id = dddddddd-0000-4000-8000-000000000001 AND dia = '2026-10-12';
-- Q4: SELECT * FROM eventos_por_envio WHERE envio_id = aaaaaaaa-0000-4000-8000-000000000001;
-- Q5: SELECT * FROM eventos_por_contenedor
--       WHERE contenedor_id = dddddddd-0000-4000-8000-000000000001 AND anio_mes = '2026-10';
--
-- Consulta que FALLA a proposito (para la defensa): falta parte de la partition key
-- SELECT * FROM lecturas_por_sensor WHERE sensor_id = 11111111-1111-4111-8111-111111111111;
--   -> pide ALLOW FILTERING o da error: Cassandra no sabe en que particion buscar.
