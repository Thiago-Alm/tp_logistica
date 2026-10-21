"""Menu de reportes operativos y analiticos del enunciado."""
from logistica.cli import consola
from logistica.exceptions import LogisticaError
from logistica.services.reporte_service import ReporteService


def _duracion(valor) -> str:
    if valor is None:
        return "-"
    dias = valor.days
    horas = valor.seconds // 3600
    return f"{dias}d {horas}h"


def construir(servicio: ReporteService) -> None:
    def por_pais() -> None:
        consola.titulo("Envios por pais de destino")
        filas = servicio.envios_por_pais()
        consola.tabla(["PAIS", "ENVIOS"], [[f.pais, str(f.cantidad)] for f in filas])

    def por_estado() -> None:
        consola.titulo("Envios por estado")
        filas = servicio.envios_por_estado()
        consola.tabla(["ESTADO", "ENVIOS"], [[f.estado.value, str(f.cantidad)] for f in filas])

    def por_cliente() -> None:
        consola.titulo("Envios por cliente")
        filas = servicio.envios_por_cliente()
        consola.tabla(
            ["CLIENTE", "ENVIOS"], [[f.razon_social, str(f.cantidad)] for f in filas]
        )

    def tiempos_por_cliente() -> None:
        consola.titulo("Tiempos maximo y minimo de envio por cliente")
        consola.aviso("Solo cuentan los envios entregados.")
        filas = servicio.tiempos_de_envio_por_cliente()
        consola.tabla(
            ["CLIENTE", "MINIMO", "MAXIMO"],
            [[f.razon_social, _duracion(f.minimo), _duracion(f.maximo)] for f in filas],
        )

    def promedio_entrega() -> None:
        consola.titulo("Tiempo promedio de entrega")
        promedio = servicio.tiempo_promedio_de_entrega()
        if promedio is None:
            consola.aviso("Todavia no hay envios entregados.")
        else:
            consola.aviso(f"Promedio: {_duracion(promedio)}")

    def ranking_volumen() -> None:
        consola.titulo("Ranking de clientes por volumen transportado")
        filas = servicio.ranking_clientes_por_volumen(limite=10)
        consola.tabla(
            ["#", "CLIENTE", "VOLUMEN"],
            [[str(i), f.razon_social, f"{f.volumen:.2f}"] for i, f in enumerate(filas, 1)],
        )

    def costos_transporte() -> None:
        consola.titulo("Costos por tipo de transporte")
        costos = servicio.costos_por_tipo_de_transporte()
        consola.tabla(
            ["MEDIO", "COSTO TOTAL"],
            [[m.value, f"{c:.2f}"] for m, c in costos.items()],
        )

    def seguro(funcion):
        def envoltorio() -> None:
            try:
                funcion()
            except LogisticaError as e:
                consola.error(str(e))

        return envoltorio

    consola.menu(
        "Reportes",
        {
            "1": ("Envios por pais", seguro(por_pais)),
            "2": ("Envios por estado", seguro(por_estado)),
            "3": ("Envios por cliente", seguro(por_cliente)),
            "4": ("Tiempos max/min por cliente", seguro(tiempos_por_cliente)),
            "5": ("Tiempo promedio de entrega", seguro(promedio_entrega)),
            "6": ("Ranking de clientes por volumen", seguro(ranking_volumen)),
            "7": ("Costos por tipo de transporte", seguro(costos_transporte)),
        },
    )
