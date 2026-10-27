# Modelo de Neo4j

Responsable: UMBI

## Objetivo

Neo4j se utilizará para consultar las relaciones de la red logística:

- Recorridos de los envíos.
- Conexiones entre clientes, operadores y envíos.
- Movimientos históricos de los contenedores.

## Identificadores compartidos

Los nodos que representen entidades de PostgreSQL conservarán
el mismo UUID en la propiedad `id`.

Esto permitirá identificar la misma entidad en ambos motores.

## Estado del modelo

Este documento es una propuesta inicial.
Las relaciones y propiedades deberán coordinarse con el
modelo de PostgreSQL y el proceso de sincronización del grupo.

## Nodos propuestos

| Etiqueta | Representa |
|---|---|
| Cliente | Cliente que solicita un envío |
| Operador | Operador logístico |
| Ubicacion | Lugar de origen, destino o paso |
| Contenedor | Contenedor utilizado para transportar carga |
| Envio | Envío realizado |
| Vehiculo | Vehículo utilizado en el transporte |
| Tramo | Etapa del recorrido de un envío |

Cada nodo tendrá una propiedad `id` con el UUID de la entidad
correspondiente en PostgreSQL.

Las propiedades adicionales se definirán según las consultas
necesarias y el modelo acordado con el grupo.

## Relaciones propuestas

| Nodo de origen | Relación | Nodo de destino |
|---|---|---|
| Cliente | SOLICITA | Envio |
| Operador | OPERA | Vehiculo |
| Envio | INCLUYE | Contenedor |
| Envio | ORIGEN | Ubicacion |
| Envio | DESTINO | Ubicacion |

Estas relaciones son una propuesta que deberá validarse
con el modelo de PostgreSQL.

Un envío puede incluir varios contenedores.
Un contenedor puede participar en distintos envíos a lo
largo del tiempo.

Los tramos del recorrido se modelarán por separado para
conservar su orden y vincular los vehículos utilizados.

## Tramos del recorrido

Se propone agregar un nodo con etiqueta `Tramo`.

Cada tramo tendrá:
- `id`: UUID del tramo en PostgreSQL.
- `orden`: posición del tramo dentro del envío.

### Relaciones de los tramos

| Nodo de origen | Relación | Nodo de destino |
|---|---|---|
| Envio | TIENE_TRAMO | Tramo |
| Tramo | DESDE | Ubicacion |
| Tramo | HASTA | Ubicacion |
| Tramo | UTILIZA | Vehiculo |

El recorrido de un envío se reconstruirá consultando sus
tramos y ordenándolos por la propiedad `orden`.

Las fechas previstas y reales, y la asignación de vehículos,
se coordinarán con el modelo de PostgreSQL.

## Movimientos de contenedores

Los contenedores se relacionan con los tramos a través del envío:

`Contenedor ← INCLUYE ← Envio → TIENE_TRAMO → Tramo`

Esta relación permite consultar los tramos asociados al envío
en el que está incluido un contenedor. Por sí sola, no confirma
que el contenedor haya recorrido efectivamente cada tramo.

## Reglas de integridad propuestas

- La propiedad `id` será obligatoria en todos los nodos.
- El `id` será único dentro de cada etiqueta.
- Cada tramo pertenecerá a un único envío.
- El orden de los tramos no se repetirá dentro del mismo envío.
- Cada tramo tendrá una ubicación de origen y una de destino.


La unicidad de `id` se implementará mediante restricciones
de Neo4j, que también permitirán buscar los nodos por su UUID.

Las demás reglas deberán validarse en la aplicación y en
el proceso de sincronización.

## Relación entre operadores y envíos — D11

El operador se vincula con sus vehículos mediante `OPERA`.
Los envíos se vinculan con los vehículos mediante sus tramos:

`Envio → TIENE_TRAMO → Tramo → UTILIZA → Vehiculo ← OPERA ← Operador`

No se crea la relación directa `GESTIONA`.
Los proveedores se administran en PostgreSQL y quedan fuera
del grafo porque el modelo no define su vínculo con los envíos.

## Modelo físico: restricciones, índices y particionamiento

El script `scripts/neo4j/01_constraints.cypher` crea restricciones
de unicidad de `id` para Cliente, Operador, Ubicacion, Contenedor,
Envio, Vehiculo y Tramo.

Cada restricción crea un índice de respaldo para buscar por `id`.
No es necesario crear otro índice sobre la misma propiedad.

La unicidad no obliga a que exista la propiedad: la aplicación
validará que todos los nodos tengan `id`.

En desarrollo se utiliza una única instancia de Neo4j,
sin particionamiento del grafo entre servidores.

Validación realizada: ejecución del script y consulta
`SHOW CONSTRAINTS`, con las siete restricciones presentes.