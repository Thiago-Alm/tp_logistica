"""Consultas de lectura del grafo de Neo4j."""

from neo4j import Driver

from logistica.domain.reportes import (
    MovimientoDeContenedor,
    RelacionClienteEnvioOperador,
    TramoDeRuta,
)
from logistica.infrastructure.neo4j.conexion import traducir_errores


class Neo4jConsultaRepository:
    def __init__(self, driver: Driver) -> None:
        self._driver = driver

    @traducir_errores
    def ruta_de_envio(self, envio_id: str) -> list[TramoDeRuta]:
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
    def red_de_cliente(self, cliente_id: str) -> list[RelacionClienteEnvioOperador]:
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
        self, contenedor_id: str
    ) -> list[MovimientoDeContenedor]:
        """Devuelve los tramos vinculados a un contenedor."""
        consulta = """
        MATCH (contenedor:Contenedor {id: $contenedor_id})
              -[:RECORRE]->(tramo:Tramo)
        OPTIONAL MATCH (envio:Envio)-[:TIENE_TRAMO]->(tramo)
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