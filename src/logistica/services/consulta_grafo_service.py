"""Consultas de lectura de la red logistica en Neo4j (D37, D46)."""

from uuid import UUID

from logistica.domain.reportes import (
    MovimientoDeContenedor,
    RelacionClienteEnvioOperador,
    TramoDeRuta,
)
from logistica.exceptions import NoEncontrado
from logistica.repositories.consulta_repository import ConsultaRepository
from logistica.repositories.unidad_de_trabajo import UnidadDeTrabajo


class ConsultaGrafoService:
    """Antes de ir al grafo confirma en PostgreSQL que la entidad exista.

    El grafo es una proyeccion: si devuelve una lista vacia no se sabe si el id
    no existe o si existe y todavia no tiene relaciones. PostgreSQL es la fuente
    de verdad y lo distingue.
    """

    def __init__(
        self,
        consultas: ConsultaRepository,
        unidad_de_trabajo: UnidadDeTrabajo,
    ) -> None:
        self._consultas = consultas
        self._uow = unidad_de_trabajo

    def ruta_de_envio(self, envio_id: UUID) -> list[TramoDeRuta]:
        with self._uow as uow:
            if uow.envios.obtener(envio_id) is None:
                raise NoEncontrado(f"No existe el envio {envio_id}")

        return self._consultas.ruta_de_envio(envio_id)

    def red_de_cliente(
        self, cliente_id: UUID
    ) -> list[RelacionClienteEnvioOperador]:
        with self._uow as uow:
            if uow.clientes.obtener(cliente_id) is None:
                raise NoEncontrado(f"No existe el cliente {cliente_id}")

        return self._consultas.red_de_cliente(cliente_id)

    def movimientos_de_contenedor(
        self, contenedor_id: UUID
    ) -> list[MovimientoDeContenedor]:
        with self._uow as uow:
            if uow.contenedores.obtener(contenedor_id) is None:
                raise NoEncontrado(f"No existe el contenedor {contenedor_id}")

        return self._consultas.movimientos_de_contenedor(contenedor_id)
