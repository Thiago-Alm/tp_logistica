"""Interfaz de persistencia de Alerta. La implementa infrastructure/mongo."""
from abc import ABC, abstractmethod
from uuid import UUID

from logistica.domain.alerta import Alerta


class AlertaRepository(ABC):
    @abstractmethod
    def guardar(self, alerta: Alerta) -> bool:
        """Persiste la alerta si todavia no existe.

        Devuelve True si la creo y False si ya existia. Es idempotente: como el id
        es deterministico (Alerta.generar_id), reintentar la misma deteccion no
        duplica la alerta ni lanza error (D33).
        """
        ...

    @abstractmethod
    def actualizar(self, alerta: Alerta) -> None:
        """Persiste una alerta ya modificada, por ejemplo al reconocerla o
        cerrarla. Hace falta aparte de `guardar` porque `guardar` es un
        insert-if-not-exists: si la alerta existe, no la toca.

        Lanza NoEncontrado si no existe.
        """
        ...

    @abstractmethod
    def obtener(self, id: UUID) -> Alerta | None: ...

    @abstractmethod
    def listar_abiertas(self) -> list[Alerta]:
        """ABIERTA y RECONOCIDA, la mas reciente primero."""
        ...

    @abstractmethod
    def listar_por_sensor(self, sensor_id: UUID, limite: int = 50) -> list[Alerta]:
        """Las ultimas alertas de un sensor, la mas reciente primero."""
        ...
