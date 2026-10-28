"""Deteccion de sensores inactivos con el heartbeat de Redis (D43).

Las pruebas del servicio usan un heartbeat en memoria y un reloj fijo. Las del
repositorio van contra un Redis real y se saltean si no esta arriba.
"""

from uuid import uuid4

import pytest
from redis import Redis
from redis.exceptions import ConnectionError, TimeoutError

from logistica.config import settings
from logistica.exceptions import ErrorDePersistencia, ValidacionError
from logistica.infrastructure.redis.heartbeat_repository import (
    CLAVE_HEARTBEAT,
    RedisHeartbeatRepository,
)
from logistica.repositories.heartbeat_repository import HeartbeatRepository
from logistica.services.deteccion_inactividad_service import (
    DeteccionInactividadService,
    SensorMonitoreado,
)

AHORA = 1_000_000.0


class _HeartbeatEnMemoria(HeartbeatRepository):
    def __init__(self, senales=None, falla=False):
        self._senales = dict(senales or {})
        self._falla = falla

    def registrar(self, sensor_id, timestamp):
        self._senales[sensor_id] = timestamp

    def ultimo_reporte(self, sensor_id):
        if self._falla:
            raise ErrorDePersistencia("Redis caido")
        return self._senales.get(sensor_id)


def _verificar(senales, *sensores, falla=False):
    servicio = DeteccionInactividadService(
        heartbeat=_HeartbeatEnMemoria(senales, falla),
        cargar_sensores=lambda: list(sensores),
        reloj=lambda: AHORA,
    )
    return servicio.verificar()


# --- Servicio ----------------------------------------------------------------


def test_un_sensor_que_reporto_dentro_del_intervalo_esta_activo():
    sensor = SensorMonitoreado(uuid4(), 60)
    [resultado] = _verificar({sensor.sensor_id: AHORA - 30}, sensor)
    assert resultado.estado == "ACTIVO"
    assert resultado.segundos_sin_reportar == 30


def test_un_sensor_que_supero_el_intervalo_esta_inactivo():
    sensor = SensorMonitoreado(uuid4(), 60)
    [resultado] = _verificar({sensor.sensor_id: AHORA - 61}, sensor)
    assert resultado.estado == "INACTIVO"
    assert resultado.segundos_sin_reportar == 61


def test_justo_en_el_limite_todavia_esta_activo():
    sensor = SensorMonitoreado(uuid4(), 60)
    [resultado] = _verificar({sensor.sensor_id: AHORA - 60}, sensor)
    assert resultado.estado == "ACTIVO"


def test_un_sensor_sin_heartbeat_queda_sin_datos_y_no_inactivo():
    """Puede ser un sensor nuevo: no hay que alertar como si se hubiera caido."""
    sensor = SensorMonitoreado(uuid4(), 60)
    [resultado] = _verificar({}, sensor)
    assert resultado.estado == "SIN_DATOS"
    assert resultado.segundos_sin_reportar is None


def test_un_heartbeat_en_el_futuro_marca_reloj_invalido():
    sensor = SensorMonitoreado(uuid4(), 60)
    [resultado] = _verificar({sensor.sensor_id: AHORA + 10}, sensor)
    assert resultado.estado == "RELOJ_INVALIDO"


def test_cada_sensor_se_evalua_con_su_propio_intervalo():
    rapido = SensorMonitoreado(uuid4(), 10)
    lento = SensorMonitoreado(uuid4(), 300)
    resultados = _verificar(
        {rapido.sensor_id: AHORA - 60, lento.sensor_id: AHORA - 60}, rapido, lento
    )
    assert [r.estado for r in resultados] == ["INACTIVO", "ACTIVO"]


@pytest.mark.parametrize("intervalo", [0, -5])
def test_un_intervalo_invalido_se_rechaza(intervalo):
    sensor = SensorMonitoreado(uuid4(), intervalo)
    with pytest.raises(ValidacionError):
        _verificar({sensor.sensor_id: AHORA}, sensor)


def test_un_redis_caido_no_se_confunde_con_inactividad():
    """Si Redis falla, el error sube: no se marca a todos los sensores inactivos."""
    sensor = SensorMonitoreado(uuid4(), 60)
    with pytest.raises(ErrorDePersistencia):
        _verificar({}, sensor, falla=True)


# --- Repositorio contra Redis real -------------------------------------------


@pytest.fixture
def heartbeat():
    cliente = Redis(
        host=settings.redis_host, port=settings.redis_port,
        socket_connect_timeout=1, socket_timeout=1,
    )
    creados = []
    try:
        try:
            cliente.ping()
        except (ConnectionError, TimeoutError):
            pytest.skip("Redis no disponible: docker compose up -d redis")
        yield RedisHeartbeatRepository(cliente), creados
    finally:
        # La clave es la misma que usa el simulador: se borran solo los sensores
        # de la prueba, no el sorted set entero.
        if creados:
            cliente.zrem(CLAVE_HEARTBEAT, *[str(s) for s in creados])
        cliente.close()


def test_registrar_y_leer_el_ultimo_reporte(heartbeat):
    repositorio, creados = heartbeat
    sensor_id = uuid4()
    creados.append(sensor_id)

    repositorio.registrar(sensor_id, 1000.0)
    assert repositorio.ultimo_reporte(sensor_id) == 1000.0


def test_una_senal_vieja_no_pisa_una_mas_nueva(heartbeat):
    """Con lecturas que llegan desordenadas, el heartbeat no retrocede."""
    repositorio, creados = heartbeat
    sensor_id = uuid4()
    creados.append(sensor_id)

    repositorio.registrar(sensor_id, 2000.0)
    repositorio.registrar(sensor_id, 1500.0)
    assert repositorio.ultimo_reporte(sensor_id) == 2000.0

    repositorio.registrar(sensor_id, 2500.0)
    assert repositorio.ultimo_reporte(sensor_id) == 2500.0


def test_un_sensor_que_nunca_reporto_devuelve_none(heartbeat):
    repositorio, _ = heartbeat
    assert repositorio.ultimo_reporte(uuid4()) is None
