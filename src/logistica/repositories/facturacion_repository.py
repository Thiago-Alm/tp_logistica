"""Interfaces de persistencia de facturacion. Las implementa infrastructure/postgres.

Las cuatro van en un modulo porque se usan siempre dentro de la misma
transaccion: emitir una factura toca la factura, el movimiento y la cuenta.
"""
from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from logistica.domain.facturacion import (
    CuentaCorriente,
    EstadoFactura,
    Factura,
    MovimientoCuenta,
    Pago,
    TitularTipo,
)


class FacturaRepository(ABC):
    @abstractmethod
    def guardar(self, factura: Factura) -> None: ...

    @abstractmethod
    def actualizar(self, factura: Factura) -> None: ...

    @abstractmethod
    def obtener(self, id: UUID) -> Factura | None: ...

    @abstractmethod
    def obtener_por_numero(self, numero: str) -> Factura | None: ...

    @abstractmethod
    def listar_por_titular(
        self, titular_tipo: TitularTipo, titular_id: UUID
    ) -> list[Factura]:
        """Las facturas de un titular, de la mas reciente a la mas vieja."""
        ...

    @abstractmethod
    def listar_por_estado(self, estado: EstadoFactura) -> list[Factura]: ...

    @abstractmethod
    def obtener_por_envio(self, envio_id: UUID) -> Factura | None:
        """La factura de un envio, si ya se emitio.

        La usa la facturacion automatica para no emitir dos veces por el mismo
        envio: es lo que hace idempotente a ese proceso periodico.
        """
        ...

    @abstractmethod
    def listar_vencidas(self, momento: datetime) -> list[Factura]:
        """Facturas EMITIDAS cuyo vencimiento ya paso."""
        ...

    @abstractmethod
    def proximo_numero(self) -> str:
        """Genera el proximo numero de factura.

        Se pide al repositorio y no se arma en el servicio porque la unicidad
        depende de lo que ya hay en la tabla, y eso solo lo sabe la base.
        """
        ...


class PagoRepository(ABC):
    @abstractmethod
    def guardar(self, pago: Pago) -> None: ...

    @abstractmethod
    def listar_por_factura(self, factura_id: UUID) -> list[Pago]: ...

    @abstractmethod
    def total_pagado(self, factura_id: UUID) -> object:
        """Suma de los pagos de una factura. Devuelve Decimal, nunca float (D15)."""
        ...


class CuentaCorrienteRepository(ABC):
    @abstractmethod
    def guardar(self, cuenta: CuentaCorriente) -> None: ...

    @abstractmethod
    def actualizar(self, cuenta: CuentaCorriente) -> None: ...

    @abstractmethod
    def obtener(self, id: UUID) -> CuentaCorriente | None: ...

    @abstractmethod
    def obtener_por_titular(
        self, titular_tipo: TitularTipo, titular_id: UUID
    ) -> CuentaCorriente | None:
        """Hay una sola cuenta por titular: lo garantiza un UNIQUE en la base."""
        ...

    @abstractmethod
    def listar(self) -> list[CuentaCorriente]: ...


class MovimientoCuentaRepository(ABC):
    @abstractmethod
    def guardar(self, movimiento: MovimientoCuenta) -> None:
        """Solo se agrega: un movimiento nunca se modifica ni se borra. Es el
        libro mayor, y corregir un error es otro movimiento en sentido
        contrario, no una edicion."""
        ...

    @abstractmethod
    def listar_por_cuenta(
        self,
        cuenta_id: UUID,
        desde: datetime | None = None,
        hasta: datetime | None = None,
    ) -> list[MovimientoCuenta]:
        """Estado de cuenta, del mas viejo al mas nuevo."""
        ...

    @abstractmethod
    def saldo_calculado(self, cuenta_id: UUID) -> object:
        """El saldo segun la suma de los movimientos.

        Existe para poder CONTRASTARLO con el saldo guardado: si difieren, hubo
        una escritura que no paso por la transaccion. Es un control de
        integridad, no la forma normal de leer el saldo (D41).
        """
        ...
