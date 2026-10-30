"""Implementacion de ContenedorRepository sobre PostgreSQL."""
from uuid import UUID

import psycopg

from logistica.domain.contenedor import Contenedor, EstadoContenedor
from logistica.infrastructure.postgres.conexion import traducir_errores
from logistica.repositories.contenedor_repository import ContenedorRepository

COLUMNAS = "id, codigo_iso, tipo, capacidad, estado"


def _a_contenedor(fila: tuple) -> Contenedor:
    return Contenedor(
        id=fila[0],
        codigo_iso=fila[1],
        tipo=fila[2],
        capacidad=float(fila[3]),
        estado=EstadoContenedor(fila[4]),
    )


class PostgresContenedorRepository(ContenedorRepository):
    def __init__(self, conexion: psycopg.Connection) -> None:
        self._conexion = conexion

    @traducir_errores
    def guardar(self, contenedor: Contenedor) -> None:
        self._conexion.execute(
            """insert into contenedor (id, codigo_iso, tipo, capacidad, estado)
               values (%s, %s, %s, %s, %s)""",
            (contenedor.id, contenedor.codigo_iso, contenedor.tipo,
             contenedor.capacidad, contenedor.estado.value),
        )

    @traducir_errores
    def actualizar(self, contenedor: Contenedor) -> None:
        self._conexion.execute(
            """update contenedor set codigo_iso = %s, tipo = %s, capacidad = %s,
                                     estado = %s
               where id = %s""",
            (contenedor.codigo_iso, contenedor.tipo, contenedor.capacidad,
             contenedor.estado.value, contenedor.id),
        )

    @traducir_errores
    def obtener(self, id: UUID) -> Contenedor | None:
        fila = self._conexion.execute(
            f"select {COLUMNAS} from contenedor where id = %s", (id,)
        ).fetchone()
        return _a_contenedor(fila) if fila else None

    @traducir_errores
    def obtener_por_codigo(self, codigo_iso: str) -> Contenedor | None:
        fila = self._conexion.execute(
            f"select {COLUMNAS} from contenedor where codigo_iso = %s", (codigo_iso,)
        ).fetchone()
        return _a_contenedor(fila) if fila else None

    @traducir_errores
    def listar(self) -> list[Contenedor]:
        filas = self._conexion.execute(
            f"select {COLUMNAS} from contenedor order by codigo_iso"
        ).fetchall()
        return [_a_contenedor(f) for f in filas]

    @traducir_errores
    def listar_por_estado(self, estado: EstadoContenedor) -> list[Contenedor]:
        filas = self._conexion.execute(
            f"select {COLUMNAS} from contenedor where estado = %s order by codigo_iso",
            (estado.value,),
        ).fetchall()
        return [_a_contenedor(f) for f in filas]
