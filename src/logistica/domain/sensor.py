"""Sensor IoT instalado en un contenedor. Vive en PostgreSQL.

El sensor es el equipo: su ficha (modelo, numero de serie, cada cuanto reporta)
es un dato estable que se consulta por id y se relaciona con el contenedor, asi
que va en el relacional. Lo que el sensor *mide* es una serie temporal que
crece sin parar, y eso vive en Cassandra (D20).
"""
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import UUID

from logistica.exceptions import ValidacionError


class TipoSensor(Enum):
    TEMPERATURA = "TEMPERATURA"
    HUMEDAD = "HUMEDAD"
    VIBRACION = "VIBRACION"
    GPS = "GPS"
    MULTISENSOR = "MULTISENSOR"


class EstadoSensor(Enum):
    ACTIVO = "ACTIVO"
    INACTIVO = "INACTIVO"
    EN_MANTENIMIENTO = "EN_MANTENIMIENTO"
    BAJA = "BAJA"


@dataclass
class Sensor:
    """`contenedor_id` es opcional: un sensor en stock todavia no esta instalado
    en ningun contenedor, y la FK es ON DELETE SET NULL."""

    id: UUID
    numero_serie: str
    modelo: str
    tipo: TipoSensor
    intervalo_reporte_segundos: int
    fecha_instalacion: datetime
    contenedor_id: UUID | None = None
    estado: EstadoSensor = EstadoSensor.ACTIVO

    def __post_init__(self) -> None:
        self.validar()

    def validar(self) -> None:
        """Invariantes que se verifican con los campos del objeto, sin tocar
        ninguna base. Que el contenedor exista se valida en el servicio, porque
        eso requiere consultar (D3)."""
        if not self.numero_serie.strip():
            raise ValidacionError("El sensor necesita un numero de serie")
        if not self.modelo.strip():
            raise ValidacionError("El sensor necesita un modelo")
        if self.intervalo_reporte_segundos <= 0:
            raise ValidacionError(
                "El intervalo de reporte tiene que ser mayor que cero "
                f"(recibido: {self.intervalo_reporte_segundos})"
            )

    def esta_instalado(self) -> bool:
        return self.contenedor_id is not None

    def esta_monitoreado(self) -> bool:
        """Solo los ACTIVO se esperan reportando: la deteccion de inactividad no
        mira los demas (D43)."""
        return self.estado is EstadoSensor.ACTIVO
