from abc import ABC, abstractmethod
from uuid import UUID

from logistica.domain.contenedor import Contenedor


class ContenedorRepository(ABC):
    @abstractmethod
    def guardar(self, contenedor: Contenedor) -> None: ...

    @abstractmethod
    def obtener(self, id: UUID) -> Contenedor | None: ...

    @abstractmethod
    def obtener_por_codigo(self, codigo_iso: str) -> Contenedor | None: ...

    @abstractmethod
    def listar_por_estado(self, estado: str) -> list[Contenedor]: ...

    @abstractmethod
    def cambiar_estado(self, id: UUID, estado: str) -> None: ...
