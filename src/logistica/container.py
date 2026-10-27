"""Inyeccion de dependencias: aca se decide que implementacion usa cada interfaz.

Es el UNICO lugar del proyecto donde se nombra una tecnologia concreta junto a
una interfaz. Los servicios reciben una `UnidadDeTrabajo` y no saben si detras
hay PostgreSQL, otro motor o un doble de prueba. Por eso los tests pueden
construir un `Contenedor` con una unidad de trabajo falsa sin tocar este
archivo.

Uso:

    contenedor = Contenedor()
    contenedor.clientes.alta(cuit="30-71122334-9", ...)
"""
import logging
from functools import cached_property

from logistica.config import Settings
from logistica.config import settings as settings_por_defecto
from logistica.infrastructure.postgres.unidad_de_trabajo import UnidadDeTrabajoPostgres
from logistica.logging_config import setup_logging
from logistica.repositories.alerta_repository import AlertaRepository
from logistica.repositories.consulta_repository import ConsultaRepository
from logistica.repositories.incidente_repository import IncidenteRepository
from logistica.repositories.lectura_repository import LecturaRepository
from logistica.repositories.umbral_repository import UmbralRepository
from logistica.repositories.unidad_de_trabajo import UnidadDeTrabajo
from logistica.services.cliente_service import ClienteService
from logistica.services.envio_service import EnvioService
from logistica.services.reporte_service import ReporteService
from logistica.services.usuario_service import UsuarioService
from logistica.sync.consistencia import ChequeoDeConsistencia
from logistica.sync.proyector_neo4j import ProyectorNeo4j
from logistica.sync.worker import WorkerDeSincronizacion

log = logging.getLogger(__name__)


class Contenedor:
    def __init__(
        self,
        settings: Settings | None = None,
        unidad_de_trabajo: UnidadDeTrabajo | None = None,
        configurar_logging: bool = True,
    ) -> None:
        self.settings = settings or settings_por_defecto
        if configurar_logging:
            setup_logging(self.settings.log_level)
        # Se puede inyectar otra unidad de trabajo (por ejemplo, una falsa en los
        # tests) sin tocar nada mas.
        self._uow = unidad_de_trabajo

    @cached_property
    def unidad_de_trabajo(self) -> UnidadDeTrabajo:
        if self._uow is None:
            self._uow = UnidadDeTrabajoPostgres(self.settings)
        return self._uow

    @cached_property
    def clientes(self) -> ClienteService:
        return ClienteService(self.unidad_de_trabajo)

    @cached_property
    def usuarios(self) -> UsuarioService:
        return UsuarioService(self.unidad_de_trabajo)

    @cached_property
    def envios(self) -> EnvioService:
        return EnvioService(self.unidad_de_trabajo)

    @cached_property
    def reportes(self) -> ReporteService:
        return ReporteService(self.unidad_de_trabajo)

    # -- Cassandra y MongoDB -------------------------------------------------
    # Estos repositorios no pasan por la UnidadDeTrabajo: son otros motores y no
    # comparten transaccion con PostgreSQL (la coherencia entre bases la cubre el
    # Outbox). Los imports son perezosos para que la aplicacion siga arrancando
    # aunque todavia no esten instalados los drivers.

    @cached_property
    def lecturas(self) -> LecturaRepository:
        from logistica.infrastructure.cassandra.conexion import conectar
        from logistica.infrastructure.cassandra.lectura_repository import (
            CassandraLecturaRepository,
        )

        return CassandraLecturaRepository(conectar(self.settings))

    @cached_property
    def base_mongo(self):
        """Una sola conexion a MongoDB, compartida por los repositorios que la
        usan. El driver de pymongo ya maneja un pool interno: abrir un cliente
        por repositorio multiplicaria las conexiones sin ningun beneficio."""
        from logistica.infrastructure.mongo.conexion import conectar

        return conectar(self.settings)

    @cached_property
    def incidentes(self) -> IncidenteRepository:
        from logistica.infrastructure.mongo.incidente_repository import (
            MongoIncidenteRepository,
        )

        return MongoIncidenteRepository(self.base_mongo)

    @cached_property
    def umbrales(self) -> UmbralRepository:
        from logistica.infrastructure.mongo.umbral_repository import (
            MongoUmbralRepository,
        )

        return MongoUmbralRepository(self.base_mongo)

    @cached_property
    def alertas(self) -> AlertaRepository:
        from logistica.infrastructure.mongo.alerta_repository import (
            MongoAlertaRepository,
        )

        return MongoAlertaRepository(self.base_mongo)

    # -- Sincronizacion ------------------------------------------------------

    @cached_property
    def worker_de_sincronizacion(self) -> WorkerDeSincronizacion:
        """El worker que vacia el Outbox hacia los demas motores.

        Hoy el unico proyector es el de Neo4j: es el unico motor que contiene
        una PROYECCION de datos de PostgreSQL. MongoDB no necesita proyector
        porque es dueno de sus entidades (incidentes, alertas, chat): nadie las
        deriva de otra base. Agregar un destino nuevo es sumar un proyector a
        esta lista, sin tocar el worker (D35).
        """
        return WorkerDeSincronizacion(self.unidad_de_trabajo, [self.proyector_neo4j])

    @cached_property
    def proyector_neo4j(self) -> ProyectorNeo4j:
        from logistica.infrastructure.neo4j.conexion import conectar

        return ProyectorNeo4j(conectar(self.settings))

    @cached_property
    def chequeo_de_consistencia(self) -> ChequeoDeConsistencia:
        """Compara PostgreSQL contra el grafo y permite reconstruirlo."""
        return ChequeoDeConsistencia(self.unidad_de_trabajo, self.proyector_neo4j)

    @cached_property
    def consultas_grafo(self) -> ConsultaRepository:
        """Repositorio para consultar la red logística en Neo4j."""
        from logistica.infrastructure.neo4j.conexion import conectar
        from logistica.infrastructure.neo4j.consulta_repository import (
            Neo4jConsultaRepository,
        )

        return Neo4jConsultaRepository(conectar(self.settings))