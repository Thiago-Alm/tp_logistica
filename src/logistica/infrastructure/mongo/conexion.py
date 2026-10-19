"""Conexion a MongoDB y traduccion de sus errores a errores del dominio."""
import logging
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

from pymongo import MongoClient
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError, PyMongoError, WriteError

from logistica.config import Settings
from logistica.exceptions import ConflictoDeDatos, ErrorDePersistencia, ValidacionError

log = logging.getLogger(__name__)

T = TypeVar("T")

# Codigo con el que MongoDB rechaza un documento que no cumple el $jsonSchema.
CODIGO_VALIDACION_FALLIDA = 121


def conectar(settings: Settings) -> Database:
    """Abre el cliente y devuelve la base.

    - uuidRepresentation="standard": un uuid.UUID de Python se guarda como binData
      subtipo 4, igual que UUID() en mongosh. Sin esto, los ids que escribe la
      aplicacion no coinciden con los de los scripts ni con los de las otras bases.
    - tz_aware=True: las fechas vuelven con zona UTC, no "ingenuas".
    """
    try:
        cliente: MongoClient = MongoClient(
            settings.mongo_uri,
            uuidRepresentation="standard",
            tz_aware=True,
            serverSelectionTimeoutMS=5000,
        )
        cliente.admin.command("ping")  # falla ya, no en la primera consulta
        return cliente[settings.mongo_db]
    except PyMongoError as error:
        raise ErrorDePersistencia(f"No se pudo conectar a MongoDB: {error}") from error


def cerrar(base: Database) -> None:
    base.client.close()


def traducir_errores(funcion: Callable[..., T]) -> Callable[..., T]:
    """Convierte los errores de pymongo en errores del dominio.

    DuplicateKeyError es subclase de WriteError, por eso se captura primero.
    """

    @wraps(funcion)
    def envoltorio(*args: Any, **kwargs: Any) -> T:
        try:
            return funcion(*args, **kwargs)
        except DuplicateKeyError as error:
            log.warning("Clave duplicada en %s: %s", funcion.__name__, error)
            raise ConflictoDeDatos("Ya existe un documento con esa clave") from error
        except WriteError as error:
            if error.code == CODIGO_VALIDACION_FALLIDA:
                log.warning("Validacion fallida en %s: %s", funcion.__name__, error.details)
                raise ValidacionError(
                    "El documento no cumple el esquema de la coleccion"
                ) from error
            log.exception("Fallo de escritura en MongoDB en %s", funcion.__name__)
            raise ErrorDePersistencia(str(error)) from error
        except PyMongoError as error:
            log.exception("Fallo de MongoDB en %s", funcion.__name__)
            raise ErrorDePersistencia(str(error)) from error

    return envoltorio
