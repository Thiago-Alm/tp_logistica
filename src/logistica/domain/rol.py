"""Rol: nivel de permisos de un usuario. Vive en PostgreSQL."""
from dataclasses import dataclass
from uuid import UUID

from logistica.exceptions import ValidacionError

NIVEL_MINIMO = 1
NIVEL_MAXIMO = 100


@dataclass
class Rol:
    id: UUID
    descripcion: str
    nivel_permisos: int

    def __post_init__(self) -> None:
        self.validar()

    def validar(self) -> None:
        if not self.descripcion.strip():
            raise ValidacionError("La descripcion del rol no puede estar vacia")
        if not NIVEL_MINIMO <= self.nivel_permisos <= NIVEL_MAXIMO:
            raise ValidacionError(
                f"El nivel de permisos va de {NIVEL_MINIMO} a {NIVEL_MAXIMO} "
                f"(recibido: {self.nivel_permisos})"
            )

    def puede_mas_que(self, otro: "Rol") -> bool:
        return self.nivel_permisos > otro.nivel_permisos
