# Registro de decisiones de diseño

Cada decisión de diseño que tomamos queda acá, con el motivo. No es burocracia:
la nota sale de una **defensa individual** donde cualquiera puede ser preguntado
sobre cualquier parte, y este archivo es la fuente del informe técnico y de la
justificación de persistencia políglota (entregables 1 y 2 del enunciado).

Formato de cada entrada: **qué se decidió**, **por qué**, **qué consecuencias
tiene** y **a quién le cambia el trabajo**.

---

## D1 — Los estados son `Enum`, no `str`

**Fecha:** 11/10/2026 · **Alcance:** todo el dominio

Todo campo que represente un estado o una categoría cerrada se modela como un
`Enum` de Python (`EstadoEnvio`, `PrioridadEnvio`, `EstadoContenedor`), no como
un `str` libre.

**Por qué:** el enunciado pide "controles de integridad" entre los requisitos de
calidad. Un `str` acepta `"EN_TRANISTO"` sin chistar y el error aparece semanas
después en un reporte que devuelve menos filas de las que debería. Además, la
lista de valores válidos tiene que existir en un solo lugar, porque el DDL de
Postgres la repite en un `CHECK (estado IN (...))` o en un tipo `ENUM`.

**Consecuencias:** la fuente de verdad de los valores válidos es el dominio. Si
se agrega un estado, se agrega primero acá y después en el DDL.

**Le cambia el trabajo a:** Fran (los `CHECK` del DDL salen de estos enums).

---

## D2 — `Enum` puro, no `(str, Enum)`

**Fecha:** 11/10/2026 · **Alcance:** todo el dominio

Los enums heredan de `Enum` y no de `(str, Enum)`. Convertir a string al escribir
(`envio.estado.value`) y reconstruir al leer (`EstadoEnvio(fila["estado"])`) es
responsabilidad del repositorio.

**Por qué:** el dominio no conoce la persistencia. Es coherente con la
arquitectura en capas, que es lo que el enunciado pide en "Restricciones
Técnicas". Con `(str, Enum)` la conversión queda implícita y el día que Mongo
devuelva el string crudo nadie se entera de que se perdió el tipo.

**Consecuencias:** cada repositorio necesita un mapeo explícito dominio ↔ fila.
Eso no es costo perdido: ese mismo mapeo se reusa en el Outbox, donde la misma
entidad tiene que salir hacia Neo4j y Mongo.

**Le cambia el trabajo a:** todos los que escriban un repositorio.

---

## D3 — Dónde van las validaciones

**Fecha:** 11/10/2026 · **Alcance:** dominio y servicios

El criterio es uno solo: **¿puedo verificar esta regla con los campos del objeto,
sin consultar ninguna base?**

- **Sí** → va en el dominio, en `__post_init__` / `_validar()`.
  Ejemplo: `origen_id != destino_id`.
- **No** → va en el servicio.
  Ejemplo: que `cliente_id` exista, o que un contenedor no esté en dos envíos
  activos a la vez.

**Por qué:** sin un criterio explícito, la misma validación termina duplicada en
el dominio, en el servicio y en el repositorio, y las tres versiones se
desincronizan.

**Consecuencias:** el dominio queda sin dependencias de infraestructura y se
puede testear sin levantar ninguna base (los 16 tests actuales corren en 0,05 s).

---

## D4 — Las transiciones de estado viven en el dominio

**Fecha:** 11/10/2026 · **Alcance:** `domain/envio.py`

Las transiciones permitidas entre estados de un envío son un diccionario
(`_TRANSICIONES_ENVIO`) consultado desde métodos del propio enum
(`puede_pasar_a`, `es_final`). El cambio de estado se hace con `Envio.pasar_a()`,
no asignando `envio.estado` directo.

**Por qué va en el dominio:** por D3 — para saber si `CREADO → ENTREGADO` es
válido no hace falta consultar nada.

**Por qué un diccionario y no el patrón State:** cinco clases para cinco estados
que casi no tienen comportamiento propio es sobreingeniería. El profesor pidió
simplificar. Un mapa da el mismo control y se lee de un vistazo.

**Por qué `pasar_a()` y no asignación directa:** sin ese método el mapa es
decorativo, porque cualquiera lo esquiva asignando el campo. `pasar_a()` además
revierte el cambio si la validación posterior falla, con el mismo razonamiento
que una transacción: el objeto queda consistente en el estado nuevo o como
estaba, nunca a mitad de camino.

**Transiciones definidas:**

| Desde | Hacia |
|---|---|
| `CREADO` | `EN_TRANSITO`, `CANCELADO` |
| `EN_TRANSITO` | `EN_PUERTO`, `ENTREGADO`, `CANCELADO` |
| `EN_PUERTO` | `EN_TRANSITO`, `ENTREGADO`, `CANCELADO` |
| `ENTREGADO` | — (final) |
| `CANCELADO` | — (final) |

`EN_PUERTO → EN_TRANSITO` es intencional: un envío marítimo pasa por varios
puertos antes de llegar.

---

## D5 — `Tramo` es una tabla propia en PostgreSQL

**Fecha:** 12/10/2026 · **Alcance:** modelo físico de Postgres

`Tramo` es una tabla con clave primaria propia y FK a `envio`, `vehiculo` y
`ubicacion` (origen y destino). **No** es una columna `JSONB` dentro de `envio`.

**Por qué:**

1. **Integridad referencial.** Tramo tiene tres claves foráneas
   (`vehiculo_id`, `origen_id`, `destino_id`). Dentro de un `JSONB`, Postgres no
   puede imponer ninguna: se podría borrar un vehículo y los tramos quedarían
   apuntando a un registro inexistente. Perderíamos exactamente la capacidad por
   la que elegimos un motor relacional para esta parte del sistema.
2. **Agregación.** Los reportes "Costos por tipo de transporte" y "Tiempos
   promedio de entrega" agrupan sobre campos del tramo
   (`medio_transporte`, `costo`). Con tabla propia es un `GROUP BY` indexable;
   con `JSONB` hay que desarmar el array de cada envío con `jsonb_array_elements`
   antes de poder agrupar, escaneando todos los envíos.
3. **Sincronización.** El Outbox propaga cada tramo a Neo4j como una relación
   entre dos `Ubicacion`. Un tramo embebido en un JSON no tiene id propio
   estable, y sin ese id no se puede hacer un `MERGE` idempotente en Cypher.

**Le cambia el trabajo a:** Fran (tabla `tramo` con tres FK en el DDL) y a
Umbi (la relación en el grafo sale de esta tabla).

---

## D6 — `Envio` no carga sus tramos; el servicio los compone

**Fecha:** 12/10/2026 · **Alcance:** dominio, repositorios y servicios

`Tramo` tiene su propio repositorio (`TramoRepository`). El dataclass `Envio`
**no** tiene un campo `tramos: list[Tramo]`. Cuando una consulta necesita el
envío con sus tramos ("ruta completa de un envío", "seguimiento temporal"), el
**servicio** llama a los dos repositorios y compone el resultado.

