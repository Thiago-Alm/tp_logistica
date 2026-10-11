# Modelo de Neo4j

Responsable: UMBI

## Objetivo

Neo4j se utilizará para consultar las relaciones de la red logística:

- Recorridos de los envíos.
- Conexiones entre clientes, operadores y proveedores.
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
| Proveedor | Proveedor que participa en la operación |
| Ubicacion | Lugar de origen, destino o paso |
| Contenedor | Contenedor utilizado para transportar carga |
| Envio | Envío realizado |
| Vehiculo | Vehículo utilizado en el transporte |

Cada nodo tendrá una propiedad `id` con el UUID de la entidad
correspondiente en PostgreSQL.

Las propiedades adicionales se definirán según las consultas
necesarias y el modelo acordado con el grupo.

## Relaciones propuestas

| Nodo de origen | Relación | Nodo de destino |
|---|---|---|
| Cliente | SOLICITA | Envio |
| Operador | GESTIONA | Envio |
| Proveedor | PARTICIPA_EN | Envio |
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

## Movimientos históricos de contenedores

Se propone la relación:

| Nodo de origen | Relación | Nodo de destino |
|---|---|---|
| Contenedor | RECORRE | Tramo |

Esta relación indicará en qué tramos participó cada contenedor.
No se supondrá que todos los contenedores de un envío recorren
automáticamente todos sus tramos.

Para consultar movimientos realizados, se necesitarán las fechas
reales de los tramos y la confirmación de su ejecución.

La fuente de estos datos y su sincronización deberán acordarse
con el grupo.

## Reglas de integridad propuestas

- La propiedad `id` será obligatoria en todos los nodos.
- El `id` será único dentro de cada etiqueta.
- Cada tramo pertenecerá a un único envío.
- El orden de los tramos no se repetirá dentro del mismo envío.
- Cada tramo tendrá una ubicación de origen y una de destino.
- Un contenedor relacionado con un tramo deberá estar incluido
  en el envío al que pertenece ese tramo.

La unicidad de `id` se implementará mediante restricciones
de Neo4j, que también permitirán buscar los nodos por su UUID.

Las demás reglas deberán validarse en la aplicación y en
el proceso de sincronización.