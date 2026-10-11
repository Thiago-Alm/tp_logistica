"""Contenedor: unidad de carga. Vive en PostgreSQL."""
from dataclasses import dataclass
from enum import Enum
from uuid import UUID

from logistica.exceptions import ValidacionError

# Un codigo ISO 6346 son 4 letras (dueño + categoria) y 7 digitos.
LARGO_CODIGO_ISO = 11


class EstadoContenedor(Enum):
    """Los estados ocupados son los que impiden asignar el contenedor a un
    envio nuevo: sostienen la restriccion de que un contenedor no puede estar
    en dos envios activos a la vez (supuesto 1, EnvioContenedor N:M)."""

    DISPONIBLE = "DISPONIBLE"
    ASIGNADO = "ASIGNADO"
    EN_TRANSITO = "EN_TRANSITO"
    EN_MANTENIMIENTO = "EN_MANTENIMIENTO"
    BAJA = "BAJA"

    def esta_ocupado(self) -> bool:
        return self in (EstadoContenedor.ASIGNADO, EstadoContenedor.EN_TRANSITO)

    def puede_asignarse(self) -> bool:
        return self is EstadoContenedor.DISPONIBLE


@dataclass
class Contenedor:
    id: UUID
    codigo_iso: str  # ej: "MSKU1234567"
    tipo: str
    capacidad: float
    estado: EstadoContenedor

    def __post_init__(self) -> None:
        self._validar()

    def _validar(self) -> None:
        if len(self.codigo_iso) != LARGO_CODIGO_ISO:
            raise ValidacionError(
                f"codigo_iso debe tener {LARGO_CODIGO_ISO} caracteres "
                f"(recibido: {self.codigo_iso!r})"
            )
        if self.capacidad <= 0:
            raise ValidacionError(f"La capacidad debe ser positiva (recibido: {self.capacidad})")