**Por qué:**

1. El reporte "Costos por tipo de transporte" agrupa tramos de *todos* los
   envíos. Si los tramos solo se alcanzaran a través de un `Envio`, habría que
   levantar todos los envíos a memoria y sumar en Python, teniendo Postgres al
   lado: lo contrario de elegir el motor según el proceso.
2. Coherencia: la arquitectura ya es un repositorio por entidad con interfaces
   `ABC`. `TramoRepository` encaja sin inventar un patrón nuevo.
3. Simplicidad, que es lo que pidió el profesor.
4. El Outbox propaga tramos individuales; con repositorio propio el evento lleva
   el tramo y no hace falta levantar el envío entero.

**Objeción prevista y su respuesta:** *¿quién garantiza que el origen del primer
tramo coincida con el origen del envío, o que los tramos no se pisen en el
tiempo?* El **servicio** (`EnvioService`), por el criterio de D3: son reglas que
necesitan consultar otras entidades.

---

## D7 — `fecha_llegada_estimada` se deriva, no se denormaliza

**Fecha:** 12/10/2026 · **Alcance:** `domain/envio.py`, reportes

`Envio` **no** tiene `fecha_llegada_estimada`. El reporte "Envíos demorados" se
calcula como: *el envío no está entregado y el máximo de
`fecha_llegada_estimada` entre sus tramos ya pasó*.

**Por qué:** denormalizar la estimada en `Envio` haría el reporte trivial, pero
crearía un dato que hay que mantener sincronizado cada vez que cambia un tramo
— un problema de consistencia **dentro de una sola base**, justamente en un TP
cuyo tema es la consistencia entre bases. Derivarlo cuesta un `MAX ... GROUP BY`
y no cuesta nada de defender.

**Le cambia el trabajo a:** Fran (el reporte sale de un `GROUP BY ... HAVING`,
no de una columna).

---

## D8 — `codigo_iso` se valida con 11 caracteres (ISO 6346)

**Fecha:** 11/10/2026 · **Alcance:** `domain/contenedor.py`, datos de prueba

El código internacional de contenedor se valida con largo exacto 11, que es el
formato ISO 6346 (4 letras de dueño y categoría + 7 dígitos), por ejemplo
`MSKU1234567`.

**Por qué:** es un control de integridad barato sobre un identificador que es
único por contenedor y que se usa para buscarlo
(`ContenedorRepository.obtener_por_codigo`).

**Le cambia el trabajo a: Umbi.** El generador de datos de prueba **tiene que
producir códigos de 11 caracteres** o va a fallar la construcción de todo
`Contenedor`. Hay un test que lo verifica
(`test_el_codigo_iso_debe_tener_once_caracteres`). Si el generador no puede
cumplirlo, hay que relajar la validación antes, no después.

---

# Decisiones abiertas (propuestas, pendientes de acordar)

Las siguientes surgen de contrastar el modelo de Neo4j y Redis (PR #1, Umbi)
contra el modelo de PostgreSQL y el enunciado. Cada una tiene una **propuesta**
y un **responsable**. Mientras digan "propuesta", no están cerradas.

---

## D9 — `Tramo` es un nodo en Neo4j, no una relación

**Estado:** acordada (decidida por Umbi, se registra acá) · **Alcance:** Neo4j

La tabla del documento del grupo decía "Tramo → Neo4j (relación entre
ubicaciones)". El modelo implementado lo hace **nodo**, con `id` y `orden`.

**Por qué el nodo es correcto:** en Neo4j una relación no puede ser extremo de
otra relación. La consulta "historial de movimientos de un contenedor" requiere
`(:Contenedor)-[:RECORRE]->(:Tramo)`, y eso obliga a que `Tramo` sea un nodo.

**Consecuencia:** la entidad `Ruta` del documento del grupo queda **subsumida en
los tramos** y no se modela aparte. El recorrido de un envío se reconstruye
siguiendo `(:Envio)-[:TIENE_TRAMO]->(:Tramo)`.

**Acción:** corregir la tabla del documento del grupo, que hoy dice lo contrario.

---

## D10 — `orden` se agrega como columna en PostgreSQL

**Estado:** propuesta · **Responsables:** Thiago y Fran · **Urgente: bloquea el DDL**

El nodo `Tramo` de Neo4j tiene una propiedad `orden` que no existe en la tabla
`tramo` de PostgreSQL. El Outbox no puede propagar un campo inexistente.

**Propuesta:** agregar `orden` (entero) a la tabla `tramo`, en lugar de derivarlo
ordenando por `fecha_salida`.

**Por qué:**

