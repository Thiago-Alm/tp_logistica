"""Consulta los sensores habilitados para el monitoreo."""

from logistica.config import Settings
from logistica.infrastructure.postgres.conexion import conectar, traducir_errores
from logistica.services.deteccion_inactividad_service import SensorMonitoreado

SQL_SENSORES_MONITOREADOS = """
    SELECT id, intervalo_reporte_segundos
    FROM sensor
    WHERE estado = 'ACTIVO'
    ORDER BY id
"""


@traducir_errores
def cargar_sensores_monitoreados(
    settings: Settings,
) -> list[SensorMonitoreado]:
    with conectar(settings) as conexion:
        filas = conexion.execute(SQL_SENSORES_MONITOREADOS).fetchall()

    return [
        SensorMonitoreado(
            sensor_id=fila[0],
            intervalo_reporte_segundos=fila[1],
        )
        for fila in filas
    ]