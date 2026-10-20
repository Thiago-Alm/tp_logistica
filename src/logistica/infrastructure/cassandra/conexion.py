"""Conexion a Cassandra y traduccion de sus errores a errores del dominio."""
import logging
import sys
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

from cassandra.cluster import Cluster, NoHostAvailable, Session

from cassandra import DriverException
from logistica.config import Settings
from logistica.exceptions import ErrorDePersistencia

log = logging.getLogger(__name__)

T = TypeVar("T")

try:
    # Python 3.12 ya no trae asyncore, que es el reactor por defecto de algunas
    # versiones del driver: ahi hace falta el de asyncio.
    if sys.version_info >= (3, 12):
        from cassandra.io.asyncioreactor import AsyncioConnection
    else:
        AsyncioConnection = None
except ImportError:  # pragma: no cover
    AsyncioConnection = None


def conectar(settings: Settings) -> Session:
    """Abre una sesion sobre el keyspace configurado. Cassandra no tiene
    transacciones entre tablas, asi que no hay Unidad de Trabajo: la sesion vive
    mientras viva la aplicacion."""
    opciones: dict[str, Any] = {"port": settings.cassandra_port}
    if AsyncioConnection is not None:
        opciones["connection_class"] = AsyncioConnection
    try:
        cluster = Cluster([settings.cassandra_host], **opciones)
        return cluster.connect(settings.cassandra_keyspace)
    except (NoHostAvailable, DriverException) as error:
        raise ErrorDePersistencia(f"No se pudo conectar a Cassandra: {error}") from error


def cerrar(sesion: Session) -> None:
    sesion.cluster.shutdown()


def traducir_errores(funcion: Callable[..., T]) -> Callable[..., T]:
    """Convierte los errores del driver de Cassandra en errores del dominio.

    Cassandra no tiene claves unicas ni foraneas que se puedan violar (una
    escritura repetida pisa la fila), asi que aca solo hay fallos de
    persistencia: nodo caido, timeout, consulta invalida.
    """

    @wraps(funcion)
    def envoltorio(*args: Any, **kwargs: Any) -> T:
        try:
            return funcion(*args, **kwargs)
        except (NoHostAvailable, DriverException) as error:
            log.exception("Fallo de Cassandra en %s", funcion.__name__)
            raise ErrorDePersistencia(str(error)) from error

    return envoltorio
