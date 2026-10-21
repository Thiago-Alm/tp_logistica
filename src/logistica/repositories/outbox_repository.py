"""Interfaz del Outbox. La implementa infrastructure/postgres.

Este repositorio es distinto de todos los demas: no se usa solo para leer y
escribir una entidad, sino que es el canal por el que viajan los cambios hacia
los otros motores. Por eso vive en la MISMA Unidad de Trabajo que el resto: el
evento tiene que escribirse en la misma transaccion que el dato.
"""
from abc import ABC, abstractmethod
from uuid import UUID

from logistica.domain.evento_outbox import EventoOutbox


class OutboxRepository(ABC):
    @abstractmethod
    def guardar(self, evento: EventoOutbox) -> None:
        """Encola un evento. Se llama DENTRO de la transaccion del cambio que
        lo origina, nunca despues."""
        ...

    @abstractmethod
    def actualizar(self, evento: EventoOutbox) -> None:
        """Persiste el resultado de un intento de propagacion."""
        ...

    @abstractmethod
    def obtener(self, id: UUID) -> EventoOutbox | None: ...

    @abstractmethod
    def tomar_pendientes(self, limite: int = 100) -> list[EventoOutbox]:
        """Devuelve eventos sin procesar, del mas viejo al mas nuevo.

        El orden importa: si un envio se crea y despues cambia de estado, los
        dos eventos tienen que llegar en ese orden o el grafo queda con el
        estado viejo.
        """
        ...

    @abstractmethod
    def contar_pendientes(self) -> int:
        """Cuantos eventos esperan propagacion. Es la metrica de salud de la
        sincronizacion: si crece sin bajar, el worker no esta dando abasto o
        alguna base esta caida."""
        ...

    @abstractmethod
    def listar_vencidos(self, reintentos_maximos: int) -> list[EventoOutbox]:
        """Eventos que agotaron sus reintentos y nunca llegaron.

        Son los que el chequeo de consistencia tiene que reportar: no se
        resuelven solos.
        """
        ...
