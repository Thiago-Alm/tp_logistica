-- ============================================================================
-- 01_schema.sql
-- Base de datos: PostgreSQL 16
-- Plataforma de Logística Internacional y Monitoreo IoT
--
-- Contiene las 17 tablas relacionales y transaccionales del sistema,
-- respetando estrictamente las decisiones de diseño de docs/decisiones.md:
--   - D1 / D17: Enums como restricciones CHECK
--   - D5: Tramo como tabla propia con FKs a envio, vehiculo, origen y destino
--   - D7: fecha_llegada_estimada se deriva de los tramos (no denormalizada en envio)
--   - D8: codigo_iso de contenedor validado en 11 caracteres (ISO 6346) y UNIQUE
--   - D10: orden entero >= 1 en tramo con UNIQUE (envio_id, orden)
--   - D15: Dinero e importes en NUMERIC(12,2) (nunca FLOAT ni REAL)
--   - D16: tramo.vehiculo_id NOT NULL, tramo sin columna estado
-- ============================================================================

-- Extensión para generación de UUID v4 (PostgreSQL 16 lo incluye nativo)
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================================================
-- 1. TABLAS MAESTRAS Y DE ACTORES
-- ============================================================================

-- 1.1 Usuarios del sistema (para gestión de accesos y sesiones en Redis)
CREATE TABLE usuario (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nombre VARCHAR(100) NOT NULL,
    email VARCHAR(255) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    rol VARCHAR(50) NOT NULL,
    activo BOOLEAN NOT NULL DEFAULT TRUE,
    fecha_creacion TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_usuario_email UNIQUE (email),
    CONSTRAINT chk_usuario_rol CHECK (rol IN ('ADMINISTRADOR', 'OPERADOR', 'AUDITOR', 'CLIENTE'))
);

-- 1.2 Clientes (solicitantes de envíos)
CREATE TABLE cliente (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cuit VARCHAR(20) NOT NULL,
    razon_social VARCHAR(150) NOT NULL,
    email VARCHAR(255) NOT NULL,
    telefono VARCHAR(50),
    direccion VARCHAR(255),
    activo BOOLEAN NOT NULL DEFAULT TRUE,
    fecha_creacion TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_cliente_cuit UNIQUE (cuit)
);

-- 1.3 Operadores logísticos (gestores de flota / vehículos - D11)
CREATE TABLE operador (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cuit VARCHAR(20) NOT NULL,
    nombre VARCHAR(150) NOT NULL,
    email VARCHAR(255) NOT NULL,
    telefono VARCHAR(50),
    activo BOOLEAN NOT NULL DEFAULT TRUE,
    fecha_creacion TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_operador_cuit UNIQUE (cuit)
);

-- 1.4 Proveedores (servicios portuarios, mantenimiento, etc. - D11)
CREATE TABLE proveedor (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cuit VARCHAR(20) NOT NULL,
    razon_social VARCHAR(150) NOT NULL,
    tipo_servicio VARCHAR(100) NOT NULL,
    email VARCHAR(255) NOT NULL,
    telefono VARCHAR(50),
    activo BOOLEAN NOT NULL DEFAULT TRUE,
    fecha_creacion TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_proveedor_cuit UNIQUE (cuit)
);

-- 1.5 Ubicaciones (puertos, aeropuertos, centros de distribución, almacenes)
CREATE TABLE ubicacion (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nombre VARCHAR(150) NOT NULL,
    tipo VARCHAR(50) NOT NULL,
    codigo_locode VARCHAR(10),
    ciudad VARCHAR(100) NOT NULL,
    pais VARCHAR(100) NOT NULL,
    latitud NUMERIC(9,6),
    longitud NUMERIC(9,6),
    activo BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT chk_ubicacion_tipo CHECK (tipo IN ('PUERTO', 'AEROPUERTO', 'CENTRO_DISTRIBUCION', 'ALMACEN', 'DEPOSITO_FISCAL'))
);

