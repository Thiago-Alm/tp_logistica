"""Tests de integracion de LecturaRepository contra Cassandra.

Necesitan el contenedor de Cassandra arriba y el keyspace `logistica` creado
(scripts/cassandra/cassandra_modelo.cql). Si no hay conexion, se saltean.
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from logistica.config import settings
from logistica.domain.lectura import Lectura
from logistica.exceptions import ErrorDePersistencia, ValidacionError
from logistica.infrastructure.cassandra.conexion import cerrar, conectar
from logistica.infrastructure.cassandra.lectura_repository import (
    CassandraLecturaRepository,
)

UTC = timezone.utc
AHORA = datetime(2026, 10, 19, 12, 0, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def sesion():
    try:
        s = conectar(settings)
    except ErrorDePersistencia:
        pytest.skip("Cassandra no esta disponible")
    yield s
    cerrar(s)


@pytest.fixture
def repo(sesion):
    try:
        return CassandraLecturaRepository(sesion, ahora=lambda: AHORA)
    except ErrorDePersistencia:
        pytest.skip("Faltan las tablas: aplicar scripts/cassandra/cassandra_modelo.cql")


@pytest.fixture
def ids(sesion):
    """Ids nuevos por test, para no pisar datos ajenos. Al terminar se borran las
    particiones de los ultimos dias."""
    sensor_id, contenedor_id = uuid4(), uuid4()
    yield sensor_id, contenedor_id
    for atras in range(5):
        dia = (AHORA - timedelta(days=atras)).date()
        sesion.execute(
            "DELETE FROM lecturas_por_sensor WHERE sensor_id = %s AND dia = %s",
            (sensor_id, dia),
        )
        sesion.execute(
            "DELETE FROM recorrido_por_contenedor WHERE contenedor_id = %s AND dia = %s",
            (contenedor_id, dia),
        )


def _lectura(ids, momento, temperatura=5.5, envio_id=None) -> Lectura:
    sensor_id, contenedor_id = ids
    return Lectura(
        sensor_id=sensor_id,
        contenedor_id=contenedor_id,
        momento=momento,
        temperatura=temperatura,
        humedad=60.0,
        vibracion=0.25,
        latitud=-34.5,
        longitud=-58.25,
        bateria=90,
        envio_id=envio_id,
    )


def test_guardar_escribe_en_las_dos_tablas(repo, ids):
    envio_id = uuid4()
    momento = AHORA.replace(hour=10)
    repo.guardar(_lectura(ids, momento, envio_id=envio_id))

    lecturas = repo.listar_por_sensor(ids[0], momento, momento)
    assert len(lecturas) == 1
    assert lecturas[0].temperatura == 5.5
    assert lecturas[0].momento == momento

    posiciones = repo.posiciones_de_contenedor(ids[1], momento, momento)
    assert len(posiciones) == 1
    assert posiciones[0].envio_id == envio_id
    assert (posiciones[0].latitud, posiciones[0].longitud) == (-34.5, -58.25)


def test_guardar_es_idempotente(repo, ids):
    momento = AHORA.replace(hour=10)
    repo.guardar(_lectura(ids, momento))
    repo.guardar(_lectura(ids, momento))
    assert len(repo.listar_por_sensor(ids[0], momento, momento)) == 1


def test_una_lectura_sin_envio_se_guarda_y_la_posicion_queda_sin_envio(repo, ids):
    momento = AHORA.replace(hour=10)
    repo.guardar(_lectura(ids, momento, envio_id=None))
    assert repo.posiciones_de_contenedor(ids[1], momento, momento)[0].envio_id is None


def test_listar_por_sensor_sale_en_orden_cronologico(repo, ids):
    base = AHORA.replace(hour=8)
    for minutos in (30, 0, 15):  # se guardan desordenadas a proposito
        repo.guardar(_lectura(ids, base + timedelta(minutes=minutos), temperatura=minutos))
    momentos = [l.momento for l in repo.listar_por_sensor(ids[0], base, base + timedelta(hours=1))]
    assert momentos == sorted(momentos)
    assert len(momentos) == 3


def test_listar_por_sensor_respeta_el_rango(repo, ids):
    base = AHORA.replace(hour=8)
    for minutos in (0, 10, 20, 30):
        repo.guardar(_lectura(ids, base + timedelta(minutes=minutos)))
    resultado = repo.listar_por_sensor(
        ids[0], base + timedelta(minutes=10), base + timedelta(minutes=20)
    )
    assert [l.momento for l in resultado] == [
        base + timedelta(minutes=10),
        base + timedelta(minutes=20),
    ]


def test_un_rango_que_cruza_la_medianoche_lee_las_dos_particiones(repo, ids):
    antes = datetime(2026, 10, 18, 23, 59, 0, tzinfo=UTC)
    despues = datetime(2026, 10, 19, 0, 1, 0, tzinfo=UTC)
    repo.guardar(_lectura(ids, antes))
    repo.guardar(_lectura(ids, despues))
    resultado = repo.listar_por_sensor(
        ids[0], antes - timedelta(hours=1), despues + timedelta(hours=1)
    )
    assert [l.momento for l in resultado] == [antes, despues]


def test_ultimas_devuelve_las_mas_recientes_primero_y_cruza_dias(repo, ids):
    repo.guardar(_lectura(ids, datetime(2026, 10, 19, 10, 0, tzinfo=UTC)))
    repo.guardar(_lectura(ids, datetime(2026, 10, 19, 11, 0, tzinfo=UTC)))
    repo.guardar(_lectura(ids, datetime(2026, 10, 18, 22, 0, tzinfo=UTC)))

    tres = repo.ultimas(ids[0], 3)
    assert [l.momento.hour for l in tres] == [11, 10, 22]

    dos = repo.ultimas(ids[0], 2)
    assert [l.momento.hour for l in dos] == [11, 10]


def test_guardar_lote(repo, ids):
    base = AHORA.replace(hour=6)
    lecturas = [_lectura(ids, base + timedelta(minutes=i)) for i in range(150)]
    repo.guardar_lote(lecturas)
    assert len(repo.listar_por_sensor(ids[0], base, base + timedelta(hours=3))) == 150


def test_cantidad_invalida_en_ultimas(repo, ids):
    with pytest.raises(ValidacionError):
        repo.ultimas(ids[0], 0)


def test_rango_invertido(repo, ids):
    with pytest.raises(ValidacionError):
        repo.listar_por_sensor(ids[0], AHORA, AHORA - timedelta(hours=1))


def test_rango_demasiado_largo(repo, ids):
    with pytest.raises(ValidacionError):
        repo.listar_por_sensor(ids[0], AHORA - timedelta(days=40), AHORA)
