"""Casos de uso de Usuario y Rol. Requisito: administracion de usuarios y roles."""
import logging
from datetime import datetime, timezone
from uuid import UUID, uuid4

from logistica.domain.rol import Rol
from logistica.domain.usuario import EstadoUsuario, Usuario
from logistica.exceptions import ConflictoDeDatos, NoEncontrado, ValidacionError
from logistica.repositories.unidad_de_trabajo import UnidadDeTrabajo
from logistica.seguridad import hashear_password, verificar_password

LARGO_MINIMO_PASSWORD = 8

log = logging.getLogger(__name__)


class UsuarioService:
    def __init__(self, unidad_de_trabajo: UnidadDeTrabajo) -> None:
        self._uow = unidad_de_trabajo

    def alta(
        self,
        rol_id: UUID,
        nombre: str,
        apellido: str,
        email: str,
        password: str,
        cliente_id: UUID | None = None,
    ) -> Usuario:
        """La contrasena en claro entra aca y no sale: se guarda solo su hash."""
        if len(password) < LARGO_MINIMO_PASSWORD:
            raise ValidacionError(
                f"La contrasena necesita al menos {LARGO_MINIMO_PASSWORD} caracteres"
            )

        usuario = Usuario(
            id=uuid4(),
            rol_id=rol_id,
            cliente_id=cliente_id,
            nombre=nombre,
            apellido=apellido,
            email=email,
            password_hash=hashear_password(password),
            fecha_registro=datetime.now(timezone.utc),
        )
        with self._uow as uow:
            if uow.usuarios.obtener_por_email(email) is not None:
                raise ConflictoDeDatos(f"Ya existe un usuario con el email {email}")
            if uow.roles.obtener(rol_id) is None:
                raise ValidacionError(f"No existe el rol {rol_id}")
            if cliente_id is not None and uow.clientes.obtener(cliente_id) is None:
                raise ValidacionError(f"No existe el cliente {cliente_id}")
            uow.usuarios.guardar(usuario)
            uow.commit()
        log.info("Usuario dado de alta: %s (%s)", usuario.email, usuario.id)
        return usuario

    def autenticar(self, email: str, password: str) -> Usuario:
        """Devuelve el usuario si las credenciales son validas.

        El mensaje de error es el mismo para "no existe" y para "contrasena
        equivocada": decir cual de las dos fallo le confirmaria a un atacante
        que ese email esta registrado.
        """
        with self._uow as uow:
            usuario = uow.usuarios.obtener_por_email(email)
        if usuario is None or not verificar_password(password, usuario.password_hash):
            log.warning("Intento de autenticacion fallido para %s", email)
            raise ValidacionError("Email o contrasena incorrectos")
        if not usuario.esta_activo():
            raise ValidacionError("El usuario esta dado de baja")
        log.info("Usuario autenticado: %s", email)
        return usuario

    def cambiar_password(self, id: UUID, password_nueva: str) -> None:
        if len(password_nueva) < LARGO_MINIMO_PASSWORD:
            raise ValidacionError(
                f"La contrasena necesita al menos {LARGO_MINIMO_PASSWORD} caracteres"
            )
        with self._uow as uow:
            usuario = uow.usuarios.obtener(id)
            if usuario is None:
                raise NoEncontrado(f"No existe el usuario {id}")
            usuario.password_hash = hashear_password(password_nueva)
            uow.usuarios.actualizar(usuario)
            uow.commit()
        log.info("Contrasena cambiada para el usuario %s", id)

    def baja(self, id: UUID) -> Usuario:
        with self._uow as uow:
            usuario = uow.usuarios.obtener(id)
            if usuario is None:
                raise NoEncontrado(f"No existe el usuario {id}")
            usuario.dar_de_baja()
            uow.usuarios.actualizar(usuario)
            uow.commit()
        log.info("Usuario dado de baja: %s", id)
        return usuario

    def obtener(self, id: UUID) -> Usuario:
        with self._uow as uow:
            usuario = uow.usuarios.obtener(id)
        if usuario is None:
            raise NoEncontrado(f"No existe el usuario {id}")
        return usuario

    def listar(self, solo_activos: bool = False) -> list[Usuario]:
        with self._uow as uow:
            return uow.usuarios.listar(EstadoUsuario.ACTIVO if solo_activos else None)

    def listar_por_cliente(self, cliente_id: UUID) -> list[Usuario]:
        with self._uow as uow:
            return uow.usuarios.listar_por_cliente(cliente_id)

    def listar_roles(self) -> list[Rol]:
        with self._uow as uow:
            return uow.roles.listar()

    def obtener_rol_por_descripcion(self, descripcion: str) -> Rol:
        with self._uow as uow:
            rol = uow.roles.obtener_por_descripcion(descripcion)
        if rol is None:
            raise NoEncontrado(f"No existe el rol {descripcion!r}")
        return rol

    def obtener_rol(self, rol_id: UUID) -> Rol:
        """El rol de un usuario, para saber su nivel de permisos."""
        with self._uow as uow:
            rol = uow.roles.obtener(rol_id)
        if rol is None:
            raise NoEncontrado(f"No existe el rol {rol_id}")
        return rol

    def modificar(
        self,
        id: UUID,
        nombre: str | None = None,
        apellido: str | None = None,
        email: str | None = None,
        rol_id: UUID | None = None,
    ) -> Usuario:
        """Solo cambia lo que viene con valor.

        La contrasena NO se toca aca: tiene su propio metodo, porque cambiarla
        exige el largo minimo y el hasheo, y mezclarla con los datos de contacto
        haria facil pisarla sin querer.
        """
        with self._uow as uow:
            usuario = uow.usuarios.obtener(id)
            if usuario is None:
                raise NoEncontrado(f"No existe el usuario {id}")
            if email is not None and email != usuario.email:
                otro = uow.usuarios.obtener_por_email(email)
                if otro is not None and otro.id != id:
                    raise ConflictoDeDatos(f"Ya existe un usuario con el email {email}")
            if rol_id is not None and uow.roles.obtener(rol_id) is None:
                raise ValidacionError(f"No existe el rol {rol_id}")

            for campo, valor in (
                ("nombre", nombre),
                ("apellido", apellido),
                ("email", email),
                ("rol_id", rol_id),
            ):
                if valor is not None:
                    setattr(usuario, campo, valor)
            # Un setattr se saltea __post_init__: hay que revalidar entero.
            usuario.validar()
            uow.usuarios.actualizar(usuario)
            uow.commit()
        log.info("Usuario modificado: %s (%s)", usuario.email, usuario.id)
        return usuario

    def reactivar(self, id: UUID) -> Usuario:
        """Deshace una baja logica (D26)."""
        with self._uow as uow:
            usuario = uow.usuarios.obtener(id)
            if usuario is None:
                raise NoEncontrado(f"No existe el usuario {id}")
            usuario.estado = EstadoUsuario.ACTIVO
            uow.usuarios.actualizar(usuario)
            uow.commit()
        return usuario

    # --- Roles ---------------------------------------------------------------

    def alta_rol(self, descripcion: str, nivel_permisos: int) -> Rol:
        """El nivel de permisos es lo que filtra el menu (D42), asi que dar de
        alta un rol con nivel 100 es dar acceso total: la opcion es de
        administrador."""
        rol = Rol(
            id=uuid4(),
            descripcion=descripcion.strip().upper(),
            nivel_permisos=nivel_permisos,
        )
        with self._uow as uow:
            if uow.roles.obtener_por_descripcion(rol.descripcion) is not None:
                raise ConflictoDeDatos(f"Ya existe el rol {rol.descripcion}")
            uow.roles.guardar(rol)
            uow.commit()
        log.info("Rol dado de alta: %s (nivel %s)", rol.descripcion, rol.nivel_permisos)
        return rol

    def modificar_rol(
        self,
        id: UUID,
        descripcion: str | None = None,
        nivel_permisos: int | None = None,
    ) -> Rol:
        """Cambiar el nivel de un rol cambia lo que ven TODOS sus usuarios en el
        menu, no solo uno: por eso queda registrado en el log."""
        with self._uow as uow:
            rol = uow.roles.obtener(id)
            if rol is None:
                raise NoEncontrado(f"No existe el rol {id}")
            anterior = rol.nivel_permisos
            if descripcion is not None:
                nueva = descripcion.strip().upper()
                otro = uow.roles.obtener_por_descripcion(nueva)
                if otro is not None and otro.id != id:
                    raise ConflictoDeDatos(f"Ya existe el rol {nueva}")
                rol.descripcion = nueva
            if nivel_permisos is not None:
                rol.nivel_permisos = nivel_permisos
            rol.validar()
            uow.roles.actualizar(rol)
            uow.commit()
        if nivel_permisos is not None and nivel_permisos != anterior:
            log.warning(
                "El rol %s paso de nivel %s a %s: cambia el menu de todos sus usuarios",
                rol.descripcion, anterior, nivel_permisos,
            )
        return rol

    def contar_usuarios_por_rol(self, rol_id: UUID) -> int:
        """Cuantos usuarios tiene un rol. Sirve para avisar antes de cambiarle
        el nivel a cuanta gente le va a cambiar el menu."""
        with self._uow as uow:
            return sum(1 for u in uow.usuarios.listar() if u.rol_id == rol_id)
