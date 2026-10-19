"""Envio: la entidad transaccional central. Vive en PostgreSQL."""
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import UUID

from logistica.exceptions import ValidacionError


class EstadoEnvio(Enum):
    """Ciclo de vida de un envio. ENTREGADO y CANCELADO son finales."""

    CREADO = "CREADO"
    EN_TRANSITO = "EN_TRANSITO"
    EN_PUERTO = "EN_PUERTO"
    ENTREGADO = "ENTREGADO"
    CANCELADO = "CANCELADO"

    def transiciones_posibles(self) -> frozenset["EstadoEnvio"]:
        return _TRANSICIONES_ENVIO[self]

    def puede_pasar_a(self, nuevo: "EstadoEnvio") -> bool:
        return nuevo in _TRANSICIONES_ENVIO[self]

    def es_final(self) -> bool:
        return not _TRANSICIONES_ENVIO[self]


# Transiciones permitidas. Se define despues de la clase porque dentro del
# cuerpo del Enum los miembros todavia no existen como tales.
_TRANSICIONES_ENVIO: dict[EstadoEnvio, frozenset[EstadoEnvio]] = {
    EstadoEnvio.CREADO: frozenset({EstadoEnvio.EN_TRANSITO, EstadoEnvio.CANCELADO}),
    EstadoEnvio.EN_TRANSITO: frozenset(
        {EstadoEnvio.EN_PUERTO, EstadoEnvio.ENTREGADO, EstadoEnvio.CANCELADO}
    ),
    EstadoEnvio.EN_PUERTO: frozenset(
        {EstadoEnvio.EN_TRANSITO, EstadoEnvio.ENTREGADO, EstadoEnvio.CANCELADO}
    ),
    EstadoEnvio.ENTREGADO: frozenset(),
    EstadoEnvio.CANCELADO: frozenset(),
}


class PrioridadEnvio(Enum):
    """Supuesto: el enunciado lista Prioridad sin definir sus valores."""

    BAJA = "BAJA"
    MEDIA = "MEDIA"
    ALTA = "ALTA"


@dataclass
class Envio:
    id: UUID
    cliente_id: UUID
    origen_id: UUID
    destino_id: UUID
    estado: EstadoEnvio
    prioridad: PrioridadEnvio
    fecha_creacion: datetime
    fecha_llegada_real: datetime | None = None

    def __post_init__(self) -> None:
        self.validar()

    def validar(self) -> None:
        """Invariantes que se verifican con los campos del objeto, sin tocar
        ninguna base. Lo que necesite consultar algo va en el servicio."""
        if self.origen_id == self.destino_id:
            raise ValidacionError("El origen y el destino de un envio no pueden ser iguales")

        entregado = self.estado is EstadoEnvio.ENTREGADO
        if entregado and self.fecha_llegada_real is None:
            raise ValidacionError("Un envio ENTREGADO necesita fecha_llegada_real")
        if not entregado and self.fecha_llegada_real is not None:
            raise ValidacionError(
                f"Solo un envio ENTREGADO lleva fecha_llegada_real (estado: {self.estado.value})"
            )

        if self.fecha_llegada_real is not None and self.fecha_llegada_real < self.fecha_creacion:
            raise ValidacionError("fecha_llegada_real no puede ser anterior a fecha_creacion")

    def pasar_a(self, nuevo: EstadoEnvio, momento: datetime | None = None) -> None:
        """Cambia el estado respetando las transiciones permitidas.

        `momento` es obligatorio al pasar a ENTREGADO y se guarda como
        fecha_llegada_real.
        """
        if not self.estado.puede_pasar_a(nuevo):
            raise ValidacionError(
                f"Transicion invalida: {self.estado.value} -> {nuevo.value}"
            )

        anterior, fecha_anterior = self.estado, self.fecha_llegada_real
        self.estado = nuevo
        if nuevo is EstadoEnvio.ENTREGADO:
            self.fecha_llegada_real = momento
        try:
            self.validar()
        except ValidacionError:
            self.estado, self.fecha_llegada_real = anterior, fecha_anterior
            raise

    def esta_entregado(self) -> bool:
        return self.estado is EstadoEnvio.ENTREGADO
