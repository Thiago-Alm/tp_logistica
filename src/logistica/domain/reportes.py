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


@dataclass(frozen=True)
class ConteoIncidentes:
    """Cantidad de incidentes de un grupo (pais, cliente, estado o ruta).

    `grupo` es siempre texto: cuando el eje es el cliente, es su UUID en forma
    de cadena, porque MongoDB no resuelve la razon social (vive en PostgreSQL).
    Resolverla es tarea del servicio.
    """

    grupo: str
    cantidad: int


@dataclass(frozen=True)
class RutaConIncidentes:
    """Una fila del ranking de rutas con mas incidentes (D12).

    `ruta` es el par origen-destino tal como quedo en el snapshot del incidente,
    por ejemplo "ARBUE->NLRTM".
    """

    ruta: str
    cantidad: int


@dataclass(frozen=True)
class TramoDeRuta:
    """Un tramo de la ruta de un envío."""

    tramo_id: str
    orden: int | None
    medio_transporte: str | None
    origen: str | None
    destino: str | None
    vehiculo: str | None


@dataclass(frozen=True)
class RelacionClienteEnvioOperador:
    """Un envío de un cliente y un operador vinculado."""

    cliente_id: str
    cliente: str | None
    envio_id: str
    estado_envio: str | None
    operador_id: str | None
    operador: str | None


@dataclass(frozen=True)
class MovimientoDeContenedor:
    """Un tramo vinculado a un contenedor."""

    contenedor_id: str
    envio_id: str | None
    tramo_id: str
    orden: int | None
    origen: str | None
    destino: str | None
