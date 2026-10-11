from uuid import uuid4

import pytest

from logistica.domain.contenedor import Contenedor, EstadoContenedor
from logistica.exceptions import ValidacionError


def nuevo_contenedor(**cambios) -> Contenedor:
    datos = dict(
        id=uuid4(),
        codigo_iso="MSKU1234567",
        tipo="DRY",
        capacidad=33.2,
        estado=EstadoContenedor.DISPONIBLE,
    )
    datos.update(cambios)
    return Contenedor(**datos)


def test_un_contenedor_valido_se_construye():
    assert nuevo_contenedor().estado is EstadoContenedor.DISPONIBLE


def test_el_codigo_iso_debe_tener_once_caracteres():
    with pytest.raises(ValidacionError):
        nuevo_contenedor(codigo_iso="CONT-001")


def test_la_capacidad_debe_ser_positiva():
    with pytest.raises(ValidacionError):
        nuevo_contenedor(capacidad=0)


def test_solo_un_contenedor_disponible_puede_asignarse():
    assert EstadoContenedor.DISPONIBLE.puede_asignarse()
    assert not EstadoContenedor.ASIGNADO.puede_asignarse()
    assert not EstadoContenedor.EN_MANTENIMIENTO.puede_asignarse()


def test_los_estados_ocupados_son_asignado_y_en_transito():
    ocupados = {e for e in EstadoContenedor if e.esta_ocupado()}
    assert ocupados == {EstadoContenedor.ASIGNADO, EstadoContenedor.EN_TRANSITO}
