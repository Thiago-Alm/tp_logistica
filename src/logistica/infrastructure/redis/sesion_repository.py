"""Almacenamiento de sesiones activas en Redis.

Por que Redis y no una tabla: la sesion tiene que desaparecer sola cuando
vence. En PostgreSQL haria falta un proceso que barra las vencidas; aca el TTL
del motor lo hace sin que nadie lo corra.
"""

from datetime import datetime, timezone
from uuid import UUID

from redis import Redis
from redis.exceptions import RedisError

from logistica.domain.sesion import EstadoSesion, Sesion
from logistica.exceptions import ErrorDePersistencia, ValidacionError
from logistica.repositories.sesion_repository import SesionRepository

PREFIJO = "sesion:"


def _texto(valor: bytes | str) -> str:
    """El cliente Redis del contenedor no usa decode_responses, asi que las
    respuestas llegan en bytes."""
    return valor.decode() if isinstance(valor, bytes) else valor


class RedisSesionRepository(SesionRepository):
    """Guarda cada sesion como un Hash con vencimiento. La clave es
    `sesion:<uuid>`, para poder recorrerlas con SCAN sin tocar el resto del
    espacio de claves (locks, cache de reportes, heartbeat)."""

    def __init__(self, cliente: Redis) -> None:
        self._cliente = cliente

    def _clave(self, sesion_id: UUID) -> str:
        return f"{PREFIJO}{sesion_id}"

    def guardar(self, sesion: Sesion) -> None:
        """Guarda la sesion y deja que Redis la borre al vencer.

        El TTL sale de la propia sesion: `fecha_fin` es la unica fuente de
        verdad sobre cuando muere."""
        ttl_segundos = sesion.segundos_restantes(datetime.now(timezone.utc))
        if ttl_segundos <= 0:
            raise ValidacionError("La sesion ya vencio: no se guarda")

        datos = {
            "usuario_id": str(sesion.usuario_id),
            "fecha_inicio": sesion.fecha_inicio.isoformat(),
            "fecha_fin": sesion.fecha_fin.isoformat(),
            "estado": sesion.estado.value,
        }

        try:
            # El hset y el expire van juntos: si el expire se perdiera, la
            # sesion quedaria viva para siempre.
            with self._cliente.pipeline(transaction=True) as operacion:
                operacion.hset(self._clave(sesion.id), mapping=datos)
                operacion.expire(self._clave(sesion.id), ttl_segundos)
                operacion.execute()
        except RedisError as error:
            raise ErrorDePersistencia("No se pudo guardar la sesion en Redis") from error

    def obtener(self, sesion_id: UUID) -> Sesion | None:
        try:
            datos = self._cliente.hgetall(self._clave(sesion_id))
        except RedisError as error:
            raise ErrorDePersistencia("No se pudo leer la sesion de Redis") from error
        if not datos:
            return None
        return self._reconstruir(sesion_id, datos)

    def listar_activas(self) -> list[Sesion]:
        """Recorre las sesiones con SCAN, no con KEYS: KEYS bloquea el motor
        mientras recorre todo el espacio de claves."""
        try:
            claves = list(self._cliente.scan_iter(match=f"{PREFIJO}*", count=100))
            with self._cliente.pipeline(transaction=False) as operacion:
                for clave in claves:
                    operacion.hgetall(clave)
                respuestas = operacion.execute()
        except RedisError as error:
            raise ErrorDePersistencia("No se pudieron listar las sesiones") from error

        sesiones = []
        for clave, datos in zip(claves, respuestas, strict=True):
            # Una clave puede vencer entre el SCAN y el HGETALL: ahi viene vacia.
            if not datos:
                continue
            sesion_id = UUID(_texto(clave).removeprefix(PREFIJO))
            sesiones.append(self._reconstruir(sesion_id, datos))
        return sorted(sesiones, key=lambda s: s.fecha_inicio)

    def eliminar(self, sesion_id: UUID) -> bool:
        try:
            return bool(self._cliente.delete(self._clave(sesion_id)))
        except RedisError as error:
            raise ErrorDePersistencia("No se pudo cerrar la sesion en Redis") from error

    def _reconstruir(self, sesion_id: UUID, datos: dict) -> Sesion:
        try:
            plano = {_texto(c): _texto(v) for c, v in datos.items()}
            return Sesion(
                id=sesion_id,
                usuario_id=UUID(plano["usuario_id"]),
                fecha_inicio=datetime.fromisoformat(plano["fecha_inicio"]),
                fecha_fin=datetime.fromisoformat(plano["fecha_fin"]),
                estado=EstadoSesion(plano["estado"]),
            )
        except (KeyError, ValueError, UnicodeDecodeError) as error:
            raise ErrorDePersistencia(
                f"La sesion {sesion_id} esta guardada con un formato invalido"
            ) from error
