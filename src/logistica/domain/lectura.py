"""Lectura de un sensor IoT. Vive en Cassandra (serie temporal)."""
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
    # Opcional porque un contenedor puede estar reportando sin estar asignado a
    # ningun envio (en deposito, en mantenimiento). Lo necesita la tabla
    # recorrido_por_contenedor de Cassandra (D20).
    envio_id: UUID | None = None

    @property
    def dia(self) -> str:
        """Clave de particion de Cassandra: un bucket por sensor y por dia.

        Se deriva de `momento` en vez de guardarse: dos fuentes para el mismo
        dato se terminan contradiciendo.
        """
        return self.momento.strftime("%Y-%m-%d")


@dataclass(frozen=True)
class Posicion:
    """Un punto del recorrido de un contenedor (tabla recorrido_por_contenedor).

    No es una Lectura: esa tabla guarda solo lo necesario para dibujar la ruta
    (posicion, sensor y envio), no temperatura, humedad, vibracion ni bateria
    (D31).
    """

    contenedor_id: UUID
    sensor_id: UUID
    momento: datetime
    latitud: float
    longitud: float
    envio_id: UUID | None = None