1. Permite declarar la restricción `UNIQUE (envio_id, orden)` en Postgres. Esa es
   exactamente la regla de integridad que el modelo de Neo4j ya enuncia ("el
   orden de los tramos no se repetirá dentro del mismo envío"), y sin la columna
   no es declarable: habría que validarla a mano en la aplicación.
2. El recorrido es una secuencia planificada que existe **antes** de que las
   fechas sean ciertas. Derivar el orden de `fecha_salida` ata el orden a un dato
   que puede ser nulo o estimado al crear el envío.
3. Cuesta una columna de tipo entero.

**Consecuencia:** es un supuesto nuevo a documentar (el enunciado no lo pide).

---

## D11 — El operador llega al envío a través del vehículo

**Estado:** propuesta · **Responsables:** Thiago y Umbi

El modelo de Neo4j propone `(:Operador)-[:GESTIONA]->(:Envio)` y
`(:Proveedor)-[:PARTICIPA_EN]->(:Envio)`. **Ninguna de las dos es derivable de
PostgreSQL:** no existe campo que una un operador con un envío, ni nada que una
un proveedor con un envío. El worker de sincronización no tendría de dónde
leerlas.

**Propuesta:**

1. Agregar `(:Operador)-[:OPERA]->(:Vehiculo)`, que **sí** es derivable
   (`vehiculo.operador_id`).
2. **No materializar `GESTIONA`.** El requisito "red de relaciones entre
   clientes, operadores y envíos" se resuelve recorriendo el camino real:
   `(:Envio)-[:TIENE_TRAMO]->(:Tramo)-[:UTILIZA]->(:Vehiculo)<-[:OPERA]-(:Operador)`.
   Son tres saltos, triviales en Cypher. Si más adelante la consulta resultara
   lenta, se materializa y se documenta el porqué.
3. **Sacar `Proveedor` del grafo.** El enunciado pide CRUD de proveedores (se
   cumple en PostgreSQL) pero nunca los relaciona con envíos: la red que pide es
   "clientes, operadores y envíos". Sin dato que la respalde ni requisito que la
   pida, esa relación es complejidad gratuita.

**Nota de defensa:** este camino de tres saltos es la mejor justificación
concreta que tenemos para Neo4j — en SQL es un join de cuatro tablas que empeora
si se quiere profundidad variable.

---

## D12 — El ranking de rutas con incidentes se resuelve en MongoDB

**Estado:** acordada · **Fecha:** 13/10/2026 · **Responsable:** Mati · **Alcance:** MongoDB

> **Esta decision reemplaza a una version anterior** que proponia propagar los
> incidentes a Neo4j y resolver el ranking en Cypher. Al ver el modelo de
> MongoDB quedo claro que la solucion de Mati es mejor, y se adopta esa.

El enunciado pide "ranking de rutas con mayor cantidad de incidentes". Cada
incidente guarda embebido un **snapshot del contexto del envio** al momento de
ocurrir:

```js
contexto_envio: { cliente_id, origen, destino, pais_origen, pais_destino, ruta }
db.incidentes.createIndex({ "contexto_envio.ruta": 1 })
```

El ranking es un `$group` sobre un campo indexado. Lo mismo resuelve "promedio
de incidentes por pais / estado / cliente", con los otros indices del snapshot.

**Por que se descarto propagarlos a Neo4j:** habria obligado a sincronizar los
incidentes a un cuarto motor y a mantenerlos consistentes, para contestar lo
mismo que una agregacion de Mongo contesta sin cruzar bases. El argumento de
"asi se justifica Neo4j" era debil: el grafo ya se justifica solo con la ruta
completa de un envio, la red cliente-operador-envio y el historial de
movimientos de un contenedor (D11).

**Por que un snapshot y no una referencia:** es el patron documental por
excelencia. El snapshot **no se actualiza** si despues cambia la ruta del envio,
y eso es intencional: un incidente registra las circunstancias de cuando
ocurrio, no las actuales. Es la respuesta a la pregunta previsible en la defensa
("¿y si despues cambia la ruta?").

**Imprecision aceptada:** el enunciado liga el incidente al **envio**, no al
tramo, asi que "ruta" es el par origen-destino del envio y no el de un tramo
individual. Ganar precision exigiria agregar `tramo_id` al incidente, que es un
supuesto mas. Se documenta y no se agrega.

## D13 — El heartbeat de sensores usa un sorted set

**Estado:** propuesta · **Responsable:** Umbi

El modelo de Redis usa una clave String por sensor
(`sensor:actividad:<sensor_id>`) con TTL. El plan original del grupo era un
**sorted set**.

**Propuesta:** volver al sorted set
(`ZADD sensores:heartbeat <timestamp> <sensor_id>`).

**Por qué:**

1. El proceso periódico "detección de sensores inactivos" pasa a ser **un solo
   comando**: `ZRANGEBYSCORE sensores:heartbeat -inf <corte>`. Con claves
   sueltas hay que traer todos los sensores de PostgreSQL y consultar Redis una
   vez por sensor.
2. Con TTL, al vencer la clave **se pierde cuándo reportó por última vez**: solo
   queda "no hay clave". Con el sorted set el score siempre está, y se puede
   informar "inactivo desde tal hora", que es lo que un operador necesita.
3. La ambigüedad que el propio documento de Redis señala con cuidado (clave
   ausente = nunca reportó, o = venció) desaparece: un sensor que nunca reportó
   simplemente no está en el conjunto.

---

## D14 — El modelo de Redis cubre también locks y caché

**Estado:** propuesta · **Responsable:** Umbi, con Thiago para los locks

El plan del grupo asignaba a Redis cuatro usos; el modelo documenta dos.

**Faltan:**

1. **Locks `SET NX EX` para los procesos periódicos.** Sin ellos, dos ejecuciones
   simultáneas del job de facturación generan facturas duplicadas. Afecta a los
   cuatro procesos periódicos del enunciado.
2. **Caché de reportes.** La tabla del grupo dice "Reporte → Redis (caché)".

**Pendiente también para el entregable 3** ("modelos físicos de todas las
bases"): el enunciado pide índices, restricciones y particionamiento por motor.
Hoy el modelo de Neo4j enuncia la restricción de unicidad de `id` pero no escribe
el Cypher, y el de Redis no dice que no hay particionamiento ni por qué.

---

## D15 — El dinero se modela con `Decimal`, no con `float`

**Estado:** acordada · **Fecha:** 12/10/2026 · **Alcance:** todo el dominio y el DDL

Todo campo monetario (`Tramo.costo`, `Tarifa.monto`, `Factura.importe_total`,
`Pago.monto`, `CuentaCorriente.saldo`, `MovimientoCuenta.monto`) se modela con
`decimal.Decimal` en Python y con `NUMERIC` en PostgreSQL. Nunca `float` ni
`REAL`/`DOUBLE PRECISION`.

**Por qué:** `float` es binario y no representa exactamente los decimales. En
Python, `0.1 + 0.2` da `0.30000000000000004`. Sumando cientos de tramos, el
importe de una factura se desvía de a centavos respecto del total real, y el
cierre mensual de cuentas corrientes no cierra. El enunciado pide "controles de
integridad", y en facturación eso empieza por el tipo de dato.

**Le cambia el trabajo a:** Fran (columnas `NUMERIC(12,2)` en `tramo`, `tarifa`,
`factura`, `pago`, `cuenta_corriente` y `movimiento_cuenta`).

---

## D16 — `Tramo` no tiene estado; `vehiculo_id` es obligatorio

**Estado:** acordada · **Fecha:** 12/10/2026 · **Alcance:** `domain/tramo.py`

**Tramo no lleva un campo `estado`.** Se considera completado cuando tiene
`fecha_llegada_real` (método `esta_completado()`).

**Por qué:** `Envio` necesita estado porque el enunciado se lo lista y porque hay
un reporte que agrupa por él ("Envíos por estado"). Tramo no tiene "Estado" en el
enunciado y ningún reporte agrupa por él: agregarlo sería un supuesto sin
requisito detrás. La presencia o ausencia de `fecha_llegada_real` ya responde si
el tramo se ejecutó.

**Consecuencia — asimetría con `Envio`, a tener presente en la defensa:** en
`Envio` la regla es bicondicional (hay `fecha_llegada_real` **si y solo si** el
estado es `ENTREGADO`), porque hay dos campos que pueden contradecirse. En
`Tramo` no hay estado, así que solo se exige coherencia temporal: si la fecha
está, no puede ser anterior a `fecha_salida`.

**`vehiculo_id` es obligatorio (`UUID`, no `UUID | None`).**

**Por qué:** es una **simplificación asumida**. En la realidad se planifica la
ruta y después se asignan los vehículos, con lo cual el campo sería nulo entre
una cosa y la otra. Se asume que un tramo se crea ya con su vehículo asignado,
porque el enunciado no describe ninguna etapa de planificación previa y porque
permitir nulos obliga a manejar ese caso en cada consulta y en cada propagación
del Outbox. Con el campo obligatorio, la FK es `NOT NULL` y la relación
`(:Tramo)-[:UTILIZA]->(:Vehiculo)` siempre existe en Neo4j.

---

## D17 — `medio_transporte` es un enum de tres valores

**Estado:** acordada · **Fecha:** 12/10/2026 · **Alcance:** `domain/tramo.py`, `tarifa`

`MedioTransporte` toma `TERRESTRE`, `MARITIMO` o `AEREO`, por el objetivo del
enunciado ("envíos terrestres, marítimos y aéreos"). No es texto libre.

**Por qué no texto libre:**

1. El reporte obligatorio "Costos por tipo de transporte" es un
   `GROUP BY medio_transporte`. Con texto libre, `"Maritimo"`, `"MARITIMO"` y
   `"maritimo "` son tres grupos distintos: el reporte no sale lento, sale **mal**,
   y en silencio.
2. `Tarifa.medio_transporte` tiene que coincidir con `Tramo.medio_transporte`
   para que la facturación automática encuentre la tarifa. Con texto libre la
   búsqueda no encuentra nada y la factura sale en cero.

**Regla general que se desprende:** un campo puede ser texto libre si es
descriptivo (`Incidente.descripcion`), pero nunca si es eje de agrupación de un
reporte o clave de búsqueda entre tablas.

**Le cambia el trabajo a:** Fran (el `CHECK` o el tipo `ENUM` de la columna, en
`tramo` y en `tarifa`).

---

## D18 — Los repositorios no exponen `cambiar_estado`

**Estado:** acordada · **Fecha:** 12/10/2026 · **Alcance:** todos los repositorios

Ninguna interfaz de repositorio tiene un metodo del tipo
`cambiar_estado(id, estado)`. La escritura se hace con dos metodos: `guardar`
para el alta y `actualizar` para persistir una entidad ya modificada.

**Por qué:** un metodo que recibe un `id` suelto y un estado **saltea el
dominio**. Permite escribir cualquier estado directamente en la base sin pasar
por las reglas de la entidad: con `cambiar_estado(id, EstadoEnvio.CREADO)` se
puede devolver a `CREADO` un envio ya `ENTREGADO`, que es exactamente lo que D4
prohíbe. El flujo correcto es: el servicio obtiene la entidad, la modifica a
través de sus propios métodos (`Envio.pasar_a()`), y la guarda entera.

**Consecuencia:** la regla de negocio vive en un solo lugar (el dominio) y el
repositorio queda reducido a lo suyo, que es leer y escribir.

**Le cambia el trabajo a:** todos los que escriban un repositorio. La convención
es `guardar` / `actualizar` / `obtener` / `listar_*`.

**Pendiente relacionado:** `Contenedor` todavía no tiene el equivalente de
`Envio.pasar_a()`. Hoy el servicio le asigna el estado directamente después de
consultar `puede_asignarse()`. Si aparecen más reglas sobre el ciclo de vida del
contenedor, conviene darle su propio método de cambio de estado.

---

# Decisiones de la integracion del trabajo del grupo (13/10/2026)

Surgen de revisar el DDL de PostgreSQL (Fran) y los modelos de MongoDB y
Cassandra (Mati) contra el enunciado y las decisiones anteriores. **Thiago
aplico estos cambios directamente sobre el trabajo de los dos**; quedan
registradas aca para que puedan revisarlas.

---

## D19 — Un unico juego de valores, en MAYUSCULAS, en los cinco motores

**Estado:** acordada · **Alcance:** todos los motores y el dominio

El mismo concepto se escribe **identico** en PostgreSQL, MongoDB, Cassandra,
Neo4j, Redis y el dominio Python: `EN_TRANSITO`, `ALTA`, `ABIERTO`,
`CARGA_INICIADA`. En MAYUSCULAS y con guion bajo.

**Por que:** antes de unificar, el mismo concepto convivia en tres formas:
`'EN_TRANSITO'` en los `CHECK` de Postgres, `"abierto"` en los validadores de
Mongo y `'carga_iniciada'` en Cassandra. Eso obliga al worker del Outbox a
traducir en cada propagacion, y el dia que alguien se olvida de una traduccion
el dato entra mal y **ningun motor se queja**: los tres valores son validos en
su propia base. Es la clase de error que no se detecta hasta que un reporte
devuelve menos filas de las que deberia.

**Aplicado:** se pasaron a mayusculas todos los `enum` de los validadores de
MongoDB y los tipos de evento de Cassandra.

**Le cambia el trabajo a:** Umbi (los valores que escriba en Neo4j y Redis siguen
la misma regla).

---

## D20 — `Lectura` lleva `envio_id` opcional

**Estado:** acordada · **Alcance:** `domain/lectura.py`, Cassandra

La tabla `recorrido_por_contenedor` de Cassandra tiene una columna `envio_id`
que la entidad `Lectura` no podia completar, porque no existia en el dominio.

**Aplicado:** `Lectura.envio_id: UUID | None = None`.

**Por que opcional:** un contenedor en deposito o en mantenimiento sigue
reportando lecturas sin estar asignado a ningun envio. Obligarlo a tener uno
seria modelar una realidad que no existe.

Ademas se agrego la propiedad derivada `Lectura.dia`, que es la clave de
particion de Cassandra. **Se deriva de `momento` en vez de guardarse**: dos
fuentes para el mismo dato se terminan contradiciendo.

Y se documento en `LecturaRepository.guardar()` que la implementacion de
Cassandra escribe en **dos tablas** (`lecturas_por_sensor` y
`recorrido_por_contenedor`). Es doble escritura a proposito, porque Cassandra no
hace JOIN y cada consulta necesita su propia tabla.

---

## D21 — Los eventos de Cassandra guardan `ubicacion_id` y el nombre

**Estado:** acordada · **Responsable:** Mati · **Alcance:** Cassandra

Las tablas de eventos guardaban solo `ubicacion_nombre` como texto. Se agrego
`ubicacion_id uuid` **sin sacar el nombre**.

**Por que los dos:** el `uuid` conserva la identidad compartida entre motores
(regla comun del grupo) y permite volver desde un evento a la `ubicacion` de
PostgreSQL o al nodo de Neo4j. Solo con el nombre, ese camino de vuelta no
existe. El nombre se mantiene denormalizado para mostrar el evento sin tener que
ir a buscarlo a otra base, que es justamente para lo que sirve Cassandra.

---

## D22 — `Conversacion` es una entidad nueva

**Estado:** acordada · **Responsable:** Mati · **Alcance:** MongoDB

El enunciado modela `Mensaje` con `Destinatario` y un `Tipo` (privado/grupal).
El modelo implementado agrega una coleccion `conversaciones`, y los mensajes
referencian `conversacion_id`.

**Por que se acepta:** es el modelo estandar de chat. Hace que "historial de
conversaciones" sea una consulta indexada por conversacion en vez de un filtro
por pares de usuarios, y permite declarar un **indice unico parcial** sobre
`clave_participantes` que garantiza que no existan dos chats privados entre las
mismas dos personas. Los mensajes van referenciados y no embebidos porque crecen
sin limite y un documento de MongoDB no puede pasar los 16 MB.

**Es un supuesto a documentar en el informe:** es una entidad que no esta en el
enunciado. Tambien se enriquecio `grupos_trabajo.integrantes`, que paso de una
lista de ids a objetos con `rol` y `desde`.

---

## D23 — Los datos semilla comparten los ids de PostgreSQL

**Estado:** acordada · **Alcance:** todos los scripts de datos de prueba

PostgreSQL es el **dueno** de cliente, usuario, envio, contenedor, sensor,
ubicacion, operador y proveedor. Los datos semilla de los otros motores usan
**exactamente los UUID de `scripts/postgres/02_datos_prueba.sql`**.

**Por que:** antes, los seeds de Mongo y Cassandra usaban un esquema propio
(`aaaaaaaa-...`, `cccccccc-...`) distinto del de Postgres (`a0000000-...`,
`20000000-...`). Con ids que no coinciden **no se puede demostrar nada de punta
a punta**: un incidente de Mongo apuntaba a un envio que no existia en Postgres.
Para la defensa hay que poder seguir un mismo envio por las cinco bases.

**Las entidades propias de MongoDB** (conversacion, mensaje, incidente, alerta,
reporte, prediccion) conservan sus propios ids: Mongo es su dueno y nadie mas
los genera.

---

## D24 — Correcciones al esquema de PostgreSQL

**Estado:** acordada · **Responsable:** Fran (aplicadas por Thiago)

El DDL cumplia las siete decisiones que lo tocaban y replicaba los invariantes
del dominio como `CHECK`, incluida la bicondicional de estado y fecha de llegada
de D16. Se corrigieron ocho puntos:

1. **Se agrego la tabla `rol`.** El enunciado la lista como entidad propia (ID,
   Descripcion, Nivel de permisos) y pide "administracion de usuarios y roles".
   Estaba resuelta como una columna `VARCHAR` con `CHECK` en `usuario`, con lo
   cual no habia donde guardar la descripcion ni el nivel, y crear un rol nuevo
   exigia un `ALTER TABLE`.
2. **`usuario`** recupera `cliente_id` (NULL para los usuarios internos) y
   `apellido`, los dos listados en el enunciado, y `rol` pasa a `rol_id` con FK.
3. **`activo BOOLEAN` pasa a `estado VARCHAR` con `CHECK`** en cliente, operador,
   proveedor, ubicacion, vehiculo, tarifa y usuario (D1). La baja logica es
   `estado = 'INACTIVO'`.
4. **`pais`** se agrega a cliente, operador y proveedor (el enunciado lo lista).
5. **`operador.nombre` pasa a `razon_social`**, para unificar con cliente y
   proveedor.
6. **`vehiculo.patente` pasa a `identificacion`**: un buque se identifica por
   numero IMO y un avion por matricula; ninguno tiene patente.
7. **`factura`, `pago` y `cuenta_corriente` pasan a `titular_tipo` +
   `titular_id`** (CLIENTE / PROVEEDOR / OPERADOR), segun el supuesto 4, que se
   apoya en la pagina 1 del enunciado: *"facturacion, pagos y cuentas corrientes
   de los clientes, proveedores y operadores logisticos"*. Estaban limitadas a
   `cliente_id`, lo que hacia **imposible** ese requisito. `pago` ya no lleva
   titular: se deriva de su factura.
8. **`contenedor.tipo`** recibe su `CHECK`, como el resto de los campos `tipo`.

**Costo asumido en el punto 7:** `titular_id` es una referencia polimorfica, asi
que no admite una FK. La existencia del titular la valida el servicio. Es el
precio de cumplir el requisito con una tabla en vez de tres.

**Se conservan dos mejoras** que el DDL traia sin acordar y que son mejores que
el modelo original: `tarifa` con `costo_base` / `costo_por_km` / vigencia por
fechas, y `sensor.intervalo_reporte_segundos`, que es justo el dato que faltaba
para que la deteccion de sensores inactivos (D13) sepa a partir de cuando el
silencio es una anomalia.

---

## D25 — PENDIENTE: los umbrales configurados no tienen donde vivir

**Estado:** ABIERTA · **Responsable:** Mati

`alertas.detalle.umbral` guarda el umbral **que se violo**, despues del hecho.
Pero "deteccion de anomalias de temperatura" necesita el umbral **configurado de
antemano**, y no existe en ninguna coleccion ni tabla.

Las dos salidas son: una constante en el codigo (defendible solo si se declara
como simplificacion) o una coleccion de configuracion en MongoDB por `tipo` de
contenedor, que es lo realista: un `REEFER_40` con pescado y un `DRY_20` con
electronica no toleran lo mismo.

**Sigue sin decidir.** Es el unico hueco funcional abierto del enunciado.

---

# Decisiones de la primera rebanada vertical (19/10/2026)

Salen de implementar Cliente, Rol y Usuario de punta a punta: dominio,
repositorio, PostgreSQL, servicio y consola. Es la primera parte de la
aplicacion que realmente corre contra una base.

---

## D26 — La baja de clientes y usuarios es logica

**Estado:** acordada · **Alcance:** dominio, servicios, PostgreSQL

El enunciado pide "alta, **baja** y modificacion de clientes". La baja **no
borra la fila**: pasa `estado` a `INACTIVO`.

**Por que:** un cliente borrado se lleva puestos sus envios, sus facturas y su
cuenta corriente, que lo referencian con `FOREIGN KEY ... ON DELETE RESTRICT`.
Un borrado fisico o fallaria por la FK o, peor, obligaria a borrar en cascada el
historial. Ademas los reportes analiticos ("tiempos de envio por cliente",
"promedio de incidentes por cliente") necesitan los datos de clientes que ya no
operan.

**Consecuencia:** `ClienteRepository` no tiene `eliminar()`. La baja es un
cambio de estado, o sea un `actualizar()` como cualquier otro (D18).
`listar(solo_activos=True)` filtra los dados de baja.

**Relacion con la sincronizacion:** esto es lo que el plan del grupo llamaba
"soft delete". Al propagar a Neo4j y Mongo, la baja viaja como un cambio de
propiedad y no como un `DELETE`, con lo cual el grafo conserva las relaciones
historicas del cliente.

---

## D27 — Las contrasenas se hashean con PBKDF2-HMAC-SHA256

**Estado:** acordada · **Alcance:** `seguridad.py`, `usuario`

El enunciado pide "Contrasena encriptada". Se usa PBKDF2-HMAC-SHA256 con salt
aleatorio de 16 bytes y 200.000 iteraciones, de `hashlib` (biblioteca estandar).

Formato guardado: `pbkdf2_sha256$<iteraciones>$<salt_hex>$<hash_hex>`.

**Por que no un SHA256 pelado:** un hash comun esta disenado para ser **rapido**,
que es justo lo que no se quiere. PBKDF2 repite el calculo cientos de miles de
veces, asi que probar un diccionario entero cuesta tiempo real.

**Por que el salt:** sin salt, dos usuarios con la misma contrasena guardan el
mismo hash, y una tabla precalculada los rompe a los dos de una. Con salt
aleatorio por usuario, cada hash es unico (hay un test que lo verifica).

**Por que `hmac.compare_digest` y no `==`:** un `==` corta en el primer byte
distinto, y medir cuanto tarda permite adivinar el hash byte a byte.
`compare_digest` tarda lo mismo siempre.

**Por que de la biblioteca estandar y no bcrypt o argon2:** para no sumar otra
dependencia. En un sistema real irian argon2 o bcrypt, y eso se aclara en el
informe.

**Consecuencia en los datos de prueba:** los hashes semilla eran cadenas de
ejemplo con pinta de bcrypt que no verificaban con nada. Se reemplazaron por
hashes PBKDF2 reales. **La contrasena de los cuatro usuarios semilla es
`demo1234`**, y la autenticacion de la aplicacion funciona con ellos.

**Nota para la defensa:** `autenticar()` devuelve el **mismo** mensaje de error
para "ese email no existe" y para "contrasena incorrecta". Distinguirlos le
confirma a un atacante que un email esta registrado. Hay un test que compara los
dos mensajes.

---

## D28 — La transaccion se maneja con Unit of Work

**Estado:** acordada · **Alcance:** `repositories/unidad_de_trabajo.py` y su
implementacion en PostgreSQL

Los repositorios **no confirman** por su cuenta. Se agrupan en una
`UnidadDeTrabajo` que abre una conexion, se la presta a todos y confirma una
sola vez:

```python
with self._uow as uow:
    if uow.usuarios.obtener_por_email(email) is not None:
        raise ConflictoDeDatos(...)
    uow.usuarios.guardar(usuario)
    uow.commit()
```

**Por que:** es lo que hace real la justificacion de PostgreSQL de la tabla
PROCESOS del grupo: *"Facturacion, pagos y cierre mensual de cuentas →
transacciones: o se hace todo o nada"*. Si cada repositorio confirmara por su
lado, una facturacion a medias dejaria la factura escrita y la cuenta corriente
sin actualizar, y no habria forma de deshacerlo.

**El detalle que lo hace funcionar:** los tres repositorios comparten **la misma
conexion**. Con una conexion por repositorio, el commit de uno no arrastraria al
otro y la atomicidad seria una ilusion.

**Salir sin commit deshace todo.** El `__exit__` llama siempre a `rollback()`:
si ya hubo commit no queda nada que deshacer, y si el bloque se corto por una
excepcion (o alguien se olvido del commit) no queda nada escrito a medias. Hay
un test de integracion que lo verifica: un alta de usuario con un rol
inexistente no deja rastro.

---

## D29 — Los errores de psycopg se traducen a errores del dominio

**Estado:** acordada · **Alcance:** `infrastructure/postgres/conexion.py`

Un decorador `@traducir_errores` envuelve cada metodo de repositorio y convierte:

| Error de PostgreSQL | Error de la aplicacion |
|---|---|
| `UniqueViolation` | `ConflictoDeDatos` |
| `ForeignKeyViolation` | `ValidacionError` |
| `CheckViolation` | `ValidacionError` |
| cualquier otro `psycopg.Error` | `ErrorDePersistencia` |

**Por que:** las capas de arriba no tienen por que saber que existe psycopg. Si
manana una entidad se mudara de motor, los `except` del servicio y de la consola
seguirian valiendo sin tocar una linea. Es el mismo principio de D2: la
infraestructura no se filtra hacia arriba.

Ademas cada traduccion deja un registro en el log con el nombre de la
restriccion violada, que dice mucho mas que el mensaje crudo de Postgres. Eso
cubre "manejo o control de errores" y "registro de logs" de las restricciones
tecnicas del enunciado.

---

## D30 — El esquema se aplica con un script, no solo con docker-compose

**Estado:** acordada · **Alcance:** `scripts/aplicar_esquema.py`

`docker-compose.yml` monta `scripts/postgres/` en
`/docker-entrypoint-initdb.d`, pero esa carpeta **solo se ejecuta la primera vez
que se crea el volumen de datos**. Como el contenedor de Postgres se levanto
antes de que los scripts existieran, el volumen ya estaba creado y los scripts
no corrieron nunca: la base quedo vacia sin que nadie se enterara.

`python scripts/aplicar_esquema.py` crea el esquema y carga los datos semilla;
con `--reiniciar` borra todo y lo rehace. Es idempotente y sirve tanto para
montar el entorno de cero como para dejarlo limpio antes de la defensa.

---


---

## D31 — `LecturaRepository` en Cassandra: qué devuelve y cómo escribe

**Estado:** propuesta · **Responsable:** Mati · **Alcance:** `domain/lectura.py`, `repositories/lectura_repository.py`, `infrastructure/cassandra`

**1. `posiciones_de_contenedor` devuelve `Posicion`, no `Lectura`.**
La tabla `recorrido_por_contenedor` guarda solo lo necesario para dibujar la ruta
(contenedor, sensor, envío, latitud y longitud). Una `Lectura` exige temperatura,
humedad, vibración y batería, que esa tabla no tiene. Había dos salidas: ensanchar
la tabla hasta duplicar `lecturas_por_sensor`, o devolver un tipo más chico. Se
eligió lo segundo. **Es un cambio a la interfaz** (se agrega `Posicion` al dominio).

**2. `guardar` escribe en las dos tablas con un batch `LOGGED`.**
Cassandra registra el batch antes de aplicarlo: si el nodo cae a mitad, lo completa
después, y las dos tablas no quedan desincronizadas. Cuesta algo de rendimiento,
pero son solo dos escrituras. La escritura es idempotente (misma clave, misma fila).
Se usa nivel de consistencia `ONE`: perder una lectura aislada es tolerable.

**3. Una lectura sin envío no escribe `envio_id`.**
Escribir `None` en Cassandra crea un tombstone. Se usa `UNSET_VALUE`, que no
escribe la columna. Al leer, esa columna vuelve como `None`.

**4. La partición se calcula en UTC.**
Un `momento` sin zona horaria se interpreta como UTC, que es la convención del
grupo. Se normaliza antes de calcular el día de la partición. Al leer, el driver
devuelve fechas sin zona y se la reponemos.

**5. Los rangos tienen límite.**
Cada día es una partición, así que un rango es una consulta por día. `desde` y
`hasta` son inclusivos, y un rango de más de 31 días se rechaza con
`ValidacionError`. `ultimas` retrocede como máximo 30 días hasta juntar la cantidad
pedida; un sensor que lleva más tiempo callado devuelve menos lecturas.

**Limitación aceptada:** `listar_por_sensor` no completa `envio_id`, porque
`lecturas_por_sensor` no lo guarda. Está disponible en `recorrido_por_contenedor`.

**Le cambia el trabajo a:** Thiago (interfaz y `container.py`) y Umbi (el
simulador tiene que generar `momento` en UTC).

---

## D32 — `IncidenteRepository` en MongoDB y la entidad `Incidente`

**Estado:** propuesta · **Responsable:** Mati · **Alcance:** `domain/incidente.py`, `repositories/incidente_repository.py`, `infrastructure/mongo`

**1. Entidad `Incidente`.** Sigue D1, D2 y D4: estados, tipos y severidades son
`Enum` puro con valores en mayúsculas (D19), y el cambio de estado se hace solo con
`pasar_a()`, que valida la transición y la deja en el historial embebido. El
`ContextoEnvio` es la foto del envío al ocurrir el incidente (D12) y su `ruta` se
deriva de origen y destino, como `Lectura.dia`.

**2. Transiciones (supuesto nuevo).** `ABIERTO → EN_ANALISIS | RESUELTO`,
`EN_ANALISIS → RESUELTO`, `RESUELTO → CERRADO | ABIERTO` (reapertura). `CERRADO` es
final. El enunciado no define el ciclo de vida de un incidente: es un supuesto a
documentar.

**3. "Incidentes abiertos" son `ABIERTO` y `EN_ANALISIS`.** Otro supuesto: el
enunciado no define qué cuenta como abierto.

**4. `contar_agrupado` recibe un enum, no un nombre de campo.** Evita filtrar
detalles de Mongo hacia arriba y agrupar por un campo inexistente. Es la mitad
Mongo del "promedio de incidentes por país, estado y cliente": el promedio lo
calcula el servicio dividiendo por la cantidad de envíos, que vive en PostgreSQL.
`ranking_de_rutas` es el mismo conteo agrupado por ruta (D12).

**5. Configuración de la conexión.** `uuidRepresentation="standard"` guarda los
`uuid.UUID` como `binData` subtipo 4, igual que `UUID()` en mongosh; sin eso, los
ids no coinciden con los de los scripts ni con los de las otras bases, y pymongo ni
siquiera acepta guardarlos. `tz_aware=True` devuelve las fechas con zona UTC.

**6. `actualizar` reemplaza el documento entero (D18)** y lanza `NoEncontrado` si
no existe. Los errores de pymongo se traducen igual que los de psycopg (D29): una
clave duplicada es `ConflictoDeDatos` y un documento que no cumple el `$jsonSchema`
(código 121) es `ValidacionError`.

**Le cambia el trabajo a:** Thiago (`container.py`).

---

## D33 — Los reportes devuelven objetos del dominio, nunca tuplas

**Estado:** acordada · **Fecha:** 20/10/2026 · **Alcance:** todos los repositorios

Los metodos de agregacion devuelven dataclasses `frozen` de
`domain/reportes.py`, no `tuple` ni `dict`.

**Por que:** la regla del proyecto es que los repositorios reciben y devuelven
objetos del dominio, nunca filas (D2). Una `tuple[str, int]` ES una fila: en
quien la consume queda `fila[0]` y `fila[1]`, sin que nada diga que el primero
es el pais y el segundo la cantidad. Con un objeto, el nombre del campo lo dice,
y si manana la consulta agrega una columna, los consumidores no se rompen.

**Aplicado el 20/10 sobre `IncidenteRepository`:** `contar_agrupado` devolvia
`list[tuple[str, int]]` y ahora devuelve `list[ConteoIncidentes]`;
`ranking_de_rutas` devolvia lo mismo y ahora devuelve `list[RutaConIncidentes]`.
Se agregaron las dos clases a `domain/reportes.py`, junto a las que ya existian
para los reportes de envios.

**Nota sobre `ConteoIncidentes.grupo`:** es siempre texto, incluso cuando el eje
es el cliente, porque MongoDB guarda el UUID pero no la razon social, que vive
en PostgreSQL. Resolver el nombre es tarea del servicio, no del repositorio.

---

## D34 — El evento del Outbox lo publica el SERVICIO, no el repositorio ni un trigger

**Estado:** acordada · **Fecha:** 21/10/2026 · **Alcance:** `services/`, `sync/eventos.py`

Cada operacion que cambia un dato que vive en mas de un motor encola su evento
**dentro de la misma transaccion**, desde el servicio:

```python
with self._uow as uow:
    uow.envios.guardar(envio)
    uow.outbox.guardar(eventos.envio_creado(envio, envio.fecha_creacion))
    uow.commit()
```

**El problema que resuelve (dual write).** La alternativa obvia seria guardar en
PostgreSQL, hacer commit y despues escribir en Neo4j. Eso falla de dos maneras
distintas: si el proceso se cae o Neo4j esta caido entre las dos operaciones,
PostgreSQL tiene el dato y Neo4j no, **y no queda registro de que faltaba
hacerlo**; y si la escritura a Neo4j falla, no se puede deshacer el commit, que
ya ocurrio. Invertir el orden no mejora: deja nodos de envios que nunca
existieron, que es peor, porque un dato de mas no tiene contra que compararse.
La raiz es que **ninguna transaccion abarca las dos bases**.

Con el Outbox hay una sola escritura atomica, en una sola base: si commitea,
estan el dato y el evento; si falla, no esta ninguno. La propagacion es otro
problema, y si falla el evento **sigue pendiente** para reintentarse.

**Por que el servicio y no el repositorio.** El repositorio ve un `UPDATE` sobre
`envio`; no puede distinguir si fue un cambio de estado, una correccion de
prioridad o una baja. El servicio si, porque el decidio la operacion. El evento
se arma donde esta la intencion, no donde esta el SQL. Ademas, ponerlo en el
repositorio obligaria a acordarse de encolarlo en cada implementacion nueva.

**Por que no un TRIGGER de PostgreSQL.** Seria imposible de olvidar, pero la
logica de sincronizacion quedaria escrita en SQL dentro de la base, fuera del
control de versiones del codigo, imposible de testear sin levantar PostgreSQL e
invisible para quien lee el servicio. Tampoco sabria distinguir la intencion,
por el mismo motivo que el repositorio.

**Forma del payload** (`sync/eventos.py`): lleva solo lo que los destinos
necesitan para construir el nodo o el documento, no la entidad entera. Mandar
todo acoplaria el grafo a cambios de PostgreSQL que no le importan. Los
`Decimal` viajan como texto y no como float, para no reintroducir el error de
redondeo que D15 evita.

**Consecuencia en los datos semilla:** las filas de `outbox` usaban
`evento_tipo = 'ENVIO_CREADO'`, que repite el agregado dentro del tipo de
evento. Son dos ejes independientes: quedo `agregado_tipo = 'ENVIO'` y
`evento_tipo = 'CREADO'`.

---

## D35 — Los proyectores son idempotentes: MERGE, nunca CREATE

**Estado:** acordada · **Fecha:** 21/10/2026 · **Alcance:** `sync/`

El worker garantiza **entrega al menos una vez** (*at-least-once*), no
exactamente una vez. Entre el instante en que Neo4j confirma la escritura y el
instante en que el worker marca el evento como procesado hay una ventana: si el
proceso muere ahi, el evento sigue pendiente y **se vuelve a entregar**.

Esa ventana **no se puede eliminar** sin una transaccion distribuida entre
PostgreSQL y Neo4j. Asi que la solucion no es perseguir el *exactamente una
vez*, sino hacer que recibir el evento dos veces sea inofensivo:

> entrega al menos una vez + proyector idempotente = efecto exactamente una vez

**En la practica: `MERGE` y nunca `CREATE`.** Con `CREATE` pasa una de dos, y
las dos son malas: sin restriccion de unicidad quedan dos nodos con el mismo
id; con la restriccion que define `scripts/neo4j/01_constraints.cypher`, el
segundo intento **falla**, el evento se marca fallido, se reintenta, vuelve a
fallar, y se vence sin haber llegado nunca. `MERGE` busca el nodo y lo crea
solo si no existe.

Las restricciones de Umbi cumplen aqui un segundo papel ademas del de
integridad: le dan a `MERGE` el indice que evita recorrer todos los nodos.

**Otras decisiones del worker:**

- **Un proyector por motor de destino, detras de una interfaz.** Agregar un
  destino es sumar un proyector a la lista del contenedor, sin tocar el worker.
  Y permite testear el worker entero con proyectores falsos, **sin levantar
  ninguna base**: los 14 tests de `test_sync_worker.py` corren en memoria.
- **MongoDB no tiene proyector, y es correcto.** El Outbox existe para los
  motores que contienen una *proyeccion* de datos de PostgreSQL. MongoDB es
  **dueno** de sus entidades (incidentes, alertas, chat, reportes,
  predicciones): nadie las deriva de otra base. El unico destino real es Neo4j.
- **Un evento que falla no frena la tanda.** Si un destino esta caido, los
  eventos de los otros destinos tienen que poder seguir. El fallido queda
  pendiente para el proximo turno.
- **Backoff medido desde el ultimo intento.** Se agrego la columna
  `outbox.fecha_ultimo_intento`. Midiendo desde `fecha_creacion`, un evento
  viejo con varios reintentos pasaria el control siempre y el backoff no
  serviria de nada.
- **Payloads tolerantes.** El proyector completa con `null` los parametros que
  el payload no trae, y lo registra en el log. Un evento encolado por una
  version anterior del codigo no debe trabar la cola para siempre.

---

## D36 — El chequeo de consistencia complementa al Outbox, no lo reemplaza

**Estado:** acordada · **Fecha:** 21/10/2026 · **Alcance:** `sync/consistencia.py`

El Outbox garantiza que ningun cambio hecho **a traves de los servicios** se
pierda. Pero el grafo puede quedar distinto de PostgreSQL por tres caminos que
el Outbox no cubre:

1. **Un evento agoto sus reintentos.** El destino estuvo caido mas tiempo que
   la politica de reintentos y el evento se vencio.
2. **Alguien escribio en PostgreSQL sin pasar por los servicios.** Un INSERT a
   mano, una carga masiva, o **los propios datos semilla del proyecto**, que se
   cargan con SQL directo. Esos cambios no generan eventos.
3. **Un nodo quedo huerfano** despues de que su fila se borrara en PostgreSQL.

Por eso hay dos herramientas mas:

**`verificar()`** compara, tipo por tipo, los ids de PostgreSQL contra los ids
de los nodos del grafo, y reporta los que **faltan** y los que **sobran**,
ademas de los eventos pendientes y los vencidos. No modifica nada.

**`reconstruir()`** rearma el grafo entero leyendo PostgreSQL, sin pasar por el
Outbox. Arma el mismo evento que habria emitido el servicio y lo aplica con el
mismo proyector, de modo que el resultado es identico al de la propagacion
normal.

**Por que reconstruir es posible, y por que importa:** el grafo **no contiene
ningun dato original**, solo una proyeccion de PostgreSQL. Si se perdiera
entero, se puede rehacer. Esa propiedad es la que permite tratar su
sincronizacion como **eventual** sin comprometer la correccion del sistema, y
es el argumento central para defender por que es aceptable que el grafo quede
momentaneamente desactualizado.

**El detalle de `borrar_antes`:** `MERGE` agrega y corrige, pero **no borra**.
Para eliminar un nodo sobrante hay que vaciar el grafo y rearmarlo. Reparar
faltantes es barato; reparar sobrantes cuesta una reconstruccion completa.

**Orden de reconstruccion.** Primero los maestros (ubicaciones, operadores,
vehiculos), despues clientes y contenedores, y al final envios y tramos. Al
reves, los `MERGE` de los envios crearian nodos de ubicacion vacios, sin
propiedades, que recien se completarian despues.

**Hueco que encontro esta pieza:** nada creaba los nodos `Operador` ni la
relacion `OPERA`, porque ningun evento de negocio los menciona. Sin eso, el
requisito "red de relaciones entre clientes, operadores y envios" **no se podia
resolver**. Quedo claro el reparto: los datos **transaccionales** (envios,
tramos, clientes, contenedores) se sincronizan por eventos, y los **maestros**
(ubicaciones, vehiculos, operadores) por reconciliacion, que es como se hace en
la practica porque cambian poco y en bloque.

**Un repositorio aparte para esto.** `ConsistenciaRepository` existe porque la
reconciliacion necesita ver el contenido completo de una tabla, sin filtros ni
paginado: es una necesidad distinta de la de los casos de uso del negocio, y
mezclarlas ensuciaria las interfaces de las entidades.

---

## D37 — Consultas de lectura de Neo4j

**Estado:** propuesta · **Responsable:** UMBI

Se implementan tres consultas en `Neo4jConsultaRepository`:

- Ruta de un envío: obtiene sus tramos y los ordena por `orden`.
- Red de un cliente: obtiene sus envíos y los operadores vinculados
  a través de los vehículos y tramos.
- Tramos de un contenedor: consulta la relación `RECORRE`.

En línea con D33, las consultas devuelven objetos definidos en
`domain/reportes.py`. Se usan relaciones opcionales cuando pueden faltar
datos en la proyección del grafo.

**Validación:** las tres consultas se probaron con datos ficticios creados
en Neo4j local, incluyendo una relación `RECORRE` creada para la prueba.

**Pendiente de coordinación:** el proyector actual no crea `RECORRE` ni
proyecta las fechas reales de los tramos. Por eso, la tercera consulta
todavía no constituye un historial completo de movimientos reales.