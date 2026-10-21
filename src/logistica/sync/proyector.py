"""Proyectores: lo que convierte un evento del Outbox en un cambio real en otro motor.

Un proyector tiene que ser IDEMPOTENTE: aplicar el mismo evento dos veces debe
dejar el destino igual que aplicarlo una sola vez.

No es una precaucion opcional. Entre el momento en que el destino confirma la
escritura y el momento en que el worker marca el evento como procesado hay un
instante en el que, si el proceso se cae, el evento se vuelve a entregar. Ese
instante no se puede eliminar sin una transaccion distribuida entre las dos
bases. Entonces la garantia disponible es *entrega al menos una vez*, y la
unica forma de que eso alcance es que el efecto sea el mismo aunque el evento
llegue repetido.
"""
from abc import ABC, abstractmethod

from logistica.domain.evento_outbox import EventoOutbox


class Proyector(ABC):
    """Aplica eventos del Outbox sobre un motor de destino."""

    @property
    @abstractmethod
    def nombre(self) -> str:
        """Para los logs y el reporte de consistencia."""
        ...

    @abstractmethod
    def le_interesa(self, evento: EventoOutbox) -> bool:
        """Si devuelve False, el worker saltea este proyector para este evento.

        Permite que cada motor reciba solo lo suyo sin que el worker tenga que
        conocer los detalles de ninguno.
        """
        ...

    @abstractmethod
    def aplicar(self, evento: EventoOutbox) -> None:
        """Aplica el evento. Debe poder ejecutarse varias veces sin cambiar el
        resultado."""
        ...

    def cerrar(self) -> None:  # noqa: B027 - opcional a proposito
        """Libera los recursos del motor de destino.

        No es abstracto: un proyector que no abre conexiones (por ejemplo
        uno de prueba) no tiene nada que cerrar y no deberia estar obligado
        a escribir un metodo vacio.
        """
