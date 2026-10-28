"""Menu de consulta del recorrido GPS."""

from datetime import datetime
from uuid import UUID

from logistica.cli import consola
from logistica.exceptions import LogisticaError
from logistica.services.gps_service import GPSService


def construir(servicio: GPSService) -> None:
    def consultar_recorrido() -> None:
        consola.titulo("Recorrido GPS de un contenedor")
        consola.aviso("Intervalo maximo: 31 dias.")
        consola.aviso(
            "Fechas con zona horaria. Ejemplo: 2026-10-28T08:00:00-03:00"
        )

        try:
            contenedor_id = UUID(
                consola.pedir("ID del contenedor").strip()
            )
            desde = datetime.fromisoformat(
                consola.pedir("Desde (fecha y hora con zona)").strip()
            )
            hasta = datetime.fromisoformat(
                consola.pedir("Hasta (fecha y hora con zona)").strip()
            )
        except ValueError:
            consola.error(
                "ID o fecha invalida. Usa un UUID y fechas como "
                "2026-10-28T08:00:00-03:00."
            )
            return

        try:
            posiciones = servicio.recorrido(contenedor_id, desde, hasta)
        except LogisticaError as error:
            consola.error(str(error))
            return

        if not posiciones:
            consola.aviso("No hay posiciones registradas en ese intervalo.")
            return

        consola.tabla(
            ["MOMENTO", "LATITUD", "LONGITUD", "SENSOR", "ENVIO"],
            [
                [
                    posicion.momento.isoformat(),
                    f"{posicion.latitud:.6f}",
                    f"{posicion.longitud:.6f}",
                    str(posicion.sensor_id),
                    str(posicion.envio_id)
                    if posicion.envio_id is not None
                    else "-",
                ]
                for posicion in posiciones
            ],
        )

    consola.menu(
        "Seguimiento GPS",
        {
            "1": ("Consultar recorrido de un contenedor", consultar_recorrido),
        },
    )