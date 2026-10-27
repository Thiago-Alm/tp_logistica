"""Deteccion de anomalias: compara cada lectura con los umbrales configurados."""
import logging
from collections.abc import Callable
from typing import Any
from uuid import UUID

from logistica.domain.alerta import Alerta, TipoAlerta
from logistica.domain.lectura import Lectura
from logistica.domain.umbral import MagnitudUmbral
from logistica.repositories.alerta_repository import AlertaRepository
from logistica.repositories.umbral_repository import UmbralRepository

log = logging.getLogger(__name__)

# (magnitud del umbral, tipo de alerta, como se lee ese valor en la lectura).
# El enunciado pide solo la temperatura: sumar humedad o vibracion es agregar una fila.
_MEDICIONES = (
    (MagnitudUmbral.TEMPERATURA, TipoAlerta.TEMPERATURA, lambda lectura: lectura.temperatura),
)


class DeteccionAnomaliasService:
    """Evalua lecturas y, si violan un umbral, crea la alerta en MongoDB.

    No consulta PostgreSQL: recibe una funcion que dice de que tipo es cada
    contenedor. El simulador la arma con su lista de sensores; un pipeline real la
    armaria con el repositorio de contenedores (D33). Las alertas y los umbrales
    estan en MongoDB y no comparten transaccion con PostgreSQL, por eso este
    servicio no usa la UnidadDeTrabajo.
    """

    def __init__(
        self,
        umbrales: UmbralRepository,
        alertas: AlertaRepository,
        tipo_de_contenedor: Callable[[UUID], str | None],
    ) -> None:
        self._umbrales = umbrales
        self._alertas = alertas
        self._tipo_de_contenedor = tipo_de_contenedor
        # Para avisar UNA vez por problema de configuracion y no en cada lectura.
        self._avisados: set[Any] = set()

    def evaluar(self, lectura: Lectura) -> list[Alerta]:
        """Las alertas que esta lectura genero (vacio si no violo nada).

        Una lectura que ya habia generado su alerta (reintento) devuelve vacio:
        la alerta existe y no se duplica.
        """
        tipo = self._tipo_de_contenedor(lectura.contenedor_id)
        if tipo is None:
            self._avisar_una_vez(
                ("contenedor", lectura.contenedor_id),
                "No se conoce el tipo del contenedor %s: no se evaluan sus lecturas",
                lectura.contenedor_id,
            )
            return []

        creadas: list[Alerta] = []
        for magnitud, tipo_alerta, leer in _MEDICIONES:
            umbral = self._umbrales.obtener(tipo, magnitud)
            if umbral is None:
                self._avisar_una_vez(
                    ("umbral", tipo, magnitud),
                    "No hay umbral de %s configurado para %s: no se evalua esa medicion",
                    magnitud.value,
                    tipo,
                )
                continue
            alerta = Alerta.por_umbral(lectura, tipo_alerta, leer(lectura), umbral)
            if alerta is None:
                continue
            if self._alertas.guardar(alerta):
                log.warning(
                    "Alerta %s %s en el sensor %s: %.2f fuera del rango [%.2f, %.2f]",
                    alerta.severidad.value,
                    tipo_alerta.value,
                    lectura.sensor_id,
                    leer(lectura),
                    umbral.minimo,
                    umbral.maximo,
                )
                creadas.append(alerta)
        return creadas

    def _avisar_una_vez(self, clave: Any, mensaje: str, *args: Any) -> None:
        if clave not in self._avisados:
            self._avisados.add(clave)
            log.warning(mensaje, *args)
