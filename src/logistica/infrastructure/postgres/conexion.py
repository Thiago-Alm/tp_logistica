"""Conexion a PostgreSQL y traduccion de sus errores a errores del dominio."""
import logging
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

import psycopg

from logistica.config import Settings
from logistica.exceptions import ConflictoDeDatos, ErrorDePersistencia, ValidacionError

log = logging.getLogger(__name__)

T = TypeVar("T")


def armar_dsn(settings: Settings) -> str:
    return (
        f"host={settings.postgres_host} port={settings.postgres_port} "
        f"user={settings.postgres_user} password={settings.postgres_password} "
        f"dbname={settings.postgres_db}"
    )


def conectar(settings: Settings) -> psycopg.Connection:
    """Abre una conexion. La transaccion la maneja la Unidad de Trabajo, por eso
    autocommit queda en False."""
    try:
        return psycopg.connect(armar_dsn(settings), connect_timeout=10)
    except psycopg.Error as error:
        raise ErrorDePersistencia(f"No se pudo conectar a PostgreSQL: {error}") from error


def traducir_errores(funcion: Callable[..., T]) -> Callable[..., T]:
    """Convierte los errores de psycopg en errores del dominio.

    Las capas de arriba no tienen por que saber que existe psycopg: si la
    aplicacion cambiara de motor, los `except` del servicio seguirian valiendo.
    """

    @wraps(funcion)
    def envoltorio(*args: Any, **kwargs: Any) -> T:
        try:
            return funcion(*args, **kwargs)
        except psycopg.errors.UniqueViolation as error:
            log.warning("Violacion de unicidad en %s: %s", funcion.__name__, error)
            raise ConflictoDeDatos(_detalle(error)) from error
        except psycopg.errors.ForeignKeyViolation as error:
            log.warning("Violacion de clave foranea en %s: %s", funcion.__name__, error)
            raise ValidacionError(_detalle(error)) from error
        except psycopg.errors.CheckViolation as error:
            log.warning("Violacion de CHECK en %s: %s", funcion.__name__, error)
            raise ValidacionError(_detalle(error)) from error
        except psycopg.Error as error:
            log.exception("Fallo de PostgreSQL en %s", funcion.__name__)
            raise ErrorDePersistencia(str(error)) from error

    return envoltorio


def _detalle(error: psycopg.Error) -> str:
    """El nombre de la restriccion dice mas que el mensaje crudo de Postgres."""
    restriccion = getattr(error.diag, "constraint_name", None)
    return f"Restriccion violada: {restriccion}" if restriccion else str(error)
