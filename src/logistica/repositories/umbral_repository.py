"""Interfaz de persistencia de Umbral. La implementa infrastructure/mongo."""
from abc import ABC, abstractmethod

from logistica.domain.umbral import MagnitudUmbral, Umbral


class UmbralRepository(ABC):
    @abstractmethod
    def guardar(self, umbral: Umbral) -> None:
        """Alta o modificacion (se identifica por el id del umbral).

        Hay un solo umbral por tipo de contenedor y magnitud: guardar otro con un
        id distinto para la misma combinacion lanza ConflictoDeDatos.
        """
        ...

    @abstractmethod
    def obtener(self, tipo_contenedor: str, magnitud: MagnitudUmbral) -> Umbral | None:
        """El umbral de un tipo de contenedor, o None si no esta configurado."""
        ...

    @abstractmethod
    def listar(self) -> list[Umbral]: ...
