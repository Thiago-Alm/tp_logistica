"""Cliente: quien solicita los envios. Vive en PostgreSQL."""
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import UUID

from logistica.exceptions import ValidacionError

DIGITOS_CUIT = 11


class EstadoCliente(Enum):
    """La baja de un cliente es logica: pasa a INACTIVO (D26)."""

    ACTIVO = "ACTIVO"
    INACTIVO = "INACTIVO"


@dataclass
class Cliente:
    id: UUID
    cuit: str
    razon_social: str
    email: str
    pais: str
    fecha_creacion: datetime
    telefono: str | None = None
    direccion: str | None = None
    estado: EstadoCliente = EstadoCliente.ACTIVO

    def __post_init__(self) -> None:
        self.validar()

    def validar(self) -> None:
        if not self.razon_social.strip():
            raise ValidacionError("La razon social no puede estar vacia")
        if not self.pais.strip():
            raise ValidacionError("El pais no puede estar vacio")
        if "@" not in self.email:
            raise ValidacionError(f"Email invalido: {self.email!r}")

        digitos = [c for c in self.cuit if c.isdigit()]
        if len(digitos) != DIGITOS_CUIT:
            raise ValidacionError(
                f"El CUIT debe tener {DIGITOS_CUIT} digitos (recibido: {self.cuit!r})"
            )

    def esta_activo(self) -> bool:
        return self.estado is EstadoCliente.ACTIVO

    def dar_de_baja(self) -> None:
        """Baja logica. No se borra la fila: hay envios y facturas que la referencian."""
        self.estado = EstadoCliente.INACTIVO

    def reactivar(self) -> None:
        self.estado = EstadoCliente.ACTIVO
