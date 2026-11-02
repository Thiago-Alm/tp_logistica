"""Implementacion de UbicacionRepository sobre PostgreSQL."""
from uuid import UUID

import psycopg

from logistica.domain.ubicacion import EstadoUbicacion, TipoUbicacion, Ubicacion
from logistica.infrastructure.postgres.conexion import traducir_errores
from logistica.repositories.ubicacion_repository import UbicacionRepository

COLUMNAS = "id, nombre, tipo, ciudad, pais, codigo_locode, estado"


def _a_ubicacion(fila: tuple) -> Ubicacion:
    return Ubicacion(
        id=fila[0],
        nombre=fila[1],
        tipo=TipoUbicacion(fila[2]),
        ciudad=fila[3],
        pais=fila[4],
        codigo_locode=fila[5],
        estado=EstadoUbicacion(fila[6]),
    )


class PostgresUbicacionRepository(UbicacionRepository):
    def __init__(self, conexion: psycopg.Connection) -> None:
        self._conexion = conexion

    @traducir_errores
    def obtener(self, id: UUID) -> Ubicacion | None:
        fila = self._conexion.execute(
            f"select {COLUMNAS} from ubicacion where id = %s", (id,)
        ).fetchone()
        return _a_ubicacion(fila) if fila else None

    @traducir_errores
    def obtener_por_locode(self, codigo_locode: str) -> Ubicacion | None:
        fila = self._conexion.execute(
            f"select {COLUMNAS} from ubicacion where codigo_locode = %s",
            (codigo_locode,),
        ).fetchone()
        return _a_ubicacion(fila) if fila else None

    @traducir_errores
    def listar(self) -> list[Ubicacion]:
        filas = self._conexion.execute(
            f"select {COLUMNAS} from ubicacion order by pais, ciudad"
        ).fetchall()
        return [_a_ubicacion(f) for f in filas]
