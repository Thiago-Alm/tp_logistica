from dataclasses import FrozenInstanceError
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from logistica.domain.envio import EstadoEnvio
from logistica.domain.reportes import (
    ConteoEnviosPorCliente,
    ConteoEnviosPorEstado,
    ConteoEnviosPorPais,
    TiemposDeEnvioPorCliente,
    VolumenPorCliente,
)


def test_los_resultados_de_reporte_son_inmutables():
    conteo = ConteoEnviosPorPais(pais="Argentina", cantidad=12)
    with pytest.raises(FrozenInstanceError):
        conteo.cantidad = 99


def test_conteo_por_estado_usa_el_enum():
    conteo = ConteoEnviosPorEstado(estado=EstadoEnvio.EN_TRANSITO, cantidad=4)
    assert conteo.estado is EstadoEnvio.EN_TRANSITO


def test_conteo_por_cliente():
    conteo = ConteoEnviosPorCliente(
        cliente_id=uuid4(), razon_social="Importadora SA", cantidad=7
    )
    assert conteo.cantidad == 7


def test_un_cliente_sin_envios_entregados_no_tiene_tiempos():
    tiempos = TiemposDeEnvioPorCliente(
        cliente_id=uuid4(), razon_social="Nueva SRL", minimo=None, maximo=None
    )
    assert tiempos.minimo is None and tiempos.maximo is None


def test_tiempos_con_valores():
    tiempos = TiemposDeEnvioPorCliente(
        cliente_id=uuid4(),
        razon_social="Importadora SA",
        minimo=timedelta(days=3),
        maximo=timedelta(days=21),
    )
    assert tiempos.maximo > tiempos.minimo


def test_el_volumen_usa_decimal():
    volumen = VolumenPorCliente(
        cliente_id=uuid4(), razon_social="Importadora SA", volumen=Decimal("1320.50")
    )
    assert volumen.volumen == Decimal("1320.50")
