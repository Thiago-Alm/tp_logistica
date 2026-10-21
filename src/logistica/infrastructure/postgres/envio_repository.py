"""Implementacion de EnvioRepository sobre PostgreSQL."""
from datetime import datetime
from uuid import UUID

import psycopg

from logistica.domain.envio import Envio, EstadoEnvio, PrioridadEnvio
from logistica.infrastructure.postgres.conexion import traducir_errores
from logistica.repositories.envio_repository import EnvioRepository

COLUMNAS = """e.id, e.cliente_id, e.origen_id, e.destino_id, e.estado,
              e.prioridad, e.fecha_creacion, e.fecha_llegada_real"""


def _a_envio(fila: tuple) -> Envio:
    return Envio(
        id=fila[0],
        cliente_id=fila[1],
        origen_id=fila[2],
        destino_id=fila[3],
        estado=EstadoEnvio(fila[4]),
        prioridad=PrioridadEnvio(fila[5]),
        fecha_creacion=fila[6],
        fecha_llegada_real=fila[7],
    )


class PostgresEnvioRepository(EnvioRepository):
    def __init__(self, conexion: psycopg.Connection) -> None:
        self._conexion = conexion

    # --- Escritura -------------------------------------------------------

    @traducir_errores
    def guardar(self, envio: Envio) -> None:
        self._conexion.execute(
            """insert into envio (id, cliente_id, origen_id, destino_id, estado,
                                  prioridad, fecha_creacion, fecha_llegada_real)
               values (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (envio.id, envio.cliente_id, envio.origen_id, envio.destino_id,
             envio.estado.value, envio.prioridad.value, envio.fecha_creacion,
             envio.fecha_llegada_real),
        )

    @traducir_errores
    def actualizar(self, envio: Envio) -> None:
        self._conexion.execute(
            """update envio set cliente_id = %s, origen_id = %s, destino_id = %s,
                                estado = %s, prioridad = %s, fecha_llegada_real = %s
               where id = %s""",
            (envio.cliente_id, envio.origen_id, envio.destino_id,
             envio.estado.value, envio.prioridad.value, envio.fecha_llegada_real,
             envio.id),
        )

    @traducir_errores
    def asociar_contenedor(self, envio_id: UUID, contenedor_id: UUID) -> None:
        self._conexion.execute(
            """insert into envio_contenedor (envio_id, contenedor_id)
               values (%s, %s)""",
            (envio_id, contenedor_id),
        )

    @traducir_errores
    def listar_contenedores(self, envio_id: UUID) -> list[UUID]:
        filas = self._conexion.execute(
            """select contenedor_id from envio_contenedor
               where envio_id = %s order by fecha_asignacion""",
            (envio_id,),
        ).fetchall()
        return [f[0] for f in filas]

    # --- Lectura puntual -------------------------------------------------

    @traducir_errores
    def obtener(self, id: UUID) -> Envio | None:
        fila = self._conexion.execute(
            f"select {COLUMNAS} from envio e where e.id = %s", (id,)
        ).fetchone()
        return _a_envio(fila) if fila else None

    @traducir_errores
    def listar_por_cliente(self, cliente_id: UUID) -> list[Envio]:
        filas = self._conexion.execute(
            f"""select {COLUMNAS} from envio e
                where e.cliente_id = %s
                order by e.fecha_creacion desc""",
            (cliente_id,),
        ).fetchall()
        return [_a_envio(f) for f in filas]

    @traducir_errores
    def listar_por_estado(self, estado: EstadoEnvio) -> list[Envio]:
        filas = self._conexion.execute(
            f"""select {COLUMNAS} from envio e
                where e.estado = %s
                order by e.fecha_creacion desc""",
            (estado.value,),
        ).fetchall()
        return [_a_envio(f) for f in filas]

    @traducir_errores
    def listar_por_pais_destino(self, pais: str) -> list[Envio]:
        # El envio no guarda el pais: se resuelve por su ubicacion de destino.
        filas = self._conexion.execute(
            f"""select {COLUMNAS}
                from envio e
                join ubicacion u on u.id = e.destino_id
                where u.pais = %s
                order by e.fecha_creacion desc""",
            (pais,),
        ).fetchall()
        return [_a_envio(f) for f in filas]

    @traducir_errores
    def listar_demorados(self, momento: datetime) -> list[Envio]:
        """Demorado = no entregado ni cancelado, y la ultima llegada estimada
        entre sus tramos ya paso (D7).

        La fecha estimada no esta en `envio` a proposito: se deriva con un MAX
        sobre `tramo`, para no mantener un dato duplicado que haya que
        sincronizar cada vez que cambia un tramo.
        """
        filas = self._conexion.execute(
            f"""select {COLUMNAS}
                from envio e
                join tramo t on t.envio_id = e.id
                where e.estado not in ('ENTREGADO', 'CANCELADO')
                group by e.id
                having max(t.fecha_llegada_estimada) < %s
                order by max(t.fecha_llegada_estimada)""",
            (momento,),
        ).fetchall()
        return [_a_envio(f) for f in filas]
