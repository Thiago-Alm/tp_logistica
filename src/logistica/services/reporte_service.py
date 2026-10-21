"""Reportes operativos y analiticos.

Es el unico servicio que cruza motores: los reportes de envios salen de
PostgreSQL y los de incidentes de MongoDB. El "promedio de incidentes por
pais / cliente" se arma aca, combinando el conteo de Mongo con la cantidad de
envios de Postgres, porque ningun motor tiene las dos mitades.
"""
import logging
from datetime import datetime, timedelta

from logistica.domain.reportes import (
    ConteoEnviosPorCliente,
    ConteoEnviosPorEstado,
    ConteoEnviosPorPais,
    TiemposDeEnvioPorCliente,
    VolumenPorCliente,
)
from logistica.domain.tramo import MedioTransporte
from logistica.repositories.unidad_de_trabajo import UnidadDeTrabajo

log = logging.getLogger(__name__)


class ReporteService:
    def __init__(self, unidad_de_trabajo: UnidadDeTrabajo) -> None:
        self._uow = unidad_de_trabajo

    # --- Operativos -------------------------------------------------------

    def envios_por_pais(
        self, desde: datetime | None = None, hasta: datetime | None = None
    ) -> list[ConteoEnviosPorPais]:
        with self._uow as uow:
            return uow.reportes_envio.envios_por_pais(desde, hasta)

    def envios_por_estado(
        self, desde: datetime | None = None, hasta: datetime | None = None
    ) -> list[ConteoEnviosPorEstado]:
        with self._uow as uow:
            return uow.reportes_envio.envios_por_estado(desde, hasta)

    def envios_por_cliente(
        self, desde: datetime | None = None, hasta: datetime | None = None
    ) -> list[ConteoEnviosPorCliente]:
        with self._uow as uow:
            return uow.reportes_envio.envios_por_cliente(desde, hasta)

    # --- Analiticos -------------------------------------------------------

    def tiempos_de_envio_por_cliente(
        self, desde: datetime | None = None, hasta: datetime | None = None
    ) -> list[TiemposDeEnvioPorCliente]:
        with self._uow as uow:
            return uow.reportes_envio.tiempos_de_envio_por_cliente(desde, hasta)

    def tiempo_promedio_de_entrega(
        self, desde: datetime | None = None, hasta: datetime | None = None
    ) -> timedelta | None:
        with self._uow as uow:
            return uow.reportes_envio.tiempo_promedio_de_entrega(desde, hasta)

    def ranking_clientes_por_volumen(
        self,
        limite: int = 10,
        desde: datetime | None = None,
        hasta: datetime | None = None,
    ) -> list[VolumenPorCliente]:
        with self._uow as uow:
            return uow.reportes_envio.ranking_clientes_por_volumen(limite, desde, hasta)

    def costos_por_tipo_de_transporte(self) -> dict[MedioTransporte, object]:
        """Requisito: "Costos por tipo de transporte". Agrega sobre los tramos."""
        with self._uow as uow:
            return uow.tramos.costo_por_medio_de_transporte()
