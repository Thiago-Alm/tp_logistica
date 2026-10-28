"""Pruebas de sesiones usando Redis."""

import time
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from redis import Redis
from redis.exceptions import ConnectionError, TimeoutError

from logistica.config import settings
from logistica.infrastructure.redis.sesion_repository import RedisSesionRepository
from logistica.services.sesion_service import SesionService


@pytest.fixture
def cliente_redis():
    cliente = Redis(
        host=settings.redis_host, port=settings.redis_port,
        socket_connect_timeout=1, socket_timeout=1,
    )
    try:
        try:
            cliente.ping()
        except (ConnectionError, TimeoutError):
            pytest.skip("Redis no disponible: docker compose up -d redis")
        yield cliente
    finally:
        cliente.close()


def test_crear_consultar_y_cerrar_sesion(cliente_redis):
    repositorio = RedisSesionRepository(cliente_redis)
    servicio = SesionService(repositorio, ttl_segundos=300)
    usuario_id = uuid4()
    sesion_id = servicio.iniciar(usuario_id)
    clave = f"sesion:{sesion_id}"

    try:
        datos = servicio.consultar(sesion_id)

        assert datos is not None
        assert datos["usuario_id"] == str(usuario_id)
        assert datos["estado"] == "ACTIVA"

        inicio = datetime.fromisoformat(datos["fecha_inicio"])
        fin = datetime.fromisoformat(datos["fecha_fin"])
        assert fin - inicio == timedelta(seconds=300)
        assert 0 < cliente_redis.ttl(clave) <= 300

        assert servicio.cerrar(sesion_id) is True
        assert servicio.consultar(sesion_id) is None
        assert servicio.cerrar(sesion_id) is False
    finally:
        cliente_redis.delete(clave)


def test_duracion_invalida(cliente_redis):
    repositorio = RedisSesionRepository(cliente_redis)

    with pytest.raises(ValueError):
        SesionService(repositorio, ttl_segundos=0)

    with pytest.raises(ValueError):
        SesionService(repositorio, ttl_segundos=-1)


def test_sesion_vence_realmente(cliente_redis):
    servicio = SesionService(RedisSesionRepository(cliente_redis), ttl_segundos=1)
    sesion_id = servicio.iniciar(uuid4())
    try:
        assert servicio.consultar(sesion_id) is not None
        limite = time.monotonic() + 3
        while servicio.consultar(sesion_id) is not None and time.monotonic() < limite:
            time.sleep(0.05)
        assert servicio.consultar(sesion_id) is None
        assert servicio.cerrar(sesion_id) is False
    finally:
        cliente_redis.delete(f"sesion:{sesion_id}")
