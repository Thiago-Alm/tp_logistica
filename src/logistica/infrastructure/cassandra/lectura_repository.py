"""Implementacion de LecturaRepository sobre Cassandra."""
import logging
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from cassandra import ConsistencyLevel
from cassandra.cluster import Session
from cassandra.query import UNSET_VALUE, BatchStatement, BatchType

from logistica.domain.lectura import Lectura, Posicion
from logistica.exceptions import ValidacionError
from logistica.infrastructure.cassandra.conexion import traducir_errores
from logistica.repositories.lectura_repository import (
    MAX_DIAS_POR_CONSULTA,
    LecturaRepository,
    dias_del_rango,
)

log = logging.getLogger(__name__)

# `ultimas` retrocede dia por dia hasta juntar la cantidad pedida. Un sensor que
# lleva mas de este tiempo callado devuelve menos lecturas de las pedidas.
MAX_DIAS_HACIA_ATRAS = 30
# Escrituras en vuelo a la vez en guardar_lote.
CONCURRENCIA = 64

_COLUMNAS_LECTURA = (
    "sensor_id, contenedor_id, momento, temperatura, humedad, vibracion, "
    "latitud, longitud, bateria"
)
_COLUMNAS_POSICION = "contenedor_id, sensor_id, momento, envio_id, latitud, longitud"


def _a_utc(momento: datetime) -> datetime:
    """Normaliza a UTC. Un datetime sin zona horaria se interpreta como UTC, que
    es la convencion del grupo para todas las bases."""
    if momento.tzinfo is None:
        return momento.replace(tzinfo=timezone.utc)
    return momento.astimezone(timezone.utc)


def _a_lectura(fila: Any) -> Lectura:
    """Fila -> entidad de dominio (D2). El driver devuelve `momento` sin zona
    horaria, en UTC: se la reponemos."""
    return Lectura(
        sensor_id=fila.sensor_id,
        contenedor_id=fila.contenedor_id,
        momento=fila.momento.replace(tzinfo=timezone.utc),
        temperatura=fila.temperatura,
        humedad=fila.humedad,
        vibracion=fila.vibracion,
        latitud=fila.latitud,
        longitud=fila.longitud,
        bateria=fila.bateria,
    )


def _a_posicion(fila: Any) -> Posicion:
    return Posicion(
        contenedor_id=fila.contenedor_id,
        sensor_id=fila.sensor_id,
        momento=fila.momento.replace(tzinfo=timezone.utc),
        latitud=fila.latitud,
        longitud=fila.longitud,
        envio_id=fila.envio_id,
    )


