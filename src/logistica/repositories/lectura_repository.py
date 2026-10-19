"""Interfaz de persistencia de Lectura. La implementa infrastructure/cassandra."""
from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from logistica.domain.lectura import Lectura, Posicion


class LecturaRepository(ABC):
    @abstractmethod
    def guardar(self, lectura: Lectura) -> None:
        """Persiste una lectura.

        La implementacion de Cassandra escribe en DOS tablas: lecturas_por_sensor
        y recorrido_por_contenedor. Es doble escritura a proposito, porque
        Cassandra no hace JOIN y cada consulta necesita su propia tabla. Es
        idempotente: repetir la escritura con la misma clave no duplica.
        """
        ...

    @abstractmethod
    def guardar_lote(self, lecturas: list[Lectura]) -> None:
        """Persiste varias lecturas.

        No es atomico entre lecturas, pero cada escritura es idempotente: ante un
        error se puede reintentar el lote completo sin duplicar nada.
        """
        ...

    @abstractmethod
    def listar_por_sensor(
        self, sensor_id: UUID, desde: datetime, hasta: datetime
    ) -> list[Lectura]:
        """Lecturas de un sensor entre `desde` y `hasta` (ambos inclusivos), de la
        mas vieja a la mas nueva. No completa `envio_id`: esa tabla no lo guarda."""
        ...

    @abstractmethod
    def posiciones_de_contenedor(
        self, contenedor_id: UUID, desde: datetime, hasta: datetime
    ) -> list[Posicion]:
        """Recorrido GPS de un contenedor, de la mas vieja a la mas nueva.

        Devuelve Posicion y no Lectura: la tabla recorrido_por_contenedor guarda
        solo lo necesario para dibujar la ruta (D31)."""
        ...

    @abstractmethod
    def ultimas(self, sensor_id: UUID, cantidad: int) -> list[Lectura]:
        """Las `cantidad` lecturas mas recientes, de la mas nueva a la mas vieja."""
        ...
