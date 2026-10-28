"""Reportes operativos y analiticos.

Es el unico servicio que cruza motores: los reportes de envios salen de
PostgreSQL y los de incidentes de MongoDB. El "promedio de incidentes por
pais / cliente" se arma aca, combinando el conteo de Mongo con la cantidad de
envios de Postgres, porque ningun motor tiene las dos mitades.
"""
import json
import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import TypeVar
from uuid import UUID

from logistica.domain.envio import EstadoEnvio
from logistica.domain.reportes import (
    ConteoEnviosPorCliente,
    ConteoEnviosPorEstado,
    ConteoEnviosPorPais,
    TiemposDeEnvioPorCliente,
    VolumenPorCliente,
)
from logistica.domain.tramo import MedioTransporte
from logistica.exceptions import ErrorDePersistencia
from logistica.repositories.cache_reportes_repository import CacheReportesRepository
from logistica.repositories.unidad_de_trabajo import UnidadDeTrabajo

log = logging.getLogger(__name__)

T = TypeVar("T")
class ReporteService:
    def __init__(
        self,
        unidad_de_trabajo: UnidadDeTrabajo,
        cache: CacheReportesRepository | None = None,
    ) -> None:
        self._uow = unidad_de_trabajo
        self._cache = cache
    def _con_cache(
        self,
        nombre: str,
        parametros: list,
        consultar: Callable[[], T],
        serializar: Callable[[T], str],
        deserializar: Callable[[str], T],
    ) -> T:
        filtros = json.dumps(parametros, ensure_ascii=False)
        identificador = sha256(filtros.encode("utf-8")).hexdigest()
        clave = f"cache:reportes:v1:{nombre}:{identificador}"

        if self._cache is not None:
            try:
                contenido = self._cache.obtener(clave)
                if contenido is not None:
                    return deserializar(contenido)
            except (
                ErrorDePersistencia,
                ValueError,
                TypeError,
                KeyError,
                OverflowError,
            ) as error:
                log.warning("Cache no disponible o invalida: %s", error)

        resultado = consultar()

        if self._cache is not None:
            try:
                contenido = serializar(resultado)
                self._cache.guardar(clave, contenido, ttl_segundos=60)
            except (
                ErrorDePersistencia,
                ValueError,
                TypeError,
                OverflowError,
            ) as error:
                log.warning("No se pudo guardar el reporte en cache: %s", error)

        return resultado
    # --- Operativos -------------------------------------------------------

    def envios_por_pais(
        self, desde: datetime | None = None, hasta: datetime | None = None
    ) -> list[ConteoEnviosPorPais]:
        filtros = json.dumps(
            [
                desde.isoformat() if desde is not None else None,
                hasta.isoformat() if hasta is not None else None,
            ]
        )
        identificador = sha256(filtros.encode("utf-8")).hexdigest()
        clave = f"cache:reportes:v1:envios_por_pais:{identificador}"

        if self._cache is not None:
            try:
                contenido = self._cache.obtener(clave)
                if contenido is not None:
                    filas = json.loads(contenido)
                    if not isinstance(filas, list):
                        raise ValueError("Se esperaba una lista")
                    resultado = []
                    for fila in filas:
                        if (
                            not isinstance(fila, dict)
                            or not isinstance(fila.get("pais"), str)
                            or type(fila.get("cantidad")) is not int
                            or fila["cantidad"] < 0
                        ):
                            raise ValueError("Fila de cache invalida")
                        resultado.append(
                            ConteoEnviosPorPais(
                                pais=fila["pais"],
                                cantidad=fila["cantidad"],
                            )
                        )
                    return resultado
            except (ErrorDePersistencia, ValueError, TypeError) as error:
                log.warning("Cache no disponible o invalida: %s", error)

        with self._uow as uow:
            resultado = uow.reportes_envio.envios_por_pais(desde, hasta)

        if self._cache is not None:
            contenido = json.dumps(
                [
                    {"pais": fila.pais, "cantidad": fila.cantidad}
                    for fila in resultado
                ],
                ensure_ascii=False,
            )
            try:
                self._cache.guardar(clave, contenido, ttl_segundos=60)
            except ErrorDePersistencia as error:
                log.warning("No se pudo guardar el reporte en cache: %s", error)

        return resultado

    def envios_por_estado(
        self, desde: datetime | None = None, hasta: datetime | None = None
    ) -> list[ConteoEnviosPorEstado]:
        def consultar() -> list[ConteoEnviosPorEstado]:
            with self._uow as uow:
                return uow.reportes_envio.envios_por_estado(desde, hasta)

        def serializar(filas: list[ConteoEnviosPorEstado]) -> str:
            return json.dumps(
                [
                    {"estado": fila.estado.value, "cantidad": fila.cantidad}
                    for fila in filas
                ]
            )

        def deserializar(contenido: str) -> list[ConteoEnviosPorEstado]:
            filas = json.loads(contenido)
            if not isinstance(filas, list):
                raise ValueError("Se esperaba una lista")

            resultado = []
            for fila in filas:
                if (
                    not isinstance(fila, dict)
                    or not isinstance(fila.get("estado"), str)
                    or type(fila.get("cantidad")) is not int
                    or fila["cantidad"] < 0
                ):
                    raise ValueError("Fila de cache invalida")

                resultado.append(
                    ConteoEnviosPorEstado(
                        estado=EstadoEnvio(fila["estado"]),
                        cantidad=fila["cantidad"],
                    )
                )
            return resultado

        return self._con_cache(
            nombre="envios_por_estado",
            parametros=[
                desde.isoformat() if desde is not None else None,
                hasta.isoformat() if hasta is not None else None,
            ],
            consultar=consultar,
            serializar=serializar,
            deserializar=deserializar,
        )

    def envios_por_cliente(
        self, desde: datetime | None = None, hasta: datetime | None = None
    ) -> list[ConteoEnviosPorCliente]:
        def consultar() -> list[ConteoEnviosPorCliente]:
            with self._uow as uow:
                return uow.reportes_envio.envios_por_cliente(desde, hasta)

        def serializar(filas: list[ConteoEnviosPorCliente]) -> str:
            return json.dumps(
                [
                    {
                        "cliente_id": str(fila.cliente_id),
                        "razon_social": fila.razon_social,
                        "cantidad": fila.cantidad,
                    }
                    for fila in filas
                ],
                ensure_ascii=False,
            )

        def deserializar(contenido: str) -> list[ConteoEnviosPorCliente]:
            filas = json.loads(contenido)
            if not isinstance(filas, list):
                raise ValueError("Se esperaba una lista")

            resultado = []
            for fila in filas:
                if (
                    not isinstance(fila, dict)
                    or not isinstance(fila.get("cliente_id"), str)
                    or not isinstance(fila.get("razon_social"), str)
                    or type(fila.get("cantidad")) is not int
                    or fila["cantidad"] < 0
                ):
                    raise ValueError("Fila de cache invalida")

                resultado.append(
                    ConteoEnviosPorCliente(
                        cliente_id=UUID(fila["cliente_id"]),
                        razon_social=fila["razon_social"],
                        cantidad=fila["cantidad"],
                    )
                )
            return resultado

        return self._con_cache(
            nombre="envios_por_cliente",
            parametros=[
                desde.isoformat() if desde is not None else None,
                hasta.isoformat() if hasta is not None else None,
            ],
            consultar=consultar,
            serializar=serializar,
            deserializar=deserializar,
        )

    # --- Analiticos -------------------------------------------------------

    def tiempos_de_envio_por_cliente(
        self, desde: datetime | None = None, hasta: datetime | None = None
    ) -> list[TiemposDeEnvioPorCliente]:
        def consultar() -> list[TiemposDeEnvioPorCliente]:
            with self._uow as uow:
                return uow.reportes_envio.tiempos_de_envio_por_cliente(
                    desde, hasta
                )

        def guardar_duracion(valor: timedelta | None) -> list[int] | None:
            if valor is None:
                return None
            return [valor.days, valor.seconds, valor.microseconds]

        def recuperar_duracion(datos: object) -> timedelta | None:
            if datos is None:
                return None
            if (
                not isinstance(datos, list)
                or len(datos) != 3
                or any(type(valor) is not int for valor in datos)
                or not 0 <= datos[1] < 86400
                or not 0 <= datos[2] < 1000000
            ):
                raise ValueError("Duracion de cache invalida")
            return timedelta(
                days=datos[0],
                seconds=datos[1],
                microseconds=datos[2],
            )

        def serializar(filas: list[TiemposDeEnvioPorCliente]) -> str:
            return json.dumps(
                [
                    {
                        "cliente_id": str(fila.cliente_id),
                        "razon_social": fila.razon_social,
                        "minimo": guardar_duracion(fila.minimo),
                        "maximo": guardar_duracion(fila.maximo),
                    }
                    for fila in filas
                ],
                ensure_ascii=False,
            )

        def deserializar(contenido: str) -> list[TiemposDeEnvioPorCliente]:
            filas = json.loads(contenido)
            if not isinstance(filas, list):
                raise ValueError("Se esperaba una lista")

            resultado = []
            for fila in filas:
                if (
                    not isinstance(fila, dict)
                    or not isinstance(fila.get("cliente_id"), str)
                    or not isinstance(fila.get("razon_social"), str)
                ):
                    raise ValueError("Fila de cache invalida")

                resultado.append(
                    TiemposDeEnvioPorCliente(
                        cliente_id=UUID(fila["cliente_id"]),
                        razon_social=fila["razon_social"],
                        minimo=recuperar_duracion(fila["minimo"]),
                        maximo=recuperar_duracion(fila["maximo"]),
                    )
                )
            return resultado

        return self._con_cache(
            nombre="tiempos_de_envio_por_cliente",
            parametros=[
                desde.isoformat() if desde is not None else None,
                hasta.isoformat() if hasta is not None else None,
            ],
            consultar=consultar,
            serializar=serializar,
            deserializar=deserializar,
        )

    def tiempo_promedio_de_entrega(
        self, desde: datetime | None = None, hasta: datetime | None = None
    ) -> timedelta | None:
        def consultar() -> timedelta | None:
            with self._uow as uow:
                return uow.reportes_envio.tiempo_promedio_de_entrega(desde, hasta)

        def serializar(valor: timedelta | None) -> str:
            if valor is None:
                return json.dumps(None)

            return json.dumps(
                {
                    "dias": valor.days,
                    "segundos": valor.seconds,
                    "microsegundos": valor.microseconds,
                }
            )

        def deserializar(contenido: str) -> timedelta | None:
            datos = json.loads(contenido)
            if datos is None:
                return None

            if (
                not isinstance(datos, dict)
                or set(datos) != {"dias", "segundos", "microsegundos"}
                or any(type(valor) is not int for valor in datos.values())
                or not 0 <= datos["segundos"] < 86400
                or not 0 <= datos["microsegundos"] < 1000000
            ):
                raise ValueError("Duracion de cache invalida")

            return timedelta(
                days=datos["dias"],
                seconds=datos["segundos"],
                microseconds=datos["microsegundos"],
            )

        return self._con_cache(
            nombre="tiempo_promedio_de_entrega",
            parametros=[
                desde.isoformat() if desde is not None else None,
                hasta.isoformat() if hasta is not None else None,
            ],
            consultar=consultar,
            serializar=serializar,
            deserializar=deserializar,
        )

    def ranking_clientes_por_volumen(
        self,
        limite: int = 10,
        desde: datetime | None = None,
        hasta: datetime | None = None,
    ) -> list[VolumenPorCliente]:
        def consultar() -> list[VolumenPorCliente]:
            with self._uow as uow:
                return uow.reportes_envio.ranking_clientes_por_volumen(
                    limite, desde, hasta
                )

        def serializar(filas: list[VolumenPorCliente]) -> str:
            return json.dumps(
                [
                    {
                        "cliente_id": str(fila.cliente_id),
                        "razon_social": fila.razon_social,
                        "volumen": str(fila.volumen),
                    }
                    for fila in filas
                ],
                ensure_ascii=False,
            )

        def deserializar(contenido: str) -> list[VolumenPorCliente]:
            filas = json.loads(contenido)
            if not isinstance(filas, list):
                raise ValueError("Se esperaba una lista")

            resultado = []
            for fila in filas:
                if (
                    not isinstance(fila, dict)
                    or not isinstance(fila.get("cliente_id"), str)
                    or not isinstance(fila.get("razon_social"), str)
                    or not isinstance(fila.get("volumen"), str)
                ):
                    raise ValueError("Fila de cache invalida")

                try:
                    volumen = Decimal(fila["volumen"])
                except InvalidOperation as error:
                    raise ValueError("Volumen de cache invalido") from error

                if not volumen.is_finite() or volumen < 0:
                    raise ValueError("Volumen de cache invalido")

                resultado.append(
                    VolumenPorCliente(
                        cliente_id=UUID(fila["cliente_id"]),
                        razon_social=fila["razon_social"],
                        volumen=volumen,
                    )
                )
            return resultado

        return self._con_cache(
            nombre="ranking_clientes_por_volumen",
            parametros=[
                limite,
                desde.isoformat() if desde is not None else None,
                hasta.isoformat() if hasta is not None else None,
            ],
            consultar=consultar,
            serializar=serializar,
            deserializar=deserializar,
        )

    def costos_por_tipo_de_transporte(self) -> dict[MedioTransporte, object]:
        def consultar() -> dict[MedioTransporte, object]:
            with self._uow as uow:
                return uow.tramos.costo_por_medio_de_transporte()

        def serializar(costos: dict[MedioTransporte, object]) -> str:
            return json.dumps(
                {medio.value: str(importe) for medio, importe in costos.items()}
            )

        def deserializar(contenido: str) -> dict[MedioTransporte, object]:
            datos = json.loads(contenido)
            if not isinstance(datos, dict):
                raise ValueError("Se esperaba un diccionario")

            resultado = {}
            for medio, importe in datos.items():
                if not isinstance(importe, str):
                    raise ValueError("Importe de cache invalido")

                try:
                    valor = Decimal(importe)
                except InvalidOperation as error:
                    raise ValueError("Importe de cache invalido") from error

                if not valor.is_finite() or valor < 0:
                    raise ValueError("Importe de cache invalido")

                resultado[MedioTransporte(medio)] = valor

            return resultado

        return self._con_cache(
            nombre="costos_por_tipo_de_transporte",
            parametros=[],
            consultar=consultar,
            serializar=serializar,
            deserializar=deserializar,
        )
