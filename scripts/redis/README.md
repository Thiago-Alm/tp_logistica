# Convención de claves de Redis

Responsable: UMBI

| Clave | Tipo | Contenido | Vencimiento |
|---|---|---|---|
| `sesion:<sesion_id>` | Hash | usuario_id, fecha_inicio, fecha_fin, estado | TTL configurable |
| `sensores:heartbeat` | Sorted Set | Miembro: sensor_id; score: último reporte en timestamp Unix | Sin TTL |
| `lock:proceso:<nombre_proceso>` | String | Token único de la ejecución | TTL configurable |
| `cache:reporte:<nombre>:<hash_parametros>` | String | Resultado del reporte en JSON | TTL configurable |

## Reglas comunes

- Claves en minúsculas, sin tildes y con `:` como separador.
- Los identificadores compartidos conservan el UUID de PostgreSQL.
- Fechas de sesiones en formato ISO 8601 y UTC.
- Scores de heartbeat en segundos Unix.
- Cada clave mantiene un único tipo de dato.
- La aplicación valida campos, identificadores y vencimientos.

## Índices y particionamiento

El acceso a sesiones, locks y caché se realiza por clave.
El Sorted Set permite buscar sensores por el score de su último reporte.
No se crean índices secundarios adicionales.

En desarrollo se utiliza una instancia de Redis, sin Redis Cluster
ni particionamiento entre servidores.

## Alcance

Redis crea las estructuras al escribir el primer dato.
Este documento define la convención; no carga datos ni ejecuta comandos.
El comportamiento se detalla en `docs/modelo_redis.md`.