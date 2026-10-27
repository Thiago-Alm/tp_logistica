"""Interfaz para las consultas de la red logística."""

from abc import ABC, abstractmethod
from uuid import UUID

from logistica.domain.reportes import (
    MovimientoDeContenedor,
    RelacionClienteEnvioOperador,
    TramoDeRuta,
)


class ConsultaRepository(ABC):
    @abstractmethod
    def ruta_de_envio(self, envio_id: UUID) -> list[TramoDeRuta]:
        """Devuelve los tramos de un envío ordenados."""
        ...

    @abstractmethod
    def red_de_cliente(
        self, cliente_id: UUID
    ) -> list[RelacionClienteEnvioOperador]:
        """Devuelve los envíos del cliente y sus operadores vinculados."""
        ...

    @abstractmethod
    def movimientos_de_contenedor(
        self, contenedor_id: UUID
    ) -> list[MovimientoDeContenedor]:
        """Devuelve los tramos que recorrio un contenedor, via sus envios."""
        ...
