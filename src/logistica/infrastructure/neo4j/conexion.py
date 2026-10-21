"""Conexion a Neo4j y traduccion de sus errores a errores del dominio."""
import logging
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

from neo4j import Driver, GraphDatabase
from neo4j.exceptions import Neo4jError, ServiceUnavailable

from logistica.config import Settings
from logistica.exceptions import ConflictoDeDatos, ErrorDePersistencia

log = logging.getLogger(__name__)

T = TypeVar("T")


def conectar(settings: Settings) -> Driver:
    """Abre el driver. Neo4j no participa de la transaccion de PostgreSQL, asi
    que no hay Unidad de Trabajo: el driver vive mientras viva el proceso."""
    try:
        driver = GraphDatabase.driver(
            settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)
        )
        driver.verify_connectivity()
        return driver
    except (ServiceUnavailable, Neo4jError) as error:
        raise ErrorDePersistencia(f"No se pudo conectar a Neo4j: {error}") from error


def traducir_errores(funcion: Callable[..., T]) -> Callable[..., T]:
    """Convierte los errores del driver de Neo4j en errores del dominio.

    La violacion de restriccion se traduce a ConflictoDeDatos y no a un error de
    persistencia porque significa algo distinto: que se intento crear un nodo
    que ya existe. Si eso aparece, es senal de que un proyector esta usando
    CREATE en vez de MERGE y perdio la idempotencia (D35).
    """

    @wraps(funcion)
    def envoltorio(*args: Any, **kwargs: Any) -> T:
        try:
            return funcion(*args, **kwargs)
        except Neo4jError as error:
            if "ConstraintValidationFailed" in str(error.code or ""):
                log.warning("Restriccion de Neo4j violada en %s: %s", funcion.__name__, error)
                raise ConflictoDeDatos(str(error)) from error
            log.exception("Fallo de Neo4j en %s", funcion.__name__)
            raise ErrorDePersistencia(str(error)) from error
        except ServiceUnavailable as error:
            log.warning("Neo4j no disponible en %s: %s", funcion.__name__, error)
            raise ErrorDePersistencia(str(error)) from error

    return envoltorio
