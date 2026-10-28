"""Interfaz para el almacenamiento de sesiones activas."""

from abc import ABC, abstractmethod
from uuid import UUID

from logistica.domain.sesion import Sesion


class SesionRepository(ABC):
    """Los metodos reciben y devuelven entidades de dominio, nunca diccionarios
    ni filas (D33). El vencimiento no se pasa aparte: se deriva de
    `sesion.fecha_fin`, para que haya una sola fuente de verdad sobre cuando
    muere la sesion."""

    @abstractmethod
    def guardar(self, sesion: Sesion) -> None:
        """Guarda la sesion con vencimiento automatico."""

    @abstractmethod
    def obtener(self, sesion_id: UUID) -> Sesion | None:
        """Devuelve la sesion o None si no existe o ya vencio."""

    @abstractmethod
    def listar_activas(self) -> list[Sesion]:
        """Devuelve todas las sesiones vigentes."""

    @abstractmethod
    def eliminar(self, sesion_id: UUID) -> bool:
        """Elimina la sesion y devuelve si existia."""
