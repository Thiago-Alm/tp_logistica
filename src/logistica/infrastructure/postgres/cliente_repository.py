"""Implementacion de ClienteRepository sobre PostgreSQL."""
from uuid import UUID

import psycopg

from logistica.domain.cliente import Cliente, EstadoCliente
from logistica.infrastructure.postgres.conexion import traducir_errores
from logistica.repositories.cliente_repository import ClienteRepository

COLUMNAS = """id, cuit, razon_social, email, telefono, direccion, pais,
              estado, fecha_creacion"""


def _a_cliente(fila: tuple) -> Cliente:
    """Fila -> entidad de dominio. El repositorio es el unico que conoce las dos
    formas: hacia arriba solo circulan entidades (D2)."""
    return Cliente(
        id=fila[0],
        cuit=fila[1],
        razon_social=fila[2],
        email=fila[3],
        telefono=fila[4],
        direccion=fila[5],
        pais=fila[6],
        estado=EstadoCliente(fila[7]),
        fecha_creacion=fila[8],
    )


class PostgresClienteRepository(ClienteRepository):
    def __init__(self, conexion: psycopg.Connection) -> None:
        self._conexion = conexion

    @traducir_errores
    def guardar(self, cliente: Cliente) -> None:
        self._conexion.execute(
            """insert into cliente (id, cuit, razon_social, email, telefono,
                                    direccion, pais, estado, fecha_creacion)
               values (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (cliente.id, cliente.cuit, cliente.razon_social, cliente.email,
             cliente.telefono, cliente.direccion, cliente.pais,
             cliente.estado.value, cliente.fecha_creacion),
        )

    @traducir_errores
    def actualizar(self, cliente: Cliente) -> None:
        self._conexion.execute(
            """update cliente set cuit = %s, razon_social = %s, email = %s,
                                  telefono = %s, direccion = %s, pais = %s,
                                  estado = %s
               where id = %s""",
            (cliente.cuit, cliente.razon_social, cliente.email, cliente.telefono,
             cliente.direccion, cliente.pais, cliente.estado.value, cliente.id),
        )

    @traducir_errores
    def obtener(self, id: UUID) -> Cliente | None:
        fila = self._conexion.execute(
            f"select {COLUMNAS} from cliente where id = %s", (id,)
        ).fetchone()
        return _a_cliente(fila) if fila else None

    @traducir_errores
    def obtener_por_cuit(self, cuit: str) -> Cliente | None:
        fila = self._conexion.execute(
            f"select {COLUMNAS} from cliente where cuit = %s", (cuit,)
        ).fetchone()
        return _a_cliente(fila) if fila else None

    @traducir_errores
    def listar(self, estado: EstadoCliente | None = None) -> list[Cliente]:
        if estado is None:
            filas = self._conexion.execute(
                f"select {COLUMNAS} from cliente order by razon_social"
            ).fetchall()
        else:
            filas = self._conexion.execute(
                f"select {COLUMNAS} from cliente where estado = %s order by razon_social",
                (estado.value,),
            ).fetchall()
        return [_a_cliente(f) for f in filas]
