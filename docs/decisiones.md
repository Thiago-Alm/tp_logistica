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

**Por qué el nodo es correcto: un tramo se conecta con CUATRO entidades.**

```
(:Envio)-[:TIENE_TRAMO]->(:Tramo)-[:DESDE]->(:Ubicacion)
                          (:Tramo)-[:HASTA]->(:Ubicacion)
                          (:Tramo)-[:UTILIZA]->(:Vehiculo)
```

Una relación de Neo4j une exactamente **dos** nodos y no puede ser extremo de
otra. Modelar el tramo como una relación entre las dos ubicaciones dejaría sin
forma de expresar qué vehículo lo recorre ni a qué envío pertenece: habría que
meter el `vehiculo_id` como propiedad de la relación, y entonces el vehículo
dejaría de ser un nodo alcanzable, con lo cual la consulta
`Envio → Tramo → Vehiculo ← Operador` —que es la que justifica tener Neo4j
(D11)— sería imposible.

Además el tramo tiene **identidad y propiedades propias** (`id`, `orden`,
`medio_transporte`, `costo`), y se consulta por sí mismo.

> **Corrección del 27/10.** La versión anterior de esta decisión justificaba el
> nodo diciendo que hacía falta para colgar de él `(:Contenedor)-[:RECORRE]->`.
> Esa relación terminó descartándose (D37), así que el argumento quedó apoyado
> en algo que no existe. El fundamento real es el de arriba, que no depende de
> ninguna relación opcional y es más fuerte.

**Consecuencia:** la entidad `Ruta` del documento del grupo queda **subsumida en
los tramos** y no se modela aparte. El recorrido de un envío se reconstruye
siguiendo `(:Envio)-[:TIENE_TRAMO]->(:Tramo)`.

**Hecho el 27/10:** `docs/modelo_neo4j.md` y `docs/diagramas.md` quedaron
alineados con el código, sin `RECORRE` y con `Tramo` en la tabla de nodos.

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

**Estado:** acordada · **Responsable:** Umbi (correcciones de Thiago el 27/10)
**Alcance:** `infrastructure/neo4j/consulta_repository.py`

Se implementan en `Neo4jConsultaRepository` las tres consultas avanzadas que
pide el enunciado:

- **Ruta completa de un envio:** sus tramos, ordenados por `orden`, con origen,
  destino, medio de transporte y vehiculo.
- **Red de relaciones cliente-operador-envio:** los envios de un cliente y los
  operadores vinculados, recorriendo
  `Envio -> Tramo -> Vehiculo <- Operador`. Son los tres saltos que justifican
  tener un motor de grafos: en SQL es un join de cuatro tablas que empeora si se
  quiere profundidad variable.
- **Historial de movimientos de un contenedor:** los tramos por los que paso.

En linea con D33, las consultas devuelven objetos de `domain/reportes.py` y no
diccionarios ni tuplas. Se usan `OPTIONAL MATCH` donde la proyeccion puede
todavia no tener el dato, para que la consulta devuelva el envio igual aunque
le falte, por ejemplo, el operador.

---

### Correccion del 27/10: la relacion `RECORRE` no existe

La consulta de movimientos de un contenedor estaba escrita sobre
`(:Contenedor)-[:RECORRE]->(:Tramo)`, una relacion que **ningun proyector
crea**. El modelo inicial de Neo4j la proponia, pero nunca se implemento.
Resultado: la consulta devolvia **siempre una lista vacia**, sin error, y el
requisito "historial completo de movimientos de un contenedor" no funcionaba.
Neo4j incluso emitia una advertencia de que el tipo de relacion no existia, que
pasaba desapercibida porque el driver no la trata como error.

**Por que no se agrego la relacion, y se cambio la consulta.** No hay en
PostgreSQL ningun dato que diga por que tramos concretos paso cada contenedor.
Solo se sabe en que envios estuvo (`envio_contenedor`) y que tramos tuvo cada
envio (`tramo.envio_id`). Una relacion `RECORRE` derivada de esos dos datos no
agregaria ninguna informacion que el camino
`(:Contenedor)<-[:INCLUYE]-(:Envio)-[:TIENE_TRAMO]->(:Tramo)` no tenga ya, y
habria que mantenerla sincronizada en el proyector y en la reconstruccion. Es
complejidad sin contrapartida.

El modelo inicial anotaba, con buen criterio, que "no se supondra que todos los
contenedores de un envio recorren automaticamente todos sus tramos". La
observacion es correcta, pero **ese detalle fino no existe en PostgreSQL**: vive
en Cassandra, en `eventos_por_contenedor`, que registra el movimiento real de
cada contenedor. El grafo responde lo que puede responder con los datos que
proyecta, y la granularidad mayor se consulta donde esta.

**Leccion para la defensa:** una consulta que devuelve vacio no siempre es una
consulta sin resultados. Antes de dar por buena una consulta sobre un grafo
conviene verificar que las relaciones que nombra existan de verdad:

```cypher
MATCH ()-[r]->() RETURN type(r) AS tipo, count(*) AS cantidad ORDER BY cantidad DESC
```

Hay un test de regresion (`test_el_grafo_no_tiene_la_relacion_recorre`) que deja
constancia de que `RECORRE` no existe y de que la consulta funciona igual.

### Otras correcciones

- **Los parametros pasan de `str` a `UUID`**, como en todos los demas
  repositorios del proyecto. La conversion a texto se hace dentro de la
  implementacion, porque el grafo guarda los identificadores como cadenas.

---

## D25 — El umbral de temperatura vive en la colección `umbrales` de MongoDB

**Estado:** acordada · **Responsable:** Mati · **Alcance:** MongoDB, detección de anomalías

