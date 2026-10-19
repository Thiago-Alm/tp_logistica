# Modelo de Redis

Responsable: UMBI

## Objetivo

Redis se utilizará para:

- Gestionar las sesiones activas de los usuarios.
- Registrar la actividad reciente de los sensores para detectar sensores inactivos.
- Coordinar procesos periódicos mediante bloqueos temporales.
- Guardar temporalmente resultados de reportes en caché.

Las sesiones tendrán un tiempo de vencimiento (TTL).

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

La clave tendrá un TTL. Al vencer, se eliminará de Redis.
Al cerrar sesión, se eliminará la clave.

La duración de la sesión queda pendiente de acordar con el grupo.

## Actividad de sensores — D13

- Clave: `sensores:heartbeat`.
- Tipo: Sorted Set.
- Miembro: UUID del sensor.
- Score: timestamp Unix en segundos de recepción de su última señal.

Cada señal actualiza el score del sensor.
El conjunto no tendrá TTL, para conservar el momento del último reporte.

Los sensores atrasados se buscan por score según un instante de corte.
Si tienen distintos intervalos de reporte, la aplicación deberá evaluar
el atraso según `intervalo_reporte_segundos` de cada sensor.

Los sensores que nunca reportaron no aparecen en el conjunto.
Se comprobarán contra los sensores que deben estar reportando en
PostgreSQL, contemplando un período inicial de espera.

Un error de conexión con Redis no se interpretará como inactividad.

## Fuente de datos de los sensores

PostgreSQL conserva los datos maestros y el intervalo de reporte
configurado para cada sensor.

Redis conserva el último reporte recibido mediante el Sorted Set
`sensores:heartbeat`.

Si un sensor no pertenece al conjunto, no hay un reporte registrado
en Redis. La aplicación deberá consultar cuándo comenzó su monitoreo
y aplicar el período inicial de espera antes de considerarlo inactivo.

Los sensores dados de baja o fuera de monitoreo se retirarán del
conjunto cuando corresponda. La ausencia de datos tras una pérdida
de Redis deberá tratarse como información desconocida.

## Bloqueos de procesos — D14

- Clave: `lock:proceso:<nombre_proceso>`.
- Tipo: String.
- Valor: token único de la ejecución.
- Vencimiento: duración máxima del bloqueo, configurable.

El bloqueo se adquiere con `SET clave token NX EX segundos`.
Solo la ejecución que consigue el bloqueo puede iniciar el proceso.

Para liberarlo, se debe comprobar el token y eliminar la clave
en una única operación atómica. No se usará un DEL sin comprobar
quién es el dueño del bloqueo.

Si el proceso supera la duración del bloqueo, deberá renovarlo
comprobando su token o detenerse antes de perder la exclusividad.

El bloqueo reduce ejecuciones simultáneas. La prevención de
facturas duplicadas también requiere controles e idempotencia
en PostgreSQL, coordinados con Thiago.

## Caché de reportes — D14

- Clave: `cache:reporte:<nombre>:<hash_parametros>`.
- Tipo: String.
- Valor: resultado del reporte serializado en JSON.
- TTL: configurable según la vigencia aceptable del reporte.

El hash se calculará a partir de parámetros normalizados,
incluyendo filtros, fechas y alcance de acceso del usuario.

Si la clave no existe, se calcula el reporte desde su fuente
y se guarda temporalmente en Redis.

La caché puede contener resultados desactualizados hasta su
vencimiento. Los reportes que requieran datos actuales deberán
omitirla o invalidarla cuando cambien los datos.