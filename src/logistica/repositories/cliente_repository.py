"""Interfaz de persistencia de Cliente. La implementa infrastructure/postgres."""
from abc import ABC, abstractmethod
from uuid import UUID

from logistica.domain.cliente import Cliente, EstadoCliente


class ClienteRepository(ABC):
    @abstractmethod
    def guardar(self, cliente: Cliente) -> None:
        """Alta. Requisito: "Alta, baja y modificacion de clientes"."""
        ...

    @abstractmethod
    def actualizar(self, cliente: Cliente) -> None:
        """Modificacion, y tambien la baja: la baja es logica (D26), asi que es
        un cambio de estado como cualquier otro (D18)."""
        ...

    @abstractmethod
    def obtener(self, id: UUID) -> Cliente | None: ...

    @abstractmethod
    def obtener_por_cuit(self, cuit: str) -> Cliente | None:
        """El CUIT es unico por cliente."""
        ...

    @abstractmethod
    def listar(self, estado: EstadoCliente | None = None) -> list[Cliente]:
        """Sin estado devuelve todos, incluidos los dados de baja."""
        ...
