"""Interfaz de persistencia de Incidente. La implementa infrastructure/mongo."""
from abc import ABC, abstractmethod
from enum import Enum
from uuid import UUID

from logistica.domain.incidente import Incidente


class AgrupacionIncidentes(Enum):
    """Ejes por los que se pueden contar incidentes.

    Es un enum y no un nombre de campo libre: la interfaz no filtra detalles de
    Mongo hacia arriba (D2) y no se puede agrupar por un campo inexistente.
    """

    PAIS_ORIGEN = "PAIS_ORIGEN"
    PAIS_DESTINO = "PAIS_DESTINO"
    CLIENTE = "CLIENTE"
    ESTADO = "ESTADO"
    RUTA = "RUTA"


class IncidenteRepository(ABC):
    @abstractmethod
    def guardar(self, incidente: Incidente) -> None:
        """Alta."""
        ...

    @abstractmethod
    def actualizar(self, incidente: Incidente) -> None:
        """Persiste una entidad ya modificada, por ejemplo despues de `pasar_a()`
        (D18). Reemplaza el documento entero. Lanza NoEncontrado si no existe."""
        ...

    @abstractmethod
    def obtener(self, id: UUID) -> Incidente | None: ...

    @abstractmethod
    def listar_abiertos(self) -> list[Incidente]:
        """Reporte "Incidentes abiertos": ABIERTO y EN_ANALISIS, el mas reciente
        primero."""
        ...

    @abstractmethod
    def listar_por_envio(self, envio_id: UUID) -> list[Incidente]:
        """Incidentes de un envio, el mas reciente primero."""
        ...

    @abstractmethod
    def contar_agrupado(
        self, por: AgrupacionIncidentes, limite: int | None = None
    ) -> list[tuple[str, int]]:
        """Cantidad de incidentes por grupo, de mayor a menor.

        Es la mitad Mongo de "promedio de incidentes por pais / estado / cliente":
        el promedio lo calcula el servicio dividiendo por la cantidad de envios,
        que vive en PostgreSQL. La clave es siempre un texto (los UUID se
        devuelven como str)."""
        ...

    @abstractmethod
    def ranking_de_rutas(self, limite: int = 10) -> list[tuple[str, int]]:
        """Reporte "Ranking de rutas con mayor cantidad de incidentes" (D12)."""
        ...
