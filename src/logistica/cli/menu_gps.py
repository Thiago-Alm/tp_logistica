"""Menu de consulta del recorrido GPS."""

from datetime import datetime, timedelta, timezone

from logistica.cli import consola
from logistica.exceptions import LogisticaError
from logistica.services.gps_service import GPSService

DIAS_POR_DEFECTO = 7


def construir(servicio: GPSService) -> None:
    def consultar_recorrido() -> None:
        consola.titulo("Recorrido GPS de un contenedor")
        consola.aviso("Se acepta el codigo ISO (MAEU1122334) o el UUID interno.")
        consola.aviso(
            f"Enter en las fechas usa los ultimos {DIAS_POR_DEFECTO} dias. "
            "Formato con zona: 2026-10-28T08:00:00-03:00"
        )

        try:
            contenedor = servicio.buscar_contenedor(consola.pedir("Contenedor"))
        except LogisticaError as error:
            consola.error(str(error))
            return

        # Las fechas por defecto evitan el error mas comun: el intervalo se
        # mide en dias de calendario, asi que "los ultimos 31 dias" abarca 32
        # particiones y el repositorio lo rechaza (D45).
        hasta_por_defecto = datetime.now(timezone.utc)
        desde_por_defecto = hasta_por_defecto - timedelta(days=DIAS_POR_DEFECTO - 1)

        texto_desde = consola.pedir("Desde (Enter para el valor por defecto)").strip()
        texto_hasta = consola.pedir("Hasta (Enter para ahora)").strip()
        try:
            desde = datetime.fromisoformat(texto_desde) if texto_desde else desde_por_defecto
            hasta = datetime.fromisoformat(texto_hasta) if texto_hasta else hasta_por_defecto
        except ValueError:
            consola.error("Fecha invalida. Usa 2026-10-28T08:00:00-03:00, o Enter.")
            return

        consola.aviso(
            f"{contenedor.codigo_iso}: de {desde.astimezone():%d/%m %H:%M} "
            f"a {hasta.astimezone():%d/%m %H:%M}"
        )

        try:
            posiciones = servicio.recorrido(contenedor.id, desde, hasta)
        except LogisticaError as error:
            consola.error(str(error))
            return

        if not posiciones:
            consola.aviso("No hay posiciones registradas en ese intervalo.")
            consola.aviso(
                "Si el contenedor no esta en un envio en transito, no reporta. "
                "Para generar recorridos: python -m logistica.jobs.simulador_iot"
            )
            return

        consola.tabla(
            ["MOMENTO", "LATITUD", "LONGITUD", "SENSOR", "ENVIO"],
            [
                [
                    posicion.momento.isoformat(),
                    f"{posicion.latitud:.6f}",
                    f"{posicion.longitud:.6f}",
                    str(posicion.sensor_id),
                    str(posicion.envio_id) if posicion.envio_id is not None else "-",
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
