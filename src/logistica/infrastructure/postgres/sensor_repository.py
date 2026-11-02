"""Implementacion de SensorRepository sobre PostgreSQL."""
from uuid import UUID

import psycopg

from logistica.domain.sensor import EstadoSensor, Sensor, TipoSensor
from logistica.infrastructure.postgres.conexion import traducir_errores
from logistica.repositories.sensor_repository import SensorRepository

COLUMNAS = (
    "id, contenedor_id, numero_serie, modelo, tipo, "
    "intervalo_reporte_segundos, estado, fecha_instalacion"
)


def _a_sensor(fila: tuple) -> Sensor:
    return Sensor(
        id=fila[0],
        contenedor_id=fila[1],
        numero_serie=fila[2],
        modelo=fila[3],
        tipo=TipoSensor(fila[4]),
        intervalo_reporte_segundos=fila[5],
        estado=EstadoSensor(fila[6]),
        fecha_instalacion=fila[7],
    )


class PostgresSensorRepository(SensorRepository):
    def __init__(self, conexion: psycopg.Connection) -> None:
        self._conexion = conexion

    @traducir_errores
    def guardar(self, sensor: Sensor) -> None:
        self._conexion.execute(
            """insert into sensor (id, contenedor_id, numero_serie, modelo, tipo,
                                   intervalo_reporte_segundos, estado, fecha_instalacion)
               values (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (sensor.id, sensor.contenedor_id, sensor.numero_serie, sensor.modelo,
             sensor.tipo.value, sensor.intervalo_reporte_segundos,
             sensor.estado.value, sensor.fecha_instalacion),
        )

    @traducir_errores
    def actualizar(self, sensor: Sensor) -> None:
        self._conexion.execute(
            """update sensor set contenedor_id = %s, numero_serie = %s, modelo = %s,
                                 tipo = %s, intervalo_reporte_segundos = %s,
                                 estado = %s
               where id = %s""",
            (sensor.contenedor_id, sensor.numero_serie, sensor.modelo,
             sensor.tipo.value, sensor.intervalo_reporte_segundos,
             sensor.estado.value, sensor.id),
        )

    @traducir_errores
    def obtener(self, id: UUID) -> Sensor | None:
        fila = self._conexion.execute(
            f"select {COLUMNAS} from sensor where id = %s", (id,)
        ).fetchone()
        return _a_sensor(fila) if fila else None

    @traducir_errores
    def obtener_por_numero_serie(self, numero_serie: str) -> Sensor | None:
        fila = self._conexion.execute(
            f"select {COLUMNAS} from sensor where numero_serie = %s", (numero_serie,)
        ).fetchone()
        return _a_sensor(fila) if fila else None

    @traducir_errores
    def listar(self, estado: EstadoSensor | None = None) -> list[Sensor]:
        if estado is None:
            filas = self._conexion.execute(
                f"select {COLUMNAS} from sensor order by numero_serie"
            ).fetchall()
        else:
            filas = self._conexion.execute(
                f"""select {COLUMNAS} from sensor where estado = %s
                    order by numero_serie""",
                (estado.value,),
            ).fetchall()
        return [_a_sensor(f) for f in filas]

    @traducir_errores
    def listar_por_contenedor(self, contenedor_id: UUID) -> list[Sensor]:
        filas = self._conexion.execute(
            f"""select {COLUMNAS} from sensor where contenedor_id = %s
                order by numero_serie""",
            (contenedor_id,),
        ).fetchall()
        return [_a_sensor(f) for f in filas]
