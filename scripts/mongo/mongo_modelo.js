// =====================================================================
// MongoDB - Modelo fisico | TP Persistencia Poliglota (Logistica IoT)
// Ejecutar:  mongosh --file mongo_modelo.js     (o pegar en MongoSH de Compass)
//
// Convenciones (acordadas para todas las bases):
//  - Nombres en espanol, snake_case, sin tildes.
//  - Todo id es UUID (binData subtipo 4): _id propio y toda referencia a
//    entidades de otras bases (envio_id, contenedor_id, sensor_id, cliente_id,
//    usuario_id). MongoDB NO es dueno de esas entidades: solo las referencia.
//  - Fechas en UTC (tipo date).
//  - Valores de enum en MAYUSCULAS, iguales en los cinco motores (D19):
//    el mismo estado se escribe igual en Postgres, Mongo, Cassandra y el dominio.
//  - IMPORTANTE en la app: configurar el driver con UUID estandar
//    (Python: uuidRepresentation="standard" | Java: UuidRepresentation.STANDARD),
//    si no los UUID se guardan con otro subtipo y no coinciden con las otras bases.
//
// Que vive aca (y por que): datos con estructura variable o anidada, con
// consultas variadas y agregaciones ($group): incidentes, alertas, chat,
// grupos, reportes y predicciones. Lo masivo y append-only va a Cassandra.
// =====================================================================

db = db.getSiblingDB("logistica");

// Crea la coleccion con su validador, o actualiza el validador si ya existe
// (el script se puede correr mas de una vez sin romper nada).
function crearColeccion(nombre, jsonSchema) {
  if (db.getCollectionNames().includes(nombre)) {
    db.runCommand({ collMod: nombre, validator: { $jsonSchema: jsonSchema }, validationLevel: "strict", validationAction: "error" });
  } else {
    db.createCollection(nombre, { validator: { $jsonSchema: jsonSchema }, validationLevel: "strict", validationAction: "error" });
  }
}

// ---------------------------------------------------------------------
// 1) incidentes
//  Relaciones: referencia por UUID a envio, contenedor (Postgres).
//  contexto_envio = SNAPSHOT embebido (cliente, paises, ruta) tomado al crear
//  el incidente: permite "promedio de incidentes por pais/cliente" y
//  "ranking de rutas con mas incidentes" con un solo aggregate, sin cruzar bases.
//  historial_estados embebido: se lee siempre junto al incidente.
// ---------------------------------------------------------------------
crearColeccion("incidentes", {
  bsonType: "object",
  required: ["_id", "envio_id", "tipo", "severidad", "estado", "descripcion", "fecha", "contexto_envio"],
  properties: {
    _id: { bsonType: "binData" },
    envio_id: { bsonType: "binData" },
    contenedor_id: { bsonType: ["binData", "null"] },
    tipo: { enum: ["DEMORA", "DANO_CARGA", "TEMPERATURA", "ROBO", "ADUANA", "ACCIDENTE", "OTRO"] },
    severidad: { enum: ["BAJA", "MEDIA", "ALTA", "CRITICA"] },
    estado: { enum: ["ABIERTO", "EN_ANALISIS", "RESUELTO", "CERRADO"] },
    descripcion: { bsonType: "string", minLength: 1 },
    fecha: { bsonType: "date" },
    contexto_envio: {
      bsonType: "object",
      required: ["cliente_id", "pais_origen", "pais_destino", "ruta"],
      properties: {
        cliente_id: { bsonType: "binData" },
        origen: { bsonType: "string" },
        destino: { bsonType: "string" },
        pais_origen: { bsonType: "string" },
        pais_destino: { bsonType: "string" },
        ruta: { bsonType: "string" }            // ej: "ARBUE->NLRTM" (codigos LOCODE de ubicacion)
      }
    },
    historial_estados: {
      bsonType: "array",
      items: {
        bsonType: "object",
        required: ["estado", "fecha"],
        properties: { estado: { bsonType: "string" }, fecha: { bsonType: "date" }, usuario_id: { bsonType: ["binData", "null"] } }
      }
    }
  }
});
db.incidentes.createIndex({ estado: 1, fecha: -1 });                 // reporte "incidentes abiertos"
db.incidentes.createIndex({ envio_id: 1, fecha: -1 });               // incidentes de un envio
db.incidentes.createIndex({ "contexto_envio.cliente_id": 1 });       // promedio por cliente
db.incidentes.createIndex({ "contexto_envio.pais_origen": 1 });      // promedio por pais
db.incidentes.createIndex({ "contexto_envio.ruta": 1 });             // ranking de rutas

