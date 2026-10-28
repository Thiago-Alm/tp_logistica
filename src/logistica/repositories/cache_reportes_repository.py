"""Contrato para guardar temporalmente resultados de reportes."""

from abc import ABC, abstractmethod


class CacheReportesRepository(ABC):
    @abstractmethod
    def obtener(self, clave: str) -> str | None:
        """Devuelve el resultado serializado o None si no existe."""
        raise NotImplementedError

    @abstractmethod
    def guardar(self, clave: str, contenido: str, ttl_segundos: int) -> None:
        """Guarda el resultado con un tiempo de vencimiento."""
        raise NotImplementedError