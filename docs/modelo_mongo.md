# Modelo de MongoDB

Responsable: MATI

## Objetivo

MongoDB se utilizará para:

- Registrar incidentes de los envíos.
- Registrar alertas generadas a partir de las lecturas de los sensores.
- Gestionar la mensajería privada y grupal, y los grupos de trabajo.
- Guardar las solicitudes de reportes.
- Guardar las predicciones diarias de riesgo.

Son datos con estructura anidada o variable, que se consultan de formas
distintas y que requieren agregaciones (promedios, rankings). Los datos masivos
y de solo agregar (lecturas y eventos) se guardan en Cassandra.

Script de creación: `scripts/mongo/mongo_modelo.js`.

## Convenciones

- Base de datos: `logistica`.
- Nombres en español, `snake_case`, sin tildes.
- Todo id es UUID (`binData` subtipo 4), tanto el `_id` propio como las
  referencias a entidades de otras bases.
- Fechas en UTC (tipo `date`).
- El driver de la aplicación debe usar UUID estándar
  (Python: `uuidRepresentation="standard"`, Java: `UuidRepresentation.STANDARD`).

## Fuente de datos

PostgreSQL conserva los datos maestros (clientes, usuarios, contenedores,
sensores, envíos). MongoDB solo guarda sus ids como referencia y no valida que
existan: esa validación la hace la capa de aplicación y el chequeo de
consistencia de la sincronización.

## Colecciones

### incidentes

Incidentes asociados a un envío.

| Campo | Descripción |
|---|---|
| _id | UUID del incidente |
| envio_id | UUID del envío (referencia a PostgreSQL) |
| contenedor_id | UUID del contenedor, opcional |
| tipo | demora, dano_carga, temperatura, robo, aduana, accidente, otro |
| severidad | baja, media, alta, critica |
| estado | abierto, en_analisis, resuelto, cerrado |
| descripcion | Texto libre |
| fecha | Fecha y hora del incidente |
| contexto_envio | Documento embebido con cliente_id, origen, destino, pais_origen, pais_destino y ruta |
| historial_estados | Arreglo embebido con estado, fecha y usuario_id de cada cambio |

`contexto_envio` es una copia de datos del envío tomada al crear el incidente.
Permite calcular el promedio de incidentes por país o cliente y el ranking de
rutas con un solo `aggregate`, sin consultar otras bases. Se acepta la
redundancia porque esos datos no cambian después de ocurrido el incidente.

Índices:

- `{ estado: 1, fecha: -1 }`: incidentes abiertos.
- `{ envio_id: 1, fecha: -1 }`: incidentes de un envío.
- `{ contexto_envio.cliente_id: 1 }`: promedio por cliente.
- `{ contexto_envio.pais_origen: 1 }`: promedio por país.
- `{ contexto_envio.ruta: 1 }`: ranking de rutas.

### alertas

Alertas generadas por la aplicación al detectar una anomalía en una lectura.

| Campo | Descripción |
|---|---|
| _id | UUID determinístico (calculado con sensor_id, fecha de la lectura y tipo) |
| tipo | temperatura, humedad, vibracion, bateria, inactividad, geocerca |
| sensor_id | UUID del sensor |
| contenedor_id, envio_id, evento_id | Referencias opcionales |
| estado | abierta, reconocida, cerrada |
| severidad | baja, media, alta, critica |
| fecha | Fecha y hora de la alerta |
| detalle | Documento embebido con valor leído, umbral y fecha de la lectura |

El `_id` determinístico evita duplicar alertas si el proceso se reintenta.

Índices: `{ estado: 1, fecha: -1 }`, `{ sensor_id: 1, fecha: -1 }`,
`{ envio_id: 1, fecha: -1 }`.

### conversaciones

Una conversación por cada par de usuarios (privada) o por grupo (grupal).

| Campo | Descripción |
|---|---|
| _id | UUID de la conversación |
| tipo | privada, grupal |
| participantes | Arreglo de UUID de usuarios (mínimo 2) |
| grupo_id | UUID del grupo, solo en las grupales |
| clave_participantes | Ids ordenados y unidos con `:` (solo en las privadas) |
| creada_en | Fecha de creación |
| ultimo_mensaje | Fecha y resumen del último mensaje |

Índices:

