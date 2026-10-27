from datetime import datetime, timezone
from uuid import uuid4

import pytest

from logistica.domain.evento_logistico import EventoLogistico, TipoEventoLogistico
from logistica.exceptions import ValidacionError

MOMENTO = datetime(2026, 3, 15, 10, 30, tzinfo=timezone.utc)


def nuevo(**cambios) -> EventoLogistico:
    datos = dict(
        id=uuid4(),
        envio_id=uuid4(),
        tipo=TipoEventoLogistico.EN_TRANSITO,
        momento=MOMENTO,
        descripcion="El envio salio en transito",
    )
    datos.update(cambios)
    return EventoLogistico(**datos)


def test_un_evento_valido_se_construye():
    assert nuevo().tipo is TipoEventoLogistico.EN_TRANSITO


def test_la_descripcion_es_obligatoria():
    with pytest.raises(ValidacionError):
        nuevo(descripcion="   ")


def test_la_posicion_va_completa_o_no_va():
    """Media coordenada no sirve para nada: o estan las dos o ninguna."""
    with pytest.raises(ValidacionError):
        nuevo(latitud=-34.6)
    with pytest.raises(ValidacionError):
        nuevo(longitud=-58.4)
    assert nuevo(latitud=-34.6, longitud=-58.4).tiene_posicion()


@pytest.mark.parametrize(("lat", "lon"), [(91, 0), (-91, 0), (0, 181), (0, -181)])
def test_las_coordenadas_tienen_rango(lat, lon):
    with pytest.raises(ValidacionError):
        nuevo(latitud=lat, longitud=lon)


def test_el_anio_mes_se_deriva_del_momento():
    """Es la clave de particion de eventos_por_contenedor. Se deriva en vez de
    guardarse, para que no pueda contradecir al momento."""
    assert nuevo().anio_mes == "2026-03"
    assert nuevo(momento=datetime(2025, 12, 31, 23, 0, tzinfo=timezone.utc)).anio_mes == "2025-12"


def test_un_momento_sin_zona_se_toma_como_utc():
    evento = nuevo(momento=datetime(2026, 3, 15, 10, 30))
    assert evento.momento_utc.tzinfo is timezone.utc
    assert evento.anio_mes == "2026-03"


def test_los_tipos_de_estado_son_automaticos():
    for tipo in (
        TipoEventoLogistico.CARGA_INICIADA,
        TipoEventoLogistico.EN_TRANSITO,
        TipoEventoLogistico.EN_PUERTO,
        TipoEventoLogistico.ENTREGADO,
        TipoEventoLogistico.CANCELADO,
    ):
        assert tipo.es_automatico()


def test_los_tipos_que_carga_una_persona_no_son_automaticos():
    for tipo in (
        TipoEventoLogistico.ADUANA,
        TipoEventoLogistico.RETRASO,
        TipoEventoLogistico.DESCARGA,
    ):
        assert not tipo.es_automatico()


def test_todos_los_valores_van_en_mayusculas():
    """D19: el mismo valor se escribe igual en los cinco motores."""
    for tipo in TipoEventoLogistico:
        assert tipo.value == tipo.name == tipo.value.upper()
