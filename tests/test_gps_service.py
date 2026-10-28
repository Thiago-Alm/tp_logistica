from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from logistica.domain.lectura import Posicion
from logistica.exceptions import NoEncontrado, ValidacionError
from logistica.services.gps_service import GPSService

ART = timezone(timedelta(hours=-3))


class _Contenedores:
    def __init__(self, existentes):
        self._existentes = existentes

    def obtener(self, contenedor_id):
        return object() if contenedor_id in self._existentes else None


class _Uow:
    def __init__(self, existentes):
        self.contenedores = _Contenedores(existentes)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Lecturas:
    def __init__(self, posiciones):
        self.posiciones = posiciones
        self.llamadas = []

    def posiciones_de_contenedor(self, contenedor_id, desde, hasta):
        self.llamadas.append((contenedor_id, desde, hasta))
        return self.posiciones


def _servicio(contenedor_id, posiciones=()):
    lecturas = _Lecturas(list(posiciones))
    return GPSService(lecturas, _Uow({contenedor_id})), lecturas


def test_devuelve_el_recorrido_y_consulta_en_utc():
    cid = uuid4()
    posicion = Posicion(cid, uuid4(), datetime.now(timezone.utc), -34.6, -58.4)
    servicio, lecturas = _servicio(cid, [posicion])
    desde = datetime(2026, 10, 28, 8, tzinfo=ART)

    assert servicio.recorrido(cid, desde, desde + timedelta(hours=4)) == [posicion]
    _, desde_utc, hasta_utc = lecturas.llamadas[0]
    assert desde_utc.tzinfo == timezone.utc and desde_utc.hour == 11
    assert hasta_utc.hour == 15


def test_rechaza_fechas_sin_zona_horaria():
    cid = uuid4()
    servicio, _ = _servicio(cid)
    with pytest.raises(ValidacionError):
        servicio.recorrido(cid, datetime(2026, 10, 28), datetime.now(timezone.utc))


def test_rechaza_intervalo_invertido():
    cid = uuid4()
    servicio, _ = _servicio(cid)
    hasta = datetime(2026, 10, 28, tzinfo=ART)
    with pytest.raises(ValidacionError):
        servicio.recorrido(cid, hasta + timedelta(hours=1), hasta)


def test_rechaza_intervalo_de_mas_de_31_dias():
    cid = uuid4()
    servicio, _ = _servicio(cid)
    desde = datetime(2026, 9, 1, tzinfo=ART)
    with pytest.raises(ValidacionError):
        servicio.recorrido(cid, desde, desde + timedelta(days=32))


def test_contenedor_inexistente():
    servicio, lecturas = _servicio(uuid4())
    desde = datetime(2026, 10, 28, tzinfo=ART)
    with pytest.raises(NoEncontrado):
        servicio.recorrido(uuid4(), desde, desde + timedelta(hours=1))
    assert lecturas.llamadas == []
