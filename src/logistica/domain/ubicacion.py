"""Punto de la red logistica: puerto, aeropuerto, deposito. Vive en PostgreSQL."""
from dataclasses import dataclass
from enum import Enum
from uuid import UUID

from logistica.exceptions import ValidacionError


class TipoUbicacion(Enum):
    PUERTO = "PUERTO"
    AEROPUERTO = "AEROPUERTO"
    CENTRO_DISTRIBUCION = "CENTRO_DISTRIBUCION"
    ALMACEN = "ALMACEN"
    DEPOSITO_FISCAL = "DEPOSITO_FISCAL"


class EstadoUbicacion(Enum):
    ACTIVO = "ACTIVO"
    INACTIVO = "INACTIVO"


@dataclass
class Ubicacion:
    """`codigo_locode` es el codigo UN/LOCODE (ARBUE, NLRTM). Es opcional porque
    un deposito propio no tiene uno asignado."""

    id: UUID
    nombre: str
    tipo: TipoUbicacion
    ciudad: str
    pais: str
    codigo_locode: str | None = None
    estado: EstadoUbicacion = EstadoUbicacion.ACTIVO

    def __post_init__(self) -> None:
        self.validar()

    def validar(self) -> None:
        """Invariantes que se verifican con los campos del objeto, sin tocar
        ninguna base (D3)."""
        if not self.nombre.strip():
            raise ValidacionError("La ubicacion necesita un nombre")
        if not self.ciudad.strip():
            raise ValidacionError("La ubicacion necesita una ciudad")
        if not self.pais.strip():
            raise ValidacionError("La ubicacion necesita un pais")

    @property
    def etiqueta(self) -> str:
        """Como se nombra en una tabla o en el snapshot de un incidente: el
        LOCODE si lo tiene, porque es corto y univoco, y el nombre si no."""
        return self.codigo_locode or self.nombre
