"""Gestión de sesiones activas."""

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from logistica.repositories.sesion_repository import SesionRepository


class SesionService:
    def __init__(
        self,
        repositorio: SesionRepository,
        ttl_segundos: int,
    ) -> None:
        if type(ttl_segundos) is not int or ttl_segundos <= 0:
            raise ValueError("El TTL debe ser un entero positivo de segundos")

        self._repositorio = repositorio
        self._ttl_segundos = ttl_segundos

    def iniciar(self, usuario_id: UUID) -> UUID:
        """Crea una sesión para un usuario y devuelve su identificador."""
        sesion_id = uuid4()
        inicio = datetime.now(timezone.utc)
        fin = inicio + timedelta(seconds=self._ttl_segundos)

        self._repositorio.guardar(
            sesion_id=sesion_id,
            usuario_id=usuario_id,
            fecha_inicio=inicio.isoformat(),
            fecha_fin=fin.isoformat(),
            ttl_segundos=self._ttl_segundos,
        )
        return sesion_id

    def consultar(self, sesion_id: UUID) -> dict[str, str] | None:
        """Devuelve la sesión activa o None si no existe."""
        return self._repositorio.obtener(sesion_id)

    def cerrar(self, sesion_id: UUID) -> bool:
        """Cierra la sesión. Devuelve True si existía."""
        return self._repositorio.eliminar(sesion_id)
