"""Sesion activa de un usuario. Vive en Redis, no en PostgreSQL.

Es el unico dato del sistema que nace con fecha de muerte: Redis la borra sola
cuando vence el TTL. Por eso no es una tabla.
"""
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import ceil
from uuid import UUID

from logistica.exceptions import ValidacionError


class EstadoSesion(Enum):
    ACTIVA = "ACTIVA"
    VENCIDA = "VENCIDA"


@dataclass
class Sesion:
    """Una sesion no guarda la contrasena ni el hash: solo quien es y hasta cuando.

    `estado` es derivable comparando `fecha_fin` con el reloj, pero se guarda
    porque Redis devuelve el hash tal cual y el menu lo muestra sin recalcular.
    """

    id: UUID
    usuario_id: UUID
    fecha_inicio: datetime
    fecha_fin: datetime
    estado: EstadoSesion = EstadoSesion.ACTIVA

    def __post_init__(self) -> None:
        self.validar()

    def validar(self) -> None:
        """Invariantes que se verifican con los campos del objeto, sin tocar
        ninguna base. Que el usuario_id exista se valida en el servicio, porque
        eso requiere consultar PostgreSQL (D3)."""
        # La zona horaria se valida primero: comparar una fecha naive con una
        # con zona tira TypeError, no ValidacionError.
        if self.fecha_inicio.tzinfo is None or self.fecha_fin.tzinfo is None:
            raise ValidacionError("Las fechas de la sesion deben tener zona horaria")
        if self.fecha_fin <= self.fecha_inicio:
            raise ValidacionError(
                "La sesion no puede terminar antes o al mismo tiempo que empieza"
            )

    def esta_activa(self, ahora: datetime) -> bool:
        return self.estado is EstadoSesion.ACTIVA and ahora < self.fecha_fin

    def segundos_restantes(self, ahora: datetime) -> int:
        """Cuanto le queda de vida, redondeando HACIA ARRIBA. Nunca negativo:
        una sesion vencida da 0.

        Se redondea hacia arriba porque este numero es el TTL que se le pasa a
        Redis: truncar mataria la sesion antes de su `fecha_fin`, y a una de un
        segundo le daria TTL 0 apenas el reloj avanza un microsegundo, con lo
        cual `guardar` la rechazaria por vencida.
        """
        return max(0, ceil((self.fecha_fin - ahora).total_seconds()))