// ---------------------------------------------------------------------
// 2) alertas
//  Las genera la app al detectar una anomalia en una lectura (que vive en
//  Cassandra). _id DETERMINISTICO (uuid5 de sensor_id + ts + tipo) para que si
//  el proceso se reintenta no se dupliquen alertas (idempotencia).
// ---------------------------------------------------------------------
crearColeccion("alertas", {
  bsonType: "object",
  required: ["_id", "tipo", "sensor_id", "estado", "severidad", "fecha"],
  properties: {
    _id: { bsonType: "binData" },
    tipo: { enum: ["TEMPERATURA", "HUMEDAD", "VIBRACION", "BATERIA", "INACTIVIDAD", "GEOCERCA"] },
    sensor_id: { bsonType: "binData" },
    contenedor_id: { bsonType: ["binData", "null"] },
    envio_id: { bsonType: ["binData", "null"] },
    evento_id: { bsonType: ["binData", "null"] },
    estado: { enum: ["ABIERTA", "RECONOCIDA", "CERRADA"] },
    severidad: { enum: ["BAJA", "MEDIA", "ALTA", "CRITICA"] },
    fecha: { bsonType: "date" },
    detalle: {                                  // valor leido vs umbral que se violo
      bsonType: "object",
      properties: { valor: { bsonType: "number" }, umbral: { bsonType: "number" }, momento_lectura: { bsonType: "date" } }
    }
  }
});
db.alertas.createIndex({ estado: 1, fecha: -1 });
db.alertas.createIndex({ sensor_id: 1, fecha: -1 });
db.alertas.createIndex({ envio_id: 1, fecha: -1 });

// ---------------------------------------------------------------------
// 3) conversaciones + 4) mensajes (mensajeria con las partes)
//  El enunciado pide "Servicio de Mensajeria con las partes (Cliente -
//  Proveedores - Operadores Logisticos)", asi que una conversacion es un hilo
//  entre la empresa y UNA parte, identificada como en la cuenta corriente:
//  parte_tipo + parte_id (D41). El modelo anterior era un chat entre usuarios
//  (PRIVADA/GRUPAL), que no cubria a proveedores ni operadores porque no
//  tienen usuarios en el modelo.
//  Se conserva la decision estructural original: los mensajes REFERENCIAN la
//  conversacion en vez de ir embebidos, porque crecen sin limite y embeberlos
//  pasaria el limite de 16 MB por documento.
//  envio_id opcional: el hilo puede ser sobre un envio puntual o general.
// ---------------------------------------------------------------------
crearColeccion("conversaciones", {
  bsonType: "object",
  required: ["_id", "parte_tipo", "parte_id", "asunto", "estado", "creada_en"],
  properties: {
    _id: { bsonType: "binData" },
    parte_tipo: { enum: ["CLIENTE", "PROVEEDOR", "OPERADOR"] },
    parte_id: { bsonType: "binData" },
    asunto: { bsonType: "string", minLength: 1 },
    envio_id: { bsonType: ["binData", "null"] },
    estado: { enum: ["ABIERTA", "CERRADA"] },
    creada_en: { bsonType: "date" },
    actividad: { bsonType: "date" },
    sin_leer: { bsonType: "int", minimum: 0 }
  }
});
db.conversaciones.createIndex({ actividad: -1 });                      // listado por actividad reciente
db.conversaciones.createIndex({ parte_id: 1, actividad: -1 });         // "los hilos de este cliente"
db.conversaciones.createIndex({ envio_id: 1 });                        // "los hilos de este envio"
db.conversaciones.createIndex({ sin_leer: 1 });                        // bandeja de pendientes

crearColeccion("mensajes", {
  bsonType: "object",
  required: ["_id", "conversacion_id", "autor", "cuerpo", "fecha"],
  properties: {
    _id: { bsonType: "binData" },
    conversacion_id: { bsonType: "binData" },
    autor: { enum: ["INTERNO", "PARTE"] },
    autor_id: { bsonType: ["binData", "null"] },   // el usuario, cuando es INTERNO
    cuerpo: { bsonType: "string", minLength: 1, maxLength: 2000 },
    fecha: { bsonType: "date" },
    leido: { bsonType: "bool" }
  }
});
db.mensajes.createIndex({ conversacion_id: 1, fecha: 1 });   // el hilo, como se escribio

