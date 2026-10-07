"""Errores propios de la aplicacion."""


class LogisticaError(Exception):
    """Base de todos los errores de la aplicacion."""


class NoEncontrado(LogisticaError):
    """El registro pedido no existe."""


class ConflictoDeDatos(LogisticaError):
    """Viola una regla de unicidad o integridad (por ejemplo, codigo repetido)."""


class ValidacionError(LogisticaError):
    """Los datos recibidos no son validos."""


class ErrorDePersistencia(LogisticaError):
    """Fallo al hablar con una base de datos."""


class ErrorDeSincronizacion(LogisticaError):
    """Fallo al propagar un cambio entre bases."""
