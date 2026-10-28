"""Pruebas de sesiones contra un Redis real.

Se saltean si Redis no esta arriba, igual que el resto de las pruebas de
integracion del proyecto.
"""

import time
from datetime import timedelta
from uuid import uuid4

import pytest
from redis import Redis
from redis.exceptions import ConnectionError, TimeoutError

from logistica.config import settings
from logistica.domain.sesion import EstadoSesion, Sesion
from logistica.exceptions import ValidacionError
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
    sesion = servicio.iniciar(usuario_id)
    clave = f"sesion:{sesion.id}"

    try:
        guardada = servicio.consultar(sesion.id)

        # D33: lo que vuelve es la entidad, no el hash de Redis.
        assert isinstance(guardada, Sesion)
        assert guardada.usuario_id == usuario_id
        assert guardada.estado is EstadoSesion.ACTIVA
        assert guardada.fecha_fin - guardada.fecha_inicio == timedelta(seconds=300)

        # El TTL del motor sale de fecha_fin, no de un parametro aparte.
        assert 0 < cliente_redis.ttl(clave) <= 300

        assert servicio.cerrar(sesion.id) is True
        assert servicio.consultar(sesion.id) is None
        assert servicio.cerrar(sesion.id) is False
    finally:
        cliente_redis.delete(clave)


def test_listar_activas_encuentra_la_sesion_recien_abierta(cliente_redis):
    servicio = SesionService(RedisSesionRepository(cliente_redis), ttl_segundos=300)
    sesion = servicio.iniciar(uuid4())
    try:
        activas = servicio.listar_activas()
        assert sesion.id in [s.id for s in activas]
        assert all(isinstance(s, Sesion) for s in activas)
    finally:
        cliente_redis.delete(f"sesion:{sesion.id}")


def test_duracion_invalida(cliente_redis):
    repositorio = RedisSesionRepository(cliente_redis)

    # D29: el proyecto usa sus propias excepciones, no las de Python.
    with pytest.raises(ValidacionError):
        SesionService(repositorio, ttl_segundos=0)

    with pytest.raises(ValidacionError):
        SesionService(repositorio, ttl_segundos=-1)


def test_sesion_vence_realmente(cliente_redis):
    """Lo que justifica guardar las sesiones en Redis: vencen solas, sin que
    ningun proceso las barra."""
    servicio = SesionService(RedisSesionRepository(cliente_redis), ttl_segundos=1)
    sesion = servicio.iniciar(uuid4())
    try:
        assert servicio.consultar(sesion.id) is not None
        limite = time.monotonic() + 3
        while servicio.consultar(sesion.id) is not None and time.monotonic() < limite:
            time.sleep(0.05)
        assert servicio.consultar(sesion.id) is None
        assert servicio.cerrar(sesion.id) is False
    finally:
        cliente_redis.delete(f"sesion:{sesion.id}")
