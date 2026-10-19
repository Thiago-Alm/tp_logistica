"""Interfaz de persistencia de Rol. La implementa infrastructure/postgres."""
from abc import ABC, abstractmethod
from uuid import UUID

from logistica.domain.rol import Rol


class RolRepository(ABC):
    @abstractmethod
    def guardar(self, rol: Rol) -> None: ...

    @abstractmethod
    def actualizar(self, rol: Rol) -> None: ...

    @abstractmethod
    def obtener(self, id: UUID) -> Rol | None: ...

    @abstractmethod
    def obtener_por_descripcion(self, descripcion: str) -> Rol | None: ...

    @abstractmethod
    def listar(self) -> list[Rol]:
        """Ordenados por nivel de permisos, de mayor a menor."""
        ...
