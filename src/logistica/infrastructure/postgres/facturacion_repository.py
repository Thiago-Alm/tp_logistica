"""Implementaciones de los repositorios de facturacion sobre PostgreSQL."""
from datetime import datetime
from decimal import Decimal
from uuid import UUID

import psycopg

from logistica.domain.facturacion import (
    CuentaCorriente,
    EstadoFactura,
    Factura,
    MedioPago,
    MovimientoCuenta,
    Pago,
    TipoMovimiento,
    TitularTipo,
)
from logistica.infrastructure.postgres.conexion import traducir_errores
from logistica.repositories.facturacion_repository import (
    CuentaCorrienteRepository,
    FacturaRepository,
    MovimientoCuentaRepository,
    PagoRepository,
)

CERO = Decimal("0")

COL_FACTURA = """id, titular_tipo, titular_id, envio_id, numero_factura,
                 fecha_emision, fecha_vencimiento, importe_total, estado"""
COL_PAGO = "id, factura_id, monto, medio_pago, fecha_pago, referencia_transaccion"
COL_CUENTA = """id, titular_tipo, titular_id, saldo, limite_credito,
                fecha_apertura, fecha_actualizacion"""
COL_MOVIMIENTO = """id, cuenta_corriente_id, factura_id, pago_id, tipo, monto,
                    descripcion, fecha"""

# Formato de los datos semilla: FC-<letra>-<punto de venta>-<numero>
PREFIJO_NUMERO = "FC-A-0001-"
LARGO_NUMERO = 8


def _a_factura(f: tuple) -> Factura:
    return Factura(
        id=f[0],
        titular_tipo=TitularTipo(f[1]),
        titular_id=f[2],
        envio_id=f[3],
        numero_factura=f[4],
        fecha_emision=f[5],
        fecha_vencimiento=f[6],
        importe_total=f[7],
        estado=EstadoFactura(f[8]),
    )


def _a_pago(f: tuple) -> Pago:
    return Pago(
        id=f[0],
        factura_id=f[1],
        monto=f[2],
        medio_pago=MedioPago(f[3]),
        fecha_pago=f[4],
        referencia_transaccion=f[5],
    )


def _a_cuenta(f: tuple) -> CuentaCorriente:
    return CuentaCorriente(
        id=f[0],
        titular_tipo=TitularTipo(f[1]),
        titular_id=f[2],
        saldo=f[3],
        limite_credito=f[4],
        fecha_apertura=f[5],
        fecha_actualizacion=f[6],
    )


def _a_movimiento(f: tuple) -> MovimientoCuenta:
    return MovimientoCuenta(
        id=f[0],
        cuenta_corriente_id=f[1],
        factura_id=f[2],
        pago_id=f[3],
        tipo=TipoMovimiento(f[4]),
        monto=f[5],
        descripcion=f[6],
        fecha=f[7],
    )


