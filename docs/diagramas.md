# Diagramas de Redis y Neo4j

Responsable: UMBI

Los diagramas representan los modelos implementados. Las decisiones que los
justifican están en `docs/decisiones.md` (D9, D11, D13, D14, D37, D42, D43 y D44).

## Neo4j: actores y envíos

```mermaid
flowchart TD
    C[Cliente] -->|SOLICITA| E[Envio]
    E -->|TIENE_TRAMO| T[Tramo]
    T -->|UTILIZA| V[Vehiculo]
    O[Operador] -->|OPERA| V
    E -->|INCLUYE| CO[Contenedor]
    E -->|ORIGEN| UO[Ubicacion de origen]
    E -->|DESTINO| UD[Ubicacion de destino]
```

Las cajas representan etiquetas de nodos y las flechas,
relaciones dirigidas. Las dos ubicaciones tienen la misma
etiqueta `Ubicacion`, pero cumplen distintos roles.

## Neo4j: tramos y movimientos

```mermaid
flowchart TD
    E[Envio] -->|TIENE_TRAMO| T[Tramo]
    E -->|INCLUYE| C[Contenedor]
    T -->|DESDE| UO[Ubicacion de origen]
    T -->|HASTA| UD[Ubicacion de destino]
    T -->|UTILIZA| V[Vehiculo]
```

Cada tramo tiene un `id` y un `orden` dentro del envío.
Los contenedores se relacionan con los tramos a través del envío.
Esta relación no confirma que el contenedor haya recorrido
efectivamente cada tramo.

## Redis: ciclo de una sesión — D42

```mermaid
flowchart TD
    L[Usuario y contraseña] --> V{¿Credenciales válidas?}
    V -->|No, menos de 3 intentos| L
    V -->|No, tercer intento| X[La aplicación termina]
    V -->|Sí| H["HSET sesion:UUID + EXPIRE en el mismo pipeline"]
    H --> A[Sesión activa: el rol recorta el menú]
    A --> C[El usuario sale del menú]
    A --> T[Vence el TTL de 1 hora]
    C --> D["DEL sesion:UUID (en el finally)"]
    T --> R[Redis borra la clave solo]
```

El Hash contiene `usuario_id`, `fecha_inicio`, `fecha_fin` y `estado`.
El UUID de la clave identifica la sesión.

La sesión dura una hora. El TTL no se pasa aparte: se calcula a partir de
`fecha_fin`, redondeando hacia arriba. El `HSET` y el `EXPIRE` van en un
pipeline transaccional para que nunca quede una sesión sin vencimiento.
Las sesiones activas se listan con `SCAN`, no con `KEYS`.

## Redis: actividad de sensores — D13 y D43

```mermaid
flowchart TD
    S[El simulador guarda las lecturas en Cassandra] --> Z["ZADD GT sensores:heartbeat"]
    J[Planificador cada 30 s, con lock de 120 s] --> P["Sensores ACTIVOS en PostgreSQL"]
    P --> C["ZSCORE sensores:heartbeat por sensor"]
    Z -.-> C
    C --> R{¿Tiene heartbeat?}
    R -->|No| SD[SIN_DATOS]
    R -->|Sí| F{¿Marca de tiempo válida?}
    F -->|No, futura| RI[RELOJ_INVALIDO]
    F -->|Sí| E{¿Tiempo sin reportar mayor que su intervalo?}
    E -->|No| AC[ACTIVO]
    E -->|Sí| IN[INACTIVO]
```

El score es el timestamp Unix del último reporte. `ZADD` con `GT` evita que una
señal vieja pise una más nueva. El Sorted Set no tiene TTL.

El heartbeat se registra después de guardar las lecturas en Cassandra, para que
una señal nunca afirme un dato que no se escribió. Cada sensor se compara contra
su propio `intervalo_reporte_segundos`.

`SIN_DATOS` no es `INACTIVO`: la falta de heartbeat no distingue un sensor nuevo
de una pérdida de datos de Redis. Un error de Redis se informa como falla del
proceso, nunca como inactividad. El resultado se registra en el log; el proceso
no cambia el estado del sensor en PostgreSQL.

## Redis: caché de reportes — D44

```mermaid
flowchart TD
    P[Se pide un reporte] --> K["Clave cache:reportes:v1:nombre:SHA-256 de los parámetros"]
    K --> G{¿GET devuelve un valor válido?}
    G -->|Sí| D[Se reconstruyen los objetos del dominio]
    G -->|No existe, vencido, inválido o Redis falla| Q[Consulta de agregación en PostgreSQL]
    Q --> W["SET con EX 60"]
    W -->|Aunque falle la escritura| O[Se devuelve el reporte]
    D --> O
```

Los siete reportes de `ReporteService` se cachean 60 segundos. La caché es un
atajo, nunca una dependencia: si Redis falla, el reporte sale igual desde
PostgreSQL. Durante esos 60 segundos puede mostrar datos anteriores al último
cambio, porque no hay invalidación inmediata. Facturación, estados de envío y
saldos no se cachean.

## Redis: locks de procesos periódicos — D14

```mermaid
flowchart TD
    J[El planificador dispara un proceso] --> S["SET lock:proceso:nombre token NX EX segundos"]
    S -->|Otra instancia lo tiene| N[Se saltea esta ejecución]
    S -->|Se crea la clave| T[Corre el proceso]
    T --> L["Script Lua: borra la clave solo si el token es propio"]
    T -->|Si el proceso muere| V[El EX libera el lock solo]
```

Lo usan la sincronización del Outbox, el chequeo de consistencia, la facturación
automática, el cierre mensual, la verificación de saldos y la detección de
sensores inactivos. El lock reduce las ejecuciones simultáneas, pero no reemplaza
la idempotencia en PostgreSQL.
