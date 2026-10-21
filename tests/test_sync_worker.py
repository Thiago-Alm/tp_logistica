"""Tests del worker con proyectores falsos, sin tocar ninguna base.

El worker se puede testear sin Neo4j porque depende de la interfaz `Proyector`
y no de una implementacion concreta: ese es el beneficio concreto de haber
puesto una interfaz en el medio.
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from logistica.domain.evento_outbox import (
    REINTENTOS_MAXIMOS,
    EventoOutbox,
    TipoAgregado,
    TipoEvento,
    nuevo_evento,
)
from logistica.repositories.unidad_de_trabajo import UnidadDeTrabajo
from logistica.sync.proyector import Proyector
from logistica.sync.worker import WorkerDeSincronizacion

AHORA = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)


class ProyectorFalso(Proyector):
    """Registra lo que recibe. Puede fingir una falla."""

    def __init__(self, falla: bool = False, solo: TipoAgregado | None = None) -> None:
        self.aplicados: list[EventoOutbox] = []
        self.falla = falla
        self.solo = solo
        self.cerrado = False

    @property
    def nombre(self) -> str:
        return "Falso"

    def le_interesa(self, evento: EventoOutbox) -> bool:
        return self.solo is None or evento.agregado_tipo is self.solo

    def aplicar(self, evento: EventoOutbox) -> None:
        if self.falla:
            raise RuntimeError("el destino esta caido")
        self.aplicados.append(evento)

    def cerrar(self) -> None:
        self.cerrado = True


class OutboxFalso:
    def __init__(self, eventos: list[EventoOutbox]) -> None:
        self.eventos = eventos

    def tomar_pendientes(self, limite: int = 100) -> list[EventoOutbox]:
        return [e for e in self.eventos if not e.procesado][:limite]

    def actualizar(self, evento: EventoOutbox) -> None:
        pass

    def contar_pendientes(self) -> int:
        return sum(1 for e in self.eventos if not e.procesado)


class UowFalsa(UnidadDeTrabajo):
    def __init__(self, eventos: list[EventoOutbox]) -> None:
        self.outbox = OutboxFalso(eventos)
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        pass

    def cerrar(self) -> None:
        pass


def _evento(tipo: TipoAgregado = TipoAgregado.ENVIO, momento=AHORA) -> EventoOutbox:
    return nuevo_evento(tipo, uuid4(), TipoEvento.CREADO, {"id": str(uuid4())}, momento)


def _worker(eventos, proyectores, **kwargs):
    return WorkerDeSincronizacion(UowFalsa(eventos), proyectores, **kwargs)


# --- Camino feliz -----------------------------------------------------------


def test_procesa_los_pendientes_y_los_marca():
    eventos = [_evento(), _evento(), _evento()]
    proyector = ProyectorFalso()
    resultado = _worker(eventos, [proyector]).procesar_tanda(AHORA)

    assert resultado.procesados == 3
    assert resultado.fallidos == 0
    assert len(proyector.aplicados) == 3
    assert all(e.procesado and e.fecha_procesado == AHORA for e in eventos)


def test_un_evento_ya_procesado_no_se_vuelve_a_tomar():
    evento = _evento()
    evento.marcar_procesado(AHORA)
    proyector = ProyectorFalso()
    resultado = _worker([evento], [proyector]).procesar_tanda(AHORA)
    assert resultado.procesados == 0
    assert proyector.aplicados == []


def test_cada_proyector_recibe_solo_lo_suyo():
    envio, tramo = _evento(TipoAgregado.ENVIO), _evento(TipoAgregado.TRAMO)
    solo_envios = ProyectorFalso(solo=TipoAgregado.ENVIO)
    todos = ProyectorFalso()
    _worker([envio, tramo], [solo_envios, todos]).procesar_tanda(AHORA)

    assert [e.agregado_tipo for e in solo_envios.aplicados] == [TipoAgregado.ENVIO]
    assert len(todos.aplicados) == 2


def test_la_tanda_respeta_el_limite():
    eventos = [_evento() for _ in range(10)]
    resultado = _worker(eventos, [ProyectorFalso()], tamanio_de_tanda=4).procesar_tanda(AHORA)
    assert resultado.procesados == 4


# --- Fallas y reintentos ----------------------------------------------------


def test_si_el_proyector_falla_el_evento_queda_pendiente():
    """La garantia del patron: un evento no desaparece hasta que llego."""
    evento = _evento()
    resultado = _worker([evento], [ProyectorFalso(falla=True)]).procesar_tanda(AHORA)

    assert resultado.fallidos == 1
    assert not evento.procesado
    assert evento.reintentos == 1
    assert "el destino esta caido" in evento.error_mensaje


def test_un_evento_que_falla_no_frena_a_los_demas():
    """Un destino caido no puede trabar la cola entera."""
    malo, bueno = _evento(TipoAgregado.ENVIO), _evento(TipoAgregado.TRAMO)
    caido = ProyectorFalso(falla=True, solo=TipoAgregado.ENVIO)
    sano = ProyectorFalso(solo=TipoAgregado.TRAMO)
    worker = _worker([malo, bueno], [caido, sano])
    resultado = worker.procesar_tanda(AHORA)

    assert resultado.fallidos == 1
    assert resultado.procesados == 1
    assert not malo.procesado
    assert bueno.procesado


def test_el_backoff_pospone_el_reintento():
    evento = _evento()
    evento.marcar_fallido("primera falla", AHORA)  # espera 2 segundos

    proyector = ProyectorFalso()
    enseguida = _worker([evento], [proyector]).procesar_tanda(AHORA + timedelta(seconds=1))
    assert enseguida.pospuestos == 1
    assert proyector.aplicados == []

    despues = _worker([evento], [proyector]).procesar_tanda(AHORA + timedelta(seconds=5))
    assert despues.procesados == 1


def test_un_evento_vencido_no_se_reintenta_mas():
    evento = _evento()
    for _ in range(REINTENTOS_MAXIMOS):
        evento.marcar_fallido("falla", AHORA)

    proyector = ProyectorFalso()
    resultado = _worker([evento], [proyector]).procesar_tanda(AHORA + timedelta(hours=1))
    assert resultado.vencidos == 1
    assert resultado.procesados == 0
    assert proyector.aplicados == []


# --- Idempotencia -----------------------------------------------------------


def test_reprocesar_un_evento_lo_entrega_de_nuevo():
    """El worker garantiza entrega AL MENOS UNA VEZ, no exactamente una.

    Si el proceso muere entre "el destino confirmo" y "marque el evento", el
    evento se vuelve a entregar. Por eso los proyectores son idempotentes.
    """
    evento = _evento()
    proyector = ProyectorFalso()
    _worker([evento], [proyector]).procesar_tanda(AHORA)

    evento.procesado = False  # simula la caida justo antes de marcarlo
    evento.fecha_procesado = None
    _worker([evento], [proyector]).procesar_tanda(AHORA)

    assert len(proyector.aplicados) == 2  # llego dos veces, como debe poder pasar


def test_cerrar_libera_los_proyectores():
    proyector = ProyectorFalso()
    _worker([], [proyector]).cerrar()
    assert proyector.cerrado


@pytest.mark.parametrize("cantidad", [0, 1, 50])
def test_la_tanda_commitea_siempre(cantidad):
    """Aunque no haya trabajo: el commit cierra la transaccion que mantiene el
    FOR UPDATE SKIP LOCKED sobre las filas tomadas."""
    eventos = [_evento() for _ in range(cantidad)]
    uow = UowFalsa(eventos)
    WorkerDeSincronizacion(uow, [ProyectorFalso()]).procesar_tanda(AHORA)
    assert uow.commits == 1
