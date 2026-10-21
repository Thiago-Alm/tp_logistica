"""Interfaz de persistencia de Tramo. La implementa infrastructure/postgres.

Tramo tiene repositorio propio y no se carga dentro de Envio (D6): el servicio
compone los dos cuando una consulta necesita el envio con su recorrido.
"""
from abc import ABC, abstractmethod
from decimal import Decimal
from uuid import UUID

from logistica.domain.tramo import MedioTransporte, Tramo


class TramoRepository(ABC):
    @abstractmethod
    def guardar(self, tramo: Tramo) -> None: ...

    @abstractmethod
    def actualizar(self, tramo: Tramo) -> None: ...

    @abstractmethod
    def obtener(self, id: UUID) -> Tramo | None: ...

    @abstractmethod
    def listar_por_envio(self, envio_id: UUID) -> list[Tramo]:
        """Los tramos de un envio, ordenados por `orden`.

        Es la consulta que reconstruye el recorrido: requisito "seguimiento de
        trayectos".
        """
        ...

    @abstractmethod
    def listar_por_vehiculo(self, vehiculo_id: UUID) -> list[Tramo]:
        """Tramos asignados a un vehiculo, del mas reciente al mas viejo."""
        ...

    @abstractmethod
    def costo_por_medio_de_transporte(self) -> dict[MedioTransporte, Decimal]:
        """Requisito: reporte analitico "Costos por tipo de transporte".

        Devuelve un diccionario y no una lista de tuplas porque la clave es un
        enum del dominio, no un texto (D33). Los medios sin tramos no aparecen.
        """
        ...
