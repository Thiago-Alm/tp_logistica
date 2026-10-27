"""Umbral configurado de una medicion. Vive en MongoDB (coleccion `umbrales`, D25)."""
from dataclasses import dataclass
from enum import Enum
from uuid import UUID

from logistica.exceptions import ValidacionError


class MagnitudUmbral(Enum):
    TEMPERATURA = "TEMPERATURA"
    HUMEDAD = "HUMEDAD"
    VIBRACION = "VIBRACION"


@dataclass
class Umbral:
    """Rango normal de una magnitud para un tipo de contenedor.

    Es por tipo de contenedor porque un REEFER_40 con carga congelada y un DRY_20
    con electronica no toleran la misma temperatura (D25).
    """

    id: UUID
    tipo_contenedor: str
    magnitud: MagnitudUmbral
    minimo: float
    maximo: float
    unidad: str
    descripcion: str = ""

    def __post_init__(self) -> None:
        self._validar()

    def _validar(self) -> None:
        """Reglas verificables con los campos del propio objeto (D3)."""
        if not self.tipo_contenedor.strip():
            raise ValidacionError("El umbral necesita un tipo de contenedor")
        if not self.unidad.strip():
            raise ValidacionError("El umbral necesita una unidad")
        if self.minimo >= self.maximo:
            raise ValidacionError("El minimo del umbral tiene que ser menor que el maximo")

    @property
    def ancho(self) -> float:
        return self.maximo - self.minimo

    def limite_violado(self, valor: float) -> float | None:
        """El limite que el valor traspasa, o None si esta dentro del rango.

        Los extremos son valores normales: un valor igual al maximo no es anomalia.
        """
        if valor > self.maximo:
            return self.maximo
        if valor < self.minimo:
            return self.minimo
        return None