class CassandraLecturaRepository(LecturaRepository):
    @traducir_errores
    def __init__(
        self, sesion: Session, ahora: Callable[[], datetime] | None = None
    ) -> None:
        self._sesion = sesion
        # Se inyecta el reloj para poder probar `ultimas` sin depender de la hora.
        self._ahora = ahora or (lambda: datetime.now(timezone.utc))

        self._insertar_por_sensor = sesion.prepare(
            """INSERT INTO lecturas_por_sensor
                 (sensor_id, dia, momento, contenedor_id, temperatura, humedad,
                  vibracion, latitud, longitud, bateria)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
        )
        self._insertar_recorrido = sesion.prepare(
            """INSERT INTO recorrido_por_contenedor
                 (contenedor_id, dia, momento, sensor_id, envio_id, latitud, longitud)
               VALUES (?, ?, ?, ?, ?, ?, ?)"""
        )
        # lecturas_por_sensor se guarda en orden DESC; aca se pide ASC para que el
        # rango salga cronologico (invertir el orden de una sola particion es barato).
        self._rango_por_sensor = sesion.prepare(
            f"""SELECT {_COLUMNAS_LECTURA} FROM lecturas_por_sensor
                WHERE sensor_id = ? AND dia = ? AND momento >= ? AND momento <= ?
                ORDER BY momento ASC"""
        )
        # Orden natural de la tabla (DESC): LIMIT devuelve las mas recientes.
        self._ultimas_por_sensor = sesion.prepare(
            f"""SELECT {_COLUMNAS_LECTURA} FROM lecturas_por_sensor
                WHERE sensor_id = ? AND dia = ? LIMIT ?"""
        )
        # recorrido_por_contenedor ya esta en orden ASC.
        self._rango_recorrido = sesion.prepare(
            f"""SELECT {_COLUMNAS_POSICION} FROM recorrido_por_contenedor
                WHERE contenedor_id = ? AND dia = ? AND momento >= ? AND momento <= ?"""
        )

    # -- escritura ---------------------------------------------------------

    def _armar_lote(self, lectura: Lectura) -> BatchStatement:
        """Las dos escrituras de una lectura, en un batch LOGGED.

        LOGGED significa que Cassandra registra el batch antes de aplicarlo: si el
        nodo cae a mitad, lo completa despues. Asi las dos tablas no quedan
        desincronizadas (D31). Cuesta algo de rendimiento, pero son solo dos
        escrituras. Nivel ONE: una lectura aislada perdida es tolerable.
        """
        momento = _a_utc(lectura.momento)
        dia = momento.date()
        # Escribir None en Cassandra crea un tombstone. Para "sin envio" no se
        # escribe la columna (UNSET_VALUE).
        envio_id = lectura.envio_id if lectura.envio_id is not None else UNSET_VALUE

        lote = BatchStatement(
            batch_type=BatchType.LOGGED, consistency_level=ConsistencyLevel.ONE
        )
        lote.add(
            self._insertar_por_sensor,
            (
                lectura.sensor_id, dia, momento, lectura.contenedor_id,
                lectura.temperatura, lectura.humedad, lectura.vibracion,
                lectura.latitud, lectura.longitud, lectura.bateria,
            ),
        )
        lote.add(
            self._insertar_recorrido,
            (
                lectura.contenedor_id, dia, momento, lectura.sensor_id,
                envio_id, lectura.latitud, lectura.longitud,
            ),
        )
        return lote

    @traducir_errores
    def guardar(self, lectura: Lectura) -> None:
        self._sesion.execute(self._armar_lote(lectura))

    @traducir_errores
    def guardar_lote(self, lecturas: list[Lectura]) -> None:
        for inicio in range(0, len(lecturas), CONCURRENCIA):
            grupo = lecturas[inicio : inicio + CONCURRENCIA]
            futuros = [self._sesion.execute_async(self._armar_lote(lec)) for lec in grupo]
            for futuro in futuros:
                futuro.result()
        log.debug("Guardadas %d lecturas", len(lecturas))

    # -- lectura -----------------------------------------------------------

    @staticmethod
    def _validar_rango(desde: datetime, hasta: datetime) -> list[date]:
        if _a_utc(desde) > _a_utc(hasta):
            raise ValidacionError("'desde' no puede ser posterior a 'hasta'")
        dias = dias_del_rango(desde, hasta)
        if len(dias) > MAX_DIAS_POR_CONSULTA:
            raise ValidacionError(
                f"El rango abarca {len(dias)} dias; el maximo por consulta es "
                f"{MAX_DIAS_POR_CONSULTA}. Pedilo por tramos."
            )
        return dias

    @traducir_errores
    def listar_por_sensor(
        self, sensor_id: UUID, desde: datetime, hasta: datetime
    ) -> list[Lectura]:
        dias = self._validar_rango(desde, hasta)
        desde_utc, hasta_utc = _a_utc(desde), _a_utc(hasta)
        resultado: list[Lectura] = []
        for dia in dias:
            filas = self._sesion.execute(
                self._rango_por_sensor, (sensor_id, dia, desde_utc, hasta_utc)
            )
            resultado.extend(_a_lectura(f) for f in filas)
        return resultado

    @traducir_errores
    def posiciones_de_contenedor(
        self, contenedor_id: UUID, desde: datetime, hasta: datetime
    ) -> list[Posicion]:
        dias = self._validar_rango(desde, hasta)
        desde_utc, hasta_utc = _a_utc(desde), _a_utc(hasta)
        resultado: list[Posicion] = []
        for dia in dias:
            filas = self._sesion.execute(
                self._rango_recorrido, (contenedor_id, dia, desde_utc, hasta_utc)
            )
            resultado.extend(_a_posicion(f) for f in filas)
        return resultado

    @traducir_errores
    def ultimas(self, sensor_id: UUID, cantidad: int) -> list[Lectura]:
        if cantidad <= 0:
            raise ValidacionError("'cantidad' tiene que ser mayor que cero")
        hoy = _a_utc(self._ahora()).date()
        resultado: list[Lectura] = []
        for atras in range(MAX_DIAS_HACIA_ATRAS + 1):
            faltan = cantidad - len(resultado)
            if faltan <= 0:
                break
            dia = hoy - timedelta(days=atras)
            filas = self._sesion.execute(self._ultimas_por_sensor, (sensor_id, dia, faltan))
            resultado.extend(_a_lectura(f) for f in filas)
        return resultado
