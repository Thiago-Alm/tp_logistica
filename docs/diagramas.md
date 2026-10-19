# Diagramas de Redis y Neo4j

Responsable: UMBI

Los diagramas representan los modelos iniciales propuestos.

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
    C -->|RECORRE| T
    T -->|DESDE| UO[Ubicacion de origen]
    T -->|HASTA| UD[Ubicacion de destino]
    T -->|UTILIZA| V[Vehiculo]
```

Cada tramo tendrá un `id` y un `orden` dentro del envío.
La relación `RECORRE` identifica los tramos de cada contenedor.
Las fechas reales permitirán consultar los movimientos realizados.

## Redis: ciclo de una sesión

```mermaid
flowchart TD
    I[Inicio de sesión válido] --> H["Crear Hash sesion:UUID"]
    H --> T[Asignar TTL]
    T --> A[Sesión activa]
    A --> C[Cierre de sesión]
    A --> V[Vencimiento del TTL]
    C --> D[Eliminar clave]
    V --> D
```

El Hash contiene `usuario_id`, `fecha_inicio`, `fecha_fin`
y `estado`. El UUID de la clave identifica la sesión.

La duración del TTL queda pendiente de acordar con el grupo.

## Redis: actividad de sensores

```mermaid
flowchart TD
    S[Señal recibida] --> Z["Actualizar score en sensores:heartbeat"]
    J[Proceso periódico] --> P["Consultar sensores monitoreados en PostgreSQL"]
    P --> C[Consultar últimos reportes en Redis]
    Z --> C
    C --> R{¿Tiene reporte registrado?}
    R -->|Sí| E[Evaluar atraso según intervalo del sensor]
    R -->|No| I[Evaluar período inicial o información desconocida]
    E --> D[Determinar actividad o inactividad]
```

El score conserva el timestamp de recepción del último reporte.
El Sorted Set no tiene TTL.

La detección considera el intervalo configurado de cada sensor.
Los errores de Redis se tratan como fallas de consulta,
no como evidencia de inactividad.