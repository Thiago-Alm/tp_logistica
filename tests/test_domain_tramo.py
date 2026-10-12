from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from logistica.domain.tramo import MedioTransporte, Tramo
from logistica.exceptions import ValidacionError

SALIDA = datetime(2025, 10, 1, 8, 0)
ESTIMADA = SALIDA + timedelta(days=5)


def nuevo_tramo(**cambios) -> Tramo:
    datos = dict(
        id=uuid4(),
        envio_id=uuid4(),
        vehiculo_id=uuid4(),
        medio_transporte=MedioTransporte.MARITIMO,
        origen_id=uuid4(),
        destino_id=uuid4(),
        orden=1,
        fecha_salida=SALIDA,
        fecha_llegada_estimada=ESTIMADA,
        costo=Decimal("1500.00"),
    )
    datos.update(cambios)
    return Tramo(**datos)


def test_un_tramo_valido_se_construye():
    tramo = nuevo_tramo()
    assert tramo.medio_transporte is MedioTransporte.MARITIMO
    assert not tramo.esta_completado()


def test_origen_y_destino_no_pueden_coincidir():
    mismo = uuid4()
    with pytest.raises(ValidacionError):
        nuevo_tramo(origen_id=mismo, destino_id=mismo)


def test_el_orden_empieza_en_uno():
    with pytest.raises(ValidacionError):
        nuevo_tramo(orden=0)


def test_el_costo_no_puede_ser_negativo():
    with pytest.raises(ValidacionError):
        nuevo_tramo(costo=Decimal("-1"))


def test_el_costo_cero_es_valido():
    assert nuevo_tramo(costo=Decimal("0")).costo == Decimal("0")


def test_la_llegada_estimada_no_puede_preceder_a_la_salida():
    with pytest.raises(ValidacionError):
        nuevo_tramo(fecha_llegada_estimada=SALIDA - timedelta(hours=1))


def test_la_llegada_real_no_puede_preceder_a_la_salida():
    with pytest.raises(ValidacionError):
        nuevo_tramo(fecha_llegada_real=SALIDA - timedelta(hours=1))


def test_completar_marca_el_tramo_como_completado():
    tramo = nuevo_tramo()
    llegada = SALIDA + timedelta(days=4)
    tramo.completar(llegada)
    assert tramo.esta_completado()
    assert tramo.fecha_llegada_real == llegada


def test_completar_con_fecha_invalida_deja_el_tramo_intacto():
    tramo = nuevo_tramo()
    with pytest.raises(ValidacionError):
        tramo.completar(SALIDA - timedelta(days=1))
    assert not tramo.esta_completado()
    assert tramo.fecha_llegada_real is None


def test_un_tramo_puede_llegar_despues_de_lo_estimado():
    """Llegar tarde es valido: 'demorado' se calcula, no es un error de datos."""
    tramo = nuevo_tramo()
    tramo.completar(ESTIMADA + timedelta(days=3))
    assert tramo.esta_completado()
