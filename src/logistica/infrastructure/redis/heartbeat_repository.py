"""Registro de la última señal recibida de cada sensor en Redis."""

from uuid import UUID

from redis import Redis
from redis.exceptions import RedisError

from logistica.exceptions import ErrorDePersistencia
from logistica.repositories.heartbeat_repository import HeartbeatRepository

CLAVE_HEARTBEAT = "sensores:heartbeat"


class RedisHeartbeatRepository(HeartbeatRepository):
    def __init__(self, cliente: Redis) -> None:
        self._cliente = cliente

    def registrar(self, sensor_id: UUID, timestamp: float) -> None:
        """Registra la señal sin reemplazar una más reciente por una anterior."""
        try:
            self._cliente.zadd(
                CLAVE_HEARTBEAT,
                {str(sensor_id): timestamp},
                gt=True,
            )
        except RedisError as error:
            raise ErrorDePersistencia(
                "No se pudo registrar la señal del sensor en Redis"
            ) from error

    def ultimo_reporte(self, sensor_id: UUID) -> float | None:
        """Devuelve el timestamp de la última señal, si existe."""
        try:
            return self._cliente.zscore(CLAVE_HEARTBEAT, str(sensor_id))
        except RedisError as error:
            raise ErrorDePersistencia(
                "No se pudo consultar la señal del sensor en Redis"
            ) from error