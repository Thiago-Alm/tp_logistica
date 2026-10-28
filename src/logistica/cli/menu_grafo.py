"""Menu de consultas de la red logistica en Neo4j."""

from uuid import UUID

from logistica.cli import consola
from logistica.exceptions import LogisticaError
from logistica.services.consulta_grafo_service import ConsultaGrafoService


def _texto(valor) -> str:
    return "-" if valor is None else str(valor)


def _pedir_id(etiqueta: str) -> UUID | None:
    try:
        return UUID(consola.pedir(etiqueta).strip())
    except ValueError:
        consola.error("ID invalido. Usa un UUID.")
        return None


def construir(servicio: ConsultaGrafoService) -> None:
    def ruta_de_envio() -> None:
        consola.titulo("Ruta completa de un envio")
        envio_id = _pedir_id("ID del envio")
        if envio_id is None:
            return
        try:
            tramos = servicio.ruta_de_envio(envio_id)
        except LogisticaError as error:
            consola.error(str(error))
            return
        if not tramos:
            consola.aviso("El envio no tiene tramos en el grafo.")
            return
        consola.tabla(
            ["ORDEN", "ORIGEN", "DESTINO", "MEDIO", "VEHICULO"],
            [
                [
                    _texto(t.orden),
                    _texto(t.origen),
                    _texto(t.destino),
                    _texto(t.medio_transporte),
                    _texto(t.vehiculo),
                ]
                for t in tramos
            ],
        )

    def red_de_cliente() -> None:
        consola.titulo("Envios y operadores de un cliente")
        cliente_id = _pedir_id("ID del cliente")
        if cliente_id is None:
            return
        try:
            relaciones = servicio.red_de_cliente(cliente_id)
        except LogisticaError as error:
            consola.error(str(error))
            return
        if not relaciones:
            consola.aviso("El cliente no tiene envios en el grafo.")
            return
        consola.tabla(
            ["ENVIO", "ESTADO", "OPERADOR"],
            [
                [_texto(r.envio_id), _texto(r.estado_envio), _texto(r.operador)]
                for r in relaciones
            ],
        )

    def movimientos_de_contenedor() -> None:
        consola.titulo("Tramos recorridos por un contenedor")
        contenedor_id = _pedir_id("ID del contenedor")
        if contenedor_id is None:
            return
        try:
            movimientos = servicio.movimientos_de_contenedor(contenedor_id)
        except LogisticaError as error:
            consola.error(str(error))
            return
        if not movimientos:
            consola.aviso("El contenedor no recorrio tramos en el grafo.")
            return
        consola.tabla(
            ["ENVIO", "ORDEN", "ORIGEN", "DESTINO"],
            [
                [
                    _texto(m.envio_id),
                    _texto(m.orden),
                    _texto(m.origen),
                    _texto(m.destino),
                ]
                for m in movimientos
            ],
        )

    consola.menu(
        "Consultas de la red logistica",
        {
            "1": ("Ruta completa de un envio", ruta_de_envio),
            "2": ("Envios y operadores de un cliente", red_de_cliente),
            "3": ("Tramos recorridos por un contenedor", movimientos_de_contenedor),
        },
    )
