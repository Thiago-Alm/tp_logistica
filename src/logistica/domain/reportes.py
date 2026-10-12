"""Resultados de los reportes.

Estos no son entidades: no tienen identidad ni ciclo de vida, son el resultado
ya calculado de una consulta de agregacion. Por eso son `frozen` (nadie los
modifica despues de obtenerlos) y viven aparte de las entidades del dominio.
"""
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from uuid import UUID

from logistica.domain.envio import EstadoEnvio


@dataclass(frozen=True)
class ConteoEnviosPorPais:
    """Supuesto: el pais es el del destino del envio, no el del origen."""

    pais: str
    cantidad: int


@dataclass(frozen=True)
class ConteoEnviosPorEstado:
    estado: EstadoEnvio
    cantidad: int


@dataclass(frozen=True)
class ConteoEnviosPorCliente:
    cliente_id: UUID
    razon_social: str
    cantidad: int


@dataclass(frozen=True)
class TiemposDeEnvioPorCliente:
    """Tiempos maximo y minimo de envio por cliente.

    Solo considera envios entregados: un envio en curso todavia no tiene
    duracion. `minimo` y `maximo` son None si el cliente no tiene ninguno.
    """

    cliente_id: UUID
    razon_social: str
    minimo: timedelta | None
    maximo: timedelta | None


@dataclass(frozen=True)
class VolumenPorCliente:
    """Volumen transportado, sumando la capacidad de los contenedores de cada
    envio del cliente (via EnvioContenedor)."""

    cliente_id: UUID
    razon_social: str
    volumen: Decimal
