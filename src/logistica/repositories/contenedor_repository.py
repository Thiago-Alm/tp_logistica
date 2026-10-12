"""Interfaz de persistencia de Contenedor. La implementa infrastructure/postgres.

Los metodos reciben y devuelven entidades de dominio, nunca filas ni
diccionarios.
"""
from abc import ABC, abstractmethod
from uuid import UUID

from logistica.domain.contenedor import Contenedor, EstadoContenedor


class ContenedorRepository(ABC):
    @abstractmethod
    def guardar(self, contenedor: Contenedor) -> None:
        """Alta de un contenedor nuevo."""
        ...

    @abstractmethod
    def actualizar(self, contenedor: Contenedor) -> None:
        """Persiste los cambios de un contenedor existente, incluido su estado.

        No hay un metodo `cambiar_estado(id, estado)`: recibir un id suelto y un
        estado saltea el dominio, porque permite escribir cualquier estado sin
        pasar por las reglas de la entidad (D18). El servicio modifica el
        contenedor y lo guarda entero con este metodo.
        """
        ...

    @abstractmethod
    def obtener(self, id: UUID) -> Contenedor | None:
        """Devuelve None si no existe, en vez de lanzar."""
        ...

    @abstractmethod
    def obtener_por_codigo(self, codigo_iso: str) -> Contenedor | None:
        """Busqueda por el codigo ISO 6346, que es unico por contenedor (D8)."""
        ...

    @abstractmethod
    def listar_por_estado(self, estado: EstadoContenedor) -> list[Contenedor]:
        """Requisito: "Gestion de contenedores". Con DISPONIBLE da los
        contenedores asignables a un envio nuevo."""
        ...
