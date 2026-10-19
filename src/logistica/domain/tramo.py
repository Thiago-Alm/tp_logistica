"""Tramo: un trayecto de un envio entre dos ubicaciones. Vive en PostgreSQL."""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from logistica.exceptions import ValidacionError


class MedioTransporte(Enum):
    """Los tres medios del enunciado: envios terrestres, maritimos y aereos."""

    TERRESTRE = "TERRESTRE"
    MARITIMO = "MARITIMO"
    AEREO = "AEREO"


@dataclass
class Tramo:
    id: UUID
    envio_id: UUID
    vehiculo_id: UUID
    medio_transporte: MedioTransporte
    origen_id: UUID
    destino_id: UUID
    orden: int  # posicion dentro del envio, empieza en 1 (D10)
    fecha_salida: datetime
    fecha_llegada_estimada: datetime
    costo: Decimal
    fecha_llegada_real: datetime | None = None

    def __post_init__(self) -> None:
        self.validar()

    def validar(self) -> None:
        """Invariantes que se verifican con los campos del objeto, sin tocar
        ninguna base. Que envio_id o vehiculo_id existan de verdad se valida en
        el servicio, porque eso requiere consultar (D3)."""
        if self.origen_id == self.destino_id:
            raise ValidacionError("El origen y el destino de un tramo no pueden ser iguales")

        if self.orden < 1:
            raise ValidacionError(f"El orden de un tramo empieza en 1 (recibido: {self.orden})")

        if self.costo < 0:
            raise ValidacionError(f"El costo no puede ser negativo (recibido: {self.costo})")

        if self.fecha_llegada_estimada < self.fecha_salida:
            raise ValidacionError(
                "fecha_llegada_estimada no puede ser anterior a fecha_salida"
            )

        if self.fecha_llegada_real is not None and self.fecha_llegada_real < self.fecha_salida:
            raise ValidacionError(
                "fecha_llegada_real no puede ser anterior a fecha_salida"
            )

    def esta_completado(self) -> bool:
        """Un tramo no tiene estado: se completo cuando tiene llegada real."""
        return self.fecha_llegada_real is not None

    def completar(self, fecha_llegada_real: datetime) -> None:
        """Registra la llegada real del tramo."""
        anterior = self.fecha_llegada_real
        self.fecha_llegada_real = fecha_llegada_real
        try:
            self.validar()
        except ValidacionError:
            self.fecha_llegada_real = anterior
            raise
