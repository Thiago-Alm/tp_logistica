"""Interfaz de persistencia de Lectura. La implementa infrastructure/cassandra."""
from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from logistica.domain.lectura import Lectura


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
    def guardar_lote(self, lecturas: list[Lectura]) -> None: ...

    @abstractmethod
    def listar_por_sensor(
        self, sensor_id: UUID, desde: datetime, hasta: datetime
    ) -> list[Lectura]: ...

    @abstractmethod
    def posiciones_de_contenedor(
        self, contenedor_id: UUID, desde: datetime, hasta: datetime
    ) -> list[Lectura]: ...

    @abstractmethod
    def ultimas(self, sensor_id: UUID, cantidad: int) -> list[Lectura]: ...
