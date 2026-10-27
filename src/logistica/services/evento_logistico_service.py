"""Casos de uso de la trazabilidad.

Requisitos que cubre: "historial completo de eventos", "seguimiento temporal de
cada envio" y "reconstruccion del recorrido de un contenedor".

Los eventos que se derivan de un cambio de estado NO se registran aca: los
genera solo el proyector de Cassandra a partir del Outbox (D40). Este servicio
cubre lo que la aplicacion no puede deducir y tiene que cargar una persona: el
paso por aduana, un retraso informado, una descarga.
"""
import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from logistica.domain.evento_logistico import EventoLogistico, TipoEventoLogistico
from logistica.exceptions import NoEncontrado, ValidacionError
from logistica.repositories.evento_logistico_repository import EventoLogisticoRepository
from logistica.repositories.unidad_de_trabajo import UnidadDeTrabajo

DIAS_POR_DEFECTO = 365

log = logging.getLogger(__name__)


class EventoLogisticoService:
    def __init__(
        self,
        eventos: EventoLogisticoRepository,
        unidad_de_trabajo: UnidadDeTrabajo,
    ) -> None:
        self._eventos = eventos
        self._uow = unidad_de_trabajo

    def registrar(
        self,
        envio_id: UUID,
        tipo: TipoEventoLogistico,
        descripcion: str,
        contenedor_id: UUID | None = None,
        ubicacion_id: UUID | None = None,
        ubicacion_nombre: str | None = None,
        momento: datetime | None = None,
    ) -> EventoLogistico:
        """Registra un evento manual.

        Rechaza los tipos automaticos: si se permitiera cargar a mano un
        EN_TRANSITO, la traza tendria dos entradas para el mismo hecho, una del
        operador y otra del proyector, y dejaria de ser una fuente confiable.

        `ubicacion_nombre` lo pasa quien llama. Se denormaliza en el evento para
        poder mostrarlo sin ir a buscarlo a PostgreSQL, que es justamente para
        lo que sirve Cassandra; el id tambien se guarda, para no perder la
        identidad compartida entre motores (D21).
        """
        if tipo.es_automatico():
            raise ValidacionError(
                f"{tipo.value} lo genera el sistema a partir del cambio de estado "
                f"del envio: no se carga a mano"
            )

        with self._uow as uow:
            if uow.envios.obtener(envio_id) is None:
                raise NoEncontrado(f"No existe el envio {envio_id}")
            if contenedor_id is not None and uow.contenedores.obtener(contenedor_id) is None:
                raise NoEncontrado(f"No existe el contenedor {contenedor_id}")

        evento = EventoLogistico(
            id=uuid4(),
            envio_id=envio_id,
            tipo=tipo,
            momento=momento or datetime.now(timezone.utc),
            descripcion=descripcion,
            contenedor_id=contenedor_id,
            ubicacion_id=ubicacion_id,
            ubicacion_nombre=ubicacion_nombre,
        )
        self._eventos.guardar(evento)
        log.info("Evento %s registrado en el envio %s", tipo.value, envio_id)
        return evento

    # --- Consultas -------------------------------------------------------

    def historial(self, envio_id: UUID) -> list[EventoLogistico]:
        """Seguimiento temporal de un envio, del evento mas viejo al mas nuevo."""
        return self._eventos.historial_de_envio(envio_id)

    def ultimo_evento(self, envio_id: UUID) -> EventoLogistico | None:
        return self._eventos.ultimo_de_envio(envio_id)

    def recorrido_de_contenedor(
        self,
        contenedor_id: UUID,
        desde: datetime | None = None,
        hasta: datetime | None = None,
    ) -> list[EventoLogistico]:
        """Reconstruccion del recorrido de un contenedor.

        Sin rango toma el ultimo ano: la particion de esa tabla lleva bucket
        mensual, asi que un rango abierto recorreria todos los meses que el
        contenedor lleve en servicio.
        """
        hasta = hasta or datetime.now(timezone.utc)
        desde = desde or hasta - timedelta(days=DIAS_POR_DEFECTO)
        return self._eventos.movimientos_de_contenedor(contenedor_id, desde, hasta)

