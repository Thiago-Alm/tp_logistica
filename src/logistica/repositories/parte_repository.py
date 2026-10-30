"""Interfaces de persistencia de Proveedor y Operador.

Son dos contratos separados aunque tengan los mismos metodos: la Unidad de
Trabajo expone `proveedores` y `operadores` por separado, y un servicio que
recibe `OperadorRepository` no puede recibir proveedores por error.
"""
from abc import ABC, abstractmethod
from uuid import UUID

from logistica.domain.partes import EstadoParte, Operador, Proveedor


class OperadorRepository(ABC):
    @abstractmethod
    def guardar(self, operador: Operador) -> None: ...

    @abstractmethod
    def actualizar(self, operador: Operador) -> None:
        """Persiste una entidad ya modificada (D18). NoEncontrado si no existe."""
        ...

    @abstractmethod
    def obtener(self, id: UUID) -> Operador | None: ...

    @abstractmethod
    def obtener_por_cuit(self, cuit: str) -> Operador | None:
        """El CUIT es unico: lo garantiza uq_operador_cuit."""
        ...

    @abstractmethod
    def listar(self, estado: EstadoParte | None = None) -> list[Operador]: ...


class ProveedorRepository(ABC):
    @abstractmethod
    def guardar(self, proveedor: Proveedor) -> None: ...

    @abstractmethod
    def actualizar(self, proveedor: Proveedor) -> None:
        """Persiste una entidad ya modificada (D18). NoEncontrado si no existe."""
        ...

    @abstractmethod
    def obtener(self, id: UUID) -> Proveedor | None: ...

    @abstractmethod
    def obtener_por_cuit(self, cuit: str) -> Proveedor | None:
        """El CUIT es unico: lo garantiza uq_proveedor_cuit."""
        ...

    @abstractmethod
    def listar(self, estado: EstadoParte | None = None) -> list[Proveedor]: ...
