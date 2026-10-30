"""Implementacion de OperadorRepository y ProveedorRepository sobre PostgreSQL.

Las dos tablas tienen la misma forma salvo `tipo_servicio`, asi que comparten
el armado de las consultas. Lo que cambia —el nombre de la tabla, las columnas
y como se arma la entidad— se declara una vez por clase y el resto se reusa.
"""
from uuid import UUID

import psycopg

from logistica.domain.partes import EstadoParte, Operador, ParteComercial, Proveedor
from logistica.exceptions import NoEncontrado
from logistica.infrastructure.postgres.conexion import traducir_errores
from logistica.repositories.parte_repository import (
    OperadorRepository,
    ProveedorRepository,
)

COMUNES = "id, cuit, razon_social, email, telefono, pais, estado, fecha_creacion"


class _PartesPostgres:
    """Las operaciones que comparten las dos tablas."""

    tabla: str
    columnas: str

    def __init__(self, conexion: psycopg.Connection) -> None:
        self._conexion = conexion

    def _a_entidad(self, fila: tuple) -> ParteComercial:
        raise NotImplementedError

    @traducir_errores
    def obtener(self, id: UUID):
        fila = self._conexion.execute(
            f"select {self.columnas} from {self.tabla} where id = %s", (id,)
        ).fetchone()
        return self._a_entidad(fila) if fila else None

    @traducir_errores
    def obtener_por_cuit(self, cuit: str):
        fila = self._conexion.execute(
            f"select {self.columnas} from {self.tabla} where cuit = %s", (cuit,)
        ).fetchone()
        return self._a_entidad(fila) if fila else None

    @traducir_errores
    def listar(self, estado: EstadoParte | None = None):
        if estado is None:
            filas = self._conexion.execute(
                f"select {self.columnas} from {self.tabla} order by razon_social"
            ).fetchall()
        else:
            filas = self._conexion.execute(
                f"""select {self.columnas} from {self.tabla} where estado = %s
                    order by razon_social""",
                (estado.value,),
            ).fetchall()
        return [self._a_entidad(f) for f in filas]


class PostgresOperadorRepository(_PartesPostgres, OperadorRepository):
    tabla = "operador"
    columnas = COMUNES

    def _a_entidad(self, fila: tuple) -> Operador:
        return Operador(
            id=fila[0],
            cuit=fila[1],
            razon_social=fila[2],
            email=fila[3],
            telefono=fila[4],
            pais=fila[5],
            estado=EstadoParte(fila[6]),
            fecha_creacion=fila[7],
        )

    @traducir_errores
    def guardar(self, operador: Operador) -> None:
        self._conexion.execute(
            """insert into operador
                 (id, cuit, razon_social, email, telefono, pais, estado, fecha_creacion)
               values (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (operador.id, operador.cuit, operador.razon_social, operador.email,
             operador.telefono, operador.pais, operador.estado.value,
             operador.fecha_creacion),
        )

    @traducir_errores
    def actualizar(self, operador: Operador) -> None:
        resultado = self._conexion.execute(
            """update operador set cuit = %s, razon_social = %s, email = %s,
                                   telefono = %s, pais = %s, estado = %s
               where id = %s""",
            (operador.cuit, operador.razon_social, operador.email, operador.telefono,
             operador.pais, operador.estado.value, operador.id),
        )
        if resultado.rowcount == 0:
            raise NoEncontrado(f"No existe el operador {operador.id}")


class PostgresProveedorRepository(_PartesPostgres, ProveedorRepository):
    tabla = "proveedor"
    columnas = f"{COMUNES}, tipo_servicio"

    def _a_entidad(self, fila: tuple) -> Proveedor:
        return Proveedor(
            id=fila[0],
            cuit=fila[1],
            razon_social=fila[2],
            email=fila[3],
            telefono=fila[4],
            pais=fila[5],
            estado=EstadoParte(fila[6]),
            fecha_creacion=fila[7],
            tipo_servicio=fila[8],
        )

    @traducir_errores
    def guardar(self, proveedor: Proveedor) -> None:
        self._conexion.execute(
            """insert into proveedor
                 (id, cuit, razon_social, email, telefono, pais, estado,
                  fecha_creacion, tipo_servicio)
               values (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (proveedor.id, proveedor.cuit, proveedor.razon_social, proveedor.email,
             proveedor.telefono, proveedor.pais, proveedor.estado.value,
             proveedor.fecha_creacion, proveedor.tipo_servicio),
        )

    @traducir_errores
    def actualizar(self, proveedor: Proveedor) -> None:
        resultado = self._conexion.execute(
            """update proveedor set cuit = %s, razon_social = %s, email = %s,
                                    telefono = %s, pais = %s, estado = %s,
                                    tipo_servicio = %s
               where id = %s""",
            (proveedor.cuit, proveedor.razon_social, proveedor.email,
             proveedor.telefono, proveedor.pais, proveedor.estado.value,
             proveedor.tipo_servicio, proveedor.id),
        )
        if resultado.rowcount == 0:
            raise NoEncontrado(f"No existe el proveedor {proveedor.id}")
