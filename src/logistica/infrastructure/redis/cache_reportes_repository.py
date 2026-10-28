"""Cache de reportes en Redis con vencimiento automatico."""

from redis import Redis
from redis.exceptions import RedisError

from logistica.exceptions import ErrorDePersistencia, ValidacionError
from logistica.repositories.cache_reportes_repository import (
    CacheReportesRepository,
)


class RedisCacheReportesRepository(CacheReportesRepository):
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    def obtener(self, clave: str) -> str | None:
        try:
            contenido = self._redis.get(clave)
            if isinstance(contenido, bytes):
                return contenido.decode("utf-8")
            return contenido
        except (RedisError, UnicodeDecodeError) as error:
            raise ErrorDePersistencia(
                "No se pudo leer la cache de reportes"
            ) from error

    def guardar(self, clave: str, contenido: str, ttl_segundos: int) -> None:
        if (
            isinstance(ttl_segundos, bool)
            or not isinstance(ttl_segundos, int)
            or ttl_segundos <= 0
        ):
            raise ValidacionError(
                "El vencimiento debe ser un numero entero positivo de segundos"
            )

        try:
            self._redis.set(clave, contenido, ex=ttl_segundos)
        except RedisError as error:
            raise ErrorDePersistencia(
                "No se pudo guardar la cache de reportes"
            ) from error