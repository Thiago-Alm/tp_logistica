"""Incidente de un envio. Vive en MongoDB (documento con historial embebido)."""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from uuid import UUID

from logistica.exceptions import ValidacionError


class TipoIncidente(Enum):
    DEMORA = "DEMORA"
    DANO_CARGA = "DANO_CARGA"
    TEMPERATURA = "TEMPERATURA"
    ROBO = "ROBO"
    ADUANA = "ADUANA"
    ACCIDENTE = "ACCIDENTE"
    OTRO = "OTRO"


class SeveridadIncidente(Enum):
    BAJA = "BAJA"
    MEDIA = "MEDIA"
    ALTA = "ALTA"
    CRITICA = "CRITICA"


class EstadoIncidente(Enum):
    ABIERTO = "ABIERTO"
    EN_ANALISIS = "EN_ANALISIS"
    RESUELTO = "RESUELTO"
    CERRADO = "CERRADO"

    def puede_pasar_a(self, destino: "EstadoIncidente") -> bool:
        return destino in _TRANSICIONES_INCIDENTE[self]

    def es_final(self) -> bool:
        return not _TRANSICIONES_INCIDENTE[self]


# Mismo criterio que D4: un diccionario consultado desde el enum, no el patron
# State. RESUELTO -> ABIERTO es intencional: un incidente se puede reabrir.
_TRANSICIONES_INCIDENTE: dict[EstadoIncidente, set[EstadoIncidente]] = {
    EstadoIncidente.ABIERTO: {EstadoIncidente.EN_ANALISIS, EstadoIncidente.RESUELTO},
    EstadoIncidente.EN_ANALISIS: {EstadoIncidente.RESUELTO},
    EstadoIncidente.RESUELTO: {EstadoIncidente.CERRADO, EstadoIncidente.ABIERTO},
    EstadoIncidente.CERRADO: set(),
}

# Estados que cuentan como "abierto" en el reporte "Incidentes abiertos".
ESTADOS_ABIERTOS = (EstadoIncidente.ABIERTO, EstadoIncidente.EN_ANALISIS)


@dataclass(frozen=True)
class ContextoEnvio:
    """Foto del envio al momento del incidente (D12).

    No se actualiza si despues cambia la ruta del envio: un incidente registra
    las circunstancias de cuando ocurrio, no las actuales.
    """

    cliente_id: UUID
    origen: str
    destino: str
    pais_origen: str
    pais_destino: str

    @property
    def ruta(self) -> str:
        """Par origen-destino. Se deriva en vez de guardarse en el dominio (como
        Lectura.dia): el repositorio la escribe en el documento porque lleva
        indice para el ranking de rutas."""
        return f"{self.origen}->{self.destino}"


@dataclass(frozen=True)
class CambioEstado:
    estado: EstadoIncidente
    fecha: datetime
    usuario_id: UUID | None = None


@dataclass
class Incidente:
    id: UUID
    envio_id: UUID
    tipo: TipoIncidente
    severidad: SeveridadIncidente
    descripcion: str
    contexto_envio: ContextoEnvio
    fecha: datetime
    contenedor_id: UUID | None = None
    estado: EstadoIncidente = EstadoIncidente.ABIERTO
    historial_estados: list[CambioEstado] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.historial_estados:
            self.historial_estados.append(CambioEstado(self.estado, self.fecha))
        self._validar()

    def _validar(self) -> None:
        """Reglas verificables con los campos del propio objeto (D3)."""
        if not self.descripcion.strip():
            raise ValidacionError("El incidente necesita una descripcion")
        if self.historial_estados[-1].estado != self.estado:
            raise ValidacionError(
                "El ultimo cambio del historial no coincide con el estado actual"
            )

    def pasar_a(
        self,
        destino: EstadoIncidente,
        usuario_id: UUID | None = None,
        fecha: datetime | None = None,
    ) -> None:
        """Unica forma de cambiar el estado (D4, D18): valida la transicion y deja
        el cambio en el historial."""
        if not self.estado.puede_pasar_a(destino):
            raise ValidacionError(
                f"Un incidente {self.estado.value} no puede pasar a {destino.value}"
            )
        self.estado = destino
        self.historial_estados.append(
            CambioEstado(destino, fecha or datetime.now(timezone.utc), usuario_id)
        )

    def esta_abierto(self) -> bool:
        return self.estado in ESTADOS_ABIERTOS
