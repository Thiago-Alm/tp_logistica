"""Interfaz de los reportes que agregan sobre envios.

Esta separada de EnvioRepository porque devuelve cosas distintas: un repositorio
de entidades devuelve `Envio`, y estos metodos devuelven totales, promedios y
rankings, que no son envios. Mezclar las dos cosas en una misma interfaz obliga
a que cualquier implementacion de `EnvioRepository` (incluso una falsa, de test)
tenga que implementar tambien los reportes.

Todos los metodos aceptan un rango de fechas opcional sobre `fecha_creacion`
del envio, porque el enunciado pide reportes "parametrizados" y la entidad
Reporte guarda sus `parametros`.
"""
from abc import ABC, abstractmethod
from datetime import datetime, timedelta

from logistica.domain.reportes import (
    ConteoEnviosPorCliente,
    ConteoEnviosPorEstado,
    ConteoEnviosPorPais,
    TiemposDeEnvioPorCliente,
    VolumenPorCliente,
)


class ReporteEnvioRepository(ABC):
    # --- Reportes operativos ---------------------------------------------

    @abstractmethod
    def envios_por_pais(
        self, desde: datetime | None = None, hasta: datetime | None = None
    ) -> list[ConteoEnviosPorPais]: ...

    @abstractmethod
    def envios_por_estado(
        self, desde: datetime | None = None, hasta: datetime | None = None
    ) -> list[ConteoEnviosPorEstado]: ...

    @abstractmethod
    def envios_por_cliente(
        self, desde: datetime | None = None, hasta: datetime | None = None
    ) -> list[ConteoEnviosPorCliente]: ...

    # --- Reportes analiticos ---------------------------------------------

    @abstractmethod
    def tiempos_de_envio_por_cliente(
        self, desde: datetime | None = None, hasta: datetime | None = None
    ) -> list[TiemposDeEnvioPorCliente]:
        """Requisito: "Tiempos maximos y minimos de envio por cliente"."""
        ...

    @abstractmethod
    def tiempo_promedio_de_entrega(
        self, desde: datetime | None = None, hasta: datetime | None = None
    ) -> timedelta | None:
        """Requisito: "Tiempos promedio de entrega".

        Mide `fecha_llegada_real - fecha_creacion` sobre los envios entregados.
        Devuelve None si no hay ninguno en el rango.
        """
        ...

    @abstractmethod
    def ranking_clientes_por_volumen(
        self,
        limite: int = 10,
        desde: datetime | None = None,
        hasta: datetime | None = None,
    ) -> list[VolumenPorCliente]:
        """Requisito: "Ranking de clientes por volumen transportado".

        Ordenado de mayor a menor volumen.
        """
        ...