-- 1.6 Vehículos de transporte
CREATE TABLE vehiculo (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    operador_id UUID NOT NULL,
    patente VARCHAR(30) NOT NULL,
    tipo VARCHAR(50) NOT NULL,
    medio_transporte VARCHAR(20) NOT NULL,
    capacidad_peso_kg NUMERIC(10,2),
    capacidad_volumen_m3 NUMERIC(10,2),
    activo BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT uq_vehiculo_patente UNIQUE (patente),
    CONSTRAINT fk_vehiculo_operador FOREIGN KEY (operador_id) REFERENCES operador(id) ON DELETE RESTRICT,
    CONSTRAINT chk_vehiculo_tipo CHECK (tipo IN ('CAMION', 'BUQUE', 'AVION', 'TREN')),
    CONSTRAINT chk_vehiculo_medio CHECK (medio_transporte IN ('TERRESTRE', 'MARITIMO', 'AEREO'))
);

-- 1.7 Contenedores (unidades de carga - D1, D8)
CREATE TABLE contenedor (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    codigo_iso VARCHAR(11) NOT NULL,
    tipo VARCHAR(50) NOT NULL,
    capacidad NUMERIC(10,2) NOT NULL,
    estado VARCHAR(30) NOT NULL,
    fecha_alta TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_contenedor_codigo_iso UNIQUE (codigo_iso),
    CONSTRAINT chk_contenedor_codigo_iso_len CHECK (length(codigo_iso) = 11),
    CONSTRAINT chk_contenedor_capacidad_positiva CHECK (capacidad > 0),
    CONSTRAINT chk_contenedor_estado CHECK (estado IN ('DISPONIBLE', 'ASIGNADO', 'EN_TRANSITO', 'EN_MANTENIMIENTO', 'BAJA'))
);

-- 1.8 Sensores IoT (hardware montado en contenedores monitoreado en tiempo real)
CREATE TABLE sensor (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    contenedor_id UUID,
    numero_serie VARCHAR(50) NOT NULL,
    modelo VARCHAR(100) NOT NULL,
    tipo VARCHAR(50) NOT NULL,
    intervalo_reporte_segundos INT NOT NULL DEFAULT 60,
    estado VARCHAR(30) NOT NULL DEFAULT 'ACTIVO',
    fecha_instalacion TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_sensor_numero_serie UNIQUE (numero_serie),
    CONSTRAINT fk_sensor_contenedor FOREIGN KEY (contenedor_id) REFERENCES contenedor(id) ON DELETE SET NULL,
    CONSTRAINT chk_sensor_tipo CHECK (tipo IN ('TEMPERATURA', 'HUMEDAD', 'VIBRACION', 'GPS', 'MULTISENSOR')),
    CONSTRAINT chk_sensor_estado CHECK (estado IN ('ACTIVO', 'INACTIVO', 'MANTENIMIENTO', 'BAJA')),
    CONSTRAINT chk_sensor_intervalo CHECK (intervalo_reporte_segundos > 0)
);

-- 1.9 Tarifas de transporte (D15, D17)
CREATE TABLE tarifa (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    medio_transporte VARCHAR(20) NOT NULL,
    origen_id UUID,
    destino_id UUID,
    costo_base NUMERIC(12,2) NOT NULL,
    costo_por_km NUMERIC(12,2) NOT NULL DEFAULT 0.00,
    vigente_desde DATE NOT NULL,
    vigente_hasta DATE,
    activo BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT fk_tarifa_origen FOREIGN KEY (origen_id) REFERENCES ubicacion(id) ON DELETE RESTRICT,
    CONSTRAINT fk_tarifa_destino FOREIGN KEY (destino_id) REFERENCES ubicacion(id) ON DELETE RESTRICT,
    CONSTRAINT chk_tarifa_medio CHECK (medio_transporte IN ('TERRESTRE', 'MARITIMO', 'AEREO')),
    CONSTRAINT chk_tarifa_costo_base CHECK (costo_base >= 0),
    CONSTRAINT chk_tarifa_costo_km CHECK (costo_por_km >= 0),
    CONSTRAINT chk_tarifa_origen_destino CHECK (origen_id IS NULL OR destino_id IS NULL OR origen_id <> destino_id),
    CONSTRAINT chk_tarifa_vigencia CHECK (vigente_hasta IS NULL OR vigente_hasta >= vigente_desde)
);

