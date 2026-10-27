"""Consultas de lectura del grafo de Neo4j."""

from uuid import UUID

from neo4j import Driver

from logistica.domain.reportes import (
    MovimientoDeContenedor,
    RelacionClienteEnvioOperador,
    TramoDeRuta,
)
from logistica.infrastructure.neo4j.conexion import traducir_errores
from logistica.repositories.consulta_repository import ConsultaRepository


class Neo4jConsultaRepository(ConsultaRepository):
    def __init__(self, driver: Driver) -> None:
        self._driver = driver

    @traducir_errores
    def ruta_de_envio(self, envio_id: UUID) -> list[TramoDeRuta]:
        """Devuelve los tramos de un envío ordenados por su posición."""
        consulta = """
        MATCH (e:Envio {id: $envio_id})-[:TIENE_TRAMO]->(t:Tramo)
        OPTIONAL MATCH (t)-[:DESDE]->(origen:Ubicacion)
        OPTIONAL MATCH (t)-[:HASTA]->(destino:Ubicacion)
        OPTIONAL MATCH (t)-[:UTILIZA]->(vehiculo:Vehiculo)
        RETURN t.id AS tramo_id,
               t.orden AS orden,
               t.medio_transporte AS medio_transporte,
               origen.nombre AS origen,
               destino.nombre AS destino,
               vehiculo.identificacion AS vehiculo
        ORDER BY t.orden
        """

        with self._driver.session() as sesion:
            filas = sesion.run(consulta, envio_id=str(envio_id)).data()
            return [TramoDeRuta(**fila) for fila in filas]

    @traducir_errores
    def red_de_cliente(self, cliente_id: UUID) -> list[RelacionClienteEnvioOperador]:
        """Devuelve los envíos del cliente y sus operadores vinculados."""
        consulta = """
        MATCH (cliente:Cliente {id: $cliente_id})-[:SOLICITA]->(envio:Envio)
        OPTIONAL MATCH (envio)-[:TIENE_TRAMO]->(tramo:Tramo)
                       -[:UTILIZA]->(vehiculo:Vehiculo)
                       <-[:OPERA]-(operador:Operador)
        RETURN DISTINCT cliente.id AS cliente_id,
               cliente.razon_social AS cliente,
               envio.id AS envio_id,
               envio.estado AS estado_envio,
               operador.id AS operador_id,
               operador.razon_social AS operador
        ORDER BY envio_id, operador
        """

        with self._driver.session() as sesion:
            filas = sesion.run(consulta, cliente_id=str(cliente_id)).data()
            return [RelacionClienteEnvioOperador(**fila) for fila in filas]

    @traducir_errores
    def movimientos_de_contenedor(
        self, contenedor_id: UUID
    ) -> list[MovimientoDeContenedor]:
        """Devuelve los tramos vinculados a un contenedor.

        El recorrido se arma por el camino Contenedor <- Envio -> Tramo y no por
        una relacion directa Contenedor-RECORRE->Tramo. El modelo inicial
        proponia esa relacion, pero no hay en PostgreSQL ningun dato que diga
        por que tramos concretos paso cada contenedor: solo se sabe en que
        envios estuvo (envio_contenedor) y que tramos tuvo cada envio. Una
        relacion RECORRE derivada de esos dos datos no agregaria informacion
        que el camino no tenga ya, y habria que mantenerla sincronizada (D37).

        El detalle fino de por donde paso fisicamente un contenedor vive en
        Cassandra, en eventos_por_contenedor.
        """
        consulta = """
        MATCH (contenedor:Contenedor {id: $contenedor_id})
              <-[:INCLUYE]-(envio:Envio)-[:TIENE_TRAMO]->(tramo:Tramo)
        OPTIONAL MATCH (tramo)-[:DESDE]->(origen:Ubicacion)
        OPTIONAL MATCH (tramo)-[:HASTA]->(destino:Ubicacion)
        RETURN contenedor.id AS contenedor_id,
               envio.id AS envio_id,
               tramo.id AS tramo_id,
               tramo.orden AS orden,
               origen.nombre AS origen,
               destino.nombre AS destino
        ORDER BY envio_id, orden
        """

        with self._driver.session() as sesion:
            filas = sesion.run(
                consulta, contenedor_id=str(contenedor_id)
            ).data()
            return [MovimientoDeContenedor(**fila) for fila in filas]
