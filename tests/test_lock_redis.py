"""Tests del lock distribuido contra Redis real.

Se saltean solos si Redis no esta disponible.
"""
import pytest

from logistica.config import settings
from logistica.exceptions import ErrorDePersistencia
from logistica.infrastructure.redis.lock import (
    PREFIJO,
    LockNoDisponible,
    conectar,
    lock_de_proceso,
)

NOMBRE = "proceso_de_prueba"
OTRO = "otro_proceso_de_prueba"


@pytest.fixture
def cliente():
    try:
        r = conectar(settings)
    except ErrorDePersistencia:
        pytest.skip("Redis no disponible: docker compose up -d")
    r.delete(f"{PREFIJO}{NOMBRE}", f"{PREFIJO}{OTRO}")
    yield r
    r.delete(f"{PREFIJO}{NOMBRE}", f"{PREFIJO}{OTRO}")


def test_se_toma_y_se_libera(cliente):
    with lock_de_proceso(cliente, NOMBRE):
        assert cliente.get(f"{PREFIJO}{NOMBRE}") is not None
    assert cliente.get(f"{PREFIJO}{NOMBRE}") is None


def test_no_se_puede_tomar_dos_veces(cliente):
    """Es el caso que impide que dos ejecuciones del proceso de facturacion
    generen facturas duplicadas."""
    def tomar_de_nuevo():
        with lock_de_proceso(cliente, NOMBRE):
            pass

    with lock_de_proceso(cliente, NOMBRE), pytest.raises(LockNoDisponible):
        tomar_de_nuevo()


def test_procesos_distintos_no_se_bloquean(cliente):
    with lock_de_proceso(cliente, NOMBRE), lock_de_proceso(cliente, OTRO):
        assert cliente.get(f"{PREFIJO}{NOMBRE}") is not None
        assert cliente.get(f"{PREFIJO}{OTRO}") is not None


def test_el_lock_tiene_vencimiento(cliente):
    """Sin TTL, un proceso que muere sin liberar dejaria el lock para siempre."""
    with lock_de_proceso(cliente, NOMBRE, segundos=120):
        ttl = cliente.ttl(f"{PREFIJO}{NOMBRE}")
    assert 0 < ttl <= 120


def test_se_libera_aunque_la_tarea_falle(cliente):
    with pytest.raises(RuntimeError), lock_de_proceso(cliente, NOMBRE):
        raise RuntimeError("la tarea exploto")
    assert cliente.get(f"{PREFIJO}{NOMBRE}") is None


def test_cada_ejecucion_tiene_su_propio_token(cliente):
    with lock_de_proceso(cliente, NOMBRE) as primero:
        pass
    with lock_de_proceso(cliente, NOMBRE) as segundo:
        pass
    assert primero != segundo


def test_no_libera_el_lock_de_otro(cliente):
    """Si el lock vencio y lo tomo otro proceso, al salir no se le debe borrar.

    Por eso la liberacion es un script de Lua que compara el token antes de
    borrar, y no un simple DELETE.
    """
    ajeno = "token-de-otro-proceso"
    try:
        with lock_de_proceso(cliente, NOMBRE):
            # Simula que el lock vencio y lo tomo otra instancia.
            cliente.set(f"{PREFIJO}{NOMBRE}", ajeno)
    except LockNoDisponible:  # pragma: no cover
        pytest.fail("no deberia fallar al tomar el lock")
    assert cliente.get(f"{PREFIJO}{NOMBRE}") == ajeno
