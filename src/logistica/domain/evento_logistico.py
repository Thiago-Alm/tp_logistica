"""EventoLogistico: que le paso a un envio y cuando. Vive en Cassandra.

Es la traza del enunciado: "historial completo de eventos" y "seguimiento
temporal de cada envio". Va a Cassandra y no a PostgreSQL porque son datos de
solo agregar, acotados por entidad y consultados por rango de tiempo: nunca se
modifican ni participan de una transaccion.

Hay dos formas de que nazca un evento:

- **Automatica:** un cambio de estado del envio lo genera solo, a traves del
  Outbox (D40). Cubre CARGA_INICIADA, EN_TRANSITO, EN_PUERTO, ENTREGADO y
  CANCELADO.
- **Manual:** un operador registra algo que la aplicacion no puede deducir,
  como el paso por ADUANA o un RETRASO.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from uuid import UUID

from logistica.exceptions import ValidacionError


class TipoEventoLogistico(Enum):
    """Los tipos que ejemplifica el enunciado, mas los estados del envio.

    Los cinco primeros se corresponden con `EstadoEnvio` y los genera el
    sistema; los otros tres los registra una persona.
    """

    CARGA_INICIADA = "CARGA_INICIADA"
    EN_TRANSITO = "EN_TRANSITO"
    EN_PUERTO = "EN_PUERTO"
    ENTREGADO = "ENTREGADO"
    CANCELADO = "CANCELADO"
    ADUANA = "ADUANA"
    RETRASO = "RETRASO"
    DESCARGA = "DESCARGA"

    def es_automatico(self) -> bool:
        """Si lo genera un cambio de estado del envio o lo carga una persona."""
        return self in _AUTOMATICOS


_AUTOMATICOS = frozenset({
    TipoEventoLogistico.CARGA_INICIADA,
    TipoEventoLogistico.EN_TRANSITO,
    TipoEventoLogistico.EN_PUERTO,
    TipoEventoLogistico.ENTREGADO,
    TipoEventoLogistico.CANCELADO,
})


@dataclass
class EventoLogistico:
    id: UUID
    envio_id: UUID
    tipo: TipoEventoLogistico
    momento: datetime
    descripcion: str
    contenedor_id: UUID | None = None
    ubicacion_id: UUID | None = None
    ubicacion_nombre: str | None = None
    latitud: float | None = None
    longitud: float | None = None

    def __post_init__(self) -> None:
        self.validar()

    def validar(self) -> None:
        """Invariantes verificables con los campos del objeto (D3)."""
        if not self.descripcion.strip():
            raise ValidacionError("Un evento logistico necesita una descripcion")
        if (self.latitud is None) != (self.longitud is None):
            raise ValidacionError(
                "La posicion necesita latitud y longitud, o ninguna de las dos"
            )
        if self.latitud is not None and not -90 <= self.latitud <= 90:
            raise ValidacionError(f"Latitud fuera de rango: {self.latitud}")
        if self.longitud is not None and not -180 <= self.longitud <= 180:
            raise ValidacionError(f"Longitud fuera de rango: {self.longitud}")

    @property
    def momento_utc(self) -> datetime:
        """Un momento sin zona horaria se interpreta como UTC, que es la
        convencion del grupo para todas las bases."""
        if self.momento.tzinfo is None:
            return self.momento.replace(tzinfo=timezone.utc)
        return self.momento.astimezone(timezone.utc)

    @property
    def anio_mes(self) -> str:
        """Bucket mensual de la particion de eventos_por_contenedor.

        Se deriva de `momento` en vez de guardarse: dos fuentes para el mismo
        dato se terminan contradiciendo (mismo criterio que `Lectura.dia`).
        """
        return self.momento_utc.strftime("%Y-%m")

    def tiene_posicion(self) -> bool:
        return self.latitud is not None and self.longitud is not None
