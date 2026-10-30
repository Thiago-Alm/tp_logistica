"""EventoOutbox: un cambio que todavia no se propago a los demas motores.

Es la pieza central de la sincronizacion. El evento se escribe en la MISMA
transaccion de PostgreSQL que el cambio que lo origina, de modo que no existe
el caso "el dato se guardo pero el evento no". Despues un worker aparte lo lee
y lo propaga a Neo4j y MongoDB.
"""
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from logistica.exceptions import ValidacionError

# Tope del backoff: a partir de aca no tiene sentido esperar mas.
SEGUNDOS_MAXIMOS_DE_ESPERA = 300
REINTENTOS_MAXIMOS = 5


class TipoAgregado(Enum):
    """Que entidad cambio. Es un enum y no texto libre porque el worker decide
    a que proyector mandar el evento segun este valor (D1)."""

    CLIENTE = "CLIENTE"
    OPERADOR = "OPERADOR"
    PROVEEDOR = "PROVEEDOR"
    UBICACION = "UBICACION"
    VEHICULO = "VEHICULO"
    CONTENEDOR = "CONTENEDOR"
    ENVIO = "ENVIO"
    TRAMO = "TRAMO"


class TipoEvento(Enum):
    """Que le paso al agregado."""

    CREADO = "CREADO"
    ACTUALIZADO = "ACTUALIZADO"
    ESTADO_CAMBIADO = "ESTADO_CAMBIADO"
    DADO_DE_BAJA = "DADO_DE_BAJA"
    CONTENEDOR_ASIGNADO = "CONTENEDOR_ASIGNADO"
    CONTENEDOR_DESASIGNADO = "CONTENEDOR_DESASIGNADO"


@dataclass
class EventoOutbox:
    id: UUID
    agregado_tipo: TipoAgregado
    agregado_id: UUID
    evento_tipo: TipoEvento
    payload: dict[str, Any]
    fecha_creacion: datetime
    procesado: bool = False
    fecha_procesado: datetime | None = None
    error_mensaje: str | None = None
    reintentos: int = 0
    fecha_ultimo_intento: datetime | None = None

    def __post_init__(self) -> None:
        self.validar()

    def validar(self) -> None:
        if self.reintentos < 0:
            raise ValidacionError(
                f"Los reintentos no pueden ser negativos (recibido: {self.reintentos})"
            )
        if not self.payload:
            raise ValidacionError("Un evento del outbox necesita un payload")
        if self.procesado and self.fecha_procesado is None:
            raise ValidacionError("Un evento procesado necesita fecha_procesado")
        if not self.procesado and self.fecha_procesado is not None:
            raise ValidacionError(
                "Un evento sin procesar no puede tener fecha_procesado"
            )

    # --- Resultado de un intento de propagacion --------------------------

    def marcar_procesado(self, momento: datetime) -> None:
        """El evento llego a destino. No se borra la fila: queda como registro
        de la propagacion, y es lo que permite auditar la sincronizacion."""
        anterior = (self.procesado, self.fecha_procesado, self.error_mensaje)
        self.procesado = True
        self.fecha_procesado = momento
        self.error_mensaje = None
        try:
            self.validar()
        except ValidacionError:
            self.procesado, self.fecha_procesado, self.error_mensaje = anterior
            raise

    def marcar_fallido(self, mensaje: str, momento: datetime | None = None) -> None:
        """La propagacion fallo. El evento sigue pendiente y se reintenta.

        No se marca como procesado: esa es justamente la garantia del patron,
        que un evento no desaparece hasta que efectivamente llego.
        """
        self.reintentos += 1
        self.error_mensaje = mensaje[:500]
        self.fecha_ultimo_intento = momento

    # --- Politica de reintentos ------------------------------------------

    def puede_reintentarse(self, maximo: int = REINTENTOS_MAXIMOS) -> bool:
        return not self.procesado and self.reintentos < maximo

    def le_toca_reintentar(self, ahora: datetime) -> bool:
        """Si ya paso el tiempo de espera desde el ultimo intento.

        Un evento que nunca se intento (reintentos == 0) va de una.
        """
        if self.reintentos == 0 or self.fecha_ultimo_intento is None:
            return True
        transcurrido = (ahora - self.fecha_ultimo_intento).total_seconds()
        return transcurrido >= self.segundos_de_espera()

    def segundos_de_espera(self) -> int:
        """Backoff exponencial: 1, 2, 4, 8, 16... hasta el tope.

        Reintentar de inmediato contra una base caida solo agrega carga y
        consume los reintentos disponibles en segundos. Esperar cada vez mas le
        da tiempo a que el motor vuelva.
        """
        return min(2**self.reintentos, SEGUNDOS_MAXIMOS_DE_ESPERA)

    def esta_vencido(self, maximo: int = REINTENTOS_MAXIMOS) -> bool:
        """Agoto los reintentos y nunca llego. Requiere intervencion manual:
        lo reporta el chequeo de consistencia."""
        return not self.procesado and self.reintentos >= maximo


def nuevo_evento(
    agregado_tipo: TipoAgregado,
    agregado_id: UUID,
    evento_tipo: TipoEvento,
    payload: dict[str, Any],
    momento: datetime,
    id: UUID | None = None,
) -> EventoOutbox:
    """Atajo para crear un evento pendiente, que es el unico estado en que nace."""
    return EventoOutbox(
        id=id or uuid4(),
        agregado_tipo=agregado_tipo,
        agregado_id=agregado_id,
        evento_tipo=evento_tipo,
        payload=payload,
        fecha_creacion=momento,
    )