-- ============================================================================
-- 2. OPERACIÓN LOGÍSTICA (ENVÍOS, TRAMOS Y ASIGNACIONES)
-- ============================================================================

-- 2.1 Envíos (D1, D4, D7)
CREATE TABLE envio (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cliente_id UUID NOT NULL,
    origen_id UUID NOT NULL,
    destino_id UUID NOT NULL,
    estado VARCHAR(30) NOT NULL,
    prioridad VARCHAR(20) NOT NULL,
    fecha_creacion TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    fecha_llegada_real TIMESTAMPTZ,
    CONSTRAINT fk_envio_cliente FOREIGN KEY (cliente_id) REFERENCES cliente(id) ON DELETE RESTRICT,
    CONSTRAINT fk_envio_origen FOREIGN KEY (origen_id) REFERENCES ubicacion(id) ON DELETE RESTRICT,
    CONSTRAINT fk_envio_destino FOREIGN KEY (destino_id) REFERENCES ubicacion(id) ON DELETE RESTRICT,
    CONSTRAINT chk_envio_estado CHECK (estado IN ('CREADO', 'EN_TRANSITO', 'EN_PUERTO', 'ENTREGADO', 'CANCELADO')),
    CONSTRAINT chk_envio_prioridad CHECK (prioridad IN ('BAJA', 'MEDIA', 'ALTA')),
    CONSTRAINT chk_envio_origen_destino CHECK (origen_id <> destino_id),
    CONSTRAINT chk_envio_llegada_segun_estado CHECK (
        (estado = 'ENTREGADO' AND fecha_llegada_real IS NOT NULL) OR
        (estado <> 'ENTREGADO' AND fecha_llegada_real IS NULL)
    ),
    CONSTRAINT chk_envio_llegada_posterior_creacion CHECK (
        fecha_llegada_real IS NULL OR fecha_llegada_real >= fecha_creacion
    )
);

-- 2.2 Tramos de un envío (D5, D6, D10, D15, D16, D17)
CREATE TABLE tramo (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    envio_id UUID NOT NULL,
    vehiculo_id UUID NOT NULL,
    medio_transporte VARCHAR(20) NOT NULL,
    origen_id UUID NOT NULL,
    destino_id UUID NOT NULL,
    orden INT NOT NULL,
    fecha_salida TIMESTAMPTZ NOT NULL,
    fecha_llegada_estimada TIMESTAMPTZ NOT NULL,
    costo NUMERIC(12,2) NOT NULL,
    fecha_llegada_real TIMESTAMPTZ,
    CONSTRAINT uq_tramo_envio_orden UNIQUE (envio_id, orden),
    CONSTRAINT fk_tramo_envio FOREIGN KEY (envio_id) REFERENCES envio(id) ON DELETE CASCADE,
    CONSTRAINT fk_tramo_vehiculo FOREIGN KEY (vehiculo_id) REFERENCES vehiculo(id) ON DELETE RESTRICT,
    CONSTRAINT fk_tramo_origen FOREIGN KEY (origen_id) REFERENCES ubicacion(id) ON DELETE RESTRICT,
    CONSTRAINT fk_tramo_destino FOREIGN KEY (destino_id) REFERENCES ubicacion(id) ON DELETE RESTRICT,
    CONSTRAINT chk_tramo_orden CHECK (orden >= 1),
    CONSTRAINT chk_tramo_medio CHECK (medio_transporte IN ('TERRESTRE', 'MARITIMO', 'AEREO')),
    CONSTRAINT chk_tramo_costo CHECK (costo >= 0),
    CONSTRAINT chk_tramo_origen_destino CHECK (origen_id <> destino_id),
    CONSTRAINT chk_tramo_estimada_posterior_salida CHECK (fecha_llegada_estimada >= fecha_salida),
    CONSTRAINT chk_tramo_real_posterior_salida CHECK (fecha_llegada_real IS NULL OR fecha_llegada_real >= fecha_salida)
);

