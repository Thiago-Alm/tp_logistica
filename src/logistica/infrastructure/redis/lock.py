"""Lock distribuido sobre Redis para los procesos periodicos (D14).

Sin esto, dos ejecuciones simultaneas del mismo proceso hacen el trabajo dos
veces. En el worker de sincronizacion eso es tolerable, porque los proyectores
son idempotentes; en la generacion automatica de facturas NO lo es: saldrian
facturas duplicadas.

Se usa `SET clave valor NX EX segundos`, que es atomica: o la clave se crea, o
ya existia. No hay ventana entre "fijarse si existe" y "crearla".

El vencimiento no es opcional: si el proceso que tomo el lock muere sin
liberarlo, sin TTL la clave quedaria para siempre y nadie podria volver a
ejecutar ese proceso.
"""
import logging
import secrets
from contextlib import contextmanager

import redis

from logistica.config import Settings
from logistica.exceptions import ErrorDePersistencia

log = logging.getLogger(__name__)

PREFIJO = "lock:proceso:"

# Libera el lock solo si sigue siendo nuestro. Hace falta que sea un script de
# Lua porque "leer el valor y despues borrar" son dos operaciones: entre una y
# otra el lock podria vencer y tomarlo otro proceso, y le estariamos borrando
# el suyo.
LIBERAR = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
else
    return 0
end
"""


class LockNoDisponible(Exception):
    """Otro proceso tiene el lock. No es un error: es el caso esperado."""


def conectar(settings: Settings) -> redis.Redis:
    try:
        cliente = redis.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            socket_timeout=5,
            decode_responses=True,
        )
        cliente.ping()
        return cliente
    except redis.RedisError as error:
        raise ErrorDePersistencia(f"No se pudo conectar a Redis: {error}") from error


@contextmanager
def lock_de_proceso(cliente: redis.Redis, nombre: str, segundos: int = 300):
    """Toma el lock de un proceso, o lanza LockNoDisponible si ya esta tomado.

        with lock_de_proceso(cliente, "sincronizacion"):
            worker.procesar_tanda()

    El `token` identifica a esta ejecucion para que, al salir, solo se libere
    el lock si todavia es el nuestro.
    """
    clave = f"{PREFIJO}{nombre}"
    token = secrets.token_hex(16)
    try:
        tomado = cliente.set(clave, token, nx=True, ex=segundos)
    except redis.RedisError as error:
        raise ErrorDePersistencia(f"Fallo al tomar el lock {nombre}: {error}") from error

    if not tomado:
        raise LockNoDisponible(f"El proceso '{nombre}' ya se esta ejecutando")

    log.debug("Lock '%s' tomado por %s segundos", nombre, segundos)
    try:
        yield token
    finally:
        try:
            cliente.eval(LIBERAR, 1, clave, token)
            log.debug("Lock '%s' liberado", nombre)
        except redis.RedisError as error:
            # No se relanza: el trabajo ya se hizo, y el TTL libera el lock solo.
            log.warning("No se pudo liberar el lock '%s': %s", nombre, error)
