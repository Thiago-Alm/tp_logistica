"""Tests del dominio de Umbral y Alerta. No necesitan ninguna base (D3)."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from logistica.domain.alerta import (
    Alerta,
    EstadoAlerta,
    SeveridadAlerta,
    TipoAlerta,
)
from logistica.domain.lectura import Lectura
from logistica.domain.umbral import MagnitudUmbral, Umbral
from logistica.exceptions import ValidacionError

MOMENTO = datetime(2026, 10, 20, 12, 0, 0, tzinfo=timezone.utc)


def _umbral(minimo=-25.0, maximo=-15.0, **cambios) -> Umbral:
    datos = dict(
        id=uuid4(),
        tipo_contenedor="REEFER_40",
        magnitud=MagnitudUmbral.TEMPERATURA,
        minimo=minimo,
        maximo=maximo,
        unidad="C",
    )
    datos.update(cambios)
    return Umbral(**datos)


def _lectura(temperatura: float, momento=MOMENTO) -> Lectura:
    return Lectura(
        sensor_id=uuid4(),
        contenedor_id=uuid4(),
        momento=momento,
        temperatura=temperatura,
        humedad=60.0,
        vibracion=0.2,
        latitud=-34.6,
        longitud=-58.4,
        bateria=90,
    )


# -- Umbral ------------------------------------------------------------------


def test_el_minimo_tiene_que_ser_menor_que_el_maximo():
    with pytest.raises(ValidacionError):
        _umbral(minimo=10.0, maximo=10.0)
    with pytest.raises(ValidacionError):
        _umbral(minimo=20.0, maximo=10.0)


def test_el_tipo_de_contenedor_y_la_unidad_no_pueden_estar_vacios():
    with pytest.raises(ValidacionError):
        _umbral(tipo_contenedor="  ")
    with pytest.raises(ValidacionError):
        _umbral(unidad="")


def test_un_valor_dentro_del_rango_no_viola_nada():
    assert _umbral().limite_violado(-20.0) is None


def test_los_extremos_son_valores_normales():
    umbral = _umbral()
    assert umbral.limite_violado(-15.0) is None
    assert umbral.limite_violado(-25.0) is None


def test_un_valor_fuera_del_rango_devuelve_el_limite_que_traspaso():
    umbral = _umbral()
    assert umbral.limite_violado(-10.0) == -15.0
    assert umbral.limite_violado(-30.0) == -25.0


# -- Alerta ------------------------------------------------------------------


def test_una_lectura_dentro_del_rango_no_genera_alerta():
    assert Alerta.por_umbral(_lectura(-20.0), TipoAlerta.TEMPERATURA, -20.0, _umbral()) is None


def test_una_lectura_fuera_del_rango_genera_una_alerta_abierta_con_su_detalle():
    lectura = _lectura(-10.0)
    alerta = Alerta.por_umbral(lectura, TipoAlerta.TEMPERATURA, lectura.temperatura, _umbral())

    assert alerta is not None
    assert alerta.estado is EstadoAlerta.ABIERTA
    assert alerta.tipo is TipoAlerta.TEMPERATURA
    assert alerta.sensor_id == lectura.sensor_id
    assert alerta.contenedor_id == lectura.contenedor_id
    assert alerta.fecha == MOMENTO
    assert alerta.detalle.valor == -10.0
    assert alerta.detalle.umbral == -15.0  # el limite que traspaso
    assert alerta.detalle.momento_lectura == MOMENTO


def test_el_id_es_deterministico():
    sensor_id = uuid4()
    uno = Alerta.generar_id(sensor_id, MOMENTO, TipoAlerta.TEMPERATURA)
    otro = Alerta.generar_id(sensor_id, MOMENTO, TipoAlerta.TEMPERATURA)
    assert uno == otro


def test_el_id_cambia_con_el_sensor_el_momento_o_el_tipo():
    sensor_id = uuid4()
    base = Alerta.generar_id(sensor_id, MOMENTO, TipoAlerta.TEMPERATURA)
    assert Alerta.generar_id(uuid4(), MOMENTO, TipoAlerta.TEMPERATURA) != base
    un_milisegundo_despues = MOMENTO + timedelta(milliseconds=1)
    assert Alerta.generar_id(sensor_id, un_milisegundo_despues, TipoAlerta.TEMPERATURA) != base
    assert Alerta.generar_id(sensor_id, MOMENTO, TipoAlerta.HUMEDAD) != base


def test_un_momento_sin_zona_horaria_se_trata_como_utc():
    sensor_id = uuid4()
    con_zona = Alerta.generar_id(sensor_id, MOMENTO, TipoAlerta.TEMPERATURA)
    sin_zona = Alerta.generar_id(sensor_id, MOMENTO.replace(tzinfo=None), TipoAlerta.TEMPERATURA)
    assert con_zona == sin_zona


def test_la_misma_lectura_evaluada_dos_veces_da_el_mismo_id():
    lectura = _lectura(-10.0)
    primera = Alerta.por_umbral(lectura, TipoAlerta.TEMPERATURA, -10.0, _umbral())
    segunda = Alerta.por_umbral(lectura, TipoAlerta.TEMPERATURA, -10.0, _umbral())
    assert primera.id == segunda.id


@pytest.mark.parametrize(
    ("temperatura", "severidad"),
    [
        (-14.5, SeveridadAlerta.BAJA),  # 0.5 sobre un rango de 10 -> 5 %
        (-14.0, SeveridadAlerta.BAJA),  # 10 %, el limite de BAJA
        (-13.0, SeveridadAlerta.MEDIA),  # 20 %
        (-11.0, SeveridadAlerta.ALTA),  # 40 %
        (-5.0, SeveridadAlerta.CRITICA),  # 100 %
        (-30.0, SeveridadAlerta.ALTA),  # por debajo: 5 sobre 10 -> 50 %
        (-31.0, SeveridadAlerta.CRITICA),  # 60 %
    ],
)
def test_la_severidad_depende_de_cuanto_se_pasa_del_limite(temperatura, severidad):
    lectura = _lectura(temperatura)
    alerta = Alerta.por_umbral(lectura, TipoAlerta.TEMPERATURA, temperatura, _umbral())
    assert alerta.severidad is severidad


def test_una_alerta_reconocida_sigue_abierta_y_una_cerrada_no():
    lectura = _lectura(-10.0)
    alerta = Alerta.por_umbral(lectura, TipoAlerta.TEMPERATURA, -10.0, _umbral())
    assert alerta.esta_abierta()
    alerta.estado = EstadoAlerta.RECONOCIDA
    assert alerta.esta_abierta()
    alerta.estado = EstadoAlerta.CERRADA
    assert not alerta.esta_abierta()
