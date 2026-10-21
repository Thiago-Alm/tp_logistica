"""Proyecta los eventos del Outbox sobre el grafo de Neo4j.

Todas las consultas usan MERGE y nunca CREATE. MERGE busca el nodo o la
relacion y, si no existe, lo crea; aplicado dos veces deja el grafo igual que
aplicado una. Con CREATE, el segundo intento crearia un duplicado o chocaria
contra la restriccion de unicidad, y el evento se quedaria reintentando para
siempre.

Las restricciones de scripts/neo4j/01_constraints.cypher no son solo integridad:
le dan a MERGE el indice que hace que la busqueda no recorra todos los nodos.
"""
import logging

from neo4j import Driver

from logistica.domain.evento_outbox import EventoOutbox, TipoAgregado, TipoEvento
from logistica.infrastructure.neo4j.conexion import traducir_errores
from logistica.sync.proyector import Proyector

log = logging.getLogger(__name__)

# El grafo solo contiene una proyeccion de entidades de PostgreSQL.
AGREGADOS_DEL_GRAFO = {
    TipoAgregado.CLIENTE,
    TipoAgregado.OPERADOR,
    TipoAgregado.UBICACION,
    TipoAgregado.VEHICULO,
    TipoAgregado.CONTENEDOR,
    TipoAgregado.ENVIO,
    TipoAgregado.TRAMO,
}

CLIENTE = """
MERGE (c:Cliente {id: $id})
SET c.razon_social = $razon_social, c.cuit = $cuit,
    c.pais = $pais, c.estado = $estado
"""

# La baja NO borra el nodo (D26): si lo borrara, el grafo perderia las
# relaciones historicas del cliente con sus envios.
CLIENTE_BAJA = """
MERGE (c:Cliente {id: $id})
SET c.estado = $estado
"""

ENVIO = """
MERGE (e:Envio {id: $id})
SET e.estado = $estado, e.prioridad = $prioridad,
    e.fecha_creacion = $fecha_creacion
MERGE (c:Cliente {id: $cliente_id})
MERGE (uo:Ubicacion {id: $origen_id})
MERGE (ud:Ubicacion {id: $destino_id})
MERGE (c)-[:SOLICITA]->(e)
MERGE (e)-[:ORIGEN]->(uo)
MERGE (e)-[:DESTINO]->(ud)
"""

ENVIO_ESTADO = """
MERGE (e:Envio {id: $id})
SET e.estado = $estado, e.fecha_llegada_real = $fecha_llegada_real
"""

CONTENEDOR_ASIGNADO = """
MERGE (e:Envio {id: $envio_id})
MERGE (co:Contenedor {id: $contenedor_id})
MERGE (e)-[:INCLUYE]->(co)
"""

# Tramo es NODO y no relacion (D9): para poder colgar de el la relacion
# Contenedor-RECORRE->Tramo, que una relacion no puede sostener.
TRAMO = """
MERGE (t:Tramo {id: $id})
SET t.orden = $orden, t.medio_transporte = $medio_transporte, t.costo = $costo
MERGE (e:Envio {id: $envio_id})
MERGE (v:Vehiculo {id: $vehiculo_id})
MERGE (uo:Ubicacion {id: $origen_id})
MERGE (ud:Ubicacion {id: $destino_id})
MERGE (e)-[:TIENE_TRAMO]->(t)
MERGE (t)-[:UTILIZA]->(v)
MERGE (t)-[:DESDE]->(uo)
MERGE (t)-[:HASTA]->(ud)
"""

CONTENEDOR = """
MERGE (co:Contenedor {id: $id})
SET co.codigo_iso = $codigo_iso, co.tipo = $tipo, co.estado = $estado
"""


# Parametros que espera cada consulta. Se declaran para poder completar con
# None los que falten en el payload: un evento encolado por una version
# anterior del codigo no debe trabar la cola para siempre.
PARAMETROS = {
    CLIENTE: ("id", "razon_social", "cuit", "pais", "estado"),
    CLIENTE_BAJA: ("id", "estado"),
    ENVIO: ("id", "cliente_id", "origen_id", "destino_id", "estado", "prioridad",
            "fecha_creacion"),
    ENVIO_ESTADO: ("id", "estado", "fecha_llegada_real"),
    CONTENEDOR_ASIGNADO: ("envio_id", "contenedor_id"),
    TRAMO: ("id", "envio_id", "vehiculo_id", "origen_id", "destino_id", "orden",
            "medio_transporte", "costo"),
    CONTENEDOR: ("id", "codigo_iso", "tipo", "estado"),
}


class ProyectorNeo4j(Proyector):
    def __init__(self, driver: Driver) -> None:
        self._driver = driver

    @property
    def nombre(self) -> str:
        return "Neo4j"

    def le_interesa(self, evento: EventoOutbox) -> bool:
        return evento.agregado_tipo in AGREGADOS_DEL_GRAFO

    @traducir_errores
    def aplicar(self, evento: EventoOutbox) -> None:
        consulta = self._elegir_consulta(evento)
        if consulta is None:
            log.debug(
                "Neo4j ignora %s/%s",
                evento.agregado_tipo.value,
                evento.evento_tipo.value,
            )
            return
        faltantes = [c for c in PARAMETROS[consulta] if c not in evento.payload]
        if faltantes:
            log.warning(
                "El evento %s no trae %s; se proyecta con valor nulo",
                evento.id,
                ", ".join(faltantes),
            )
        parametros = {c: evento.payload.get(c) for c in PARAMETROS[consulta]}
        with self._driver.session() as sesion:
            sesion.run(consulta, **parametros)

    def _elegir_consulta(self, evento: EventoOutbox) -> str | None:
        tipo, accion = evento.agregado_tipo, evento.evento_tipo

        if tipo is TipoAgregado.CLIENTE:
            if accion is TipoEvento.DADO_DE_BAJA:
                return CLIENTE_BAJA
            return CLIENTE

        if tipo is TipoAgregado.ENVIO:
            if accion is TipoEvento.CREADO:
                return ENVIO
            if accion is TipoEvento.ESTADO_CAMBIADO:
                return ENVIO_ESTADO
            if accion is TipoEvento.CONTENEDOR_ASIGNADO:
                return CONTENEDOR_ASIGNADO
            return None

        if tipo is TipoAgregado.TRAMO and accion is TipoEvento.CREADO:
            return TRAMO

        if tipo is TipoAgregado.CONTENEDOR:
            return CONTENEDOR

        return None

    def cerrar(self) -> None:
        self._driver.close()
