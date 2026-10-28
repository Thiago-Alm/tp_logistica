"""Detecta sensores que dejaron de enviar señales."""

import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from math import isfinite
from uuid import UUID

from logistica.exceptions import ValidacionError
from logistica.repositories.heartbeat_repository import HeartbeatRepository


@dataclass(frozen=True)
class SensorMonitoreado:
    sensor_id: UUID
    intervalo_reporte_segundos: int


@dataclass(frozen=True)
class ResultadoInactividad:
    sensor_id: UUID
    estado: str
    segundos_sin_reportar: float | None


class DeteccionInactividadService:
    def __init__(
        self,
        heartbeat: HeartbeatRepository,
        cargar_sensores: Callable[[], Iterable[SensorMonitoreado]],
        reloj: Callable[[], float] = time.time,
    ) -> None:
        self._heartbeat = heartbeat
        self._cargar_sensores = cargar_sensores
        self._reloj = reloj

    def verificar(self) -> list[ResultadoInactividad]:
        resultados = []

        for sensor in self._cargar_sensores():
            intervalo = sensor.intervalo_reporte_segundos
            if not isfinite(intervalo) or intervalo <= 0:
                raise ValidacionError(
                    f"Intervalo de reporte invalido para {sensor.sensor_id}"
                )

            # Los errores de Redis se propagan: no significan inactividad.
            ultimo = self._heartbeat.ultimo_reporte(sensor.sensor_id)

            if ultimo is None:
                # Puede ser un sensor nuevo o haberse perdido datos de Redis.
                resultados.append(
                    ResultadoInactividad(sensor.sensor_id, "SIN_DATOS", None)
                )
                continue

            transcurrido = self._reloj() - ultimo
            if not isfinite(transcurrido) or transcurrido < 0:
                resultados.append(
                    ResultadoInactividad(
                        sensor.sensor_id, "RELOJ_INVALIDO", None
                    )
                )
                continue

            estado = "INACTIVO" if transcurrido > intervalo else "ACTIVO"
            resultados.append(
                ResultadoInactividad(
                    sensor.sensor_id, estado, transcurrido
                )
            )

        return resultados