"""Solicitud de un reporte parametrizado y facturable. Vive en MongoDB.

Por que MongoDB y no una tabla: **los parametros cambian segun el reporte**. El
de envios por pais lleva un rango de fechas, el ranking de clientes lleva ademas
un limite, y el de costos por tipo de transporte no lleva ninguno. En PostgreSQL
eso serian o una columna por parametro -casi todas en NULL- o una columna JSON,
que es un documento disfrazado. Es el mismo criterio que llevo los umbrales a
MongoDB (D25).

Lo que si vive en PostgreSQL es su **consecuencia**: la factura que genera,
porque eso es dinero y necesita la transaccion de la cuenta corriente (D41).
"""
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from logistica.domain.facturacion import TitularTipo
from logistica.exceptions import ValidacionError

# Precio por reporte. Un reporte analitico cuesta mas que uno operativo porque
# agrega sobre todo el historico en vez de contar lo que hay hoy.
#
# Es una constante y no un ABM de tarifas: el enunciado no lo pide. Si lo
# pidiera, la tarifa iria a MongoDB al lado de los umbrales, por la misma razon.
PRECIO_OPERATIVO = Decimal("150.00")
PRECIO_ANALITICO = Decimal("450.00")


class TipoReporte(Enum):
    ENVIOS_POR_PAIS = "ENVIOS_POR_PAIS"
    ENVIOS_POR_ESTADO = "ENVIOS_POR_ESTADO"
    ENVIOS_POR_CLIENTE = "ENVIOS_POR_CLIENTE"
    ENVIOS_DEMORADOS = "ENVIOS_DEMORADOS"
    INCIDENTES_ABIERTOS = "INCIDENTES_ABIERTOS"
    TIEMPOS_POR_CLIENTE = "TIEMPOS_POR_CLIENTE"
    TIEMPO_PROMEDIO_ENTREGA = "TIEMPO_PROMEDIO_ENTREGA"
    RANKING_CLIENTES_VOLUMEN = "RANKING_CLIENTES_VOLUMEN"
    COSTOS_POR_TRANSPORTE = "COSTOS_POR_TRANSPORTE"
    RANKING_RUTAS_INCIDENTES = "RANKING_RUTAS_INCIDENTES"
    PROMEDIO_INCIDENTES = "PROMEDIO_INCIDENTES"


@dataclass(frozen=True)
class EspecificacionReporte:
    """Que parametros acepta cada reporte y cuanto cuesta.

    Esta en el dominio y no en el servicio porque es lo que define si una
    solicitud es valida: pedir un limite a un reporte que no lo usa es un error
    del pedido, no de la ejecucion.
    """

    etiqueta: str
    analitico: bool
    acepta_rango: bool = False
    acepta_limite: bool = False
    acepta_eje: bool = False

    @property
    def precio(self) -> Decimal:
        return PRECIO_ANALITICO if self.analitico else PRECIO_OPERATIVO


CATALOGO: dict[TipoReporte, EspecificacionReporte] = {
    TipoReporte.ENVIOS_POR_PAIS: EspecificacionReporte(
        "Envios por pais", analitico=False, acepta_rango=True
    ),
    TipoReporte.ENVIOS_POR_ESTADO: EspecificacionReporte(
        "Envios por estado", analitico=False, acepta_rango=True
    ),
    TipoReporte.ENVIOS_POR_CLIENTE: EspecificacionReporte(
        "Envios por cliente", analitico=False, acepta_rango=True
    ),
    TipoReporte.ENVIOS_DEMORADOS: EspecificacionReporte(
        "Envios demorados", analitico=False
    ),
    TipoReporte.INCIDENTES_ABIERTOS: EspecificacionReporte(
        "Incidentes abiertos", analitico=False
    ),
    TipoReporte.TIEMPOS_POR_CLIENTE: EspecificacionReporte(
        "Tiempos maximos y minimos por cliente", analitico=True, acepta_rango=True
    ),
    TipoReporte.TIEMPO_PROMEDIO_ENTREGA: EspecificacionReporte(
        "Tiempo promedio de entrega", analitico=True, acepta_rango=True
    ),
    TipoReporte.RANKING_CLIENTES_VOLUMEN: EspecificacionReporte(
        "Ranking de clientes por volumen",
        analitico=True,
        acepta_rango=True,
        acepta_limite=True,
    ),
    TipoReporte.COSTOS_POR_TRANSPORTE: EspecificacionReporte(
        "Costos por tipo de transporte", analitico=True
    ),
    TipoReporte.RANKING_RUTAS_INCIDENTES: EspecificacionReporte(
        "Ranking de rutas con mas incidentes", analitico=True, acepta_limite=True
    ),
    TipoReporte.PROMEDIO_INCIDENTES: EspecificacionReporte(
        "Promedio de incidentes por pais / estado / cliente",
        analitico=True,
        acepta_eje=True,
    ),
}


