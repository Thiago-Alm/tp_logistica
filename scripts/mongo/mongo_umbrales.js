// =====================================================================
// MongoDB - Coleccion de umbrales configurados (D25)
// Ejecutar:  mongosh --file mongo_umbrales.js
//
// Guarda, por tipo de contenedor y magnitud, el rango normal de una lectura.
// La deteccion de anomalias lee el umbral ACA y, si una lectura lo viola,
// crea una alerta que guarda el umbral violado (alertas.detalle.umbral) como
// foto del momento: si el umbral cambia despues, la alerta no se modifica.
//
// Convenciones: valores en MAYUSCULAS (D19), id UUID, nombres en espanol.
// El script es idempotente: se puede correr varias veces.
// =====================================================================

db = db.getSiblingDB("logistica");

const esquema = {
  bsonType: "object",
  required: ["_id", "tipo_contenedor", "magnitud", "minimo", "maximo", "unidad"],
  properties: {
    _id: { bsonType: "binData" },
    // IMPORTANTE: copiar aca los valores del CHECK de contenedor.tipo (D1).
    // El dominio es la fuente de verdad; este enum solo lo repite.
    tipo_contenedor: {
      // Los siete tipos que admite chk_contenedor_tipo en PostgreSQL. Si
      // aparece uno nuevo alla, tiene que aparecer aca tambien o su umbral
      // no se puede cargar.
      enum: ["DRY_20", "DRY_40", "REEFER_20", "REEFER_40",
             "OPEN_TOP_40", "TANK_20", "FLAT_RACK_40"],
    },
    magnitud: { enum: ["TEMPERATURA", "HUMEDAD", "VIBRACION"] },
    minimo: { bsonType: "number" },
    maximo: { bsonType: "number" },
    unidad: { bsonType: "string", minLength: 1 },
    descripcion: { bsonType: "string" }
  }
};

// $jsonSchema valida tipos y valores; $expr agrega la regla minimo < maximo.
const validador = { $and: [{ $jsonSchema: esquema }, { $expr: { $lt: ["$minimo", "$maximo"] } }] };

if (db.getCollectionNames().includes("umbrales")) {
  db.runCommand({ collMod: "umbrales", validator: validador, validationLevel: "strict", validationAction: "error" });
} else {
  db.createCollection("umbrales", { validator: validador, validationLevel: "strict", validationAction: "error" });
}

// Un solo umbral por tipo de contenedor y magnitud
db.umbrales.createIndex({ tipo_contenedor: 1, magnitud: 1 }, { unique: true });

// ---------------------------------------------------------------------
// Datos semilla: un umbral de temperatura por CADA tipo de contenedor.
//
// Tiene que estar completo. Si falta el umbral de un tipo, la deteccion de
// anomalias no evalua esas lecturas: las guarda en Cassandra pero nunca genera
// una alerta, y lo hace en silencio. Por eso el script cubre los siete tipos
// que admite el CHECK de PostgreSQL, aunque algunos todavia no se usen.
//
// Los rangos son de demostracion y se justifican por el tipo de carga:
//  - REEFER:    carga refrigerada o congelada, rango estrecho y bajo cero.
//  - DRY:       carga seca, tolera el rango ambiente amplio.
//  - TANK:      liquidos a granel, no pueden congelarse ni sobrecalentarse.
//  - OPEN_TOP y FLAT_RACK: carga expuesta, el rango mas amplio de todos.
// ---------------------------------------------------------------------
const UMBRALES = [
  ["e1000000-0000-4000-8000-000000000001", "REEFER_40",    -25.0, -15.0, "Carga congelada"],
  ["e1000000-0000-4000-8000-000000000002", "DRY_20",         0.0,  40.0, "Carga seca (electronica)"],
  ["e1000000-0000-4000-8000-000000000003", "REEFER_20",     -5.0,   8.0, "Carga refrigerada (fruta, farmacia)"],
  ["e1000000-0000-4000-8000-000000000004", "DRY_40",         0.0,  40.0, "Carga seca general"],
  ["e1000000-0000-4000-8000-000000000005", "TANK_20",        5.0,  35.0, "Liquidos a granel"],
  ["e1000000-0000-4000-8000-000000000006", "OPEN_TOP_40",  -10.0,  50.0, "Carga expuesta"],
  ["e1000000-0000-4000-8000-000000000007", "FLAT_RACK_40", -10.0,  50.0, "Carga sobredimensionada"],
];

for (const [id, tipo, minimo, maximo, descripcion] of UMBRALES) {
  db.umbrales.replaceOne(
    { _id: UUID(id) },
    {
      _id: UUID(id),
      tipo_contenedor: tipo,
      magnitud: "TEMPERATURA",
      minimo: minimo,
      maximo: maximo,
      unidad: "C",
      descripcion: descripcion,
    },
    { upsert: true }
  );
}

// ---------------------------------------------------------------------
// Verificacion (descomentar)
// ---------------------------------------------------------------------
// db.umbrales.find({ tipo_contenedor: "REEFER_40", magnitud: "TEMPERATURA" })
// db.umbrales.find({ tipo_contenedor: "REEFER_40", magnitud: "TEMPERATURA" }).explain("executionStats")   // IXSCAN
// Debe FALLAR (minimo >= maximo):
// db.umbrales.insertOne({ _id: UUID(), tipo_contenedor: "DRY_20", magnitud: "HUMEDAD", minimo: 50, maximo: 10, unidad: "%" })
