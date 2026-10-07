from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass
class Lectura:
    sensor_id: UUID
    contenedor_id: UUID  # va aca aunque ya este en el sensor: Cassandra no hace JOINs
    momento: datetime
    temperatura: float
    humedad: float
    vibracion: float
    latitud: float
    longitud: float
    bateria: int
