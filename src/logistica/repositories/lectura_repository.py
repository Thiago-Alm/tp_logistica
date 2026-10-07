from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from logistica.domain.lectura import Lectura


class LecturaRepository(ABC):
    @abstractmethod
    def guardar(self, lectura: Lectura) -> None: ...

    @abstractmethod
    def guardar_lote(self, lecturas: list[Lectura]) -> None: ...

    @abstractmethod
    def listar_por_sensor(self, sensor_id: UUID, desde: datetime, hasta: datetime) -> list[Lectura]: ...

    @abstractmethod
    def posiciones_de_contenedor(self, contenedor_id: UUID, desde: datetime, hasta: datetime) -> list[Lectura]: ...

    @abstractmethod
    def ultimas(self, sensor_id: UUID, cantidad: int) -> list[Lectura]: ...
