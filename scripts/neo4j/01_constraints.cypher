// Identificadores únicos por etiqueta.
// IF NOT EXISTS permite volver a ejecutar el script.

CREATE CONSTRAINT cliente_id_unico IF NOT EXISTS
FOR (n:Cliente) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT operador_id_unico IF NOT EXISTS
FOR (n:Operador) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT ubicacion_id_unico IF NOT EXISTS
FOR (n:Ubicacion) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT contenedor_id_unico IF NOT EXISTS
FOR (n:Contenedor) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT envio_id_unico IF NOT EXISTS
FOR (n:Envio) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT vehiculo_id_unico IF NOT EXISTS
FOR (n:Vehiculo) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT tramo_id_unico IF NOT EXISTS
FOR (n:Tramo) REQUIRE n.id IS UNIQUE;