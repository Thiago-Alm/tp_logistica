"""Lecturas que necesita el chequeo de consistencia entre motores.

Es un repositorio aparte y no metodos sueltos en los demas porque responde a
una necesidad distinta: los repositorios de entidades sirven a los casos de uso
del negocio; este sirve a la reconciliacion, que necesita ver TODO el contenido
de una tabla sin filtros ni paginado.
"""
from abc import ABC, abstractmethod
from typing import Any
from uuid import UUID

from logistica.domain.evento_outbox import TipoAgregado


class ConsistenciaRepository(ABC):
    @abstractmethod
    def ids_de(self, agregado: TipoAgregado) -> set[UUID]:
        """Todos los ids de ese tipo que existen en PostgreSQL.

        Es la mitad relacional de la comparacion: la otra mitad son los ids de
        los nodos del grafo.
        """
        ...

    @abstractmethod
    def filas_para_proyectar(self, agregado: TipoAgregado) -> list[dict[str, Any]]:
        """Los datos de cada entidad, con la forma del payload que espera el
        proyector.

        Lo usa la resincronizacion para reconstruir el grafo desde cero, sin
        depender de que existan eventos en el Outbox.
        """
        ...

    @abstractmethod
    def asignaciones_de_contenedores(self) -> list[dict[str, Any]]:
        """Pares envio-contenedor de la tabla N:M.

        Va aparte porque no es una entidad con id propio: es una relacion, y
        en el grafo se proyecta como la relacion INCLUYE.
        """
        ...