// ---------------------------------------------------------------------
// 6) reportes (solicitud de reportes parametrizados y facturables)
//  Los parametros cambian segun el reporte -rango de fechas, limite, eje- asi
//  que en una tabla serian una columna por parametro casi siempre en NULL, o
//  una columna JSON, que es un documento disfrazado. Documental.
//
//  Quien lo PIDE (usuario_id) y a quien se le FACTURA (titular_tipo +
//  titular_id) son distintos: un operador de la empresa puede pedir un reporte
//  para facturarselo a un cliente. El titular se identifica igual que en la
//  cuenta corriente (D41), porque es ahi donde se imputa.
//
//  El estado sigue el ciclo del PEDIDO, no el de un archivo: SOLICITADA (se
//  pidio y se cotizo), GENERADA (se calculo), FACTURADA (se emitio la factura)
//  y CANCELADA. No hay "formato": no se exporta a PDF ni a CSV, el resultado se
//  muestra en pantalla, y declarar un campo que nadie escribe seria prometer
//  algo que el sistema no hace.
// ---------------------------------------------------------------------
crearColeccion("reportes", {
  bsonType: "object",
  required: ["_id", "tipo", "usuario_id", "titular_tipo", "titular_id",
             "costo", "estado", "fecha_solicitud"],
  properties: {
    _id: { bsonType: "binData" },
    tipo: { enum: ["ENVIOS_POR_PAIS", "ENVIOS_POR_ESTADO", "ENVIOS_POR_CLIENTE",
                   "ENVIOS_DEMORADOS", "INCIDENTES_ABIERTOS", "TIEMPOS_POR_CLIENTE",
                   "TIEMPO_PROMEDIO_ENTREGA", "RANKING_CLIENTES_VOLUMEN",
                   "COSTOS_POR_TRANSPORTE", "RANKING_RUTAS_INCIDENTES",
                   "PROMEDIO_INCIDENTES"] },
    usuario_id: { bsonType: "binData" },
    titular_tipo: { enum: ["CLIENTE", "PROVEEDOR", "OPERADOR"] },
    titular_id: { bsonType: "binData" },
    // string y no decimal/double: el driver no guarda Decimal sin configurarlo
    // y un float perderia centavos (D15).
    costo: { bsonType: "string" },
    parametros: { bsonType: "object" },
    estado: { enum: ["SOLICITADA", "GENERADA", "FACTURADA", "CANCELADA"] },
    fecha_solicitud: { bsonType: "date" },
    fecha_generacion: { bsonType: ["date", "null"] },
    filas: { bsonType: ["int", "null"] },
    factura_id: { bsonType: ["binData", "null"] }
  }
});
db.reportes.createIndex({ titular_id: 1, fecha_solicitud: -1 });   // "los reportes de este cliente"
db.reportes.createIndex({ usuario_id: 1, fecha_solicitud: -1 });   // quien los pidio
db.reportes.createIndex({ estado: 1 });                            // pendientes de generar / de facturar

// ---------------------------------------------------------------------
// COLECCIONES QUE SE SACARON, Y POR QUE
//
//  grupos_trabajo: era parte del chat entre usuarios (conversaciones
//    PRIVADA/GRUPAL). El enunciado pide mensajeria con las PARTES -clientes,
//    proveedores, operadores- y esos no tienen usuarios en el modelo, asi que
//    el chat entre usuarios se reemplazo (D57) y los grupos quedaron sin nada
//    que agrupar.
//
//  predicciones_riesgo: guardaba una prediccion por envio y por dia. La
//    prediccion de atrasos (D55) se calcula al consultar y NO se persiste, por
//    la misma razon que la fecha de llegada estimada no se guarda en `envio`
//    (D7): es un valor derivado, y guardarlo obligaria a recalcularlo cada vez
//    que cambia un tramo o aparece un incidente. Ademas el esquema pedia
//    probabilidades de 0 a 1 y un "modelo", que supone un entrenamiento que
//    este sistema no hace a proposito: lo que hay es un puntaje explicable.
//
//  Las dos estaban declaradas y vacias. Una coleccion que nadie escribe es una
//  promesa que el sistema no cumple, asi que se saca del modelo.
// ---------------------------------------------------------------------

// =====================================================================
// PARTICIONAMIENTO (documentado; en el Docker de un solo nodo no se activa)
//  - mensajes:  shard key { conversacion_id: "hashed" }  -> alta cardinalidad, baja
//    frecuencia, sin monotonia. Usar "fecha" como shard key seria monotono: todas
//    las escrituras nuevas caerian en el ultimo chunk.
//    (para fragmentar hace falta un indice hashed sobre conversacion_id).
//  - alertas:   shard key { sensor_id: "hashed" }.
//  - incidentes, reportes, conversaciones: volumen bajo;
//    alcanza con un replica set (primario + secundarios), sin sharding.
// =====================================================================

