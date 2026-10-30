"""Menu de usuarios, roles y sesiones activas."""
from datetime import datetime, timezone
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

    def listar_sesiones() -> None:
        """Las sesiones abiertas ahora mismo, leidas de Redis.

        No hay una opcion "iniciar sesion": la sesion la abre app.py al entrar,
        que es la unica puerta de la aplicacion."""
        consola.titulo("Sesiones activas")
        try:
            activas = sesiones.listar_activas()
        except LogisticaError as error:
            consola.error(str(error))
            return
        if not activas:
            consola.aviso("No hay sesiones activas.")
            return

        ahora = datetime.now(timezone.utc)
        nombres = {u.id: u.nombre_completo for u in servicio.listar()}
        consola.tabla(
            ["SESION", "USUARIO", "DESDE", "VENCE EN"],
            [
                [
                    str(s.id),
                    nombres.get(s.usuario_id, str(s.usuario_id)),
                    f"{s.fecha_inicio.astimezone():%d/%m %H:%M}",
                    f"{s.segundos_restantes(ahora) // 60} min",
                ]
                for s in activas
            ],
        )

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

    def _buscar_usuario(etiqueta: str = "ID del usuario (o un fragmento)"):
        texto = consola.pedir(etiqueta).strip().lower()
        if not texto:
            consola.error("Hace falta un ID o un email.")
            return None
        usuarios = servicio.listar()
        encontrado = next(
            (u for u in usuarios if texto in str(u.id).lower() or texto == u.email.lower()),
            None,
        )
        if encontrado is None:
            consola.error("No se encontro ese usuario.")
        return encontrado

    def modificar() -> None:
        consola.titulo("Modificar usuario")
        consola.aviso(
            "La contrasena no se cambia aca: tiene su propia operacion, porque "
            "exige largo minimo y hasheo."
        )
        usuario = _buscar_usuario("ID o email del usuario")
        if usuario is None:
            return
        consola.aviso(f"{usuario.nombre_completo} <{usuario.email}>. Enter deja igual.")
        nombre = consola.pedir(f"Nombre [{usuario.nombre}]").strip() or None
        apellido = consola.pedir(f"Apellido [{usuario.apellido}]").strip() or None
        email = consola.pedir(f"Email [{usuario.email}]").strip() or None

        rol_id = None
        roles = servicio.listar_roles()
        consola.tabla(
            ["#", "ROL", "NIVEL"],
            [[str(i), r.descripcion, str(r.nivel_permisos)] for i, r in enumerate(roles, 1)],
        )
        eleccion = consola.pedir("Numero del rol nuevo (Enter deja el actual)").strip()
        if eleccion:
            if not eleccion.isdigit() or not 1 <= int(eleccion) <= len(roles):
                consola.error("Rol invalido.")
                return
            rol_id = roles[int(eleccion) - 1].id

        try:
            actualizado = servicio.modificar(
                usuario.id, nombre=nombre, apellido=apellido, email=email, rol_id=rol_id
            )
        except LogisticaError as error:
            consola.error(str(error))
            return
        consola.exito(f"{actualizado.nombre_completo} <{actualizado.email}> actualizado.")

    def reactivar() -> None:
        consola.titulo("Reactivar usuario")
        usuario = _buscar_usuario("ID o email del usuario")
        if usuario is None:
            return
        try:
            servicio.reactivar(usuario.id)
        except LogisticaError as error:
            consola.error(str(error))
            return
        consola.exito(f"{usuario.nombre_completo} quedo ACTIVO.")

    def alta_rol() -> None:
        consola.titulo("Alta de rol")
        consola.aviso(
            "El nivel de permisos es lo que recorta el menu (D42): 100 es acceso "
            "total, 30 es solo consulta."
        )
        descripcion = consola.pedir("Descripcion (ADMINISTRADOR, OPERADOR...)")
        try:
            nivel = int(consola.pedir("Nivel de permisos (1 a 100)"))
        except ValueError:
            consola.error("El nivel tiene que ser un numero entero.")
            return
        try:
            rol = servicio.alta_rol(descripcion, nivel)
        except LogisticaError as error:
            consola.error(str(error))
            return
        consola.exito(f"Rol {rol.descripcion} creado con nivel {rol.nivel_permisos}.")

    def modificar_rol() -> None:
        consola.titulo("Modificar rol")
        roles = servicio.listar_roles()
        consola.tabla(
            ["#", "ROL", "NIVEL"],
            [[str(i), r.descripcion, str(r.nivel_permisos)] for i, r in enumerate(roles, 1)],
        )
        eleccion = consola.pedir("Numero del rol").strip()
        if not eleccion.isdigit() or not 1 <= int(eleccion) <= len(roles):
            consola.error("Rol invalido.")
            return
        rol = roles[int(eleccion) - 1]

        cuantos = servicio.contar_usuarios_por_rol(rol.id)
        if cuantos:
            consola.aviso(
                f"Cambiar el nivel de {rol.descripcion} le cambia el menu a "
                f"{cuantos} usuario(s)."
            )
        descripcion = consola.pedir(f"Descripcion [{rol.descripcion}]").strip() or None
        texto = consola.pedir(f"Nivel [{rol.nivel_permisos}]").strip()
        nivel = None
        if texto:
            try:
                nivel = int(texto)
            except ValueError:
                consola.error("El nivel tiene que ser un numero entero.")
                return
        try:
            actualizado = servicio.modificar_rol(
                rol.id, descripcion=descripcion, nivel_permisos=nivel
            )
        except LogisticaError as error:
            consola.error(str(error))
            return
        consola.exito(
            f"{actualizado.descripcion} quedo en nivel {actualizado.nivel_permisos}."
        )

    consola.menu(
        "Usuarios, roles y sesiones",
        {
            "1": ("Alta de usuario", alta),
            "2": ("Listar usuarios", listar),
            "3": ("Modificar usuario", modificar),
            "4": ("Baja de usuario", baja),
            "5": ("Reactivar usuario", reactivar),
            "6": ("Listar roles", listar_roles),
            "7": ("Alta de rol", alta_rol),
            "8": ("Modificar rol", modificar_rol),
            "9": ("Sesiones activas", listar_sesiones),
            "10": ("Cerrar una sesion activa", cerrar_sesion),
        },
    )