class PostgresFacturaRepository(FacturaRepository):
    def __init__(self, conexion: psycopg.Connection) -> None:
        self._conexion = conexion

    @traducir_errores
    def guardar(self, factura: Factura) -> None:
        self._conexion.execute(
            """insert into factura (id, titular_tipo, titular_id, envio_id,
                                    numero_factura, fecha_emision,
                                    fecha_vencimiento, importe_total, estado)
               values (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (factura.id, factura.titular_tipo.value, factura.titular_id,
             factura.envio_id, factura.numero_factura, factura.fecha_emision,
             factura.fecha_vencimiento, factura.importe_total, factura.estado.value),
        )

    @traducir_errores
    def actualizar(self, factura: Factura) -> None:
        self._conexion.execute(
            """update factura set importe_total = %s, estado = %s,
                                  fecha_vencimiento = %s
               where id = %s""",
            (factura.importe_total, factura.estado.value,
             factura.fecha_vencimiento, factura.id),
        )

    @traducir_errores
    def obtener(self, id: UUID) -> Factura | None:
        f = self._conexion.execute(
            f"select {COL_FACTURA} from factura where id = %s", (id,)
        ).fetchone()
        return _a_factura(f) if f else None

    @traducir_errores
    def obtener_por_numero(self, numero: str) -> Factura | None:
        f = self._conexion.execute(
            f"select {COL_FACTURA} from factura where numero_factura = %s", (numero,)
        ).fetchone()
        return _a_factura(f) if f else None

    @traducir_errores
    def obtener_por_envio(self, envio_id: UUID) -> Factura | None:
        f = self._conexion.execute(
            f"""select {COL_FACTURA} from factura
                where envio_id = %s and estado <> 'ANULADA'
                order by fecha_emision desc limit 1""",
            (envio_id,),
        ).fetchone()
        return _a_factura(f) if f else None

    @traducir_errores
    def listar_por_titular(
        self, titular_tipo: TitularTipo, titular_id: UUID
    ) -> list[Factura]:
        filas = self._conexion.execute(
            f"""select {COL_FACTURA} from factura
                where titular_tipo = %s and titular_id = %s
                order by fecha_emision desc""",
            (titular_tipo.value, titular_id),
        ).fetchall()
        return [_a_factura(f) for f in filas]

    @traducir_errores
    def listar_por_estado(self, estado: EstadoFactura) -> list[Factura]:
        filas = self._conexion.execute(
            f"select {COL_FACTURA} from factura where estado = %s order by fecha_emision",
            (estado.value,),
        ).fetchall()
        return [_a_factura(f) for f in filas]

    @traducir_errores
    def listar_vencidas(self, momento: datetime) -> list[Factura]:
        filas = self._conexion.execute(
            f"""select {COL_FACTURA} from factura
                where estado = 'EMITIDA' and fecha_vencimiento < %s
                order by fecha_vencimiento""",
            (momento,),
        ).fetchall()
        return [_a_factura(f) for f in filas]

    @traducir_errores
    def proximo_numero(self) -> str:
        """Toma el ultimo numero emitido y le suma uno.

        Se resuelve dentro de la transaccion que emite la factura: el UNIQUE de
        numero_factura es la garantia real de que no se repita, porque si dos
        procesos llegaran al mismo numero la base rechaza el segundo y el
        servicio lo traduce a ConflictoDeDatos.
        """
        fila = self._conexion.execute(
            "select max(numero_factura) from factura where numero_factura like %s",
            (PREFIJO_NUMERO + "%",),
        ).fetchone()
        ultimo = int(fila[0][len(PREFIJO_NUMERO):]) if fila and fila[0] else 0
        return f"{PREFIJO_NUMERO}{ultimo + 1:0{LARGO_NUMERO}d}"


class PostgresPagoRepository(PagoRepository):
    def __init__(self, conexion: psycopg.Connection) -> None:
        self._conexion = conexion

    @traducir_errores
    def guardar(self, pago: Pago) -> None:
        self._conexion.execute(
            """insert into pago (id, factura_id, monto, medio_pago, fecha_pago,
                                 referencia_transaccion)
               values (%s, %s, %s, %s, %s, %s)""",
            (pago.id, pago.factura_id, pago.monto, pago.medio_pago.value,
             pago.fecha_pago, pago.referencia_transaccion),
        )

    @traducir_errores
    def listar_por_factura(self, factura_id: UUID) -> list[Pago]:
        filas = self._conexion.execute(
            f"select {COL_PAGO} from pago where factura_id = %s order by fecha_pago",
            (factura_id,),
        ).fetchall()
        return [_a_pago(f) for f in filas]

    @traducir_errores
    def total_pagado(self, factura_id: UUID) -> Decimal:
        fila = self._conexion.execute(
            "select coalesce(sum(monto), 0) from pago where factura_id = %s",
            (factura_id,),
        ).fetchone()
        return fila[0] if fila else CERO


class PostgresCuentaCorrienteRepository(CuentaCorrienteRepository):
    def __init__(self, conexion: psycopg.Connection) -> None:
        self._conexion = conexion

    @traducir_errores
    def guardar(self, cuenta: CuentaCorriente) -> None:
        self._conexion.execute(
            """insert into cuenta_corriente (id, titular_tipo, titular_id, saldo,
                                             limite_credito)
               values (%s, %s, %s, %s, %s)""",
            (cuenta.id, cuenta.titular_tipo.value, cuenta.titular_id,
             cuenta.saldo, cuenta.limite_credito),
        )

    @traducir_errores
    def actualizar(self, cuenta: CuentaCorriente) -> None:
        self._conexion.execute(
            """update cuenta_corriente
               set saldo = %s, limite_credito = %s,
                   fecha_actualizacion = current_timestamp
               where id = %s""",
            (cuenta.saldo, cuenta.limite_credito, cuenta.id),
        )

    @traducir_errores
    def obtener(self, id: UUID) -> CuentaCorriente | None:
        f = self._conexion.execute(
            f"select {COL_CUENTA} from cuenta_corriente where id = %s", (id,)
        ).fetchone()
        return _a_cuenta(f) if f else None

    @traducir_errores
    def obtener_por_titular(
        self, titular_tipo: TitularTipo, titular_id: UUID
    ) -> CuentaCorriente | None:
        f = self._conexion.execute(
            f"""select {COL_CUENTA} from cuenta_corriente
                where titular_tipo = %s and titular_id = %s""",
            (titular_tipo.value, titular_id),
        ).fetchone()
        return _a_cuenta(f) if f else None

    @traducir_errores
    def listar(self) -> list[CuentaCorriente]:
        filas = self._conexion.execute(
            f"select {COL_CUENTA} from cuenta_corriente order by titular_tipo, saldo"
        ).fetchall()
        return [_a_cuenta(f) for f in filas]


class PostgresMovimientoCuentaRepository(MovimientoCuentaRepository):
    def __init__(self, conexion: psycopg.Connection) -> None:
        self._conexion = conexion

    @traducir_errores
    def guardar(self, movimiento: MovimientoCuenta) -> None:
        self._conexion.execute(
            """insert into movimiento_cuenta (id, cuenta_corriente_id, factura_id,
                                              pago_id, tipo, monto, descripcion, fecha)
               values (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (movimiento.id, movimiento.cuenta_corriente_id, movimiento.factura_id,
             movimiento.pago_id, movimiento.tipo.value, movimiento.monto,
             movimiento.descripcion, movimiento.fecha),
        )

    @traducir_errores
    def listar_por_cuenta(
        self,
        cuenta_id: UUID,
        desde: datetime | None = None,
        hasta: datetime | None = None,
    ) -> list[MovimientoCuenta]:
        condiciones = ["cuenta_corriente_id = %s"]
        parametros: list = [cuenta_id]
        if desde is not None:
            condiciones.append("fecha >= %s")
            parametros.append(desde)
        if hasta is not None:
            condiciones.append("fecha <= %s")
            parametros.append(hasta)
        filas = self._conexion.execute(
            f"""select {COL_MOVIMIENTO} from movimiento_cuenta
                where {" and ".join(condiciones)}
                order by fecha, id""",
            parametros,
        ).fetchall()
        return [_a_movimiento(f) for f in filas]

    @traducir_errores
    def saldo_calculado(self, cuenta_id: UUID) -> Decimal:
        """Suma los movimientos con su signo. Es el control de integridad
        contra el saldo guardado (D41)."""
        fila = self._conexion.execute(
            """select coalesce(sum(case when tipo = 'CREDITO' then monto
                                        else -monto end), 0)
               from movimiento_cuenta where cuenta_corriente_id = %s""",
            (cuenta_id,),
        ).fetchone()
        return fila[0] if fila else CERO
