-- ============================================================================
-- 01_schema.sql
-- Base de datos: PostgreSQL 16
-- Plataforma de Logística Internacional y Monitoreo IoT
--
-- Autor original: Fran. Correcciones de Thiago (ver "CORRECCIONES" abajo).
--
-- Respeta las decisiones de docs/decisiones.md:
--   - D1 / D17: enums como restricciones CHECK
--   - D5: tramo como tabla propia con FKs a envio, vehiculo, origen y destino
--   - D7: fecha_llegada_estimada se deriva de los tramos (no va en envio)
--   - D8: codigo_iso de contenedor validado en 11 caracteres (ISO 6346) y UNIQUE
--   - D10: orden entero >= 1 en tramo con UNIQUE (envio_id, orden)
--   - D15: dinero e importes en NUMERIC(12,2) (nunca FLOAT ni REAL)
--   - D16: tramo.vehiculo_id NOT NULL, tramo sin columna estado
--   - D19: todos los valores de enum en MAYUSCULAS, igual en los cinco motores
--
-- CORRECCIONES aplicadas sobre la version original:
--   1. Se agrega la tabla ROL. El enunciado la lista como entidad propia
--      (ID Rol, Descripcion, Nivel de permisos) y pide "administracion de
--      usuarios y roles". Estaba resuelta como una columna VARCHAR en usuario,
--      lo que impedia administrarlos sin un ALTER TABLE.
--   2. usuario: se agregan cliente_id y apellido (el enunciado los lista) y
--      rol pasa a ser rol_id con FK a la tabla rol.
--   3. activo BOOLEAN -> estado VARCHAR con CHECK en todas las tablas que el
--      modelo acordado define con "estado" (D1). La baja logica es
--      estado = 'INACTIVO' (D20).
--   4. Se agrega pais a cliente, operador y proveedor (el enunciado lo lista).
--   5. operador.nombre -> razon_social, para unificar con cliente y proveedor.
--   6. vehiculo.patente -> identificacion: un buque o un avion no tienen patente.
--   7. factura, pago y cuenta_corriente pasan a titular_tipo + titular_id
--      (CLIENTE / PROVEEDOR / OPERADOR), segun el supuesto 4 del grupo, que se
--      apoya en la pagina 1 del enunciado: "facturacion, pagos y cuentas
--      corrientes de los clientes, proveedores y operadores logisticos".
--      Estaban limitadas a cliente_id, lo que hacia imposible ese requisito.
--   8. contenedor.tipo recibe su CHECK, como el resto de los campos tipo.
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================================================
-- 1. TABLAS MAESTRAS Y DE ACTORES
-- ============================================================================

-- 1.1 Clientes (solicitantes de envíos)
CREATE TABLE cliente (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cuit VARCHAR(20) NOT NULL,
    razon_social VARCHAR(150) NOT NULL,
    email VARCHAR(255) NOT NULL,
    telefono VARCHAR(50),
    direccion VARCHAR(255),
    pais VARCHAR(100) NOT NULL,
    estado VARCHAR(20) NOT NULL DEFAULT 'ACTIVO',
    fecha_creacion TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_cliente_cuit UNIQUE (cuit),
    CONSTRAINT chk_cliente_estado CHECK (estado IN ('ACTIVO', 'INACTIVO'))
);

-- 1.2 Roles del sistema (entidad del enunciado: ID, Descripción, Nivel de permisos)
CREATE TABLE rol (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    descripcion VARCHAR(100) NOT NULL,
    nivel_permisos INT NOT NULL,
    CONSTRAINT uq_rol_descripcion UNIQUE (descripcion),
    CONSTRAINT chk_rol_nivel CHECK (nivel_permisos BETWEEN 1 AND 100)
);

