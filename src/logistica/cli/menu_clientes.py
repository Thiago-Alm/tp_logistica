"""Menu de clientes: alta, baja, modificacion y consulta."""
from logistica.cli import consola
from logistica.domain.cliente import Cliente
from logistica.exceptions import LogisticaError
from logistica.services.cliente_service import ClienteService


def _fila(cliente: Cliente) -> list[str]:
    return [
        str(cliente.id),
        cliente.cuit,
        cliente.razon_social,
        cliente.pais,
        cliente.estado.value,
    ]


def _mostrar(clientes: list[Cliente]) -> None:
    consola.tabla(
        ["ID", "CUIT", "RAZON SOCIAL", "PAIS", "ESTADO"],
        [_fila(c) for c in clientes],
    )


def _pedir_id(servicio: ClienteService) -> Cliente | None:
    """Acepta el id completo o cualquier fragmento suyo.

    No alcanza con comparar el principio: los ids de los datos semilla
    comparten el prefijo (20000000-0000-...) y se diferencian al final.
    """
    texto = consola.pedir("ID del cliente (o un fragmento)").lower()
    coincidencias = [c for c in servicio.listar() if texto in str(c.id).lower()]
    if not coincidencias:
        consola.error("No se encontro ningun cliente con ese id.")
        return None
    if len(coincidencias) > 1:
        consola.error(f"Hay {len(coincidencias)} clientes que coinciden. Se mas especifico.")
        return None
    return coincidencias[0]


def construir(servicio: ClienteService) -> None:
    def alta() -> None:
        consola.titulo("Alta de cliente")
        try:
            cliente = servicio.alta(
                cuit=consola.pedir("CUIT"),
                razon_social=consola.pedir("Razon social"),
                email=consola.pedir("Email"),
                pais=consola.pedir("Pais"),
                telefono=consola.pedir_opcional("Telefono"),
                direccion=consola.pedir_opcional("Direccion"),
            )
        except LogisticaError as e:
            consola.error(str(e))
            return
        consola.exito(f"Cliente creado con id {cliente.id}")

    def listar() -> None:
        consola.titulo("Clientes")
        _mostrar(servicio.listar())

    def listar_activos() -> None:
        consola.titulo("Clientes activos")
        _mostrar(servicio.listar(solo_activos=True))

    def buscar() -> None:
        consola.titulo("Buscar por CUIT")
        try:
            _mostrar([servicio.buscar_por_cuit(consola.pedir("CUIT"))])
        except LogisticaError as e:
            consola.error(str(e))

    def modificar() -> None:
        consola.titulo("Modificar cliente")
        cliente = _pedir_id(servicio)
        if cliente is None:
            return
        consola.aviso(f"Editando: {cliente.razon_social}. Enter deja el valor actual.")
        try:
            actualizado = servicio.modificar(
                cliente.id,
                razon_social=consola.pedir_opcional(f"Razon social [{cliente.razon_social}]"),
                email=consola.pedir_opcional(f"Email [{cliente.email}]"),
                telefono=consola.pedir_opcional(f"Telefono [{cliente.telefono or '-'}]"),
                direccion=consola.pedir_opcional(f"Direccion [{cliente.direccion or '-'}]"),
                pais=consola.pedir_opcional(f"Pais [{cliente.pais}]"),
            )
        except LogisticaError as e:
            consola.error(str(e))
            return
        consola.exito(f"Cliente actualizado: {actualizado.razon_social}")

    def baja() -> None:
        consola.titulo("Baja de cliente")
        cliente = _pedir_id(servicio)
        if cliente is None:
            return
        consola.aviso("La baja es logica: el cliente queda INACTIVO y conserva su historial.")
        if not consola.confirmar(f"Dar de baja a {cliente.razon_social}?"):
            consola.aviso("Cancelado.")
            return
        try:
            servicio.baja(cliente.id)
        except LogisticaError as e:
            consola.error(str(e))
            return
        consola.exito("Cliente dado de baja.")

    def reactivar() -> None:
        consola.titulo("Reactivar cliente")
        cliente = _pedir_id(servicio)
        if cliente is None:
            return
        try:
            servicio.reactivar(cliente.id)
        except LogisticaError as e:
            consola.error(str(e))
            return
        consola.exito("Cliente reactivado.")

    consola.menu(
        "Clientes",
        {
            "1": ("Alta", alta),
            "2": ("Listar todos", listar),
            "3": ("Listar solo activos", listar_activos),
            "4": ("Buscar por CUIT", buscar),
            "5": ("Modificar", modificar),
            "6": ("Baja (logica)", baja),
            "7": ("Reactivar", reactivar),
        },
    )
