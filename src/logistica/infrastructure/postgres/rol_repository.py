"""Implementacion de RolRepository sobre PostgreSQL."""
from uuid import UUID

import psycopg

from logistica.domain.rol import Rol
from logistica.infrastructure.postgres.conexion import traducir_errores
from logistica.repositories.rol_repository import RolRepository

COLUMNAS = "id, descripcion, nivel_permisos"


def _a_rol(fila: tuple) -> Rol:
    return Rol(id=fila[0], descripcion=fila[1], nivel_permisos=fila[2])


class PostgresRolRepository(RolRepository):
    def __init__(self, conexion: psycopg.Connection) -> None:
        self._conexion = conexion

    @traducir_errores
    def guardar(self, rol: Rol) -> None:
        self._conexion.execute(
            "insert into rol (id, descripcion, nivel_permisos) values (%s, %s, %s)",
            (rol.id, rol.descripcion, rol.nivel_permisos),
        )

    @traducir_errores
    def actualizar(self, rol: Rol) -> None:
        self._conexion.execute(
            "update rol set descripcion = %s, nivel_permisos = %s where id = %s",
            (rol.descripcion, rol.nivel_permisos, rol.id),
        )

    @traducir_errores
    def obtener(self, id: UUID) -> Rol | None:
        fila = self._conexion.execute(
            f"select {COLUMNAS} from rol where id = %s", (id,)
        ).fetchone()
        return _a_rol(fila) if fila else None

    @traducir_errores
    def obtener_por_descripcion(self, descripcion: str) -> Rol | None:
        fila = self._conexion.execute(
            f"select {COLUMNAS} from rol where descripcion = %s", (descripcion,)
        ).fetchone()
        return _a_rol(fila) if fila else None

    @traducir_errores
    def listar(self) -> list[Rol]:
        filas = self._conexion.execute(
            f"select {COLUMNAS} from rol order by nivel_permisos desc"
        ).fetchall()
        return [_a_rol(f) for f in filas]
