"""Saga: atomicidad entre motores, que es lo mas parecido a una transaccion
poliglota que se puede tener.

**Una transaccion no cruza motores.** PostgreSQL no sabe que hace MongoDB, y
ninguno de los dos puede deshacer lo del otro. Pedirle un `ROLLBACK` a los dos
a la vez no es algo que exista.

Lo que si existe es esto: ejecutar los pasos en orden y, si uno falla, deshacer
los anteriores con una operacion **inversa** definida por quien conoce el
negocio. No se deshace borrando: se deshace con un acto nuevo que cancela el
efecto del anterior, igual que una anulacion cancela una factura sin borrar su
asiento.

La diferencia con una transaccion real, y hay que saber decirla:

| | Transaccion (un motor) | Saga (varios motores) |
| --- | --- | --- |
| Atomicidad | el motor la garantiza | la arma la aplicacion |
| Estado intermedio | nadie lo ve | **se ve** mientras corre |
| Deshacer | `ROLLBACK`, no deja rastro | un acto inverso, **queda en el historial** |
| Si falla la vuelta atras | imposible | **posible**: hay que reportarlo |

La ultima fila es la importante. Una compensacion tambien puede fallar -el
motor puede estar caido-, y entonces el sistema queda inconsistente igual. Por
eso `SagaFallida` dice **las dos cosas**: que fallo y si se pudo volver atras.
Callar la segunda seria mentir sobre el estado del sistema.
"""
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from logistica.exceptions import LogisticaError

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Paso:
    """Un paso de la saga, con su forma de deshacerlo.

    `deshacer` recibe lo que devolvio `hacer`: para anular una factura hay que
    saber cual se emitio, y eso solo se sabe despues de emitirla.

    Un paso sin `deshacer` es un paso que no se puede volver atras. Es valido
    -el ultimo no necesita compensacion, porque si falla no hay nada posterior
    que deshacer- pero hay que ponerlo a proposito.
    """

    nombre: str
    motor: str
    hacer: Callable[[], Any]
    deshacer: Callable[[Any], None] | None = None


@dataclass
class SagaFallida(LogisticaError):
    """Un paso fallo. Dice si el sistema quedo consistente o no."""

    paso: str
    causa: Exception
    sin_compensar: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        base = f"La operacion fallo en '{self.paso}': {self.causa}"
        if not self.sin_compensar:
            return f"{base}. Se deshizo todo lo anterior: no quedo nada a medias."
        pendientes = ", ".join(self.sin_compensar)
        return (
            f"{base}. ADEMAS no se pudo deshacer: {pendientes}. "
            "El sistema quedo inconsistente y hay que revisarlo a mano."
        )

    @property
    def quedo_consistente(self) -> bool:
        return not self.sin_compensar


def ejecutar(pasos: list[Paso]) -> list[Any]:
    """Corre los pasos en orden. Si uno falla, deshace los anteriores al reves.

    Al reves y no en orden: el ultimo que se hizo es el primero que se deshace,
    porque puede depender de los anteriores.

    Devuelve lo que devolvio cada paso. Si algo falla, lanza `SagaFallida`.
    """
    hechos: list[tuple[Paso, Any]] = []

    for paso in pasos:
        try:
            hechos.append((paso, paso.hacer()))
            log.debug("Saga: '%s' ok (%s)", paso.nombre, paso.motor)
        except Exception as error:  # noqa: BLE001 - se relanza dentro de SagaFallida
            log.warning("Saga: fallo '%s' (%s): %s", paso.nombre, paso.motor, error)
            sin_compensar = _deshacer(hechos)
            raise SagaFallida(paso.nombre, error, sin_compensar) from error

    return [resultado for _, resultado in hechos]


def _deshacer(hechos: list[tuple[Paso, Any]]) -> list[str]:
    """Compensa en orden inverso. Devuelve los pasos que no se pudieron deshacer.

    Una compensacion que falla no corta la vuelta atras: se sigue con las
    demas, porque deshacer tres de cuatro deja el sistema mas cerca de donde
    estaba que deshacer cero.
    """
    sin_compensar: list[str] = []
    for paso, resultado in reversed(hechos):
        if paso.deshacer is None:
            sin_compensar.append(f"{paso.nombre} (no tiene compensacion)")
            continue
        try:
            paso.deshacer(resultado)
            log.info("Saga: se deshizo '%s' (%s)", paso.nombre, paso.motor)
        except Exception as error:  # noqa: BLE001 - se reporta, no se relanza
            # No se relanza: taparia el error original, que es el que explica
            # por que estamos deshaciendo.
            sin_compensar.append(f"{paso.nombre} ({error})")
            log.error(
                "Saga: NO se pudo deshacer '%s' (%s): %s", paso.nombre, paso.motor, error
            )
    return sin_compensar
