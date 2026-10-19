"""Interfaz de persistencia de Usuario. La implementa infrastructure/postgres."""
from abc import ABC, abstractmethod
from uuid import UUID

from logistica.domain.usuario import EstadoUsuario, Usuario


class UsuarioRepository(ABC):
    @abstractmethod
    def guardar(self, usuario: Usuario) -> None: ...

    @abstractmethod
    def actualizar(self, usuario: Usuario) -> None: ...

    @abstractmethod
    def obtener(self, id: UUID) -> Usuario | None: ...

    @abstractmethod
    def obtener_por_email(self, email: str) -> Usuario | None:
        """El email es unico. Es por aca que entra el login."""
        ...

    @abstractmethod
    def listar(self, estado: EstadoUsuario | None = None) -> list[Usuario]: ...

    @abstractmethod
    def listar_por_cliente(self, cliente_id: UUID) -> list[Usuario]: ...