-- 1.3 Usuarios del sistema (las sesiones activas viven en Redis)
-- cliente_id es NULL para los usuarios internos (administrador, operador, auditor).
CREATE TABLE usuario (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cliente_id UUID,
    rol_id UUID NOT NULL,
    nombre VARCHAR(100) NOT NULL,
    apellido VARCHAR(100) NOT NULL,
    email VARCHAR(255) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    estado VARCHAR(20) NOT NULL DEFAULT 'ACTIVO',
    fecha_registro TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_usuario_email UNIQUE (email),
    CONSTRAINT fk_usuario_cliente FOREIGN KEY (cliente_id) REFERENCES cliente(id) ON DELETE RESTRICT,
    CONSTRAINT fk_usuario_rol FOREIGN KEY (rol_id) REFERENCES rol(id) ON DELETE RESTRICT,
    CONSTRAINT chk_usuario_estado CHECK (estado IN ('ACTIVO', 'INACTIVO'))
);

-- 1.4 Operadores logísticos (dueños de la flota de vehículos - D11)
CREATE TABLE operador (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cuit VARCHAR(20) NOT NULL,
    razon_social VARCHAR(150) NOT NULL,
    email VARCHAR(255) NOT NULL,
    telefono VARCHAR(50),
    pais VARCHAR(100) NOT NULL,
    estado VARCHAR(20) NOT NULL DEFAULT 'ACTIVO',
    fecha_creacion TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_operador_cuit UNIQUE (cuit),
    CONSTRAINT chk_operador_estado CHECK (estado IN ('ACTIVO', 'INACTIVO'))
);

-- 1.5 Proveedores (servicios portuarios, mantenimiento, combustible)
CREATE TABLE proveedor (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cuit VARCHAR(20) NOT NULL,
    razon_social VARCHAR(150) NOT NULL,
    tipo_servicio VARCHAR(100) NOT NULL,
    email VARCHAR(255) NOT NULL,
    telefono VARCHAR(50),
    pais VARCHAR(100) NOT NULL,
    estado VARCHAR(20) NOT NULL DEFAULT 'ACTIVO',
    fecha_creacion TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_proveedor_cuit UNIQUE (cuit),
    CONSTRAINT chk_proveedor_estado CHECK (estado IN ('ACTIVO', 'INACTIVO'))
);

-- 1.6 Ubicaciones (puertos, aeropuertos, centros de distribución, depósitos)
CREATE TABLE ubicacion (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nombre VARCHAR(150) NOT NULL,
    tipo VARCHAR(50) NOT NULL,
    codigo_locode VARCHAR(10),
    ciudad VARCHAR(100) NOT NULL,
    pais VARCHAR(100) NOT NULL,
    latitud NUMERIC(9,6),
    longitud NUMERIC(9,6),
    estado VARCHAR(20) NOT NULL DEFAULT 'ACTIVO',
    CONSTRAINT chk_ubicacion_tipo CHECK (tipo IN ('PUERTO', 'AEROPUERTO', 'CENTRO_DISTRIBUCION', 'ALMACEN', 'DEPOSITO_FISCAL')),
    CONSTRAINT chk_ubicacion_estado CHECK (estado IN ('ACTIVO', 'INACTIVO'))
);

-- 1.7 Vehículos de transporte
-- identificacion, no patente: un buque se identifica por IMO y un avión por matrícula.
CREATE TABLE vehiculo (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    operador_id UUID NOT NULL,
    identificacion VARCHAR(30) NOT NULL,
    tipo VARCHAR(50) NOT NULL,
    medio_transporte VARCHAR(20) NOT NULL,
    capacidad_peso_kg NUMERIC(12,2),
    capacidad_volumen_m3 NUMERIC(10,2),
    estado VARCHAR(30) NOT NULL DEFAULT 'ACTIVO',
    CONSTRAINT uq_vehiculo_identificacion UNIQUE (identificacion),
    CONSTRAINT fk_vehiculo_operador FOREIGN KEY (operador_id) REFERENCES operador(id) ON DELETE RESTRICT,
    CONSTRAINT chk_vehiculo_tipo CHECK (tipo IN ('CAMION', 'BUQUE', 'AVION', 'TREN')),
    CONSTRAINT chk_vehiculo_medio CHECK (medio_transporte IN ('TERRESTRE', 'MARITIMO', 'AEREO')),
    CONSTRAINT chk_vehiculo_estado CHECK (estado IN ('ACTIVO', 'INACTIVO', 'EN_MANTENIMIENTO'))
);

