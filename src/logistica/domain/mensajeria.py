"""Mensajeria con las partes: clientes, proveedores y operadores logisticos.

Vive en MongoDB, en **dos colecciones**: `conversaciones` y `mensajes`.

Por que referenciados y no embebidos: los mensajes de un hilo **crecen sin
limite**, y un documento de MongoDB no puede pasar los 16 MB. Es la decision que
ya estaba tomada en `scripts/mongo/mongo_modelo.js` y se respeta. Al reves que
el `historial_estados` de un incidente (D12), que son unos pocos cambios de
estado y se leen siempre junto al incidente.

Por eso `Conversacion` **no carga sus mensajes**, igual que `Envio` no carga sus
tramos (D6): cuando una consulta necesita las dos cosas, es el servicio el que
las compone.
"""
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import UUID

from logistica.domain.facturacion import TitularTipo
from logistica.exceptions import ValidacionError

LARGO_MAXIMO_CUERPO = 2000


class AutorMensaje(Enum):
    """Quien escribio. No se guarda el nombre: el de un usuario vive en
    PostgreSQL y el de la parte tambien, y duplicarlos los dejaria
    desactualizados cuando alguien cambie su razon social."""

    INTERNO = "INTERNO"
    PARTE = "PARTE"


class EstadoConversacion(Enum):
    ABIERTA = "ABIERTA"
    CERRADA = "CERRADA"


@dataclass
class Mensaje:
    id: UUID
    conversacion_id: UUID
    autor: AutorMensaje
    cuerpo: str
    momento: datetime
    autor_id: UUID | None = None
    leido: bool = False

    def __post_init__(self) -> None:
        self.validar()

    def validar(self) -> None:
        """Invariantes que se verifican con los campos del objeto (D3)."""
        if not self.cuerpo.strip():
            raise ValidacionError("Un mensaje no puede estar vacio")
        if len(self.cuerpo) > LARGO_MAXIMO_CUERPO:
            raise ValidacionError(
                f"Un mensaje no puede pasar de {LARGO_MAXIMO_CUERPO} caracteres "
                f"(recibido: {len(self.cuerpo)})"
            )
        if self.autor is AutorMensaje.INTERNO and self.autor_id is None:
            raise ValidacionError(
                "Un mensaje interno tiene que decir que usuario lo escribio"
            )

    def es_de_la_parte(self) -> bool:
        return self.autor is AutorMensaje.PARTE


@dataclass
class Conversacion:
    """Un hilo con una parte.

    `envio_id` es opcional: una conversacion puede ser sobre un envio puntual
    —"donde esta mi contenedor"— o general, como una negociacion de tarifas.
    """

    id: UUID
    parte_tipo: TitularTipo
    parte_id: UUID
    asunto: str
    fecha_inicio: datetime
    envio_id: UUID | None = None
    estado: EstadoConversacion = EstadoConversacion.ABIERTA
    # Se guarda ademas de derivarse del ultimo mensaje: es por donde se ordenan
    # las conversaciones, y con los mensajes en otra coleccion derivarlo
    # obligaria a leerlos todos en cada listado.
    actividad: datetime | None = None
    sin_leer: int = 0

    def __post_init__(self) -> None:
        self.validar()
        if self.actividad is None:
            self.actividad = self.fecha_inicio

    def validar(self) -> None:
        if not self.asunto.strip():
            raise ValidacionError("La conversacion necesita un asunto")

    def admite_mensajes(self) -> None:
        """Una conversacion cerrada no recibe mas. Reabrirla es un cambio de
        estado explicito, no un efecto de escribir."""
        if self.estado is EstadoConversacion.CERRADA:
            raise ValidacionError(
                "La conversacion esta cerrada: reabrila antes de responder"
            )

    def registrar_actividad(self, momento: datetime, de_la_parte: bool) -> None:
        self.actividad = momento
        if de_la_parte:
            self.sin_leer += 1

    def marcar_leida(self) -> None:
        self.sin_leer = 0

    def cerrar(self) -> None:
        self.estado = EstadoConversacion.CERRADA

    def reabrir(self) -> None:
        self.estado = EstadoConversacion.ABIERTA

    @property
    def esta_abierta(self) -> bool:
        return self.estado is EstadoConversacion.ABIERTA

    @property
    def tiene_pendientes(self) -> bool:
        return self.sin_leer > 0


@dataclass(frozen=True)
class ConversacionConMensajes:
    """Una conversacion junto a su hilo.

    No es una entidad: es el resultado de componer las dos colecciones, igual
    que `EnvioConTramos` compone envio y tramos (D6).
    """

    conversacion: Conversacion
    mensajes: list[Mensaje]

    @property
    def ultimo(self) -> Mensaje | None:
        return self.mensajes[-1] if self.mensajes else None
