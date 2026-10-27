"""Interfaz para el almacenamiento de sesiones."""

from abc import ABC, abstractmethod
from uuid import UUID


class SesionRepository(ABC):
    @abstractmethod
    def guardar(
        self,
        sesion_id: UUID,
        usuario_id: UUID,
        fecha_inicio: str,
        fecha_fin: str,
        ttl_segundos: int,
    ) -> None:
        """Guarda una sesión con vencimiento."""

    @abstractmethod
    def obtener(self, sesion_id: UUID) -> dict[str, str] | None:
        """Devuelve la sesión o None si no existe."""

    @abstractmethod
    def eliminar(self, sesion_id: UUID) -> bool:
        """Elimina la sesión y devuelve si existía."""