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
    def eliminar(self, tipo_contenedor: str, magnitud: MagnitudUmbral) -> bool:
        """Borra el umbral de esa combinacion. Devuelve si existia.

        Es un borrado fisico y no una baja logica, a diferencia de clientes o
        contenedores (D26): un umbral no lo referencia nadie, y una alerta ya
        creada guarda en su detalle el limite que se violo, asi que no pierde
        sentido si el umbral desaparece.
        """
        ...

    @abstractmethod
    def listar(self) -> list[Umbral]: ...
