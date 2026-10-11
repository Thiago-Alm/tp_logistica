# Diagramas de Redis y Neo4j

Responsable: UMBI

Los diagramas representan los modelos iniciales propuestos.

## Neo4j: actores y envíos

```mermaid
flowchart TD
    C[Cliente] -->|SOLICITA| E[Envio]
    O[Operador] -->|GESTIONA| E
    P[Proveedor] -->|PARTICIPA_EN| E
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
    S[Señal recibida] --> R["Actualizar sensor:actividad:UUID y renovar TTL"]
    P[Sensor que debe reportar en PostgreSQL] --> C[Consultar clave en Redis]
    R --> C
    C -->|Existe| A[Actividad reciente registrada]
    C -->|No existe| V[Validar inicio de monitoreo y primera señal]
    V --> D[Determinar si corresponde marcarlo inactivo]
```

El valor de la clave contiene la fecha y hora de recepción
de la última señal.

La ausencia de la clave requiere comprobar el contexto del
sensor antes de clasificarlo como inactivo. Un error de conexión
con Redis no debe interpretarse como ausencia de actividad.

El TTL y el período inicial de espera se acordarán con el grupo.