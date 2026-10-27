"""Alerta generada al detectar una anomalia en una lectura. Vive en MongoDB."""
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from uuid import NAMESPACE_URL, UUID, uuid5

from logistica.domain.lectura import Lectura
from logistica.domain.umbral import Umbral


class TipoAlerta(Enum):
    TEMPERATURA = "TEMPERATURA"
    HUMEDAD = "HUMEDAD"
    VIBRACION = "VIBRACION"
    BATERIA = "BATERIA"
    INACTIVIDAD = "INACTIVIDAD"
    GEOCERCA = "GEOCERCA"


class EstadoAlerta(Enum):
    ABIERTA = "ABIERTA"
    RECONOCIDA = "RECONOCIDA"
    CERRADA = "CERRADA"


class SeveridadAlerta(Enum):
    BAJA = "BAJA"
    MEDIA = "MEDIA"
    ALTA = "ALTA"
    CRITICA = "CRITICA"


# Estados que cuentan como "abierta" al listar alertas pendientes.
ESTADOS_ABIERTOS_ALERTA = (EstadoAlerta.ABIERTA, EstadoAlerta.RECONOCIDA)

# Severidad segun cuanto se pasa el valor del limite, como fraccion del ancho del
# rango (D33). Hasta 10 % es BAJA, hasta 25 % MEDIA, hasta 50 % ALTA y mas, CRITICA.
_LIMITES_DE_SEVERIDAD = (
    (0.10, SeveridadAlerta.BAJA),
    (0.25, SeveridadAlerta.MEDIA),
    (0.50, SeveridadAlerta.ALTA),
)


def _severidad_por_desvio(desvio_relativo: float) -> SeveridadAlerta:
    for limite, severidad in _LIMITES_DE_SEVERIDAD:
        if desvio_relativo <= limite:
            return severidad
    return SeveridadAlerta.CRITICA


def _a_utc(momento: datetime) -> datetime:
    """Un datetime sin zona horaria se interpreta como UTC (convencion del grupo)."""
    if momento.tzinfo is None:
        return momento.replace(tzinfo=timezone.utc)
    return momento.astimezone(timezone.utc)


@dataclass(frozen=True)
class DetalleAlerta:
    """Lo que se violo: el valor leido y el limite del umbral que traspaso."""

    valor: float
    umbral: float
    momento_lectura: datetime


@dataclass
class Alerta:
    id: UUID
    tipo: TipoAlerta
    sensor_id: UUID
    severidad: SeveridadAlerta
    fecha: datetime
    detalle: DetalleAlerta | None = None
    contenedor_id: UUID | None = None
    envio_id: UUID | None = None
    evento_id: UUID | None = None
    estado: EstadoAlerta = EstadoAlerta.ABIERTA

    @staticmethod
    def generar_id(sensor_id: UUID, momento: datetime, tipo: TipoAlerta) -> UUID:
        """Id DETERMINISTICO: la misma lectura y el mismo tipo dan siempre el mismo id.

        Si el proceso se reintenta, la alerta no se duplica (D33). Se calcula con
        uuid5 sobre el sensor, el momento en UTC con milisegundos y el tipo.
        """
        momento_utc = _a_utc(momento).isoformat(timespec="milliseconds")
        return uuid5(NAMESPACE_URL, f"alerta:{sensor_id}:{momento_utc}:{tipo.value}")

    @classmethod
    def por_umbral(
        cls, lectura: Lectura, tipo: TipoAlerta, valor: float, umbral: Umbral
    ) -> "Alerta | None":
        """La alerta que corresponde si `valor` viola el umbral, o None si esta dentro."""
        limite = umbral.limite_violado(valor)
        if limite is None:
            return None
        momento = _a_utc(lectura.momento)
        return cls(
            id=cls.generar_id(lectura.sensor_id, momento, tipo),
            tipo=tipo,
            sensor_id=lectura.sensor_id,
            severidad=_severidad_por_desvio(abs(valor - limite) / umbral.ancho),
            # La fecha es la de la lectura, no la del procesamiento.
            fecha=momento,
            detalle=DetalleAlerta(valor=valor, umbral=limite, momento_lectura=momento),
            contenedor_id=lectura.contenedor_id,
            envio_id=lectura.envio_id,
        )

    def esta_abierta(self) -> bool:
        return self.estado in ESTADOS_ABIERTOS_ALERTA
