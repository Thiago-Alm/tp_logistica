"""Menu de usuarios y roles."""
from getpass import getpass
from uuid import UUID

from logistica.cli import consola
from logistica.domain.usuario import Usuario
from logistica.exceptions import LogisticaError
from logistica.services.cliente_service import ClienteService
from logistica.services.sesion_service import SesionService
from logistica.services.usuario_service import UsuarioService


def _fila(usuario: Usuario) -> list[str]:
    return [
        str(usuario.id),
        usuario.nombre_completo,
        usuario.email,
        "interno" if usuario.es_interno() else "de cliente",
        usuario.estado.value,
    ]


def _mostrar(usuarios: list[Usuario]) -> None:
    consola.tabla(
        ["ID", "NOMBRE", "EMAIL", "TIPO", "ESTADO"],
        [_fila(u) for u in usuarios],
    )


def construir(
    servicio: UsuarioService,
    clientes: ClienteService,
    sesiones: SesionService,
) -> None:
    def alta() -> None:
        consola.titulo("Alta de usuario")
        roles = servicio.listar_roles()
        if not roles:
            consola.error("No hay roles cargados. Corre scripts/postgres/02_datos_prueba.sql")
            return
        consola.tabla(
            ["#", "ROL", "NIVEL"],
            [[str(i), r.descripcion, str(r.nivel_permisos)] for i, r in enumerate(roles, 1)],
        )
        eleccion = consola.pedir("Numero de rol")
        if not eleccion.isdigit() or not 1 <= int(eleccion) <= len(roles):
            consola.error("Rol invalido.")
            return
        rol = roles[int(eleccion) - 1]

        cliente_id = None
        if consola.confirmar("El usuario pertenece a un cliente?"):
            texto = consola.pedir("ID del cliente (o un fragmento)")
            encontrado = next(
                (c for c in clientes.listar() if texto.lower() in str(c.id).lower()), None
            )
            if encontrado is None:
                consola.error("No se encontro ese cliente.")
                return
            cliente_id = encontrado.id

        # getpass no muestra lo que se escribe. La contrasena en claro no se
        # guarda ni se registra en el log: el servicio solo persiste su hash.
        password = getpass("  Contrasena (no se muestra): ")
        try:
            usuario = servicio.alta(
                rol_id=rol.id,
                nombre=consola.pedir("Nombre"),
                apellido=consola.pedir("Apellido"),
                email=consola.pedir("Email"),
                password=password,
                cliente_id=cliente_id,
            )
        except LogisticaError as e:
            consola.error(str(e))
            return
        consola.exito(f"Usuario creado con id {usuario.id}")

    def listar() -> None:
        consola.titulo("Usuarios")
        _mostrar(servicio.listar())

    def listar_roles() -> None:
        consola.titulo("Roles")
        consola.tabla(
            ["ROL", "NIVEL DE PERMISOS"],
            [[r.descripcion, str(r.nivel_permisos)] for r in servicio.listar_roles()],
        )

    def autenticar() -> None:
        consola.titulo("Iniciar sesion")
        email = consola.pedir("Email")
        password = getpass("  Contrasena (no se muestra): ")
        try:
            usuario = servicio.autenticar(email, password)
            sesion_id = sesiones.iniciar(usuario.id)
        except LogisticaError as e:
            consola.error(str(e))
            return
        consola.exito(f"Autenticado: {usuario.nombre_completo}")
        consola.aviso(f"Sesion creada: {sesion_id}")

    def cerrar_sesion() -> None:
        consola.titulo("Cerrar sesion")
        texto = consola.pedir("ID de la sesion")

        try:
            sesion_id = UUID(texto)
        except ValueError:
            consola.error("El ID de la sesion no es valido.")
            return

        try:
            cerrada = sesiones.cerrar(sesion_id)
        except LogisticaError as error:
            consola.error(str(error))
            return

        if cerrada:
            consola.exito("Sesion cerrada.")
        else:
            consola.aviso("La sesion no existe o ya vencio.")

    def baja() -> None:
        consola.titulo("Baja de usuario")
        texto = consola.pedir("ID del usuario (o un fragmento)").lower()
        usuario = next((u for u in servicio.listar() if texto in str(u.id).lower()), None)
        if usuario is None:
            consola.error("No se encontro ese usuario.")
            return
        if not consola.confirmar(f"Dar de baja a {usuario.nombre_completo}?"):
            consola.aviso("Cancelado.")
            return
        try:
            servicio.baja(usuario.id)
        except LogisticaError as e:
            consola.error(str(e))
            return
        consola.exito("Usuario dado de baja.")

    consola.menu(
        "Usuarios y roles",
        {
            "1": ("Alta de usuario", alta),
            "2": ("Listar usuarios", listar),
            "3": ("Listar roles", listar_roles),
            "4": ("Iniciar sesion", autenticar),
            "5": ("Baja de usuario", baja),
            "6": ("Cerrar sesion", cerrar_sesion),
        },
    )