-- 1.8 Contenedores (unidades de carga - D1, D8)
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
    CONSTRAINT chk_contenedor_tipo CHECK (tipo IN ('DRY_20', 'DRY_40', 'REEFER_20', 'REEFER_40', 'OPEN_TOP_40', 'TANK_20', 'FLAT_RACK_40')),
    CONSTRAINT chk_contenedor_estado CHECK (estado IN ('DISPONIBLE', 'ASIGNADO', 'EN_TRANSITO', 'EN_MANTENIMIENTO', 'BAJA'))
);

-- 1.9 Sensores IoT montados en contenedores
-- intervalo_reporte_segundos: cada cuánto debe reportar. Lo usa la detección de
-- sensores inactivos (D13) para saber a partir de cuándo el silencio es anomalía.
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
    CONSTRAINT chk_sensor_estado CHECK (estado IN ('ACTIVO', 'INACTIVO', 'EN_MANTENIMIENTO', 'BAJA')),
    CONSTRAINT chk_sensor_intervalo CHECK (intervalo_reporte_segundos > 0)
);

-- 1.10 Tarifas de transporte (D15, D17)
CREATE TABLE tarifa (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    medio_transporte VARCHAR(20) NOT NULL,
    origen_id UUID,
    destino_id UUID,
    costo_base NUMERIC(12,2) NOT NULL,
    costo_por_km NUMERIC(12,2) NOT NULL DEFAULT 0.00,
    vigente_desde DATE NOT NULL,
    vigente_hasta DATE,
    estado VARCHAR(20) NOT NULL DEFAULT 'ACTIVO',
    CONSTRAINT fk_tarifa_origen FOREIGN KEY (origen_id) REFERENCES ubicacion(id) ON DELETE RESTRICT,
    CONSTRAINT fk_tarifa_destino FOREIGN KEY (destino_id) REFERENCES ubicacion(id) ON DELETE RESTRICT,
    CONSTRAINT chk_tarifa_medio CHECK (medio_transporte IN ('TERRESTRE', 'MARITIMO', 'AEREO')),
    CONSTRAINT chk_tarifa_costo_base CHECK (costo_base >= 0),
    CONSTRAINT chk_tarifa_costo_km CHECK (costo_por_km >= 0),
    CONSTRAINT chk_tarifa_origen_destino CHECK (origen_id IS NULL OR destino_id IS NULL OR origen_id <> destino_id),
    CONSTRAINT chk_tarifa_vigencia CHECK (vigente_hasta IS NULL OR vigente_hasta >= vigente_desde),
    CONSTRAINT chk_tarifa_estado CHECK (estado IN ('ACTIVO', 'INACTIVO'))
);

-- ============================================================================
-- 2. OPERACIÓN LOGÍSTICA (ENVÍOS, TRAMOS Y ASIGNACIONES)
-- ============================================================================

-- 2.1 Envíos (D1, D4, D7)
-- Las dos últimas restricciones replican en la base los invariantes del dominio
-- (Envio._validar): la misma regla validada en las dos capas.
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