-- 2.3 Asociación Envio - Contenedor (Relación N:M)
CREATE TABLE envio_contenedor (
    envio_id UUID NOT NULL,
    contenedor_id UUID NOT NULL,
    fecha_asignacion TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT pk_envio_contenedor PRIMARY KEY (envio_id, contenedor_id),
    CONSTRAINT fk_ec_envio FOREIGN KEY (envio_id) REFERENCES envio(id) ON DELETE CASCADE,
    CONSTRAINT fk_ec_contenedor FOREIGN KEY (contenedor_id) REFERENCES contenedor(id) ON DELETE RESTRICT
);

-- ============================================================================
-- 3. FACTURACIÓN Y FINANZAS (D14, D15)
-- ============================================================================

-- 3.1 Facturas
CREATE TABLE factura (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cliente_id UUID NOT NULL,
    envio_id UUID,
    numero_factura VARCHAR(50) NOT NULL,
    fecha_emision TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    fecha_vencimiento TIMESTAMPTZ NOT NULL,
    importe_total NUMERIC(12,2) NOT NULL,
    estado VARCHAR(30) NOT NULL DEFAULT 'EMITIDA',
    CONSTRAINT uq_factura_numero UNIQUE (numero_factura),
    CONSTRAINT fk_factura_cliente FOREIGN KEY (cliente_id) REFERENCES cliente(id) ON DELETE RESTRICT,
    CONSTRAINT fk_factura_envio FOREIGN KEY (envio_id) REFERENCES envio(id) ON DELETE SET NULL,
    CONSTRAINT chk_factura_importe CHECK (importe_total >= 0),
    CONSTRAINT chk_factura_estado CHECK (estado IN ('EMITIDA', 'PAGADA', 'ANULADA', 'VENCIDA')),
    CONSTRAINT chk_factura_fechas CHECK (fecha_vencimiento >= fecha_emision)
);

-- 3.2 Pagos de clientes
CREATE TABLE pago (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    factura_id UUID NOT NULL,
    cliente_id UUID NOT NULL,
    monto NUMERIC(12,2) NOT NULL,
    medio_pago VARCHAR(50) NOT NULL,
    fecha_pago TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    referencia_transaccion VARCHAR(100),
    CONSTRAINT fk_pago_factura FOREIGN KEY (factura_id) REFERENCES factura(id) ON DELETE RESTRICT,
    CONSTRAINT fk_pago_cliente FOREIGN KEY (cliente_id) REFERENCES cliente(id) ON DELETE RESTRICT,
    CONSTRAINT chk_pago_monto CHECK (monto > 0),
    CONSTRAINT chk_pago_medio CHECK (medio_pago IN ('TRANSFERENCIA', 'TARJETA', 'EFECTIVO', 'CHEQUE'))
);

-- 3.3 Cuenta corriente por cliente
CREATE TABLE cuenta_corriente (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cliente_id UUID NOT NULL,
    saldo NUMERIC(12,2) NOT NULL DEFAULT 0.00,
    limite_credito NUMERIC(12,2) NOT NULL DEFAULT 0.00,
    fecha_apertura TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    fecha_actualizacion TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_cuenta_corriente_cliente UNIQUE (cliente_id),
    CONSTRAINT fk_cc_cliente FOREIGN KEY (cliente_id) REFERENCES cliente(id) ON DELETE RESTRICT,
    CONSTRAINT chk_cc_limite CHECK (limite_credito >= 0)
);

-- 3.4 Movimientos de cuenta corriente
CREATE TABLE movimiento_cuenta (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cuenta_corriente_id UUID NOT NULL,
    factura_id UUID,
    pago_id UUID,
    tipo VARCHAR(20) NOT NULL,
    monto NUMERIC(12,2) NOT NULL,
    descripcion VARCHAR(255) NOT NULL,
    fecha TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_mc_cuenta FOREIGN KEY (cuenta_corriente_id) REFERENCES cuenta_corriente(id) ON DELETE RESTRICT,
    CONSTRAINT fk_mc_factura FOREIGN KEY (factura_id) REFERENCES factura(id) ON DELETE SET NULL,
    CONSTRAINT fk_mc_pago FOREIGN KEY (pago_id) REFERENCES pago(id) ON DELETE SET NULL,
    CONSTRAINT chk_mc_tipo CHECK (tipo IN ('DEBITO', 'CREDITO')),
    CONSTRAINT chk_mc_monto CHECK (monto > 0)
);

