"""Gestión de sesiones activas."""

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from logistica.domain.sesion import Sesion
from logistica.exceptions import ValidacionError
from logistica.repositories.sesion_repository import SesionRepository


class SesionService:
    def __init__(self, repositorio: SesionRepository, ttl_segundos: int) -> None:
        if not isinstance(ttl_segundos, int) or isinstance(ttl_segundos, bool):
            raise ValidacionError("El TTL debe ser un entero de segundos")
        if ttl_segundos <= 0:
            raise ValidacionError("El TTL debe ser positivo")

        self._repositorio = repositorio
        self._ttl_segundos = ttl_segundos

    def iniciar(self, usuario_id: UUID) -> Sesion:
        """Abre una sesion para un usuario y la devuelve.

        No verifica que el usuario exista: lo llama `app.py` justo despues de
        `UsuarioService.autenticar()`, que ya lo trajo de PostgreSQL."""
        inicio = datetime.now(timezone.utc)
        sesion = Sesion(
            id=uuid4(),
            usuario_id=usuario_id,
            fecha_inicio=inicio,
            fecha_fin=inicio + timedelta(seconds=self._ttl_segundos),
        )
        self._repositorio.guardar(sesion)
        return sesion

    def consultar(self, sesion_id: UUID) -> Sesion | None:
        """Devuelve la sesion vigente o None si no existe o ya vencio."""
        sesion = self._repositorio.obtener(sesion_id)
        if sesion is None or not sesion.esta_activa(datetime.now(timezone.utc)):
            return None
        return sesion

    def listar_activas(self) -> list[Sesion]:
        """Las sesiones abiertas en este momento. Filtra las vencidas que Redis
        todavia no barrio."""
        ahora = datetime.now(timezone.utc)
        return [s for s in self._repositorio.listar_activas() if s.esta_activa(ahora)]

    def cerrar(self, sesion_id: UUID) -> bool:
        """Cierra la sesion. Devuelve True si existia."""
        return self._repositorio.eliminar(sesion_id)
