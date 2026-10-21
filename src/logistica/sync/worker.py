"""Worker de sincronizacion: lee el Outbox y propaga los eventos.

Es el proceso que cierra el patron. El servicio dejo el evento en PostgreSQL
dentro de la transaccion del dato; este worker lo toma, se lo pasa a cada
proyector interesado y recien entonces lo marca como procesado.

Garantia: entrega AL MENOS UNA VEZ. Si el proceso muere entre "el destino
confirmo" y "marque el evento", el evento se vuelve a entregar. Por eso los
proyectores son idempotentes (ver sync/proyector.py): al menos una vez mas
idempotencia da un efecto de exactamente una vez.
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from logistica.domain.evento_outbox import REINTENTOS_MAXIMOS, EventoOutbox
from logistica.repositories.unidad_de_trabajo import UnidadDeTrabajo
from logistica.sync.proyector import Proyector

log = logging.getLogger(__name__)


@dataclass
class ResultadoDeTanda:
    """Que paso en una pasada del worker."""

    procesados: int = 0
    fallidos: int = 0
    pospuestos: int = 0
    vencidos: int = 0
    errores: list[str] = field(default_factory=list)

    @property
    def hubo_trabajo(self) -> bool:
        return bool(self.procesados or self.fallidos or self.pospuestos)

    def __str__(self) -> str:
        return (
            f"procesados={self.procesados} fallidos={self.fallidos} "
            f"pospuestos={self.pospuestos} vencidos={self.vencidos}"
        )


class WorkerDeSincronizacion:
    def __init__(
        self,
        unidad_de_trabajo: UnidadDeTrabajo,
        proyectores: list[Proyector],
        tamanio_de_tanda: int = 100,
        reintentos_maximos: int = REINTENTOS_MAXIMOS,
    ) -> None:
        self._uow = unidad_de_trabajo
        self._proyectores = proyectores
        self._tamanio = tamanio_de_tanda
        self._reintentos_maximos = reintentos_maximos

    def procesar_tanda(self, ahora: datetime | None = None) -> ResultadoDeTanda:
        """Procesa hasta `tamanio_de_tanda` eventos pendientes.

        `ahora` se recibe por parametro para poder testear el backoff con una
        fecha fija en vez de depender del reloj.
        """
        ahora = ahora or datetime.now(timezone.utc)
        resultado = ResultadoDeTanda()

        # Toda la tanda va en UNA transaccion de PostgreSQL. El FOR UPDATE
        # SKIP LOCKED de tomar_pendientes mantiene las filas bloqueadas hasta
        # el commit, de modo que otro worker no puede tomar los mismos eventos.
        with self._uow as uow:
            pendientes = uow.outbox.tomar_pendientes(self._tamanio)
            for evento in pendientes:
                self._procesar_uno(uow, evento, ahora, resultado)
            uow.commit()

        if resultado.hubo_trabajo:
            log.info("Tanda de sincronizacion: %s", resultado)
        return resultado

    def _procesar_uno(
        self,
        uow: UnidadDeTrabajo,
        evento: EventoOutbox,
        ahora: datetime,
        resultado: ResultadoDeTanda,
    ) -> None:
        if evento.esta_vencido(self._reintentos_maximos):
            # Agoto los reintentos. No se vuelve a intentar: lo reporta el
            # chequeo de consistencia para que alguien lo mire.
            resultado.vencidos += 1
            return

        if not evento.le_toca_reintentar(ahora):
            resultado.pospuestos += 1
            return

        try:
            for proyector in self._proyectores:
                if proyector.le_interesa(evento):
                    proyector.aplicar(evento)
        except Exception as error:  # noqa: BLE001 - un proyector no puede tumbar la tanda
            # No se relanza: si un evento falla, los demas de la tanda tienen
            # que poder seguir. El evento queda pendiente para el proximo turno.
            evento.marcar_fallido(f"{type(error).__name__}: {error}", ahora)
            uow.outbox.actualizar(evento)
            resultado.fallidos += 1
            resultado.errores.append(f"{evento.id}: {error}")
            log.warning(
                "Evento %s fallo (reintento %s): %s", evento.id, evento.reintentos, error
            )
            return

        evento.marcar_procesado(ahora)
        uow.outbox.actualizar(evento)
        resultado.procesados += 1

    def cerrar(self) -> None:
        for proyector in self._proyectores:
            proyector.cerrar()
