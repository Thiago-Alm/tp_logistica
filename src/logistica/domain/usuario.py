"""Usuario del sistema. Vive en PostgreSQL; sus sesiones activas, en Redis."""
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import UUID

from logistica.exceptions import ValidacionError


class EstadoUsuario(Enum):
    ACTIVO = "ACTIVO"
    INACTIVO = "INACTIVO"


@dataclass
class Usuario:
    """El usuario NUNCA guarda la contrasena en claro, solo su hash.

    cliente_id es None en los usuarios internos (administrador, operador,
    auditor), que no pertenecen a ningun cliente.
    """

    id: UUID
    rol_id: UUID
    nombre: str
    apellido: str
    email: str
    password_hash: str
    fecha_registro: datetime
    cliente_id: UUID | None = None
    estado: EstadoUsuario = EstadoUsuario.ACTIVO

    def __post_init__(self) -> None:
        self.validar()

    def validar(self) -> None:
        if not self.nombre.strip():
            raise ValidacionError("El nombre no puede estar vacio")
        if not self.apellido.strip():
            raise ValidacionError("El apellido no puede estar vacio")
        if "@" not in self.email:
            raise ValidacionError(f"Email invalido: {self.email!r}")
        if not self.password_hash:
            raise ValidacionError("El usuario necesita un hash de contrasena")

    @property
    def nombre_completo(self) -> str:
        return f"{self.nombre} {self.apellido}"

    def es_interno(self) -> bool:
        return self.cliente_id is None

    def esta_activo(self) -> bool:
        return self.estado is EstadoUsuario.ACTIVO

    def dar_de_baja(self) -> None:
        self.estado = EstadoUsuario.INACTIVO