-- 2.3 Asociación Envío - Contenedor (N:M, supuesto 1)
-- Que un contenedor no esté en dos envíos ACTIVOS a la vez no se puede declarar
-- acá (la relación es N:M histórica, a propósito): lo valida el servicio con
-- EstadoContenedor.puede_asignarse(), según el criterio de D3.
CREATE TABLE envio_contenedor (
    envio_id UUID NOT NULL,
    contenedor_id UUID NOT NULL,
    fecha_asignacion TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT pk_envio_contenedor PRIMARY KEY (envio_id, contenedor_id),
    CONSTRAINT fk_ec_envio FOREIGN KEY (envio_id) REFERENCES envio(id) ON DELETE CASCADE,
    CONSTRAINT fk_ec_contenedor FOREIGN KEY (contenedor_id) REFERENCES contenedor(id) ON DELETE RESTRICT
);

-- ============================================================================
-- 3. FACTURACIÓN Y FINANZAS (D15, supuesto 4)
--
-- titular_tipo + titular_id: el titular puede ser un CLIENTE, un PROVEEDOR o un
-- OPERADOR (enunciado, pág. 1). Es una referencia polimórfica, así que no se
-- puede declarar una FK: la existencia del titular la valida el servicio. Es el
-- precio de cumplir el requisito con una sola tabla en vez de tres.
-- ============================================================================

-- 3.1 Facturas
CREATE TABLE factura (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    titular_tipo VARCHAR(20) NOT NULL,
    titular_id UUID NOT NULL,
    envio_id UUID,
    numero_factura VARCHAR(50) NOT NULL,
    fecha_emision TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    fecha_vencimiento TIMESTAMPTZ NOT NULL,
    importe_total NUMERIC(12,2) NOT NULL,
    estado VARCHAR(30) NOT NULL DEFAULT 'EMITIDA',
    CONSTRAINT uq_factura_numero UNIQUE (numero_factura),
    CONSTRAINT fk_factura_envio FOREIGN KEY (envio_id) REFERENCES envio(id) ON DELETE SET NULL,
    CONSTRAINT chk_factura_titular_tipo CHECK (titular_tipo IN ('CLIENTE', 'PROVEEDOR', 'OPERADOR')),
    CONSTRAINT chk_factura_importe CHECK (importe_total >= 0),
    CONSTRAINT chk_factura_estado CHECK (estado IN ('EMITIDA', 'PAGADA', 'ANULADA', 'VENCIDA')),
    CONSTRAINT chk_factura_fechas CHECK (fecha_vencimiento >= fecha_emision)
);

-- 3.2 Pagos
-- No lleva titular: se deriva de la factura, que es su única dueña.
CREATE TABLE pago (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    factura_id UUID NOT NULL,
    monto NUMERIC(12,2) NOT NULL,
    medio_pago VARCHAR(50) NOT NULL,
    fecha_pago TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    referencia_transaccion VARCHAR(100),
    CONSTRAINT fk_pago_factura FOREIGN KEY (factura_id) REFERENCES factura(id) ON DELETE RESTRICT,
    CONSTRAINT chk_pago_monto CHECK (monto > 0),
    CONSTRAINT chk_pago_medio CHECK (medio_pago IN ('TRANSFERENCIA', 'TARJETA', 'EFECTIVO', 'CHEQUE'))
);

-- 3.3 Cuentas corrientes (una por titular)
CREATE TABLE cuenta_corriente (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    titular_tipo VARCHAR(20) NOT NULL,
    titular_id UUID NOT NULL,
    saldo NUMERIC(12,2) NOT NULL DEFAULT 0.00,
    limite_credito NUMERIC(12,2) NOT NULL DEFAULT 0.00,
    fecha_apertura TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    fecha_actualizacion TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_cuenta_corriente_titular UNIQUE (titular_tipo, titular_id),
    CONSTRAINT chk_cc_titular_tipo CHECK (titular_tipo IN ('CLIENTE', 'PROVEEDOR', 'OPERADOR')),
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
-- 4. SINCRONIZACIÓN POLÍGLOTA (PATRÓN OUTBOX)
--
-- El evento se escribe en la MISMA transacción que el cambio de datos. Un
-- worker idempotente lo propaga después a Neo4j, MongoDB y Redis.
-- ============================================================================

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
    -- Momento del ultimo intento fallido. El backoff se mide desde aca y no
    -- desde fecha_creacion: si se midiera desde la creacion, un evento viejo
    -- con varios reintentos pasaria el control siempre y el backoff no
    -- serviria de nada.
    fecha_ultimo_intento TIMESTAMPTZ,
    CONSTRAINT chk_outbox_reintentos CHECK (reintentos >= 0)
);