- `{ participantes: 1, ultimo_mensaje.fecha: -1 }`: conversaciones de un usuario.
- `{ clave_participantes: 1 }`, único y parcial (solo `tipo: privada`): impide
  más de un chat privado entre los mismos dos usuarios.

### mensajes

| Campo | Descripción |
|---|---|
| _id | UUID del mensaje |
| conversacion_id | UUID de la conversación |
| remitente_id | UUID del usuario que envía |
| contenido | Texto del mensaje |
| fecha | Fecha y hora |
| leido_por | Arreglo de UUID de usuarios |

Los mensajes se guardan en una colección aparte y no dentro de la
conversación, porque crecen sin límite y un documento no puede superar los 16 MB.

Índice: `{ conversacion_id: 1, fecha: -1 }`: historial paginado.

### grupos_trabajo

| Campo | Descripción |
|---|---|
| _id | UUID del grupo |
| nombre | Nombre del grupo |
| integrantes | Arreglo embebido con usuario_id, rol y fecha de ingreso |
| creado_en | Fecha de creación |

Índices: `{ integrantes.usuario_id: 1 }` (grupos de un usuario) y
`{ nombre: 1 }` único.

### reportes

| Campo | Descripción |
|---|---|
| _id | UUID del reporte |
| usuario_id | UUID del usuario que lo solicita |
| tipo | envios_por_pais, envios_por_estado, envios_por_cliente, envios_demorados, incidentes_abiertos, tiempos_por_cliente, incidentes_promedio, tiempos_promedio_entrega, costos_por_transporte |
| parametros | Documento libre, según el tipo de reporte |
| formato | pdf, csv, xlsx |
| estado | solicitado, generando, completado, error |
| fecha_solicitud | Fecha y hora de la solicitud |
| fecha_generacion | Fecha y hora de generación, nula hasta completarse |
| resultado | Documento con el resultado o la ubicación del archivo |

Los parámetros varían según el reporte, por eso se guardan como documento libre.

Índices: `{ usuario_id: 1, fecha_solicitud: -1 }` y `{ estado: 1 }`.

### predicciones_riesgo

| Campo | Descripción |
|---|---|
| _id | UUID de la predicción |
| envio_id | UUID del envío |
| dia_calculo | Día del cálculo, formato `YYYY-MM-DD` |
| probabilidad_demora | Número entre 0 y 1 |
| riesgo_climatico | Número entre 0 y 1 |
| riesgo_operativo | Número entre 0 y 1 |
| fecha_calculo | Fecha y hora del cálculo |
| modelo | Identificador del método usado |
| factores | Arreglo de textos con los factores considerados |

Índices:

- `{ envio_id: 1, dia_calculo: 1 }`, único: hay una sola predicción por envío y
  por día, y el proceso diario se puede repetir sin duplicar.
- `{ dia_calculo: 1, probabilidad_demora: -1 }`: envíos de mayor riesgo del día.

## Relaciones

MongoDB no tiene claves foráneas. Las relaciones se resuelven por referencia
con UUID (referencing), salvo los datos que siempre se leen juntos, que van
embebidos: historial de estados, integrantes de un grupo y contexto del envío.

## Restricciones

- Validadores `$jsonSchema` (validación estricta) en todas las colecciones:
  campos obligatorios, tipos, valores permitidos y rangos.
- Índices únicos: chat privado por par de usuarios, nombre de grupo y
  predicción por envío y día.

## Particionamiento

Con la infraestructura actual (un solo nodo) no se activa el sharding. Si el
volumen lo requiere:

- `mensajes`: clave `{ conversacion_id: "hashed" }`. Tiene alta cardinalidad,
  baja frecuencia y no crece de forma monótona. Usar `fecha` como clave
  concentraría todas las escrituras nuevas en el último chunk.
- `alertas`: clave `{ sensor_id: "hashed" }`.
- `incidentes`, `reportes`, `grupos_trabajo` y `predicciones_riesgo`: volumen
  bajo; alcanza con un replica set.

## Pendiente de acordar con el grupo

- Convención de los estados: en MongoDB están en minúscula (`abierto`) y en el
  modelo de Redis en mayúscula (`ACTIVA`). Hay que elegir una.
- Umbrales que disparan cada tipo de alerta.
- Lista definitiva de tipos de reporte.
