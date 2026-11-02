"""Interfaz de persistencia de Ubicacion. La implementa infrastructure/postgres."""
from abc import ABC, abstractmethod
from uuid import UUID

from logistica.domain.ubicacion import Ubicacion


class UbicacionRepository(ABC):
    @abstractmethod
    def obtener(self, id: UUID) -> Ubicacion | None: ...

    @abstractmethod
    def obtener_por_locode(self, codigo_locode: str) -> Ubicacion | None:
        """Permite nombrar una ubicacion por su LOCODE (ARBUE) y no por su UUID."""
        ...

    @abstractmethod
    def listar(self) -> list[Ubicacion]:
        """Todas las ubicaciones, por pais y ciudad."""
        ...
