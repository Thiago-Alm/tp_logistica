"""Interfaz de persistencia de la mensajeria.

Un solo repositorio para las dos colecciones: la conversacion y sus mensajes
son **un agregado**. Estan separados por tamano -los mensajes crecen sin
limite- y no porque sean cosas distintas, asi que quien los guarda es el mismo.
"""
from abc import ABC, abstractmethod
from uuid import UUID

from logistica.domain.mensajeria import Conversacion, EstadoConversacion, Mensaje


class ConversacionRepository(ABC):
    @abstractmethod
    def guardar(self, conversacion: Conversacion) -> None:
        """Alta de la conversacion, sin mensajes."""
        ...

    @abstractmethod
    def actualizar(self, conversacion: Conversacion) -> None:
        """Persiste estado, actividad y pendientes. NoEncontrado si no existe."""
        ...

    @abstractmethod
    def obtener(self, id: UUID) -> Conversacion | None: ...

    @abstractmethod
    def listar(self, estado: EstadoConversacion | None = None) -> list[Conversacion]:
        """Las conversaciones, la de actividad mas reciente primero."""
        ...

    @abstractmethod
    def listar_por_parte(self, parte_id: UUID) -> list[Conversacion]: ...

    @abstractmethod
    def listar_por_envio(self, envio_id: UUID) -> list[Conversacion]: ...

    @abstractmethod
    def listar_con_pendientes(self) -> list[Conversacion]:
        """Las que tienen mensajes de la parte sin leer. Es la bandeja de
        entrada, y se resuelve con un filtro en la base y no recorriendo todo."""
        ...

    @abstractmethod
    def guardar_mensaje(self, mensaje: Mensaje) -> None: ...

    @abstractmethod
    def listar_mensajes(self, conversacion_id: UUID) -> list[Mensaje]:
        """El hilo, del mas viejo al mas nuevo: se lee como se escribio."""
        ...

    @abstractmethod
    def marcar_mensajes_leidos(self, conversacion_id: UUID) -> int:
        """Marca los de la parte y devuelve cuantos eran.

        Es una actualizacion masiva en la base y no un recorrido en memoria:
        traer todo el hilo para cambiar un booleano seria leer de mas.
        """
        ...
