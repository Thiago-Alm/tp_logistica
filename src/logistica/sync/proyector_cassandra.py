"""Proyecta los eventos del Outbox como eventos logisticos en Cassandra.

El enunciado pide el "historial completo de eventos" y el "seguimiento temporal
de cada envio". La parte automatica de esa traza se deriva de los cambios de
estado del envio, que ya viajan por el Outbox.

**Por que a traves del Outbox y no escribiendo directo desde el servicio.**
Seria mas corto que `EnvioService.cambiar_estado()` guardara el envio en
PostgreSQL y despues escribiera el evento en Cassandra. Pero eso es
exactamente el *dual write* que el Outbox existe para evitar (D34): entre el
commit y la escritura en Cassandra hay una ventana en la que el envio cambia de
estado y la traza se pierde para siempre, sin que nadie se entere. Pasando por
el Outbox, si Cassandra esta caida el evento queda pendiente y se reintenta.

Como todo proyector, este es **idempotente** (D35): la clave primaria de las
tablas incluye el `evento_id`, que se deriva del id del evento del Outbox, de
modo que reprocesarlo pisa la misma fila en vez de agregar una nueva.
"""
import logging
from uuid import NAMESPACE_URL, UUID, uuid5

from logistica.domain.evento_logistico import EventoLogistico, TipoEventoLogistico
from logistica.domain.evento_outbox import EventoOutbox, TipoAgregado, TipoEvento
from logistica.repositories.evento_logistico_repository import EventoLogisticoRepository
from logistica.sync.proyector import Proyector

log = logging.getLogger(__name__)

# Que estado del envio produce que evento de la traza. CREADO se traduce a
# CARGA_INICIADA, que es el nombre que usa el enunciado para el primer evento.
ESTADO_A_EVENTO = {
    "CREADO": TipoEventoLogistico.CARGA_INICIADA,
    "EN_TRANSITO": TipoEventoLogistico.EN_TRANSITO,
    "EN_PUERTO": TipoEventoLogistico.EN_PUERTO,
    "ENTREGADO": TipoEventoLogistico.ENTREGADO,
    "CANCELADO": TipoEventoLogistico.CANCELADO,
}

DESCRIPCIONES = {
    TipoEventoLogistico.CARGA_INICIADA: "Envio registrado, carga iniciada",
    TipoEventoLogistico.EN_TRANSITO: "El envio salio en transito",
    TipoEventoLogistico.EN_PUERTO: "El envio llego a puerto",
    TipoEventoLogistico.ENTREGADO: "El envio fue entregado",
    TipoEventoLogistico.CANCELADO: "El envio fue cancelado",
}


class ProyectorCassandra(Proyector):
    def __init__(self, repositorio: EventoLogisticoRepository) -> None:
        self._repositorio = repositorio

    @property
    def nombre(self) -> str:
        return "Cassandra"

    def le_interesa(self, evento: EventoOutbox) -> bool:
        """Solo los eventos de ENVIO que representan un punto de la traza.

        Los de TRAMO o CLIENTE no son eventos logisticos del envio: el tramo se
        consulta desde PostgreSQL y el cliente no forma parte de la traza.
        """
        if evento.agregado_tipo is not TipoAgregado.ENVIO:
            return False
        # CONTENEDOR_DESASIGNADO queda afuera a proposito: la traza registra
        # el recorrido del envio (carga iniciada, en transito, en puerto,
        # entregado), y sacar un contenedor es una correccion administrativa,
        # no un movimiento. En Neo4j si se proyecta, porque ahi la relacion
        # INCLUYE la recorren las consultas de D37 y quedaria mintiendo.
        return evento.evento_tipo in (
            TipoEvento.CREADO,
            TipoEvento.ESTADO_CAMBIADO,
            TipoEvento.CONTENEDOR_ASIGNADO,
        )

    def aplicar(self, evento: EventoOutbox) -> None:
        logistico = self._traducir(evento)
        if logistico is None:
            return
        self._repositorio.guardar(logistico)
        log.debug(
            "Evento logistico %s registrado para el envio %s",
            logistico.tipo.value,
            logistico.envio_id,
        )

    def _traducir(self, evento: EventoOutbox) -> EventoLogistico | None:
        if evento.evento_tipo is TipoEvento.CONTENEDOR_ASIGNADO:
            return self._de_asignacion(evento)
        return self._de_cambio_de_estado(evento)

    def _de_cambio_de_estado(self, evento: EventoOutbox) -> EventoLogistico | None:
        estado = evento.payload.get("estado")
        tipo = ESTADO_A_EVENTO.get(estado)
        if tipo is None:
            log.warning(
                "El evento %s trae el estado %r, que no tiene evento logistico",
                evento.id,
                estado,
            )
            return None
        return EventoLogistico(
            id=self._id_derivado(evento),
            envio_id=evento.agregado_id,
            tipo=tipo,
            momento=evento.fecha_creacion,
            descripcion=DESCRIPCIONES[tipo],
        )

    def _de_asignacion(self, evento: EventoOutbox) -> EventoLogistico | None:
        """La asignacion de un contenedor es el momento en que empieza a
        cargarse: se registra como CARGA_INICIADA, pero con el contenedor, para
        que tambien aparezca en su historial de movimientos."""
        contenedor = evento.payload.get("contenedor_id")
        if contenedor is None:
            return None

        return EventoLogistico(
            id=self._id_derivado(evento),
            envio_id=evento.agregado_id,
            tipo=TipoEventoLogistico.CARGA_INICIADA,
            momento=evento.fecha_creacion,
            descripcion="Contenedor asignado al envio",
            contenedor_id=UUID(str(contenedor)),
        )

    @staticmethod
    def _id_derivado(evento: EventoOutbox):
        """Id determinista a partir del evento del Outbox.

        Es lo que hace idempotente al proyector: reprocesar el mismo evento
        produce el mismo `evento_id`, que es parte de la clave primaria, asi que
        la fila se pisa en vez de duplicarse. Con un uuid4 cada reintento
        agregaria una entrada mas a la traza.
        """
        return uuid5(NAMESPACE_URL, f"outbox:{evento.id}")

    def cerrar(self) -> None:
        """La sesion de Cassandra la cierra quien la abrio (el contenedor)."""