-- ============================================================================
-- 5. ÍNDICES DE OPTIMIZACIÓN (REPORTES OPERATIVOS Y ANALÍTICOS)
-- ============================================================================

-- Reporte: envíos por fecha de creación (rango parametrizado)
CREATE INDEX idx_envio_fecha_creacion ON envio (fecha_creacion);

-- Reporte: envíos por estado (ConteoEnviosPorEstado)
CREATE INDEX idx_envio_estado_fecha ON envio (estado, fecha_creacion);

-- Reporte: envíos por cliente (ConteoEnviosPorCliente)
CREATE INDEX idx_envio_cliente_fecha ON envio (cliente_id, fecha_creacion);

-- Reporte: envíos por país destino (ConteoEnviosPorPais vía destino_id -> ubicacion.pais)
CREATE INDEX idx_envio_destino_id ON envio (destino_id);
CREATE INDEX idx_ubicacion_pais ON ubicacion (pais);

-- Reporte: tiempos de envío por cliente y tiempo promedio de entrega (solo ENTREGADO)
CREATE INDEX idx_envio_entregados_tiempos ON envio (cliente_id, fecha_creacion, fecha_llegada_real)
    WHERE estado = 'ENTREGADO';

CREATE INDEX idx_envio_entregados_promedio ON envio (fecha_creacion, fecha_llegada_real)
    WHERE estado = 'ENTREGADO';

-- Reporte: envíos demorados (D7). La estimada sale de agregar sobre tramo.
CREATE INDEX idx_envio_activos ON envio (estado)
    WHERE estado NOT IN ('ENTREGADO', 'CANCELADO');

CREATE INDEX idx_tramo_envio_estimada ON tramo (envio_id, fecha_llegada_estimada);

-- Reporte: ranking de clientes por volumen transportado
CREATE INDEX idx_ec_envio ON envio_contenedor (envio_id);
CREATE INDEX idx_ec_contenedor ON envio_contenedor (contenedor_id);

-- Reporte: costos por tipo de transporte (D5, D17)
CREATE INDEX idx_tramo_medio_costo ON tramo (medio_transporte, costo);

-- Índices de navegación operativa
CREATE INDEX idx_tramo_vehiculo ON tramo (vehiculo_id);
CREATE INDEX idx_tramo_origen ON tramo (origen_id);
CREATE INDEX idx_tramo_destino ON tramo (destino_id);
CREATE INDEX idx_sensor_contenedor ON sensor (contenedor_id);
CREATE INDEX idx_vehiculo_operador ON vehiculo (operador_id);
CREATE INDEX idx_usuario_cliente ON usuario (cliente_id);
CREATE INDEX idx_usuario_rol ON usuario (rol_id);

-- Facturación y cuentas corrientes (búsqueda por titular polimórfico)
CREATE INDEX idx_factura_titular_estado ON factura (titular_tipo, titular_id, estado);
CREATE INDEX idx_pago_factura ON pago (factura_id);
CREATE INDEX idx_mc_cuenta ON movimiento_cuenta (cuenta_corriente_id);

-- Outbox: el worker busca sólo los pendientes, por eso el índice es parcial.
CREATE INDEX idx_outbox_pendientes ON outbox (fecha_creacion)
    WHERE NOT procesado;

-- Chequeo de consistencia: buscar los eventos de una entidad concreta.
CREATE INDEX idx_outbox_agregado ON outbox (agregado_tipo, agregado_id);