-- ============================================================================
-- 4. SINCRONIZACIÓN POLÍGLOTA (OUTBOX PATTERN)
-- ============================================================================

-- 4.1 Outbox transaccional para propagación a Neo4j, MongoDB y Redis
CREATE TABLE outbox (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agregado_tipo VARCHAR(50) NOT NULL,
    agregado_id UUID NOT NULL,
    evento_tipo VARCHAR(50) NOT NULL,
    payload JSONB NOT NULL,
    fecha_creacion TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    procesado BOOLEAN NOT NULL DEFAULT FALSE,
    fecha_procesado TIMESTAMPTZ,
    error_mensaje TEXT,
    reintentos INT NOT NULL DEFAULT 0,
    CONSTRAINT chk_outbox_reintentos CHECK (reintentos >= 0)
);

-- ============================================================================
-- 5. ÍNDICES DE OPTIMIZACIÓN (REPORTES OPERATIVOS Y ANALÍTICOS)
-- ============================================================================

-- Reporte: Envíos por fecha de creación (rango parametrizado)
CREATE INDEX idx_envio_fecha_creacion ON envio (fecha_creacion);

-- Reporte: Envíos por estado (ConteoEnviosPorEstado)
CREATE INDEX idx_envio_estado_fecha ON envio (estado, fecha_creacion);

-- Reporte: Envíos por cliente (ConteoEnviosPorCliente)
CREATE INDEX idx_envio_cliente_fecha ON envio (cliente_id, fecha_creacion);

-- Reporte: Envíos por país destino (ConteoEnviosPorPais via destino_id -> ubicacion.pais)
CREATE INDEX idx_envio_destino_id ON envio (destino_id);
CREATE INDEX idx_ubicacion_pais ON ubicacion (pais);

-- Reporte: Tiempos de envío por cliente y tiempo promedio de entrega (solo ENTREGADO)
CREATE INDEX idx_envio_entregados_tiempos ON envio (cliente_id, fecha_creacion, fecha_llegada_real)
    WHERE estado = 'ENTREGADO';

CREATE INDEX idx_envio_entregados_promedio ON envio (fecha_creacion, fecha_llegada_real)
    WHERE estado = 'ENTREGADO';

-- Reporte / Consulta: Envíos demorados (D7)
-- Filtra envíos no entregados ni cancelados con llegada estimada vencida en tramos
CREATE INDEX idx_envio_activos ON envio (estado)
    WHERE estado NOT IN ('ENTREGADO', 'CANCELADO');

CREATE INDEX idx_tramo_envio_estimada ON tramo (envio_id, fecha_llegada_estimada);

-- Reporte: Ranking de clientes por volumen transportado (sumando capacidad de contenedores)
CREATE INDEX idx_ec_envio ON envio_contenedor (envio_id);
CREATE INDEX idx_ec_contenedor ON envio_contenedor (contenedor_id);

-- Reporte: Costos por tipo de transporte (D5, D17)
CREATE INDEX idx_tramo_medio_costo ON tramo (medio_transporte, costo);

-- Índices de navegación operativa
CREATE INDEX idx_tramo_vehiculo ON tramo (vehiculo_id);
CREATE INDEX idx_tramo_origen ON tramo (origen_id);
CREATE INDEX idx_tramo_destino ON tramo (destino_id);
CREATE INDEX idx_sensor_contenedor ON sensor (contenedor_id);
CREATE INDEX idx_vehiculo_operador ON vehiculo (operador_id);
CREATE INDEX idx_factura_cliente_estado ON factura (cliente_id, estado);
CREATE INDEX idx_pago_factura ON pago (factura_id);
CREATE INDEX idx_mc_cuenta ON movimiento_cuenta (cuenta_corriente_id);

-- Índice parcial de eventos pendientes de sincronización en Outbox
CREATE INDEX idx_outbox_pendientes ON outbox (fecha_creacion)
    WHERE NOT procesado;
