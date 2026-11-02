# Modelo de Redis

Responsable: UMBI

## Objetivo

Redis se utiliza para:

- Gestionar las sesiones activas de los usuarios.
- Registrar la actividad reciente de los sensores para detectar sensores inactivos.
- Coordinar procesos periódicos mediante bloqueos temporales.
- Guardar temporalmente resultados de reportes en caché.

Las sesiones tienen un tiempo de vencimiento (TTL).

## Sesiones activas

- Clave: `sesion:<sesion_id>`
- Tipo de dato: Hash.
- sesion_id: UUID que identifica una sesión.

### Campos

| Campo | Descripción |
|---|---|
| usuario_id | UUID del usuario que inició sesión |
| fecha_inicio | Fecha y hora de inicio |
| fecha_fin | Fecha y hora prevista de vencimiento |
| estado | ACTIVA |

La sesión dura una hora (`ttl_segundos=3600` en `container.py`). El TTL se
calcula a partir de `fecha_fin`, redondeando hacia arriba, y se asigna con
`EXPIRE` en el mismo pipeline transaccional que el `HSET`. Al vencer, Redis
borra la clave solo. Al salir del menú, la aplicación la borra con `DEL` (D42).

Las sesiones activas se listan con `SCAN`, no con `KEYS`, para no bloquear el
motor.

## Actividad de sensores — D13

- Clave: `sensores:heartbeat`.
- Tipo: Sorted Set.
- Miembro: UUID del sensor.
- Score: timestamp Unix en segundos de recepción de su última señal.

Cada señal actualiza el score del sensor con `ZADD ... GT`, para que una
señal vieja no pise una más nueva. El conjunto no tiene TTL, para conservar el momento del último reporte.

Cada sensor se consulta con `ZSCORE`, porque cada uno tiene su propio
`intervalo_reporte_segundos` y no sirve un único instante de corte.

La detección corre cada 30 segundos desde el planificador y compara cada sensor
`ACTIVO` de PostgreSQL contra su `intervalo_reporte_segundos`. Devuelve uno de
cuatro resultados: `ACTIVO`, `INACTIVO`, `SIN_DATOS` (no tiene heartbeat) o
`RELOJ_INVALIDO` (la marca de tiempo es futura). Ver D43.

Un error de conexión con Redis no se interpreta como inactividad.

## Fuente de datos de los sensores

PostgreSQL conserva los datos maestros y el intervalo de reporte
configurado para cada sensor.

Redis conserva el último reporte recibido mediante el Sorted Set
`sensores:heartbeat`.

Si un sensor no pertenece al conjunto, no hay un reporte registrado
en Redis y el resultado es `SIN_DATOS`: no se puede distinguir un sensor
nuevo de una pérdida de datos de Redis, así que no se lo informa como
inactivo.

## Bloqueos de procesos — D14

- Clave: `lock:proceso:<nombre_proceso>`.
- Tipo: String.
- Valor: token único de la ejecución.
- Vencimiento: duración máxima del bloqueo, distinta para cada proceso
  (por ejemplo, 120 segundos para la detección de sensores inactivos y
  3600 para la facturación automática).

El bloqueo se adquiere con `SET clave token NX EX segundos`.
Solo la ejecución que consigue el bloqueo puede iniciar el proceso.

Para liberarlo, un script de Lua comprueba el token y elimina la clave
en una única operación atómica. No se usa un DEL sin comprobar
quién es el dueño del bloqueo.

Limitación conocida: el bloqueo no se renueva. Si un proceso tardara más
que su vencimiento, otra instancia podría arrancar en paralelo.

El bloqueo reduce ejecuciones simultáneas. La prevención de
facturas duplicadas también requiere controles e idempotencia
en PostgreSQL, coordinados con Thiago.

## Caché de reportes — D14

- Clave: `cache:reportes:v1:<nombre>:<hash>`.
- Tipo: String.
- Valor: resultado del reporte serializado en JSON.
- TTL: 60 segundos.

El hash es un SHA-256 de los parámetros del reporte (fechas, límite del
ranking). El `v1` permite invalidar todas las claves de golpe si cambia
el formato guardado.

Si la clave no existe, venció, es inválida o Redis falla, el reporte se
calcula en PostgreSQL. Si falla la escritura en la caché, el reporte se
devuelve igual. También se guardan las listas vacías y los `None`.

La caché puede mostrar datos anteriores al último cambio durante esos
60 segundos: no hay invalidación inmediata. Facturación, estados de envío
y saldos no se cachean. Ver D44.