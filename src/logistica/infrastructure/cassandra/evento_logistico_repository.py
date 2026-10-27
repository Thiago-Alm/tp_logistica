"""Implementacion de EventoLogisticoRepository sobre Cassandra."""
import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from cassandra import ConsistencyLevel
from cassandra.cluster import Session

from logistica.domain.evento_logistico import EventoLogistico, TipoEventoLogistico
from logistica.exceptions import ValidacionError
from logistica.infrastructure.cassandra.conexion import traducir_errores
from logistica.repositories.evento_logistico_repository import EventoLogisticoRepository

log = logging.getLogger(__name__)

# La particion de eventos_por_contenedor lleva bucket mensual, asi que un rango
# es una consulta por mes. Se limita para que un rango enorme no dispare
# decenas de consultas.
MAX_MESES_POR_CONSULTA = 24

_COLUMNAS = (
    "tipo, contenedor_id, ubicacion_id, ubicacion_nombre, latitud, longitud, descripcion"
)


def _a_utc(momento: datetime) -> datetime:
    if momento.tzinfo is None:
        return momento.replace(tzinfo=timezone.utc)
    return momento.astimezone(timezone.utc)


def _meses(desde: datetime, hasta: datetime) -> list[str]:
    """Los buckets 'YYYY-MM' que toca un rango, ambos extremos incluidos."""
    primero = _a_utc(desde).date().replace(day=1)
    ultimo = _a_utc(hasta).date().replace(day=1)
    if ultimo < primero:
        raise ValidacionError("El rango termina antes de empezar")
    meses: list[str] = []
    actual = primero
    while actual <= ultimo:
        meses.append(actual.strftime("%Y-%m"))
        # Pasar al primero del mes siguiente sin depender de cuantos dias tiene.
        actual = (actual + timedelta(days=32)).replace(day=1)
    if len(meses) > MAX_MESES_POR_CONSULTA:
        raise ValidacionError(
            f"El rango abarca {len(meses)} meses; el maximo es {MAX_MESES_POR_CONSULTA}"
        )
    return meses


def _a_evento(fila: Any, envio_id: UUID, evento_id: UUID, momento: datetime) -> EventoLogistico:
    return EventoLogistico(
        id=evento_id,
        envio_id=envio_id,
        tipo=TipoEventoLogistico(fila.tipo),
        momento=momento.replace(tzinfo=timezone.utc),
        descripcion=fila.descripcion,
        contenedor_id=fila.contenedor_id,
        ubicacion_id=fila.ubicacion_id,
        ubicacion_nombre=fila.ubicacion_nombre,
        latitud=fila.latitud,
        longitud=fila.longitud,
    )


class CassandraEventoLogisticoRepository(EventoLogisticoRepository):
    def __init__(self, sesion: Session) -> None:
        self._sesion = sesion
        self._preparadas: dict[str, Any] = {}

    def _preparar(self, nombre: str, cql: str, consistencia: int) -> Any:
        """Las consultas se preparan una sola vez y se reusan: el servidor
        guarda el plan y la aplicacion manda solo los parametros."""
        if nombre not in self._preparadas:
            sentencia = self._sesion.prepare(cql)
            sentencia.consistency_level = consistencia
            self._preparadas[nombre] = sentencia
        return self._preparadas[nombre]

    # --- Escritura -------------------------------------------------------

    @traducir_errores
    def guardar(self, evento: EventoLogistico) -> None:
        """Escribe en las dos tablas. QUORUM y no ONE: la trazabilidad no puede
        perder eventos, a diferencia de una lectura de sensor suelta."""
        momento = evento.momento_utc
        comunes = (
            evento.tipo.value,
            evento.ubicacion_id,
            evento.ubicacion_nombre,
            evento.latitud,
            evento.longitud,
            evento.descripcion,
        )

        por_envio = self._preparar(
            "por_envio",
            """insert into eventos_por_envio
               (envio_id, momento, evento_id, tipo, contenedor_id, ubicacion_id,
                ubicacion_nombre, latitud, longitud, descripcion)
               values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ConsistencyLevel.QUORUM,
        )
        self._sesion.execute(
            por_envio,
            (evento.envio_id, momento, evento.id, comunes[0], evento.contenedor_id,
             *comunes[1:]),
        )

        if evento.contenedor_id is None:
            # Sin contenedor no hay clave de particion para la segunda tabla.
            return

        por_contenedor = self._preparar(
            "por_contenedor",
            """insert into eventos_por_contenedor
               (contenedor_id, anio_mes, momento, evento_id, envio_id, tipo,
                ubicacion_id, ubicacion_nombre, latitud, longitud, descripcion)
               values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ConsistencyLevel.QUORUM,
        )
        self._sesion.execute(
            por_contenedor,
            (evento.contenedor_id, evento.anio_mes, momento, evento.id,
             evento.envio_id, *comunes),
        )

    # --- Lectura ---------------------------------------------------------

    @traducir_errores
    def historial_de_envio(self, envio_id: UUID) -> list[EventoLogistico]:
        consulta = self._preparar(
            "historial",
            f"""select momento, evento_id, {_COLUMNAS}
                from eventos_por_envio where envio_id = ?""",
            ConsistencyLevel.QUORUM,
        )
        filas = self._sesion.execute(consulta, (envio_id,))
        # La tabla ya esta ordenada por momento ASC: no hace falta ORDER BY.
        return [_a_evento(f, envio_id, f.evento_id, f.momento) for f in filas]

    @traducir_errores
    def ultimo_de_envio(self, envio_id: UUID) -> EventoLogistico | None:
        historial = self.historial_de_envio(envio_id)
        return historial[-1] if historial else None

    @traducir_errores
    def movimientos_de_contenedor(
        self, contenedor_id: UUID, desde: datetime, hasta: datetime
    ) -> list[EventoLogistico]:
        consulta = self._preparar(
            "movimientos",
            f"""select momento, evento_id, envio_id, {_COLUMNAS}
                from eventos_por_contenedor
                where contenedor_id = ? and anio_mes = ?
                  and momento >= ? and momento <= ?""",
            ConsistencyLevel.QUORUM,
        )
        desde_utc, hasta_utc = _a_utc(desde), _a_utc(hasta)
        eventos: list[EventoLogistico] = []
        for mes in _meses(desde_utc, hasta_utc):
            filas = self._sesion.execute(
                consulta, (contenedor_id, mes, desde_utc, hasta_utc)
            )
            eventos.extend(
                _a_evento(f, f.envio_id, f.evento_id, f.momento) for f in filas
            )
        # Esa tabla ordena DESC dentro de cada particion; al unir varios meses
        # hay que reordenar para que el recorrido se lea del inicio al final.
        eventos.sort(key=lambda e: e.momento_utc)
        return eventos

