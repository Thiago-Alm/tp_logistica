"""Proveedores y operadores logisticos. Viven en PostgreSQL.

Son dos tablas distintas porque el enunciado las pide por separado y cumplen
roles distintos —el operador transporta, el proveedor presta un servicio— pero
tienen la misma forma: CUIT, razon social, contacto, pais y baja logica. En vez
de repetir esa validacion en dos entidades, comparten una base.

El sistema ya las trata como un grupo: `TitularTipo` de facturacion cubre
CLIENTE, PROVEEDOR y OPERADOR con una sola tabla de cuentas corrientes
(supuesto 4), y el enunciado habla de "las partes" al pedir la mensajeria.
`Cliente` queda aparte porque ademas lleva direccion y es el unico que origina
envios.
"""
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import UUID

from logistica.domain.facturacion import TitularTipo
from logistica.exceptions import ValidacionError

DIGITOS_CUIT = 11


class EstadoParte(Enum):
    """La baja es logica: pasa a INACTIVO (D26). No se borra la fila porque
    hay cuentas corrientes y movimientos que la referencian."""

    ACTIVO = "ACTIVO"
    INACTIVO = "INACTIVO"


@dataclass
class ParteComercial:
    """Base de Proveedor y Operador. No se instancia sola."""

    id: UUID
    cuit: str
    razon_social: str
    email: str
    pais: str
    fecha_creacion: datetime
    telefono: str | None = None
    estado: EstadoParte = EstadoParte.ACTIVO

    def __post_init__(self) -> None:
        self.validar()

    def validar(self) -> None:
        """Invariantes que se verifican con los campos del objeto, sin tocar
        ninguna base. Que el CUIT no este repetido lo valida el servicio,
        porque eso requiere consultar (D3)."""
        if not self.razon_social.strip():
            raise ValidacionError("La razon social no puede estar vacia")
        if not self.pais.strip():
            raise ValidacionError("El pais no puede estar vacio")
        if "@" not in self.email:
            raise ValidacionError(f"Email invalido: {self.email!r}")

        digitos = [c for c in self.cuit if c.isdigit()]
        if len(digitos) != DIGITOS_CUIT:
            raise ValidacionError(
                f"El CUIT debe tener {DIGITOS_CUIT} digitos (recibido: {self.cuit!r})"
            )

    @property
    def titular_tipo(self) -> TitularTipo:
        """Como se identifica esta parte en su cuenta corriente (D41)."""
        raise NotImplementedError

    def esta_activo(self) -> bool:
        return self.estado is EstadoParte.ACTIVO

    def dar_de_baja(self) -> None:
        self.estado = EstadoParte.INACTIVO

    def reactivar(self) -> None:
        self.estado = EstadoParte.ACTIVO


@dataclass
class Operador(ParteComercial):
    """Operador logistico: quien efectivamente mueve la carga (naviera,
    transportista, aerolinea de cargas)."""

    @property
    def titular_tipo(self) -> TitularTipo:
        return TitularTipo.OPERADOR


@dataclass
class Proveedor(ParteComercial):
    """Proveedor de servicios: portuarios, mantenimiento, combustible.

    `tipo_servicio` lleva valor por defecto porque los campos de la base ya lo
    tienen, y en un dataclass los que tienen default van ultimos. Se valida que
    no quede vacio, asi que el default no sirve para construir uno invalido.
    """

    tipo_servicio: str = ""

    def validar(self) -> None:
        super().validar()
        if not self.tipo_servicio.strip():
            raise ValidacionError("El proveedor necesita un tipo de servicio")

    @property
    def titular_tipo(self) -> TitularTipo:
        return TitularTipo.PROVEEDOR
