"""Facturacion y cuentas corrientes. Viven en PostgreSQL.

Es la parte del sistema que justifica haber elegido un motor relacional: emitir
una factura no es escribir una fila, son tres escrituras que tienen que ocurrir
todas o ninguna (la factura, el movimiento de cuenta y el saldo). Si una
quedara a medias, el estado de cuenta de un cliente dejaria de cuadrar y no
habria forma de saber cual es el valor correcto.

Las cuatro entidades van en un solo modulo porque se usan siempre juntas: no
existe un pago sin su factura, ni un movimiento sin su cuenta.
"""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from logistica.exceptions import ValidacionError

CERO = Decimal("0")


class TitularTipo(Enum):
    """Quien puede tener facturas y cuenta corriente.

    No es solo el cliente: el enunciado dice "facturacion, pagos y cuentas
    corrientes de los clientes, proveedores y operadores logisticos"
    (supuesto 4). Por eso la referencia es polimorfica.
    """

    CLIENTE = "CLIENTE"
    PROVEEDOR = "PROVEEDOR"
    OPERADOR = "OPERADOR"


class EstadoFactura(Enum):
    EMITIDA = "EMITIDA"
    PAGADA = "PAGADA"
    ANULADA = "ANULADA"
    VENCIDA = "VENCIDA"

    def puede_pasar_a(self, nuevo: "EstadoFactura") -> bool:
        return nuevo in _TRANSICIONES_FACTURA[self]

    def es_final(self) -> bool:
        return not _TRANSICIONES_FACTURA[self]


# Una factura PAGADA o ANULADA no vuelve atras: son estados finales. Una
# VENCIDA todavia se puede cobrar o anular.
_TRANSICIONES_FACTURA: dict[EstadoFactura, frozenset[EstadoFactura]] = {
    EstadoFactura.EMITIDA: frozenset(
        {EstadoFactura.PAGADA, EstadoFactura.ANULADA, EstadoFactura.VENCIDA}
    ),
    EstadoFactura.VENCIDA: frozenset({EstadoFactura.PAGADA, EstadoFactura.ANULADA}),
    EstadoFactura.PAGADA: frozenset(),
    EstadoFactura.ANULADA: frozenset(),
}


class MedioPago(Enum):
    TRANSFERENCIA = "TRANSFERENCIA"
    TARJETA = "TARJETA"
    EFECTIVO = "EFECTIVO"
    CHEQUE = "CHEQUE"


class TipoMovimiento(Enum):
    """DEBITO aumenta la deuda, CREDITO la reduce.

    El saldo es negativo cuando el titular debe: un debito lo baja y un credito
    lo sube. Es la convencion de los datos semilla y la que usa el cierre
    mensual.
    """

    DEBITO = "DEBITO"
    CREDITO = "CREDITO"

    def signo(self) -> int:
        return -1 if self is TipoMovimiento.DEBITO else 1


@dataclass
class Factura:
    id: UUID
    titular_tipo: TitularTipo
    titular_id: UUID
    numero_factura: str
    fecha_emision: datetime
    fecha_vencimiento: datetime
    importe_total: Decimal
    estado: EstadoFactura = EstadoFactura.EMITIDA
    envio_id: UUID | None = None

    def __post_init__(self) -> None:
        self.validar()

    def validar(self) -> None:
        if not self.numero_factura.strip():
            raise ValidacionError("La factura necesita un numero")
        if self.importe_total < CERO:
            raise ValidacionError(
                f"El importe de una factura no puede ser negativo "
                f"(recibido: {self.importe_total})"
            )
        if self.fecha_vencimiento < self.fecha_emision:
            raise ValidacionError(
                "El vencimiento no puede ser anterior a la emision"
            )

    def pasar_a(self, nuevo: EstadoFactura) -> None:
        """Mismo patron que Envio.pasar_a (D4): la regla de transiciones vive en
        el dominio y no se puede esquivar asignando el campo."""
        if not self.estado.puede_pasar_a(nuevo):
            raise ValidacionError(
                f"Transicion invalida de factura: {self.estado.value} -> {nuevo.value}"
            )
        self.estado = nuevo

    def esta_vencida(self, momento: datetime) -> bool:
        return self.estado is EstadoFactura.EMITIDA and self.fecha_vencimiento < momento

    def esta_pendiente(self) -> bool:
        return self.estado in (EstadoFactura.EMITIDA, EstadoFactura.VENCIDA)


@dataclass
class Pago:
    id: UUID
    factura_id: UUID
    monto: Decimal
    medio_pago: MedioPago
    fecha_pago: datetime
    referencia_transaccion: str | None = None

    def __post_init__(self) -> None:
        self.validar()

    def validar(self) -> None:
        if self.monto <= CERO:
            raise ValidacionError(
                f"El monto de un pago debe ser positivo (recibido: {self.monto})"
            )


@dataclass
class CuentaCorriente:
    """El saldo se guarda, ademas de existir la suma de los movimientos.

    Es una denormalizacion deliberada: sin ella, mostrar el estado de cuenta de
    un titular exigiria sumar todos sus movimientos historicos cada vez. El
    precio es que el saldo y los movimientos tienen que moverse juntos, y eso
    lo garantiza la Unidad de Trabajo (D41).
    """

    id: UUID
    titular_tipo: TitularTipo
    titular_id: UUID
    saldo: Decimal = CERO
    limite_credito: Decimal = CERO
    fecha_apertura: datetime | None = None
    fecha_actualizacion: datetime | None = None

    def __post_init__(self) -> None:
        self.validar()

    def validar(self) -> None:
        if self.limite_credito < CERO:
            raise ValidacionError(
                f"El limite de credito no puede ser negativo "
                f"(recibido: {self.limite_credito})"
            )

    def aplicar(self, movimiento: "MovimientoCuenta") -> None:
        """Mueve el saldo segun el tipo de movimiento."""
        self.saldo += movimiento.monto * movimiento.tipo.signo()

    @property
    def deuda(self) -> Decimal:
        """Lo que el titular debe, en positivo. Cero si esta al dia o a favor."""
        return -self.saldo if self.saldo < CERO else CERO

    def credito_disponible(self) -> Decimal:
        return self.limite_credito - self.deuda

    def supera_el_limite(self, importe: Decimal) -> bool:
        """Si facturar `importe` dejaria al titular por encima de su limite."""
        return self.deuda + importe > self.limite_credito


@dataclass
class MovimientoCuenta:
    """Cada linea del estado de cuenta. Es el libro mayor: nunca se modifica ni
    se borra, solo se agrega."""

    id: UUID
    cuenta_corriente_id: UUID
    tipo: TipoMovimiento
    monto: Decimal
    descripcion: str
    fecha: datetime
    factura_id: UUID | None = None
    pago_id: UUID | None = None

    def __post_init__(self) -> None:
        self.validar()

    def validar(self) -> None:
        if self.monto <= CERO:
            raise ValidacionError(
                f"El monto de un movimiento debe ser positivo "
                f"(recibido: {self.monto}). El sentido lo da el tipo, no el signo."
            )
        if not self.descripcion.strip():
            raise ValidacionError("Un movimiento necesita una descripcion")
