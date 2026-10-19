"""Tests del dominio de Incidente. No necesitan ninguna base (D3)."""
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from logistica.domain.incidente import (
    ContextoEnvio,
    EstadoIncidente,
    Incidente,
    SeveridadIncidente,
    TipoIncidente,
)
from logistica.exceptions import ValidacionError

FECHA = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)


def _contexto() -> ContextoEnvio:
    return ContextoEnvio(
        cliente_id=uuid4(),
        origen="BUE",
        destino="HAM",
        pais_origen="Argentina",
        pais_destino="Alemania",
    )


def _incidente(**cambios) -> Incidente:
    datos = dict(
        id=uuid4(),
        envio_id=uuid4(),
        tipo=TipoIncidente.DEMORA,
        severidad=SeveridadIncidente.MEDIA,
        descripcion="Retraso en aduana",
        contexto_envio=_contexto(),
        fecha=FECHA,
    )
    datos.update(cambios)
    return Incidente(**datos)


def test_un_incidente_nuevo_empieza_abierto_con_su_primer_cambio_en_el_historial():
    incidente = _incidente()
    assert incidente.estado is EstadoIncidente.ABIERTO
    assert [c.estado for c in incidente.historial_estados] == [EstadoIncidente.ABIERTO]
    assert incidente.historial_estados[0].fecha == FECHA


def test_la_descripcion_no_puede_estar_vacia():
    with pytest.raises(ValidacionError):
        _incidente(descripcion="   ")


def test_la_ruta_se_deriva_de_origen_y_destino():
    assert _contexto().ruta == "BUE->HAM"


def test_pasar_a_valida_la_transicion_y_agrega_al_historial():
    incidente = _incidente()
    incidente.pasar_a(EstadoIncidente.EN_ANALISIS)
    incidente.pasar_a(EstadoIncidente.RESUELTO)
    assert incidente.estado is EstadoIncidente.RESUELTO
    assert [c.estado for c in incidente.historial_estados] == [
        EstadoIncidente.ABIERTO,
        EstadoIncidente.EN_ANALISIS,
        EstadoIncidente.RESUELTO,
    ]


def test_no_se_puede_saltar_una_transicion_invalida():
    incidente = _incidente()
    with pytest.raises(ValidacionError):
        incidente.pasar_a(EstadoIncidente.CERRADO)
    # El estado no cambia si la transicion falla.
    assert incidente.estado is EstadoIncidente.ABIERTO
    assert len(incidente.historial_estados) == 1


def test_un_incidente_resuelto_se_puede_reabrir():
    incidente = _incidente()
    incidente.pasar_a(EstadoIncidente.RESUELTO)
    incidente.pasar_a(EstadoIncidente.ABIERTO)
    assert incidente.estado is EstadoIncidente.ABIERTO


def test_un_incidente_cerrado_es_final():
    incidente = _incidente()
    incidente.pasar_a(EstadoIncidente.RESUELTO)
    incidente.pasar_a(EstadoIncidente.CERRADO)
    assert incidente.estado.es_final()
    with pytest.raises(ValidacionError):
        incidente.pasar_a(EstadoIncidente.ABIERTO)


def test_abiertos_son_abierto_y_en_analisis():
    assert _incidente().esta_abierto()
    en_analisis = _incidente()
    en_analisis.pasar_a(EstadoIncidente.EN_ANALISIS)
    assert en_analisis.esta_abierto()
    resuelto = _incidente()
    resuelto.pasar_a(EstadoIncidente.RESUELTO)
    assert not resuelto.esta_abierto()


def test_el_historial_debe_terminar_en_el_estado_actual():
    otro = _incidente()
    otro.pasar_a(EstadoIncidente.RESUELTO)
    with pytest.raises(ValidacionError):
        _incidente(
            estado=EstadoIncidente.ABIERTO,
            historial_estados=otro.historial_estados,
        )
