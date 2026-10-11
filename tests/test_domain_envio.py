from datetime import datetime, timedelta
from uuid import uuid4

import pytest

from logistica.domain.envio import Envio, EstadoEnvio, PrioridadEnvio
from logistica.exceptions import ValidacionError

CREACION = datetime(2025, 10, 1, 9, 0)


def nuevo_envio(**cambios) -> Envio:
    datos = dict(
        id=uuid4(),
        cliente_id=uuid4(),
        origen_id=uuid4(),
        destino_id=uuid4(),
        estado=EstadoEnvio.CREADO,
        prioridad=PrioridadEnvio.MEDIA,
        fecha_creacion=CREACION,
    )
    datos.update(cambios)
    return Envio(**datos)


def test_un_envio_valido_se_construye():
    envio = nuevo_envio()
    assert envio.estado is EstadoEnvio.CREADO
    assert envio.fecha_llegada_real is None


def test_origen_y_destino_no_pueden_coincidir():
    mismo = uuid4()
    with pytest.raises(ValidacionError):
        nuevo_envio(origen_id=mismo, destino_id=mismo)


def test_entregado_exige_fecha_de_llegada():
    with pytest.raises(ValidacionError):
        nuevo_envio(estado=EstadoEnvio.ENTREGADO)


def test_solo_entregado_puede_tener_fecha_de_llegada():
    with pytest.raises(ValidacionError):
        nuevo_envio(estado=EstadoEnvio.EN_TRANSITO, fecha_llegada_real=CREACION)


def test_la_llegada_no_puede_ser_anterior_a_la_creacion():
    with pytest.raises(ValidacionError):
        nuevo_envio(
            estado=EstadoEnvio.ENTREGADO,
            fecha_llegada_real=CREACION - timedelta(days=1),
        )


def test_transicion_permitida():
    envio = nuevo_envio()
    envio.pasar_a(EstadoEnvio.EN_TRANSITO)
    assert envio.estado is EstadoEnvio.EN_TRANSITO


def test_transicion_prohibida_desde_un_estado_final():
    envio = nuevo_envio()
    envio.pasar_a(EstadoEnvio.EN_TRANSITO)
    envio.pasar_a(EstadoEnvio.ENTREGADO, momento=CREACION + timedelta(days=3))
    with pytest.raises(ValidacionError):
        envio.pasar_a(EstadoEnvio.CREADO)


def test_entregar_sin_momento_falla_y_deja_el_envio_intacto():
    envio = nuevo_envio()
    envio.pasar_a(EstadoEnvio.EN_TRANSITO)
    with pytest.raises(ValidacionError):
        envio.pasar_a(EstadoEnvio.ENTREGADO)
    assert envio.estado is EstadoEnvio.EN_TRANSITO
    assert envio.fecha_llegada_real is None


def test_estados_finales():
    assert EstadoEnvio.ENTREGADO.es_final()
    assert EstadoEnvio.CANCELADO.es_final()
    assert not EstadoEnvio.CREADO.es_final()


def test_todo_estado_tiene_transiciones_definidas():
    for estado in EstadoEnvio:
        assert isinstance(estado.transiciones_posibles(), frozenset)
