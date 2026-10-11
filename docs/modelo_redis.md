# Modelo de Redis

Responsable: UMBI

## Objetivo

Redis se utilizará para:

- Gestionar las sesiones activas de los usuarios.
- Registrar la actividad reciente de los sensores para detectar sensores inactivos.

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

## Actividad de sensores

- Clave: `sensor:actividad:<sensor_id>`
- Tipo de dato: String.
- Valor: fecha y hora de recepción de la última señal del sensor.

Cada señal recibida actualizará el valor y renovará el TTL.

El tiempo de vencimiento queda pendiente de acordar con el grupo.

Para detectar sensores inactivos, se consultarán los sensores
que deben estar reportando y se comprobará si tienen una clave
de actividad vigente en Redis.

## Fuente de datos de los sensores

PostgreSQL conservará los datos maestros de los sensores.
Redis almacenará únicamente su actividad reciente.

La ausencia de una clave en Redis indica que no hay actividad
reciente registrada. También puede corresponder a un sensor
que todavía no envió su primera señal.

La aplicación deberá contemplar este caso antes de clasificar
al sensor como inactivo.