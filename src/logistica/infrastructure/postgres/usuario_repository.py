"""Implementacion de UsuarioRepository sobre PostgreSQL."""
from uuid import UUID

import psycopg

from logistica.domain.usuario import EstadoUsuario, Usuario
from logistica.infrastructure.postgres.conexion import traducir_errores
from logistica.repositories.usuario_repository import UsuarioRepository

COLUMNAS = """id, cliente_id, rol_id, nombre, apellido, email, password_hash,
              estado, fecha_registro"""


def _a_usuario(fila: tuple) -> Usuario:
    return Usuario(
        id=fila[0],
        cliente_id=fila[1],
        rol_id=fila[2],
        nombre=fila[3],
        apellido=fila[4],
        email=fila[5],
        password_hash=fila[6],
        estado=EstadoUsuario(fila[7]),
        fecha_registro=fila[8],
    )


class PostgresUsuarioRepository(UsuarioRepository):
    def __init__(self, conexion: psycopg.Connection) -> None:
        self._conexion = conexion

    @traducir_errores
    def guardar(self, usuario: Usuario) -> None:
        self._conexion.execute(
            """insert into usuario (id, cliente_id, rol_id, nombre, apellido,
                                    email, password_hash, estado, fecha_registro)
               values (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (usuario.id, usuario.cliente_id, usuario.rol_id, usuario.nombre,
             usuario.apellido, usuario.email, usuario.password_hash,
             usuario.estado.value, usuario.fecha_registro),
        )

    @traducir_errores
    def actualizar(self, usuario: Usuario) -> None:
        self._conexion.execute(
            """update usuario set cliente_id = %s, rol_id = %s, nombre = %s,
                                  apellido = %s, email = %s, password_hash = %s,
                                  estado = %s
               where id = %s""",
            (usuario.cliente_id, usuario.rol_id, usuario.nombre, usuario.apellido,
             usuario.email, usuario.password_hash, usuario.estado.value, usuario.id),
        )

    @traducir_errores
    def obtener(self, id: UUID) -> Usuario | None:
        fila = self._conexion.execute(
            f"select {COLUMNAS} from usuario where id = %s", (id,)
        ).fetchone()
        return _a_usuario(fila) if fila else None

    @traducir_errores
    def obtener_por_email(self, email: str) -> Usuario | None:
        fila = self._conexion.execute(
            f"select {COLUMNAS} from usuario where email = %s", (email,)
        ).fetchone()
        return _a_usuario(fila) if fila else None

    @traducir_errores
    def listar(self, estado: EstadoUsuario | None = None) -> list[Usuario]:
        if estado is None:
            filas = self._conexion.execute(
                f"select {COLUMNAS} from usuario order by apellido, nombre"
            ).fetchall()
        else:
            filas = self._conexion.execute(
                f"select {COLUMNAS} from usuario where estado = %s order by apellido, nombre",
                (estado.value,),
            ).fetchall()
        return [_a_usuario(f) for f in filas]

    @traducir_errores
    def listar_por_cliente(self, cliente_id: UUID) -> list[Usuario]:
        filas = self._conexion.execute(
            f"select {COLUMNAS} from usuario where cliente_id = %s order by apellido, nombre",
            (cliente_id,),
        ).fetchall()
        return [_a_usuario(f) for f in filas]
