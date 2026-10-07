from dataclasses import dataclass
from uuid import UUID


@dataclass
class Contenedor:
    id: UUID
    codigo_iso: str  # ej: "MSKU1234567"
    tipo: str
    capacidad: float
    estado: str
