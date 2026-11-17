"""Menu de consultas de la red logistica en Neo4j."""

from logistica.cli import consola
from logistica.domain.envio import EstadoEnvio
from logistica.exceptions import LogisticaError
from logistica.services.consulta_grafo_service import ConsultaGrafoService


def _texto(valor) -> str:
    return "-" if valor is None else str(valor)


def construir(servicio: ConsultaGrafoService, envios, clientes, contenedores) -> None:
    """Las tres consultas pedian un UUID a mano. Ahora se elige de una lista
    (D66); los servicios de PostgreSQL estan solo para armarla, porque Neo4j
    guarda los ids pero no es la fuente de verdad de esos datos."""

    def _elegir_envio():
        try:
            nombres = {c.id: c.razon_social for c in clientes.listar()}
            todos = [e for estado in EstadoEnvio for e in envios.listar_por_estado(estado)]
        except LogisticaError as error:
            consola.error(str(error))
            return None
        if not todos:
            consola.aviso("No hay envios cargados.")
            return None
        return consola.elegir_de_tabla(
            todos,
            ["ID", "CLIENTE", "ESTADO", "PRIORIDAD", "CREADO"],
            lambda e: [
                str(e.id)[-12:],
                nombres.get(e.cliente_id, str(e.cliente_id)[-8:])[:24],
                e.estado.value,
                e.prioridad.value,
                f"{e.fecha_creacion.astimezone():%d/%m/%Y}",
            ],
            "Numero de envio",
        )

    def _elegir_cliente():
        try:
            lista = clientes.listar()
        except LogisticaError as error:
            consola.error(str(error))
            return None
        if not lista:
            consola.aviso("No hay clientes cargados.")
            return None
        return consola.elegir_de_tabla(
            lista,
            ["CUIT", "RAZON SOCIAL", "PAIS", "ESTADO"],
            lambda c: [c.cuit, c.razon_social[:30], c.pais, c.estado.value],
            "Numero de cliente",
        )

    def _elegir_contenedor():
        try:
            lista = contenedores.listar()
        except LogisticaError as error:
            consola.error(str(error))
            return None
        if not lista:
            consola.aviso("No hay contenedores cargados.")
            return None
        return consola.elegir_de_tabla(
            lista,
            ["CODIGO ISO", "TIPO", "CAPACIDAD", "ESTADO"],
            lambda c: [c.codigo_iso, c.tipo, f"{c.capacidad:.1f}", c.estado.value],
            "Numero de contenedor",
        )
    def ruta_de_envio() -> None:
        consola.titulo("Ruta completa de un envio")
        envio = _elegir_envio()
        if envio is None:
            return
        envio_id = envio.id
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
        cliente = _elegir_cliente()
        if cliente is None:
            return
        cliente_id = cliente.id
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
        contenedor = _elegir_contenedor()
        if contenedor is None:
            return
        contenedor_id = contenedor.id
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
