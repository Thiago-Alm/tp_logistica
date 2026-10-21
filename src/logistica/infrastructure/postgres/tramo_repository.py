"""Implementacion de TramoRepository sobre PostgreSQL."""
from decimal import Decimal
from uuid import UUID

import psycopg

from logistica.domain.tramo import MedioTransporte, Tramo
from logistica.infrastructure.postgres.conexion import traducir_errores
from logistica.repositories.tramo_repository import TramoRepository

COLUMNAS = """id, envio_id, vehiculo_id, medio_transporte, origen_id, destino_id,
              orden, fecha_salida, fecha_llegada_estimada, costo, fecha_llegada_real"""


def _a_tramo(fila: tuple) -> Tramo:
    return Tramo(
        id=fila[0],
        envio_id=fila[1],
        vehiculo_id=fila[2],
        medio_transporte=MedioTransporte(fila[3]),
        origen_id=fila[4],
        destino_id=fila[5],
        orden=fila[6],
        fecha_salida=fila[7],
        fecha_llegada_estimada=fila[8],
        costo=fila[9],
        fecha_llegada_real=fila[10],
    )


class PostgresTramoRepository(TramoRepository):
    def __init__(self, conexion: psycopg.Connection) -> None:
        self._conexion = conexion

    @traducir_errores
    def guardar(self, tramo: Tramo) -> None:
        self._conexion.execute(
            """insert into tramo (id, envio_id, vehiculo_id, medio_transporte,
                                  origen_id, destino_id, orden, fecha_salida,
                                  fecha_llegada_estimada, costo, fecha_llegada_real)
               values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (tramo.id, tramo.envio_id, tramo.vehiculo_id,
             tramo.medio_transporte.value, tramo.origen_id, tramo.destino_id,
             tramo.orden, tramo.fecha_salida, tramo.fecha_llegada_estimada,
             tramo.costo, tramo.fecha_llegada_real),
        )

    @traducir_errores
    def actualizar(self, tramo: Tramo) -> None:
        self._conexion.execute(
            """update tramo set vehiculo_id = %s, medio_transporte = %s,
                                origen_id = %s, destino_id = %s, orden = %s,
                                fecha_salida = %s, fecha_llegada_estimada = %s,
                                costo = %s, fecha_llegada_real = %s
               where id = %s""",
            (tramo.vehiculo_id, tramo.medio_transporte.value, tramo.origen_id,
             tramo.destino_id, tramo.orden, tramo.fecha_salida,
             tramo.fecha_llegada_estimada, tramo.costo, tramo.fecha_llegada_real,
             tramo.id),
        )

    @traducir_errores
    def obtener(self, id: UUID) -> Tramo | None:
        fila = self._conexion.execute(
            f"select {COLUMNAS} from tramo where id = %s", (id,)
        ).fetchone()
        return _a_tramo(fila) if fila else None

    @traducir_errores
    def listar_por_envio(self, envio_id: UUID) -> list[Tramo]:
        filas = self._conexion.execute(
            f"select {COLUMNAS} from tramo where envio_id = %s order by orden",
            (envio_id,),
        ).fetchall()
        return [_a_tramo(f) for f in filas]

    @traducir_errores
    def listar_por_vehiculo(self, vehiculo_id: UUID) -> list[Tramo]:
        filas = self._conexion.execute(
            f"""select {COLUMNAS} from tramo
                where vehiculo_id = %s
                order by fecha_salida desc""",
            (vehiculo_id,),
        ).fetchall()
        return [_a_tramo(f) for f in filas]

    @traducir_errores
    def costo_por_medio_de_transporte(self) -> dict[MedioTransporte, Decimal]:
        # Este es el GROUP BY que justifico que Tramo fuera tabla propia y no
        # una columna JSONB dentro de envio (D5).
        filas = self._conexion.execute(
            """select medio_transporte, sum(costo)
               from tramo
               group by medio_transporte
               order by sum(costo) desc"""
        ).fetchall()
        return {MedioTransporte(f[0]): f[1] for f in filas}
