"""Interfaz para las consultas de la red logística."""

from abc import ABC, abstractmethod

from logistica.domain.reportes import (
    MovimientoDeContenedor,
    RelacionClienteEnvioOperador,
    TramoDeRuta,
)


class ConsultaRepository(ABC):
    @abstractmethod
    def ruta_de_envio(self, envio_id: str) -> list[TramoDeRuta]:
        """Devuelve los tramos de un envío ordenados."""
        ...

    @abstractmethod
    def red_de_cliente(
        self, cliente_id: str
    ) -> list[RelacionClienteEnvioOperador]:
        """Devuelve los envíos del cliente y sus operadores vinculados."""
        ...

    @abstractmethod
    def movimientos_de_contenedor(
        self, contenedor_id: str
    ) -> list[MovimientoDeContenedor]:
        """Devuelve los tramos vinculados a un contenedor."""
        ...