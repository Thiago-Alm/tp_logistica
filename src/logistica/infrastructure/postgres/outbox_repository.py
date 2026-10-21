"""Implementacion de OutboxRepository sobre PostgreSQL."""
import json
from uuid import UUID

import psycopg

from logistica.domain.evento_outbox import EventoOutbox, TipoAgregado, TipoEvento
from logistica.infrastructure.postgres.conexion import traducir_errores
from logistica.repositories.outbox_repository import OutboxRepository

COLUMNAS = """id, agregado_tipo, agregado_id, evento_tipo, payload,
              fecha_creacion, procesado, fecha_procesado, error_mensaje, reintentos"""


def _a_evento(fila: tuple) -> EventoOutbox:
    return EventoOutbox(
        id=fila[0],
        agregado_tipo=TipoAgregado(fila[1]),
        agregado_id=fila[2],
        evento_tipo=TipoEvento(fila[3]),
        payload=fila[4],  # psycopg devuelve el JSONB ya convertido a dict
        fecha_creacion=fila[5],
        procesado=fila[6],
        fecha_procesado=fila[7],
        error_mensaje=fila[8],
        reintentos=fila[9],
    )


class PostgresOutboxRepository(OutboxRepository):
    def __init__(self, conexion: psycopg.Connection) -> None:
        self._conexion = conexion

    @traducir_errores
    def guardar(self, evento: EventoOutbox) -> None:
        self._conexion.execute(
            """insert into outbox (id, agregado_tipo, agregado_id, evento_tipo,
                                   payload, fecha_creacion, procesado,
                                   fecha_procesado, error_mensaje, reintentos)
               values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (evento.id, evento.agregado_tipo.value, evento.agregado_id,
             evento.evento_tipo.value, json.dumps(evento.payload, default=str),
             evento.fecha_creacion, evento.procesado, evento.fecha_procesado,
             evento.error_mensaje, evento.reintentos),
        )

    @traducir_errores
    def actualizar(self, evento: EventoOutbox) -> None:
        self._conexion.execute(
            """update outbox set procesado = %s, fecha_procesado = %s,
                                 error_mensaje = %s, reintentos = %s
               where id = %s""",
            (evento.procesado, evento.fecha_procesado, evento.error_mensaje,
             evento.reintentos, evento.id),
        )

    @traducir_errores
    def obtener(self, id: UUID) -> EventoOutbox | None:
        fila = self._conexion.execute(
            f"select {COLUMNAS} from outbox where id = %s", (id,)
        ).fetchone()
        return _a_evento(fila) if fila else None

    @traducir_errores
    def tomar_pendientes(self, limite: int = 100) -> list[EventoOutbox]:
        """Toma eventos pendientes y los bloquea para este worker.

        Dos clausulas que no son decorativas:

        FOR UPDATE: bloquea las filas devueltas hasta el fin de la transaccion,
        para que otro worker no tome los mismos eventos y los propague dos veces.

        SKIP LOCKED: en vez de esperar a que se libere una fila ya tomada, la
        saltea y sigue con la siguiente. Sin esto, un segundo worker quedaria
        bloqueado esperando al primero en lugar de trabajar en paralelo.

        El ORDER BY por fecha_creacion importa: si un envio se crea y despues
        cambia de estado, los eventos tienen que llegar en ese orden.
        """
        filas = self._conexion.execute(
            f"""select {COLUMNAS} from outbox
                where not procesado
                order by fecha_creacion, id
                limit %s
                for update skip locked""",
            (limite,),
        ).fetchall()
        return [_a_evento(f) for f in filas]

    @traducir_errores
    def contar_pendientes(self) -> int:
        fila = self._conexion.execute(
            "select count(*) from outbox where not procesado"
        ).fetchone()
        return fila[0]

    @traducir_errores
    def listar_vencidos(self, reintentos_maximos: int) -> list[EventoOutbox]:
        filas = self._conexion.execute(
            f"""select {COLUMNAS} from outbox
                where not procesado and reintentos >= %s
                order by fecha_creacion""",
            (reintentos_maximos,),
        ).fetchall()
        return [_a_evento(f) for f in filas]
