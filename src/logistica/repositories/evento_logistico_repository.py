"""Interfaz de persistencia de EventoLogistico. La implementa infrastructure/cassandra."""
from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from logistica.domain.evento_logistico import EventoLogistico


class EventoLogisticoRepository(ABC):
    @abstractmethod
    def guardar(self, evento: EventoLogistico) -> None:
        """Persiste un evento.

        La implementacion de Cassandra escribe en DOS tablas: eventos_por_envio
        y eventos_por_contenedor. Es doble escritura a proposito (diseno
        query-first): Cassandra no hace JOIN, asi que cada consulta necesita su
        propia tabla. Es idempotente, porque repetir la escritura con la misma
        clave pisa la fila en vez de duplicarla.

        Si el evento no tiene contenedor, solo se escribe la primera.
        """
        ...

    @abstractmethod
    def historial_de_envio(self, envio_id: UUID) -> list[EventoLogistico]:
        """Requisito: "historial completo de eventos" y "seguimiento temporal de
        cada envio". Del mas viejo al mas nuevo, que es el orden en que se lee
        una traza.

        Sale de UNA sola particion: el envio es la clave de particion.
        """
        ...

    @abstractmethod
    def movimientos_de_contenedor(
        self, contenedor_id: UUID, desde: datetime, hasta: datetime
    ) -> list[EventoLogistico]:
        """Requisito: "reconstruccion del recorrido de un contenedor".

        Pide un rango porque la particion lleva un bucket mensual: el historial
        de un contenedor no esta acotado (se reutiliza durante anios), asi que
        la consulta recorre un mes por vez.
        """
        ...

    @abstractmethod
    def ultimo_de_envio(self, envio_id: UUID) -> EventoLogistico | None:
        """El evento mas reciente de un envio, o None si no tiene ninguno."""
        ...
