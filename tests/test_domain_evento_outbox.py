from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from logistica.domain.evento_outbox import (
    REINTENTOS_MAXIMOS,
    SEGUNDOS_MAXIMOS_DE_ESPERA,
    EventoOutbox,
    TipoAgregado,
    TipoEvento,
    nuevo_evento,
)
from logistica.exceptions import ValidacionError

AHORA = datetime(2026, 10, 21, 10, 0, tzinfo=timezone.utc)


def nuevo(**cambios) -> EventoOutbox:
    datos = dict(
        agregado_tipo=TipoAgregado.ENVIO,
        agregado_id=uuid4(),
        evento_tipo=TipoEvento.CREADO,
        payload={"estado": "CREADO"},
        momento=AHORA,
    )
    datos.update(cambios)
    return nuevo_evento(**datos)


def test_un_evento_nace_pendiente():
    evento = nuevo()
    assert not evento.procesado
    assert evento.reintentos == 0
    assert evento.fecha_procesado is None
    assert evento.puede_reintentarse()


def test_un_evento_necesita_payload():
    with pytest.raises(ValidacionError):
        nuevo(payload={})


def test_los_reintentos_no_pueden_ser_negativos():
    with pytest.raises(ValidacionError):
        EventoOutbox(
            id=uuid4(),
            agregado_tipo=TipoAgregado.ENVIO,
            agregado_id=uuid4(),
            evento_tipo=TipoEvento.CREADO,
            payload={"x": 1},
            fecha_creacion=AHORA,
            reintentos=-1,
        )


def test_procesado_y_fecha_van_juntos():
    """Mismo criterio bicondicional que Envio con fecha_llegada_real (D16)."""
    with pytest.raises(ValidacionError):
        EventoOutbox(
            id=uuid4(),
            agregado_tipo=TipoAgregado.ENVIO,
            agregado_id=uuid4(),
            evento_tipo=TipoEvento.CREADO,
            payload={"x": 1},
            fecha_creacion=AHORA,
            procesado=True,
        )
    with pytest.raises(ValidacionError):
        EventoOutbox(
            id=uuid4(),
            agregado_tipo=TipoAgregado.ENVIO,
            agregado_id=uuid4(),
            evento_tipo=TipoEvento.CREADO,
            payload={"x": 1},
            fecha_creacion=AHORA,
            procesado=False,
            fecha_procesado=AHORA,
        )


def test_marcar_procesado_limpia_el_error_anterior():
    evento = nuevo()
    evento.marcar_fallido("Neo4j caido")
    evento.marcar_procesado(AHORA + timedelta(seconds=30))
    assert evento.procesado
    assert evento.error_mensaje is None
    assert not evento.puede_reintentarse()


def test_marcar_fallido_no_lo_da_por_procesado():
    """La garantia del patron: un evento no desaparece hasta que llego."""
    evento = nuevo()
    evento.marcar_fallido("timeout")
    assert not evento.procesado
    assert evento.reintentos == 1
    assert evento.error_mensaje == "timeout"
    assert evento.puede_reintentarse()


def test_el_mensaje_de_error_se_recorta():
    evento = nuevo()
    evento.marcar_fallido("x" * 5000)
    assert len(evento.error_mensaje) == 500


def test_el_backoff_crece_exponencialmente():
    evento = nuevo()
    esperas = []
    for _ in range(5):
        evento.marcar_fallido("falla")
        esperas.append(evento.segundos_de_espera())
    assert esperas == [2, 4, 8, 16, 32]


def test_el_backoff_tiene_tope():
    evento = nuevo()
    for _ in range(50):
        evento.marcar_fallido("falla")
    assert evento.segundos_de_espera() == SEGUNDOS_MAXIMOS_DE_ESPERA


def test_un_evento_se_vence_tras_agotar_los_reintentos():
    evento = nuevo()
    for _ in range(REINTENTOS_MAXIMOS):
        evento.marcar_fallido("falla")
    assert not evento.puede_reintentarse()
    assert evento.esta_vencido()


def test_un_evento_procesado_no_esta_vencido():
    evento = nuevo()
    evento.marcar_procesado(AHORA)
    assert not evento.esta_vencido()


def test_todos_los_tipos_tienen_valor_en_mayusculas():
    """D19: el mismo valor se escribe igual en todos los motores."""
    for tipo in (*TipoAgregado, *TipoEvento):
        assert tipo.value == tipo.value.upper()
        assert tipo.value == tipo.name