// ---------------------------------------------------------------------
// DATOS DE PRUEBA minimos (upsert: se puede correr varias veces)
// ---------------------------------------------------------------------
var ID_ENVIO = UUID("a0000000-0000-0000-0000-000000000001");
var ID_CLIENTE = UUID("20000000-0000-0000-0000-000000000001");
var ID_SENSOR = UUID("80000000-0000-0000-0000-000000000001");
var ID_CONT = UUID("70000000-0000-0000-0000-000000000001");
var ID_USR_A = UUID("10000000-0000-0000-0000-000000000001");
var ID_USR_B = UUID("10000000-0000-0000-0000-000000000002");
var ID_CONV = UUID("ffffffff-0000-4000-8000-000000000001");

db.incidentes.replaceOne({ _id: UUID("b0000000-0000-4000-8000-000000000001") }, {
  _id: UUID("b0000000-0000-4000-8000-000000000001"), envio_id: ID_ENVIO, contenedor_id: ID_CONT,
  tipo: "DEMORA", severidad: "MEDIA", estado: "ABIERTO", descripcion: "Retraso en aduana", fecha: new Date(),
  contexto_envio: { cliente_id: ID_CLIENTE, origen: "ARBUE", destino: "NLRTM", pais_origen: "Argentina", pais_destino: "Holanda", ruta: "ARBUE->NLRTM" },
  historial_estados: [{ estado: "ABIERTO", fecha: new Date(), usuario_id: ID_USR_A }]
}, { upsert: true });

db.incidentes.replaceOne({ _id: UUID("b0000000-0000-4000-8000-000000000002") }, {
  _id: UUID("b0000000-0000-4000-8000-000000000002"), envio_id: ID_ENVIO, contenedor_id: null,
  tipo: "TEMPERATURA", severidad: "ALTA", estado: "CERRADO", descripcion: "Pico de temperatura", fecha: new Date(),
  contexto_envio: { cliente_id: ID_CLIENTE, origen: "ARBUE", destino: "NLRTM", pais_origen: "Argentina", pais_destino: "Holanda", ruta: "ARBUE->NLRTM" }
}, { upsert: true });

db.alertas.replaceOne({ _id: UUID("a0000000-0000-4000-8000-000000000001") }, {
  _id: UUID("a0000000-0000-4000-8000-000000000001"), tipo: "TEMPERATURA", sensor_id: ID_SENSOR, contenedor_id: ID_CONT,
  envio_id: ID_ENVIO, estado: "ABIERTA", severidad: "ALTA", fecha: new Date(),
  detalle: { valor: 12.5, umbral: 8.0, momento_lectura: new Date() }
}, { upsert: true });

db.conversaciones.replaceOne({ _id: ID_CONV }, {
  _id: ID_CONV, tipo: "PRIVADA", participantes: [ID_USR_A, ID_USR_B],
  clave_participantes: "10000000-0000-0000-0000-000000000001:10000000-0000-0000-0000-000000000002",
  creada_en: new Date(), ultimo_mensaje: { fecha: new Date(), resumen: "Hola" }
}, { upsert: true });

db.mensajes.replaceOne({ _id: UUID("a1000000-0000-4000-8000-000000000001") }, {
  _id: UUID("a1000000-0000-4000-8000-000000000001"), conversacion_id: ID_CONV, remitente_id: ID_USR_A,
  contenido: "Hola, ya salio el contenedor", fecha: new Date(), leido_por: [ID_USR_A]
}, { upsert: true });

// ---------------------------------------------------------------------
// CONSULTAS DE VERIFICACION (descomentar para probar)
// ---------------------------------------------------------------------
// db.incidentes.find({ estado: "ABIERTO" }).sort({ fecha: -1 })
// db.incidentes.aggregate([ { $group: { _id: "$contexto_envio.pais_origen", total: { $sum: 1 } } } ])
// db.incidentes.aggregate([ { $group: { _id: "$contexto_envio.ruta", total: { $sum: 1 } } }, { $sort: { total: -1 } }, { $limit: 5 } ])
// db.mensajes.find({ conversacion_id: ID_CONV }).sort({ fecha: -1 }).limit(20)
// db.alertas.find({ sensor_id: ID_SENSOR, estado: "ABIERTA" })
// db.incidentes.find({ estado: "ABIERTO" }).explain("executionStats")   // debe decir IXSCAN
