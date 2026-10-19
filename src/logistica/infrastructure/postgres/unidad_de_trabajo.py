"""Unidad de Trabajo sobre PostgreSQL: una conexion, una transaccion."""
import logging

from logistica.config import Settings
from logistica.infrastructure.postgres.cliente_repository import PostgresClienteRepository
from logistica.infrastructure.postgres.conexion import conectar
from logistica.infrastructure.postgres.rol_repository import PostgresRolRepository
from logistica.infrastructure.postgres.usuario_repository import PostgresUsuarioRepository
from logistica.repositories.unidad_de_trabajo import UnidadDeTrabajo

log = logging.getLogger(__name__)


class UnidadDeTrabajoPostgres(UnidadDeTrabajo):
    """Los tres repositorios comparten la MISMA conexion, que es lo que hace que
    compartan la transaccion. Con una conexion por repositorio, un commit de uno
    no arrastraria al otro y la atomicidad seria una ilusion."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._conexion = None

    def __enter__(self) -> "UnidadDeTrabajoPostgres":
        self._conexion = conectar(self._settings)
        self.clientes = PostgresClienteRepository(self._conexion)
        self.roles = PostgresRolRepository(self._conexion)
        self.usuarios = PostgresUsuarioRepository(self._conexion)
        return self

    def commit(self) -> None:
        if self._conexion is not None:
            self._conexion.commit()
            log.debug("Transaccion confirmada")

    def rollback(self) -> None:
        if self._conexion is not None:
            self._conexion.rollback()

    def cerrar(self) -> None:
        if self._conexion is not None:
            self._conexion.close()
            self._conexion = None
