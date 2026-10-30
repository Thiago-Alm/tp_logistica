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
from logistica.repositories.evento_logistico_repository import (
    EventoLogisticoRepository,
)
from logistica.repositories.incidente_repository import IncidenteRepository
from logistica.repositories.lectura_repository import LecturaRepository
from logistica.repositories.umbral_repository import UmbralRepository
from logistica.repositories.unidad_de_trabajo import UnidadDeTrabajo
from logistica.services.cliente_service import ClienteService
from logistica.services.envio_service import EnvioService
from logistica.services.evento_logistico_service import EventoLogisticoService
from logistica.services.facturacion_service import FacturacionService
from logistica.services.reporte_service import ReporteService
from logistica.services.usuario_service import UsuarioService
from logistica.sync.consistencia import ChequeoDeConsistencia
from logistica.sync.proyector_cassandra import ProyectorCassandra
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
    def facturacion(self) -> FacturacionService:
        return FacturacionService(self.unidad_de_trabajo)

    @cached_property
    def reportes(self) -> ReporteService:
        return ReporteService(
            self.unidad_de_trabajo,
            cache=self.cache_reportes,
        )
    @cached_property
    def trazabilidad(self) -> EventoLogisticoService:
        return EventoLogisticoService(self.eventos_logisticos, self.unidad_de_trabajo)
    @cached_property
    def redis(self):
        """Cliente Redis compartido por los servicios que lo necesiten."""
        from redis import Redis

        return Redis(
            host=self.settings.redis_host,
            port=self.settings.redis_port,
        )

    @cached_property
    def sesiones(self):
        """Servicio para crear, consultar y cerrar sesiones."""
        from logistica.infrastructure.redis.sesion_repository import (
            RedisSesionRepository,
        )
        from logistica.services.sesion_service import SesionService

        return SesionService(
            RedisSesionRepository(self.redis),
            ttl_segundos=3600,
        )
    @cached_property
    def heartbeat(self):
        """Registro de la última señal recibida de cada sensor."""
        from logistica.infrastructure.redis.heartbeat_repository import (
            RedisHeartbeatRepository,
        )

        return RedisHeartbeatRepository(self.redis)
    @cached_property
    def deteccion_inactividad(self):
        from logistica.infrastructure.postgres.sensores_monitoreados import (
            cargar_sensores_monitoreados,
        )
        from logistica.services.deteccion_inactividad_service import (
            DeteccionInactividadService,
        )

        return DeteccionInactividadService(
            heartbeat=self.heartbeat,
            cargar_sensores=lambda: cargar_sensores_monitoreados(self.settings),
        )
    @cached_property
    def cache_reportes(self):
        from logistica.infrastructure.redis.cache_reportes_repository import (
            RedisCacheReportesRepository,
        )

        return RedisCacheReportesRepository(self.redis)

    @cached_property
    def gps(self):
        from logistica.services.gps_service import GPSService

        return GPSService(
            lecturas=self.lecturas,
            unidad_de_trabajo=self.unidad_de_trabajo,
        )


    # -- Cassandra y MongoDB -------------------------------------------------
    # Estos repositorios no pasan por la UnidadDeTrabajo: son otros motores y no
    # comparten transaccion con PostgreSQL (la coherencia entre bases la cubre el
    # Outbox). Los imports son perezosos para que la aplicacion siga arrancando
    # aunque todavia no esten instalados los drivers.

    @cached_property
    def sesion_cassandra(self):
        """Una sola sesion de Cassandra, compartida por los repositorios que la
        usan. El driver ya maneja su propio pool de conexiones."""
        from logistica.infrastructure.cassandra.conexion import conectar

        return conectar(self.settings)

    @cached_property
    def lecturas(self) -> LecturaRepository:
        from logistica.infrastructure.cassandra.lectura_repository import (
            CassandraLecturaRepository,
        )

        return CassandraLecturaRepository(self.sesion_cassandra)

    @cached_property
    def eventos_logisticos(self) -> EventoLogisticoRepository:
        from logistica.infrastructure.cassandra.evento_logistico_repository import (
            CassandraEventoLogisticoRepository,
        )

        return CassandraEventoLogisticoRepository(self.sesion_cassandra)

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

    @cached_property
    def proveedores_service(self):
        from logistica.services.parte_service import ProveedorService

        return ProveedorService(self.unidad_de_trabajo)

    @cached_property
    def operadores_service(self):
        from logistica.services.parte_service import OperadorService

        return OperadorService(self.unidad_de_trabajo)

    @cached_property
    def incidentes_service(self):
        """Incidentes: viven en MongoDB, pero el snapshot del envio y el
        denominador de los promedios salen de PostgreSQL."""
        from logistica.services.incidente_service import IncidenteService

        return IncidenteService(self.incidentes, self.unidad_de_trabajo)

    @cached_property
    def monitoreo(self):
        """Monitoreo IoT: lecturas en Cassandra, umbrales y alertas en MongoDB,
        ficha del sensor en PostgreSQL."""
        from logistica.services.monitoreo_service import MonitoreoService

        return MonitoreoService(
            self.lecturas,
            self.umbrales,
            self.alertas,
            self.unidad_de_trabajo,
            deteccion_inactividad=self.deteccion_inactividad,
            deteccion_anomalias=self.deteccion_anomalias,
        )

    @cached_property
    def deteccion_anomalias(self):
        """Compara cada lectura con el umbral de su tipo de contenedor.

        El servicio no consulta PostgreSQL: recibe una funcion que dice de que
        tipo es cada contenedor. Aca se arma con el repositorio, cacheando el
        mapa una vez por proceso: los tipos de contenedor no cambian mientras
        corre una deteccion.
        """
        from logistica.services.deteccion_anomalias_service import (
            DeteccionAnomaliasService,
        )

        tipos: dict = {}

        def tipo_de_contenedor(contenedor_id):
            if not tipos:
                with self.unidad_de_trabajo as uow:
                    tipos.update({c.id: c.tipo for c in uow.contenedores.listar()})
            return tipos.get(contenedor_id)

        return DeteccionAnomaliasService(self.umbrales, self.alertas, tipo_de_contenedor)

    # -- Sincronizacion ------------------------------------------------------

    @cached_property
    def worker_de_sincronizacion(self) -> WorkerDeSincronizacion:
        """El worker que vacia el Outbox hacia los demas motores.

        Hay dos destinos, y los dos contienen datos DERIVADOS de PostgreSQL:
        Neo4j proyecta la red de relaciones, y Cassandra la traza de eventos
        logisticos de cada envio (D40).

        MongoDB no necesita proyector porque es dueno de sus entidades
        (incidentes, alertas, chat): nadie las deriva de otra base. Agregar un
        destino nuevo es sumar un proyector a esta lista, sin tocar el worker
        (D35).
        """
        return WorkerDeSincronizacion(
            self.unidad_de_trabajo, [self.proyector_neo4j, self.proyector_cassandra]
        )

    @cached_property
    def proyector_cassandra(self) -> ProyectorCassandra:
        return ProyectorCassandra(self.eventos_logisticos)

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

    @cached_property
    def consultas_red(self):
        from logistica.services.consulta_grafo_service import ConsultaGrafoService

        return ConsultaGrafoService(
            consultas=self.consultas_grafo,
            unidad_de_trabajo=self.unidad_de_trabajo,
        )
