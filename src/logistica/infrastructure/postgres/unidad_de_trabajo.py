"""Unidad de Trabajo sobre PostgreSQL: una conexion, una transaccion."""
import logging

from logistica.config import Settings
from logistica.infrastructure.postgres.cliente_repository import PostgresClienteRepository
from logistica.infrastructure.postgres.conexion import conectar
from logistica.infrastructure.postgres.consistencia_repository import (
    PostgresConsistenciaRepository,
)
from logistica.infrastructure.postgres.contenedor_repository import (
    PostgresContenedorRepository,
)
from logistica.infrastructure.postgres.envio_repository import PostgresEnvioRepository
from logistica.infrastructure.postgres.outbox_repository import PostgresOutboxRepository
from logistica.infrastructure.postgres.reporte_envio_repository import (
    PostgresReporteEnvioRepository,
)
from logistica.infrastructure.postgres.rol_repository import PostgresRolRepository
from logistica.infrastructure.postgres.tramo_repository import PostgresTramoRepository
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
        self.envios = PostgresEnvioRepository(self._conexion)
        self.tramos = PostgresTramoRepository(self._conexion)
        self.contenedores = PostgresContenedorRepository(self._conexion)
        self.reportes_envio = PostgresReporteEnvioRepository(self._conexion)
        self.outbox = PostgresOutboxRepository(self._conexion)
        self.consistencia = PostgresConsistenciaRepository(self._conexion)
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
