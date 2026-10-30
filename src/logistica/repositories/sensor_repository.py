"""Interfaz de persistencia de Sensor. La implementa infrastructure/postgres."""
from abc import ABC, abstractmethod
from uuid import UUID

from logistica.domain.sensor import EstadoSensor, Sensor


class SensorRepository(ABC):
    @abstractmethod
    def guardar(self, sensor: Sensor) -> None:
        """Alta."""
        ...

    @abstractmethod
    def actualizar(self, sensor: Sensor) -> None:
        """Persiste una entidad ya modificada (D18)."""
        ...

    @abstractmethod
    def obtener(self, id: UUID) -> Sensor | None: ...

    @abstractmethod
    def obtener_por_numero_serie(self, numero_serie: str) -> Sensor | None:
        """El numero de serie es unico: lo garantiza uq_sensor_numero_serie."""
        ...

    @abstractmethod
    def listar(self, estado: EstadoSensor | None = None) -> list[Sensor]:
        """Todos los sensores, o solo los de un estado."""
        ...

    @abstractmethod
    def listar_por_contenedor(self, contenedor_id: UUID) -> list[Sensor]:
        """Los sensores instalados en un contenedor."""
        ...