class EstadoSolicitud(Enum):
    SOLICITADA = "SOLICITADA"
    GENERADA = "GENERADA"
    FACTURADA = "FACTURADA"
    CANCELADA = "CANCELADA"

    def puede_pasar_a(self, destino: "EstadoSolicitud") -> bool:
        return destino in _TRANSICIONES[self]

    def es_final(self) -> bool:
        return not _TRANSICIONES[self]


# Mismo criterio que D4: un diccionario consultado desde el enum. Una solicitud
# se cancela mientras no este facturada; una vez facturada hay un movimiento en
# la cuenta corriente y anularlo es otro asiento, no un cambio de estado (D41).
_TRANSICIONES: dict[EstadoSolicitud, set[EstadoSolicitud]] = {
    EstadoSolicitud.SOLICITADA: {EstadoSolicitud.GENERADA, EstadoSolicitud.CANCELADA},
    EstadoSolicitud.GENERADA: {EstadoSolicitud.FACTURADA, EstadoSolicitud.CANCELADA},
    EstadoSolicitud.FACTURADA: set(),
    EstadoSolicitud.CANCELADA: set(),
}


@dataclass
class SolicitudReporte:
    id: UUID
    tipo: TipoReporte
    titular_tipo: TitularTipo
    titular_id: UUID
    fecha_solicitud: datetime
    costo: Decimal
    parametros: dict[str, Any] = field(default_factory=dict)
    estado: EstadoSolicitud = EstadoSolicitud.SOLICITADA
    filas: int | None = None
    fecha_generacion: datetime | None = None
    factura_id: UUID | None = None

    def __post_init__(self) -> None:
        self.validar()

    def validar(self) -> None:
        """Invariantes que se verifican con los campos del objeto, sin tocar
        ninguna base. Que el titular exista se valida en el servicio, porque
        eso requiere consultar PostgreSQL (D3)."""
        if self.costo < 0:
            raise ValidacionError("El costo de un reporte no puede ser negativo")

        especificacion = CATALOGO[self.tipo]
        permitidos = set()
        if especificacion.acepta_rango:
            permitidos |= {"desde", "hasta"}
        if especificacion.acepta_limite:
            permitidos.add("limite")
        if especificacion.acepta_eje:
            permitidos.add("eje")

        sobran = set(self.parametros) - permitidos
        if sobran:
            raise ValidacionError(
                f"{especificacion.etiqueta} no acepta {', '.join(sorted(sobran))}"
            )

        limite = self.parametros.get("limite")
        if limite is not None and (not isinstance(limite, int) or limite <= 0):
            raise ValidacionError("El limite tiene que ser un entero positivo")

        desde, hasta = self.parametros.get("desde"), self.parametros.get("hasta")
        if desde is not None and hasta is not None and desde > hasta:
            raise ValidacionError("La fecha inicial no puede ser posterior a la final")

    @property
    def especificacion(self) -> EspecificacionReporte:
        return CATALOGO[self.tipo]

    def pasar_a(self, destino: EstadoSolicitud) -> None:
        """Unica forma de cambiar el estado (D4, D18)."""
        if not self.estado.puede_pasar_a(destino):
            raise ValidacionError(
                f"Una solicitud {self.estado.value} no puede pasar a {destino.value}"
            )
        self.estado = destino

    def marcar_generada(self, filas: int, momento: datetime) -> None:
        self.pasar_a(EstadoSolicitud.GENERADA)
        self.filas = filas
        self.fecha_generacion = momento

    def marcar_facturada(self, factura_id: UUID) -> None:
        self.pasar_a(EstadoSolicitud.FACTURADA)
        self.factura_id = factura_id

    def esta_pendiente_de_facturar(self) -> bool:
        return self.estado is EstadoSolicitud.GENERADA
