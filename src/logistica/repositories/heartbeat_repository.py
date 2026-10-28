"""Interfaz para registrar y consultar señales de sensores."""

from abc import ABC, abstractmethod
from uuid import UUID


class HeartbeatRepository(ABC):
    @abstractmethod
    def registrar(self, sensor_id: UUID, timestamp: float) -> None:
        """Registra la última señal recibida de un sensor."""

    @abstractmethod
    def ultimo_reporte(self, sensor_id: UUID) -> float | None:
        """Devuelve el momento del último reporte, si existe."""