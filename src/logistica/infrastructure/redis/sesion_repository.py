"""Almacenamiento de sesiones activas en Redis."""

from uuid import UUID

from redis import Redis

from logistica.repositories.sesion_repository import SesionRepository


class RedisSesionRepository(SesionRepository):
    """Guarda, consulta y elimina sesiones en Redis."""

    def __init__(self, cliente: Redis) -> None:
        self._cliente = cliente

    def guardar(
        self,
        sesion_id: UUID,
        usuario_id: UUID,
        fecha_inicio: str,
        fecha_fin: str,
        ttl_segundos: int,
    ) -> None:
        """Guarda una sesión y establece su vencimiento en segundos."""
        if ttl_segundos <= 0:
            raise ValueError("El TTL debe ser mayor que cero")

        clave = f"sesion:{sesion_id}"
        datos = {
            "usuario_id": str(usuario_id),
            "fecha_inicio": fecha_inicio,
            "fecha_fin": fecha_fin,
            "estado": "ACTIVA",
        }

        with self._cliente.pipeline(transaction=True) as operacion:
            operacion.hset(clave, mapping=datos)
            operacion.expire(clave, ttl_segundos)
            operacion.execute()

    def obtener(self, sesion_id: UUID) -> dict[str, str] | None:
        """Devuelve los datos de una sesión o None si no existe."""
        datos = self._cliente.hgetall(f"sesion:{sesion_id}")
        if not datos:
            return None

        return {
            clave.decode() if isinstance(clave, bytes) else clave:
            valor.decode() if isinstance(valor, bytes) else valor
            for clave, valor in datos.items()
        }

    def eliminar(self, sesion_id: UUID) -> bool:
        """Cierra una sesión eliminando su clave."""
        return bool(self._cliente.delete(f"sesion:{sesion_id}"))