"""Menu de envios: registro, seguimiento de trayectos y cambios de estado."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from logistica.cli import consola
from logistica.domain.envio import Envio, EstadoEnvio, PrioridadEnvio
from logistica.domain.tramo import MedioTransporte
from logistica.exceptions import LogisticaError
from logistica.services.cliente_service import ClienteService
from logistica.services.envio_service import EnvioService


def _fila(envio: Envio) -> list[str]:
    return [
        str(envio.id),
        envio.estado.value,
        envio.prioridad.value,
        envio.fecha_creacion.strftime("%Y-%m-%d"),
        envio.fecha_llegada_real.strftime("%Y-%m-%d") if envio.fecha_llegada_real else "-",
    ]


def _mostrar(envios: list[Envio]) -> None:
    consola.tabla(
        ["ID", "ESTADO", "PRIORIDAD", "CREADO", "ENTREGADO"],
        [_fila(e) for e in envios],
    )


def _elegir(opciones: list, etiqueta, titulo: str):
    """Muestra una lista numerada y devuelve el elegido, o None."""
    consola.tabla(
        ["#", titulo],
        [[str(i), etiqueta(o)] for i, o in enumerate(opciones, 1)],
    )
    texto = consola.pedir(f"Numero de {titulo.lower()}")
    if not texto.isdigit() or not 1 <= int(texto) <= len(opciones):
        consola.error("Opcion invalida.")
        return None
    return opciones[int(texto) - 1]


def _buscar_envio(servicio: EnvioService, clientes: ClienteService) -> Envio | None:
    texto = consola.pedir("ID del envio (o un fragmento)").lower()
    todos = [e for c in clientes.listar() for e in servicio.listar_por_cliente(c.id)]
    coincidencias = [e for e in todos if texto in str(e.id).lower()]
    if not coincidencias:
        consola.error("No se encontro ningun envio con ese id.")
        return None
    if len(coincidencias) > 1:
        consola.error(f"Hay {len(coincidencias)} envios que coinciden. Se mas especifico.")
        return None
    return coincidencias[0]


def construir(servicio: EnvioService, clientes: ClienteService) -> None:
    def registrar() -> None:
        consola.titulo("Registrar envio")
        activos = clientes.listar(solo_activos=True)
        if not activos:
            consola.error("No hay clientes activos.")
            return
        cliente = _elegir(activos, lambda c: f"{c.razon_social} ({c.cuit})", "Cliente")
        if cliente is None:
            return
        consola.aviso("Los ids de origen y destino salen de la tabla ubicacion.")
        origen = consola.pedir("ID de la ubicacion de origen")
        destino = consola.pedir("ID de la ubicacion de destino")
        prioridad = _elegir(list(PrioridadEnvio), lambda p: p.value, "Prioridad")
        if prioridad is None:
            return
        try:
            from uuid import UUID

            envio = servicio.registrar(cliente.id, UUID(origen), UUID(destino), prioridad)
        except (LogisticaError, ValueError) as e:
            consola.error(str(e))
            return
        consola.exito(f"Envio registrado con id {envio.id}")

    def listar_por_cliente() -> None:
        consola.titulo("Envios de un cliente")
        cliente = _elegir(clientes.listar(), lambda c: c.razon_social, "Cliente")
        if cliente is not None:
            _mostrar(servicio.listar_por_cliente(cliente.id))

    def listar_por_estado() -> None:
        consola.titulo("Envios por estado")
        estado = _elegir(list(EstadoEnvio), lambda e: e.value, "Estado")
        if estado is not None:
            _mostrar(servicio.listar_por_estado(estado))

    def listar_demorados() -> None:
        consola.titulo("Envios demorados")
        consola.aviso("Demorado = no entregado y la ultima llegada estimada ya paso.")
        _mostrar(servicio.listar_demorados())

    def ver_trayecto() -> None:
        consola.titulo("Seguimiento de trayecto")
        envio = _buscar_envio(servicio, clientes)
        if envio is None:
            return
        detalle = servicio.obtener_con_tramos(envio.id)
        consola.aviso(f"Estado: {detalle.envio.estado.value}")
        def fila_tramo(t) -> list[str]:
            real = t.fecha_llegada_real
            return [
                str(t.orden),
                t.medio_transporte.value,
                t.fecha_salida.strftime("%Y-%m-%d %H:%M"),
                t.fecha_llegada_estimada.strftime("%Y-%m-%d %H:%M"),
                real.strftime("%Y-%m-%d %H:%M") if real else "-",
                f"{t.costo:.2f}",
            ]

        consola.tabla(
            ["#", "MEDIO", "SALIDA", "LLEGADA EST.", "LLEGADA REAL", "COSTO"],
            [fila_tramo(t) for t in detalle.tramos],
        )
        if detalle.tramos:
            consola.aviso(f"Costo total: {detalle.costo_total:.2f}")
            if detalle.esta_demorado(datetime.now(timezone.utc)):
                consola.aviso("Este envio esta DEMORADO.")

    def agregar_tramo() -> None:
        consola.titulo("Agregar tramo")
        envio = _buscar_envio(servicio, clientes)
        if envio is None:
            return
        medio = _elegir(list(MedioTransporte), lambda m: m.value, "Medio de transporte")
        if medio is None:
            return
        try:
            from uuid import UUID

            origen = UUID(consola.pedir("ID de la ubicacion de origen"))
            destino = UUID(consola.pedir("ID de la ubicacion de destino"))
            vehiculo = UUID(consola.pedir("ID del vehiculo"))
            dias = int(consola.pedir("Dias estimados de viaje"))
            costo = Decimal(consola.pedir("Costo"))
        except (ValueError, InvalidOperation) as e:
            consola.error(f"Dato invalido: {e}")
            return
        salida = datetime.now(timezone.utc)
        try:
            tramo = servicio.agregar_tramo(
                envio_id=envio.id,
                vehiculo_id=vehiculo,
                medio_transporte=medio,
                origen_id=origen,
                destino_id=destino,
                fecha_salida=salida,
                fecha_llegada_estimada=salida + timedelta(days=dias),
                costo=costo,
            )
        except LogisticaError as e:
            consola.error(str(e))
            return
        consola.exito(f"Tramo {tramo.orden} agregado.")

    def cambiar_estado() -> None:
        consola.titulo("Cambiar estado de un envio")
        envio = _buscar_envio(servicio, clientes)
        if envio is None:
            return
        posibles = sorted(envio.estado.transiciones_posibles(), key=lambda e: e.value)
        if not posibles:
            consola.error(f"{envio.estado.value} es un estado final: no admite cambios.")
            return
        consola.aviso(f"Estado actual: {envio.estado.value}")
        nuevo = _elegir(posibles, lambda e: e.value, "Estado nuevo")
        if nuevo is None:
            return
        try:
            if nuevo is EstadoEnvio.ENTREGADO:
                servicio.entregar(envio.id)
            else:
                servicio.cambiar_estado(envio.id, nuevo)
        except LogisticaError as e:
            consola.error(str(e))
            return
        consola.exito(f"Envio en estado {nuevo.value}.")

    def asignar_contenedor() -> None:
        consola.titulo("Asignar contenedor")
        envio = _buscar_envio(servicio, clientes)
        if envio is None:
            return
        try:
            from uuid import UUID

            contenedor_id = UUID(consola.pedir("ID del contenedor"))
            asignado = servicio.asignar_contenedor(envio.id, contenedor_id)
        except (LogisticaError, ValueError) as e:
            consola.error(str(e))
            return
        consola.exito(f"Contenedor {asignado.codigo_iso} asignado.")

    consola.menu(
        "Envios",
        {
            "1": ("Registrar envio", registrar),
            "2": ("Ver trayecto completo", ver_trayecto),
            "3": ("Agregar tramo", agregar_tramo),
            "4": ("Cambiar estado", cambiar_estado),
            "5": ("Asignar contenedor", asignar_contenedor),
            "6": ("Listar por cliente", listar_por_cliente),
            "7": ("Listar por estado", listar_por_estado),
            "8": ("Listar demorados", listar_demorados),
        },
    )
