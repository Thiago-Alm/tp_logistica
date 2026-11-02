"""Interfaz de persistencia de SolicitudReporte. La implementa infrastructure/mongo."""
from abc import ABC, abstractmethod
from uuid import UUID

from logistica.domain.solicitud_reporte import EstadoSolicitud, SolicitudReporte


class SolicitudReporteRepository(ABC):
    @abstractmethod
    def guardar(self, solicitud: SolicitudReporte) -> None:
        """Alta."""
        ...

    @abstractmethod
    def actualizar(self, solicitud: SolicitudReporte) -> None:
        """Persiste una entidad ya modificada, por ejemplo despues de
        `marcar_generada()` (D18). NoEncontrado si no existe."""
        ...

    @abstractmethod
    def obtener(self, id: UUID) -> SolicitudReporte | None: ...

    @abstractmethod
    def listar(self, estado: EstadoSolicitud | None = None) -> list[SolicitudReporte]:
        """Todas las solicitudes, o las de un estado, la mas reciente primero."""
        ...

    @abstractmethod
    def listar_por_titular(self, titular_id: UUID) -> list[SolicitudReporte]:
        """Las solicitudes de un titular, la mas reciente primero."""
        ...