> Esta entrada reemplaza a la D25 abierta ("los umbrales configurados no tienen
> dónde vivir").

El umbral configurado de cada medición se guarda en una colección `umbrales` de
MongoDB, con un documento por tipo de contenedor y magnitud:

```js
{ _id, tipo_contenedor: "REEFER_40", magnitud: "TEMPERATURA", minimo: -25.0, maximo: -15.0, unidad: "C" }
db.umbrales.createIndex({ tipo_contenedor: 1, magnitud: 1 }, { unique: true })
```

La detección de anomalías consulta el umbral del tipo de contenedor de la lectura.
Si el valor queda fuera de `[minimo, maximo]`, crea una alerta que guarda el limite
traspasado en `alertas.detalle.umbral` (D38). Por ahora solo se cargan umbrales de
`TEMPERATURA`, que es lo que pide el enunciado; el campo `magnitud` deja lugar para
humedad y vibración sin cambiar el esquema.

**Por qué una colección y no una constante en el código:**

1. Un `REEFER_40` con pescado y un `DRY_20` con electrónica no toleran la misma
   temperatura. Una constante única genera alertas falsas en uno y deja pasar
   anomalías reales en el otro.
2. Ajustar un umbral con una constante obliga a tocar el código y volver a desplegar.
   Con una colección se cambia un documento.
3. Cuesta una colección chica con dos documentos de prueba, así que no hace falta
   defenderla como simplificación.

**Por qué MongoDB y no PostgreSQL:**

1. La alerta y su umbral viven en el mismo motor: el servicio lee el umbral y
   escribe la alerta sin pasar por otra base.
2. La estructura es chica y puede variar según la magnitud, que es el caso de uso
   del esquema flexible.
3. Es coherente con D12: la alerta guarda una copia del limite violado, de modo que
   si el umbral se modifica después, las alertas históricas conservan el valor con
   el que se generaron.

**Costo asumido:** `tipo_contenedor` repite los valores de `contenedor.tipo` de
PostgreSQL sin una clave foránea. Los valores válidos se copian del dominio al
validador (D1): el dominio sigue siendo la fuente de verdad.

**Restricciones:** validador `$jsonSchema` con los tipos y valores permitidos, regla
`minimo < maximo` con `$expr`, e índice único por tipo de contenedor y magnitud. El
rango es cerrado: un valor igual al mínimo o al máximo es normal.

**Qué pasa si no hay umbral para un tipo de contenedor:** el servicio no genera
alerta y deja un `WARNING` en el log, una sola vez por tipo. No se asume un valor
por defecto: un valor inventado genera alertas falsas o silencia las verdaderas.

**Implementación:** `domain/umbral.py`, `repositories/umbral_repository.py`,
`infrastructure/mongo/umbral_repository.py` y `scripts/mongo/mongo_umbrales.js`.

**Le cambia el trabajo a:**

- Fran: confirmar la lista de valores de `contenedor.tipo`, que se repite en el
  validador.
- Umbi: ya no hace falta que su generador de datos produzca lecturas fuera de rango
  para disparar alertas: lo hace el simulador (D39). Conviene acordar quién genera
  qué para no duplicar.

---

## D38 — Detección de anomalías y alertas

**Estado:** acordada · **Responsable:** Mati · **Alcance:** `domain/alerta.py`, `services/deteccion_anomalias_service.py`, `infrastructure/mongo/alerta_repository.py`

Cierra el requisito "detección de anomalías de temperatura".

**1. Cómo funciona.** `DeteccionAnomaliasService.evaluar(lectura)` busca el umbral
del tipo de contenedor de la lectura y, si la temperatura lo viola, crea una
`Alerta` en MongoDB. La lista de mediciones evaluadas tiene una sola fila
(temperatura): sumar humedad o vibración es agregar otra.

**2. El servicio no consulta PostgreSQL.** Recibe una función que dice de qué tipo
es cada contenedor. El simulador la arma con su lista de sensores; un pipeline real
la armaría con el repositorio de contenedores. No usa la `UnidadDeTrabajo`, porque
alertas y umbrales están en otro motor y no comparten transacción con PostgreSQL.

**3. Idempotencia.** El `_id` de la alerta es determinístico (`uuid5` de sensor,
momento de la lectura en UTC con milisegundos y tipo). Reintentar la misma detección
no duplica la alerta: `guardar` usa `$setOnInsert` con `upsert` y devuelve `True`
si la creó y `False` si ya existía.

**4. Severidad (supuesto nuevo).** Depende de cuánto se pasa el valor del límite,
como fracción del ancho del rango: hasta 10 % es `BAJA`, hasta 25 % `MEDIA`, hasta
50 % `ALTA` y más, `CRITICA`. Se usa una fracción y no grados para que valga igual
con cualquier unidad y tamaño de rango. El enunciado no define la severidad.

**5. La fecha de la alerta es la de la lectura**, no la del procesamiento: dos
corridas del mismo dato dan la misma alerta.

**Limitación aceptada:** se crea una alerta por cada lectura que viola el umbral.
Una anomalía sostenida genera una alerta por lectura. Una mejora posible es una
sola alerta abierta por sensor y tipo, que se cierre sola cuando el valor se
normaliza; se dejó afuera porque exige un ciclo de vida de la alerta (reconocer,
cerrar) que el enunciado no pide.

**Le cambia el trabajo a:** nadie por ahora; los servicios que lean alertas usan
`AlertaRepository.listar_abiertas` y `listar_por_sensor`.

---

## D39 — Simulador IoT

**Estado:** acordada · **Responsable:** Mati · **Alcance:** `jobs/simulador_iot.py`

Se ejecuta con `python -m logistica.jobs.simulador_iot`. Con `--ciclos 0` corre
hasta Ctrl+C.

**1. Qué hace en cada ciclo.** Genera una lectura por sensor, las guarda juntas con
`LecturaRepository.guardar_lote` y después evalúa cada una con la detección (D38).
Guarda antes de evaluar, para que una alerta nunca apunte a una lectura que no
quedó persistida.

**2. Modelo de los datos.** La temperatura vuelve hacia el centro del rango del
umbral con algo de ruido. Con una probabilidad configurable se inyecta una
anomalía: durante unos ciclos el valor queda fuera del rango, más seguido por
arriba (corte de frío) que por abajo. La posición se mueve, la batería baja y la
humedad y vibración varían poco. Con `--semilla` la secuencia se puede repetir.

**3. El rango que se simula sale del umbral configurado** de cada tipo de
contenedor (D25). Si un tipo no tiene umbral, se simula un rango por defecto y la
detección avisa que no puede evaluarlo.

**4. Fuente de los sensores (simplificación).** Se leen de PostgreSQL con una
consulta directa, porque todavía no existe un `SensorRepository`. Cuando exista,
se reemplaza. Alternativa: `--sensores-json archivo.json`, que no necesita
PostgreSQL ni conocer el esquema.

**5. Resiliencia.** Un ciclo que falla por un error de persistencia se registra y
la simulación sigue. Si fallan 5 seguidos, se aborta.

**6. Los momentos están en UTC con precisión de milisegundos**, que es lo que
guarda Cassandra (D31).

**Le cambia el trabajo a:** Fran (cuando exista `SensorRepository`, reemplazar la
consulta directa) y Umbi (ver D25: acordar quién genera datos de prueba).

---

### Nota de integracion (Thiago, 27/10)

Al probar el simulador contra las bases reales aparecieron tres cosas:

1. **La semilla de umbrales cubria 2 de los 7 tipos de contenedor.** El `CHECK`
   de `contenedor.tipo` en PostgreSQL admite `DRY_20`, `DRY_40`, `REEFER_20`,
   `REEFER_40`, `OPEN_TOP_40`, `TANK_20` y `FLAT_RACK_40`; el script solo traia
   `REEFER_40` y `DRY_20`. Consecuencia: la deteccion **se salteaba en silencio**
   3 de los 5 sensores de prueba, guardando sus lecturas en Cassandra sin evaluar
   ninguna. Se completaron los siete, con rangos justificados por tipo de carga, y
   el validador de la coleccion ahora los admite a todos. Tras el arreglo, las
   alertas de una corrida identica pasaron de 14 a 45.

2. **Se descarto el alias `datetime.UTC`.** El codigo original lo usaba, pero ese
   alias existe desde Python 3.11 y el proyecto declara `requires-python = ">=3.10"`
   en `pyproject.toml`. Se mantiene `timezone.utc`, que es lo que usa el resto del
   proyecto y funciona en las dos versiones. El aviso de `ruff` que motivo el
   cambio no aparece con la configuracion real del repositorio.

3. **Una sola conexion a MongoDB.** Los repositorios de incidentes, umbrales y
   alertas comparten el cliente a traves de `Contenedor.base_mongo`. `pymongo` ya
   maneja un pool interno: abrir un cliente por repositorio multiplicaria las
   conexiones sin ningun beneficio.

**Leccion que vale para la defensa:** una configuracion incompleta es peor que una
ausente. Si el umbral no existiera, el sistema fallaria y alguien lo notaria; como
existe para algunos tipos y no para otros, funcionaba "bien" y no evaluaba la mayor
parte de las lecturas. Por eso el servicio registra un `WARNING` cuando no encuentra
umbral, en vez de ignorar la medicion sin dejar rastro.

---

## D40 — La traza de eventos logísticos se escribe a través del Outbox

**Estado:** acordada · **Fecha:** 27/10/2026 · **Responsable:** Fran (implementado por Thiago)
**Alcance:** `domain/evento_logistico.py`, `sync/proyector_cassandra.py`, Cassandra

El enunciado pide el "historial completo de eventos" y el "seguimiento temporal
de cada envío". Esa traza vive en Cassandra, en las tablas `eventos_por_envio` y
`eventos_por_contenedor`, y se alimenta de **dos fuentes distintas**:

| Origen | Tipos | Cómo llega a Cassandra |
|---|---|---|
| Automático | `CARGA_INICIADA`, `EN_TRANSITO`, `EN_PUERTO`, `ENTREGADO`, `CANCELADO` | El cambio de estado del envío genera un evento en el Outbox, y el `ProyectorCassandra` lo traduce |
| Manual | `ADUANA`, `RETRASO`, `DESCARGA` | Un operador los registra con `EventoLogisticoService.registrar()` |

**Por qué a través del Outbox y no escribiendo directo desde el servicio.** Sería
más corto que `EnvioService.cambiar_estado()` guardara el envío en PostgreSQL y
después escribiera el evento en Cassandra. Pero eso es exactamente el *dual
write* que el Outbox existe para evitar (D34): entre el commit y la escritura en
Cassandra hay una ventana en la que el envío cambia de estado y **la traza se
pierde para siempre**, sin que nadie se entere. Pasando por el Outbox, si
Cassandra está caída el evento queda pendiente y se reintenta.

Esto convierte a Cassandra en el **segundo destino** del worker, junto a Neo4j.
Los dos contienen datos derivados de PostgreSQL. MongoDB sigue sin proyector
porque es dueño de sus entidades (D35).

**Idempotencia.** El `evento_id` que se escribe en Cassandra **no es un uuid4**:
se deriva del id del evento del Outbox con `uuid5`. Como `evento_id` es parte de
la clave primaria de las dos tablas, reprocesar el mismo evento pisa la misma
fila en lugar de agregar una nueva. Con un uuid4, cada reintento sumaría una
entrada repetida a la traza. Hay un test que lo verifica.

**Por qué no se permite cargar a mano un tipo automático.** Si un operador
pudiera registrar un `ENTREGADO`, la traza tendría dos entradas para el mismo
hecho —la del operador y la del proyector— y dejaría de ser una fuente
confiable. `registrar()` rechaza esos tipos con un error explícito.

**Doble escritura, otra vez a propósito.** Cada evento se escribe en las dos
tablas, porque Cassandra no hace JOIN y cada consulta necesita su propia tabla
(mismo criterio que `Lectura`, D31). Si el evento no tiene contenedor, solo se
escribe en `eventos_por_envio`: sin contenedor no hay clave de partición para la
segunda.

**Nivel de consistencia `QUORUM`, no `ONE`.** A diferencia de una lectura de
sensor suelta, cuya pérdida es tolerable frente al volumen, **la trazabilidad no
puede perder eventos**: es la que responde "qué le pasó a este envío".

**Rango obligatorio al consultar el recorrido de un contenedor.** La partición de
`eventos_por_contenedor` lleva un bucket mensual, porque un contenedor se
reutiliza durante años y su historial no está acotado. Una consulta sin rango
dispararía una consulta por cada mes en servicio: el repositorio limita el rango
a 24 meses y el servicio usa el último año por defecto.

**`anio_mes` se deriva, no se guarda.** Igual que `Lectura.dia` (D20): dos
fuentes para el mismo dato se terminan contradiciendo.

---

## D41 — El saldo se guarda además del libro mayor, y la transacción los mantiene juntos

**Estado:** acordada · **Fecha:** 27/10/2026 · **Alcance:** facturación y cuentas corrientes

`cuenta_corriente.saldo` guarda el saldo, y `movimiento_cuenta` guarda cada
asiento que lo formó. El saldo **podría derivarse** sumando los movimientos, así
que guardarlo es una **denormalización deliberada**.

**Por qué se guarda.** Mostrar el estado de cuenta de un titular, verificar su
límite de crédito antes de facturar o listar las cuentas con deuda son
operaciones frecuentes. Derivar el saldo en cada una obligaría a sumar todos los
movimientos históricos cada vez, y esa suma crece sin límite mientras el titular
opere.

**Cuál es el riesgo, y cómo se controla.** El saldo y los movimientos pueden
divergir si alguna escritura deja uno sin el otro. Por eso:

1. **Las tres escrituras van en la misma transacción.** Emitir una factura es
   `guardar(factura)` + `guardar(movimiento)` + `actualizar(cuenta)`, todas
   dentro del mismo `with uow`. Si el commit falla, no queda ninguna. Es el caso
   que justifica la Unidad de Trabajo (D28) y, con ella, haber elegido
   PostgreSQL para esta parte del sistema.
2. **Hay un control de integridad que los compara.** `verificar_saldos()` recorre
   cada cuenta y contrasta el saldo guardado contra la suma de sus movimientos.
   Devuelve solo las que no cuadran. Corre como proceso periódico cada 30
   minutos y está disponible en el menú.

Un test de integración verifica que, cuando la emisión falla por límite de
crédito, **no queda ni la factura, ni el movimiento, ni el saldo cambiado**.

---
---

### Otras decisiones de esta pieza

**El libro mayor solo se agrega.** Un `MovimientoCuenta` nunca se modifica ni se
borra. Anular una factura **no borra** su asiento original: agrega uno de signo
contrario. Corregir un error contable es otro asiento, no una edición, y así el
histórico sigue explicando cómo se llegó al saldo actual.

**El monto de un movimiento es siempre positivo; el sentido lo da el tipo.** Si
además el monto pudiera ser negativo, un `DEBITO` de `-100` sería en realidad un
crédito y habría dos formas de expresar lo mismo. El `CHECK (monto > 0)` de la
base y la validación del dominio lo impiden en las dos capas.

**Convención del signo del saldo:** negativo cuando el titular debe. Un `DEBITO`
lo baja y un `CREDITO` lo sube. Es la convención de los datos semilla y la que
usa `deuda`, que devuelve la deuda en positivo o cero.

**La facturación automática es idempotente.** `facturar_envio()` consulta primero
si el envío ya tiene factura y devuelve `None` si la tiene. Correr el proceso dos
veces el mismo día no duplica nada. Aun así el planificador lo ejecuta bajo un
lock de Redis (D14), porque dos instancias simultáneas podrían leer la lista de
entregados antes de que la otra escriba su factura: la idempotencia protege de
la repetición secuencial, el lock de la concurrencia.

**Un envío que no se puede facturar no frena a los demás.** El proceso registra
el motivo en el log y sigue con el siguiente. Si cortara, un solo envío mal
cargado dejaría sin facturar a todos los que vienen después.

**El cierre mensual no pone el saldo en cero.** El saldo es continuo y la deuda
no desaparece a fin de mes. Lo que hace el cierre es marcar como `VENCIDA` cada
factura cuyo vencimiento pasó y dejar el resumen del período. Una factura
`VENCIDA` **sigue siendo cobrable**: solo `PAGADA` y `ANULADA` son estados
finales.

**El titular es polimórfico y no admite clave foránea.** `titular_tipo` +
`titular_id` cubren CLIENTE, PROVEEDOR y OPERADOR (supuesto 4). PostgreSQL no
puede declarar una FK sobre una referencia que apunta a tres tablas distintas,
así que la existencia del titular la valida el servicio, según el criterio de
D3. Es el precio de cumplir el requisito con una tabla en lugar de tres.

**Los pagos parciales están contemplados.** Una factura pasa a `PAGADA` solo
cuando la suma de sus pagos alcanza el importe total, y un pago que supere lo que
resta se rechaza.

---

## D42 — La autenticacion es la puerta de la aplicacion, y el rol recorta el menu

**Estado:** acordada · **Fecha:** 28/10/2026 · **Alcance:** `cli/app.py`, `domain/sesion.py`, sesiones en Redis

Hasta esta semana la aplicacion tenia usuarios, roles con `nivel_permisos`,
hashes PBKDF2 (D27) y un `autenticar()` que funcionaba, pero **nada de eso
protegia nada**: `python -m logistica` abria el menu completo sin pedir
credenciales, e "Iniciar sesion" era la opcion 4 de un submenu que imprimia un
identificador que despues nadie usaba. La tabla `rol` existia y `nivel_permisos`
no se leia en ningun lado.

**Que se decidio.** `main()` no arma el menu hasta que `_autenticar()` devuelve
un usuario, su rol y una sesion abierta en Redis. Si las credenciales fallan
tres veces, la aplicacion termina con codigo 1. La sesion se cierra en un
`finally`, asi que salir del menu la borra sin esperar el TTL.

**El rol recorta el menu, y el control esta en un solo lugar.** Cada seccion
declara su nivel minimo en `_secciones()`:

| Seccion | Nivel minimo | Quien la ve |
|---|---|---|
| Clientes | 60 | ADMINISTRADOR, OPERADOR |
| Usuarios, roles y sesiones | 100 | ADMINISTRADOR |
| Envios y trayectos | 60 | ADMINISTRADOR, OPERADOR |
| Facturacion y cuentas corrientes | 60 | ADMINISTRADOR, OPERADOR |
| Reportes | 30 | ADMINISTRADOR, OPERADOR, AUDITOR |
| Sincronizacion entre motores | 100 | ADMINISTRADOR |

`_opciones_para(nivel, secciones)` filtra y **renumera desde 1**: si filtrara
sin renumerar, el menu mostraria "1, 3, 5" y se veria como un error. No hay un
`if nivel >= X` repartido por los menus; el criterio vive en una sola funcion y
hay un test parametrizado que verifica cuantas secciones ve cada nivel.

**Las secciones que el rol no alcanza no se muestran.** Mostrarlas deshabilitadas
le contaria a cualquiera que entre que existen y que hay detras.

**El rol CLIENTE (nivel 10) no ve ninguna seccion, y esta bien.** La consola es
una herramienta interna: un cliente no opera el back-office. El usuario
`mariana@agroglobal.com` autentica correctamente y la aplicacion le dice que su
rol no tiene acceso a ninguna seccion. **Es el caso que demuestra en vivo que el
control de permisos existe**, y conviene mostrarlo en la defensa.

### Por que la sesion es una entidad y vive en Redis

`Sesion` es una entidad de dominio (`domain/sesion.py`), no un diccionario. El
repositorio y el servicio reciben y devuelven `Sesion`, como el resto del
proyecto (D33). La primera version devolvia `dict[str, str]` y levantaba
`ValueError` en vez de `ValidacionError`: se corrigio para que respete D29 y D33.

**El TTL no se pasa como parametro aparte: se deriva de `sesion.fecha_fin`.** Si
viajaran los dos, podrian contradecirse y habria dos respuestas a "cuando muere
esta sesion". `guardar()` calcula los segundos que le quedan y rechaza con
`ValidacionError` una sesion que ya vencio.

**Por que Redis y no una tabla:** la sesion es el unico dato del sistema que nace
con fecha de muerte. En PostgreSQL haria falta un proceso periodico que barra las
vencidas; en Redis el `EXPIRE` del motor lo hace solo. El `hset` y el `expire`
van en el mismo pipeline transaccional: si el `expire` se perdiera, la sesion
quedaria viva para siempre. Hay un test de integracion que crea una sesion con
TTL de 1 segundo y verifica que desaparece sin que nadie la borre.

**`listar_activas()` usa SCAN, no KEYS.** `KEYS` bloquea el motor mientras
recorre todo el espacio de claves, que en este proyecto comparte los locks de
los procesos periodicos (D14), la cache de reportes y el heartbeat de sensores.
Entre el SCAN y el HGETALL una clave puede vencer, asi que el repositorio saltea
las respuestas vacias en vez de romper. El servicio ademas filtra las vencidas
que Redis todavia no barrio, porque el `EXPIRE` no es instantaneo.

**Lo que falta, y se asume:** no hay bloqueo por intentos fallidos repetidos
(solo el corte de tres intentos por ejecucion) ni renovacion de la sesion por
actividad. Con un TTL de una hora, una sesion vence aunque el usuario este
trabajando. Se deja asentado como limitacion conocida.

---

---

## D43 — Los sensores inactivos se detectan con un heartbeat en Redis, no leyendo Cassandra

**Estado:** implementada · **Fecha:** 28/10/2026 · **Responsable:** Umbi · **Alcance:** Redis, `deteccion_inactividad_service`, planificador

Un sensor esta inactivo cuando **deja de reportar**. La pregunta es "cuanto hace
que no escribe", y responderla contra Cassandra obligaria a buscar la ultima
lectura de cada sensor recorriendo particiones por fecha. En cambio Redis guarda
un **sorted set** `sensores:heartbeat` donde el score es la marca de tiempo del
ultimo reporte: la respuesta es una sola lectura.

**Como funciona.** El simulador registra el heartbeat **despues** de guardar las
lecturas en Cassandra, para que una señal nunca afirme un dato que no se
escribio. El proceso consulta los sensores con estado administrativo `ACTIVO` en
PostgreSQL y compara, para cada uno, el tiempo sin reportar contra su
`intervalo_reporte_segundos`.

**Los cuatro resultados posibles:**

| Resultado | Cuando |
|---|---|
| `ACTIVO` | reporto dentro de su intervalo (en el limite exacto todavia cuenta como activo) |
| `INACTIVO` | el tiempo sin reportar supera su intervalo |
| `SIN_DATOS` | no hay heartbeat para ese sensor |
| `RELOJ_INVALIDO` | la marca temporal es futura o no se puede interpretar |

**Por que `SIN_DATOS` es su propio resultado y no `INACTIVO`:** la ausencia de
heartbeat no permite distinguir un sensor recien dado de alta de una perdida de
datos de Redis. Informarlo como inactivo seria afirmar algo que no se sabe.

**Por que `RELOJ_INVALIDO` y no descartar la señal:** un sensor con el reloj
adelantado pareceria eternamente activo. Nombrar el caso lo hace visible en el
log en vez de esconderlo.

**Un error de Redis no es inactividad.** Si falla la lectura, el proceso informa
un fallo propio. Si lo tradujera a "todos los sensores inactivos", una caida de
Redis se veria como una caida de la planta.

**Lo que el proceso NO hace, y es deliberado:** no cambia el estado
administrativo del sensor en PostgreSQL ni crea alertas persistentes en MongoDB.
Registra el resultado en el log. El estado administrativo lo decide una persona;
este proceso informa, no actua.

**Limitacion conocida.** El planificador corre cada 30 segundos con un lock de
Redis de 120 segundos (D14). La exclusion entre instancias depende de que la
ejecucion termine antes de que venza el lock: si tardara mas, otra instancia
podria arrancar en paralelo.

---

## D44 — Los reportes se cachean en Redis 60 segundos, y la cache nunca rompe el reporte

**Estado:** implementada · **Fecha:** 28/10/2026 · **Responsable:** Umbi · **Alcance:** Redis, `ReporteService`

Los siete reportes de `ReporteService` son consultas de agregacion sobre
PostgreSQL que varios usuarios pueden pedir seguido con los mismos parametros.
Se cachean en Redis con vencimiento de 60 segundos.

**La clave.** `cache:reportes:v1:<nombre>:<hash>`, donde el hash es un SHA-256 de
los parametros del reporte (fechas, limite del ranking). Dos reportes con
parametros distintos no se pisan, y el `v1` permite invalidar todas las claves de
golpe si cambia el formato guardado.

**El principio: la cache es un atajo, nunca una dependencia.** Si la clave no
existe o vencio, si la lectura de Redis falla, o si el contenido guardado no es
valido, se consulta PostgreSQL. Si falla la **escritura** de la cache, el
reporte se devuelve igual. Un Redis caido hace la aplicacion mas lenta, no la
rompe. Hay pruebas que simulan fallos de lectura y de escritura.

**Se guardan tambien las listas vacias y los `None`.** Si no se guardaran, el
caso "no hay datos" consultaria PostgreSQL cada vez, que es justo el caso en que
la consulta no sirve para nada.

**Los tipos se reconstruyen al leer.** JSON no tiene UUID, `Decimal`,
enumeraciones ni `timedelta`. Al deserializar se vuelven a armar, porque el resto
de la aplicacion espera los objetos del dominio (D33) y porque un `Decimal` que
volviera como float rompería D15.

**La consecuencia que hay que saber defender:** durante esos 60 segundos un
reporte puede mostrar datos anteriores al ultimo cambio en PostgreSQL. **No hay
invalidacion inmediata.** Es aceptable porque son reportes de lectura para
analisis, no pantallas de operacion: nadie decide sobre un envio puntual mirando
el reporte por pais. Facturacion, estados de envio y saldos **no** se cachean.

## D45 — El recorrido GPS se consulta por intervalo acotado y con zona horaria

**Estado:** implementada · **Fecha:** 28/10/2026 · **Responsable:** Umbi · **Alcance:** Cassandra, `GPSService`, menu "Seguimiento GPS"

La visualizacion geografica lee la tabla `recorrido_por_contenedor` (D31) con
`LecturaRepository.posiciones_de_contenedor()` y muestra las posiciones en una
tabla, de la mas vieja a la mas nueva.

**La fecha tiene que traer zona horaria.** Cassandra guarda los `timestamp` en
UTC. Una fecha sin zona es ambigua: `08:00` puede ser hora de Buenos Aires o
UTC, y la diferencia son tres horas de recorrido. En vez de suponer una zona, el
servicio la exige y convierte las dos fechas a UTC antes de consultar.

**El intervalo maximo es de 31 dias.** La tabla particiona por contenedor y dia,
asi que cada dia del intervalo es una particion mas que leer. Un limite evita
que una consulta de un año barra cientos de particiones, y 31 dias alcanzan para
seguir un envio internacional completo.

**El contenedor se verifica en PostgreSQL antes de ir a Cassandra.** Una lista
vacia de Cassandra no distingue "no existe el contenedor" de "no reporto en ese
intervalo". PostgreSQL es la fuente de verdad y lo distingue, y el menu muestra
un mensaje distinto en cada caso.

### Revision del 28/10: donde vive el limite, y como se cuentan los dias

El tope de 31 dias estaba escrito dos veces: como `timedelta(days=31)` en
`GPSService` y como `MAX_DIAS_POR_CONSULTA` en la implementacion Cassandra. Y no
contaban lo mismo: el servicio medía **tiempo transcurrido** y el repositorio
**dias de calendario**, que es lo que corresponde porque cada dia es una
particion. Pedir "los ultimos 31 dias" pasaba el control del servicio y lo
rechazaba el motor diciendo "el rango abarca 32 dias", con un numero que el
usuario no habia escrito.

Ahora `MAX_DIAS_POR_CONSULTA` y `dias_del_rango()` viven en
`repositories/lectura_repository.py`, o sea en el **contrato**, no en un motor.
Los usan la implementacion Cassandra y el servicio: el servicio puede rechazar
el rango antes de consultar PostgreSQL, sin repetir el numero y sin conocer
Cassandra. De las 23:00 de un dia a las 01:00 del siguiente son dos
particiones, aunque sean dos horas, y el mensaje de error es el mismo venga de
donde venga.

**El menu ofrece valores por defecto.** La consulta pedia un UUID y dos marcas
de tiempo ISO con zona, tipeadas a mano. Ahora acepta el **codigo ISO** del
contenedor (`HLCU7654321`, que es lo que esta impreso en el contenedor real y
lo que tiene a mano un operador) y Enter en las fechas usa los ultimos 7 dias.
`obtener_por_codigo` ya existia en el repositorio: no hizo falta nada nuevo.

### El envio de cada posicion se resuelve en PostgreSQL

`recorrido_por_contenedor` tiene columna `envio_id` y el simulador tiene el
campo, pero la consulta que arma los sensores no lo traia, asi que la columna
quedaba siempre en NULL: el cableado estaba completo y nadie llenaba el dato.

Ahora `SQL_SENSORES` resuelve el envio con un LEFT JOIN. Las tres decisiones de
esa consulta:

1. **Es un LEFT JOIN, no un JOIN.** Un contenedor `DISPONIBLE` o
   `EN_MANTENIMIENTO` no esta en ningun envio, y su lectura guarda `envio_id`
   NULL. Con un JOIN interno esos sensores desaparecerian del simulador.
2. **Si el contenedor estuvo en varios envios, vale el ultimo asignado que
   todavia no termino** (`fecha_asignacion` descendente). `ENTREGADO` y
   `CANCELADO` son finales (`EstadoEnvio.es_final`), asi que no son "el envio
   actual".
3. **El dato se guarda en la lectura, no se deriva al consultar.** El envio de
   un contenedor cambia con el tiempo; la posicion registra en que envio estaba
   **en ese momento**. Derivarlo despues contestaria con el envio de hoy, no
   con el de la lectura.

---

## D46 — Las consultas del grafo se exponen con un servicio que valida contra PostgreSQL

**Estado:** implementada · **Fecha:** 28/10/2026 · **Responsable:** Umbi · **Alcance:** Neo4j, `ConsultaGrafoService`, menu "Consultas de la red logistica"

Las tres consultas de D37 (ruta de un envio, envios y operadores de un cliente,
tramos recorridos por un contenedor) existian en `Neo4jConsultaRepository` pero
solo las llamaban los tests. Ahora las usa `ConsultaGrafoService`, y el menu
"Consultas de la red logistica" las muestra con nivel Operador (D42).

**El servicio confirma en PostgreSQL que la entidad exista.** Por la misma
razon que en D45: el grafo es una proyeccion y una lista vacia no dice si el id
es incorrecto o si todavia no tiene relaciones. Si no existe en PostgreSQL, el
grafo ni se consulta.

**Las consultas no pasan por la cache de reportes (D44).** Son consultas
puntuales por id, no agregaciones que varios usuarios piden con los mismos
parametros, asi que la cache no ahorraria nada.

---

## D47 — El promedio de incidentes lo arma el servicio, porque ninguna base lo puede responder sola

**Estado:** implementada · **Fecha:** 29/10/2026 · **Alcance:** `IncidenteService`, MongoDB, PostgreSQL, menu "Incidentes"

Los incidentes viven en MongoDB y los envios en PostgreSQL. "Promedio de
incidentes por envio" necesita las dos: **MongoDB cuenta el numerador** con una
agregacion por grupo, **PostgreSQL cuenta el denominador** porque es el que sabe
cuantos envios hay. Ninguna consulta sola lo responde, asi que lo compone el
servicio. Es el ejemplo mas claro de por que el sistema es poliglota y no un
capricho: la pregunta cruza la frontera entre los dos motores.

**En que ejes tiene sentido, y en cuales no.** El promedio exige que numerador y
denominador hablen de la misma poblacion:

| Eje | Promedio | Por que |
|---|---|---|
| CLIENTE | si | `listar_por_cliente` cuenta sus envios |
| PAIS_DESTINO | si | `listar_por_pais_destino` cuenta los envios al pais |
| ESTADO | **no** | agrupa por el estado del **incidente** (ABIERTO, RESUELTO), que no es un estado de envio: "incidentes ABIERTO / envios ABIERTO" no existe |
| RUTA | **no** | no hay "envios de la ruta ARBUE->NLRTM": la ruta sale de los tramos |
| PAIS_ORIGEN | **no** | `EnvioRepository` resuelve el pais por la ubicacion de **destino** |

El eje que no corresponde se rechaza con `ValidacionError` **nombrando los ejes
disponibles**. La primera version aceptaba ESTADO y reventaba con un `ValueError`
de Python al intentar construir `EstadoEnvio("ABIERTO")`: el error aparecio
corriendo el servicio contra las bases reales, no en los tests, porque los
dobles no conocen los valores validos de un enum.

**La razon social la resuelve el servicio.** MongoDB guarda el cliente como
UUID, porque la razon social vive en PostgreSQL y duplicarla en cada documento
la dejaria desactualizada. El servicio trae el mapa de clientes y lo resuelve
antes de devolver (D2). Si un documento tuviera guardado algo que no es un UUID,
se rechaza con `ValidacionError` en vez de promediar cualquier cosa.

**El denominador se cuenta por grupo, con una consulta cada uno.** Son pocos
grupos (cuatro clientes, un pais por destino), asi que no se arma una agregacion
en PostgreSQL solo para esto. Si los grupos crecieran, aca habria que cambiarlo.

### El alta congela el contexto del envio

`registrar()` arma el `ContextoEnvio` leyendo PostgreSQL —cliente, ubicacion de
origen y de destino, con sus paises— y lo **congela** en el documento (D12). Las
cuatro lecturas van en la misma transaccion (D28): el snapshot tiene que ser
coherente entre si, no una mezcla de dos momentos.

**Si falta una ubicacion, el incidente no se guarda.** No deberia pasar porque
hay clave foranea, pero si pasara, un snapshot a medias ensuciaria el ranking de
rutas para siempre: un incidente con la ruta incompleta queda mal contado en
todas las consultas futuras. Es mas barato fallar el alta.

**La ruta usa el LOCODE y no el nombre.** `ARBUE->NLRTM` y no
`Puerto de Buenos Aires->Puerto de Rotterdam`: es corto, univoco y es lo que
indexa MongoDB para el ranking (D12).

**El estado cambia por el dominio.** `cambiar_estado()` trae el incidente, le
pide `pasar_a()` a la entidad —que valida la transicion y deja el cambio en el
historial embebido— y recien despues lo persiste con `actualizar()`. No hay un
`cambiar_estado(id, estado)` en el repositorio (D18).

---

## D48 — El monitoreo IoT reparte cuatro motores en un solo caso de uso

**Estado:** implementada · **Fecha:** 29/10/2026 · **Alcance:** `MonitoreoService`, menu "Monitoreo IoT y alertas"

Una sola pantalla —seguir un sensor— toca cuatro bases, y cada una esta elegida
por la forma de su dato:

| Dato | Motor | Por que |
|---|---|---|
| Ficha del sensor (modelo, numero de serie, cada cuanto reporta) | PostgreSQL | dato estable que se relaciona con el contenedor |
| Lectura (temperatura, humedad, vibracion, posicion) | Cassandra | serie temporal que crece sin parar, se consulta por sensor y rango (D20) |
| Umbral | MongoDB | configuracion chica y de forma distinta segun el tipo de contenedor (D25) |
| Alerta | MongoDB | documento con el detalle embebido de lo que se violo |

**El sensor pasa a ser una entidad de dominio.** No existia: el simulador
consultaba la tabla `sensor` con SQL directo y dejaba anotado "cuando exista el
repositorio, se reemplaza". Ahora hay `Sensor`, `SensorRepository` y su
implementacion PostgreSQL, y entran en la Unidad de Trabajo como los demas
(D28). Sin esto el menu obligaba a tipear un UUID de sensor sacado de la nada.

**Tambien se agrega `Ubicacion`.** Hacia falta para el snapshot de D47: el envio
guarda `origen_id` y `destino_id`, y el nombre y el pais estaban solo en la
tabla. De paso le sirve al menu de envios, que hoy pide esos ids crudos.

**Se busca por numero de serie, no por UUID.** Igual que el contenedor por su
codigo ISO (D45): el numero de serie esta impreso en el equipo y es lo que tiene
a mano un operador. El UUID sigue funcionando.

**El tope de dias es el del contrato.** `historico()` reusa
`MAX_DIAS_POR_CONSULTA` y `dias_del_rango()` de `LecturaRepository`, los mismos
que el recorrido GPS (D45): cada dia es una particion de Cassandra y el limite se
declara una sola vez.

### El control de cobertura de umbrales

Nace de un error real: los umbrales cubrian **2 de los 7 tipos de contenedor**,
asi que la deteccion salteaba sensores **en silencio** y nadie se enteraba. Al
completarlos, una corrida identica paso de 14 a 45 alertas. Una configuracion
incompleta es peor que una ausente, porque parece que esta funcionando.

`cobertura_de_umbrales()` cruza los tres motores que participan de la deteccion
—sensores y tipo de contenedor de PostgreSQL, umbrales de MongoDB— y lista, por
tipo de contenedor en uso, que magnitudes tienen umbral y cuales no.

**Solo mira las magnitudes que la deteccion realmente evalua.** La primera
version comparaba contra todas las de `MagnitudUmbral` y reportaba HUMEDAD y
VIBRACION como faltantes en los tres tipos, cuando el servicio de deteccion solo
compara temperatura a proposito. Un control que grita por algo deliberado
entrena a ignorarlo. Ahora `DeteccionAnomaliasService` publica
`MAGNITUDES_EVALUADAS` y el control usa esa lista: **algo es un hueco solo si la
deteccion lo necesita**.

### Reconocer una alerta necesito un metodo nuevo

`AlertaRepository.guardar()` es un **insert-if-not-exists** (`$setOnInsert`): si
la alerta ya existe no la toca, porque el id es deterministico y reintentar una
deteccion no debe duplicarla (D33). Eso significa que `guardar()` **no sirve para
modificar**: reconocer o cerrar una alerta llamando a `guardar()` no hubiera
guardado nada, en silencio. Se agrego `actualizar()`, que hace `replace_one` y
lanza `NoEncontrado` si no existe, igual que `IncidenteRepository`.

**La alerta no tiene mapa de transiciones** como el envio (D4) o el incidente:
sus tres estados son una secuencia lineal, asi que la unica regla es que
`CERRADA` es final.

---

## D49 — El filtro de permisos se reusa dentro de los submenus

**Estado:** implementada · **Fecha:** 29/10/2026 · **Alcance:** `cli/permisos.py`, menus de incidentes y monitoreo

D42 puso el control de acceso en el menu principal: cada seccion declara su
nivel minimo y `opciones_para()` filtra y renumera. Al sumar incidentes y
monitoreo aparecio un caso que ese nivel unico no cubre: **dentro de una misma
seccion hay opciones de distinto riesgo**. Configurar un umbral cambia lo que
todo el sistema considera una anomalia; mirar las lecturas de un sensor no
cambia nada.

La tentacion era poner un `if nivel >= ...` adentro del menu. No: el criterio
quedaria repartido y seria imposible auditarlo de un vistazo. En cambio los
niveles y `opciones_para()` se mudaron a `cli/permisos.py`, y los submenus
declaran sus opciones con la misma forma `(nivel minimo, etiqueta, accion)` y
llaman **a la misma funcion**. Un solo mecanismo, en un solo lugar, en los dos
niveles del menu.

El resultado es una jerarquia que se puede mostrar en vivo:

| Rol | Secciones | Incidentes | Monitoreo |
|---|---|---|---|
| ADMINISTRADOR (100) | 10 de 10 | 7 | 10 |
| OPERADOR (60) | 8 de 10 | 7 | 9 (sin configurar umbrales) |
| AUDITOR (30) | 3 de 10 | 5 (solo consultas) | 5 (solo consultas) |
| CLIENTE (10) | 0 | — | — |

**El rol AUDITOR dejo de ser un callejon sin salida.** Antes veia solo
"Reportes". Ahora ve tambien incidentes y monitoreo en modo lectura, que es
justo el material de una auditoria, y no ve nada que modifique datos. Las dos
secciones nuevas entran con nivel de auditor **porque sus consultas son de
auditoria**, y el filtro interno le saca las opciones de operacion.

Hubo que corregir una contradiccion en el camino: las secciones estaban
declaradas con nivel de operador mientras sus opciones internas decian nivel de
auditor, asi que esas opciones eran inalcanzables. Las dos listas tienen que
estar alineadas, y hay un test que compara lo que ve cada nivel en los dos
menus.
