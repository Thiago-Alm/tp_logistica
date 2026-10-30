"""Punto de entrada de la aplicacion de consola.

    python -m logistica

Nadie ve un menu sin autenticarse antes: `main()` no arma el menu principal
hasta que `_autenticar()` devuelve un usuario, su rol y una sesion abierta en
Redis.
"""
import logging
import sys
from getpass import getpass

from logistica.cli import (
    consola,
    menu_clientes,
    menu_contenedores,
    menu_envios,
    menu_facturacion,
    menu_gps,
    menu_grafo,
    menu_incidentes,
    menu_monitoreo,
    menu_partes,
    menu_reportes,
    menu_sincronizacion,
    menu_solicitudes,
    menu_usuarios,
)
from logistica.cli.permisos import (
    NIVEL_ADMINISTRADOR,
    NIVEL_AUDITOR,
    NIVEL_OPERADOR,
    Seccion,
    opciones_para,
)
from logistica.container import Contenedor
from logistica.domain.rol import Rol
from logistica.domain.sesion import Sesion
from logistica.domain.usuario import Usuario
from logistica.exceptions import ErrorDePersistencia, LogisticaError

log = logging.getLogger(__name__)

INTENTOS_MAXIMOS = 3


def _comprobar_base(contenedor: Contenedor) -> bool:
    """Falla temprano y con un mensaje util si PostgreSQL no esta disponible,
    en vez de explotar a la mitad de un alta."""
    try:
        contenedor.usuarios.listar_roles()
    except ErrorDePersistencia as e:
        consola.error(f"No se pudo conectar a PostgreSQL: {e}")
        consola.aviso("Revisa que los contenedores esten arriba: docker compose up -d")
        consola.aviso("Y verifica las cinco bases: python scripts/chequear_conexiones.py")
        return False
    return True


def _autenticar(contenedor: Contenedor) -> tuple[Usuario, Rol, Sesion] | None:
    """Pide credenciales hasta INTENTOS_MAXIMOS veces y abre la sesion.

    La contrasena se lee con getpass para que no quede en pantalla ni en el
    historial de la terminal. El mensaje de error no distingue entre email
    inexistente y contrasena equivocada: eso lo decide UsuarioService.
    """
    consola.aviso("Ingresa con tu usuario para continuar.")

    for intento in range(1, INTENTOS_MAXIMOS + 1):
        email = consola.pedir("Email")
        password = getpass("  Contrasena (no se muestra): ")
        try:
            usuario = contenedor.usuarios.autenticar(email, password)
            rol = contenedor.usuarios.obtener_rol(usuario.rol_id)
        except LogisticaError as e:
            consola.error(str(e))
            restantes = INTENTOS_MAXIMOS - intento
            if restantes == 1:
                consola.aviso("Te queda 1 intento.")
            elif restantes > 1:
                consola.aviso(f"Te quedan {restantes} intentos.")
            continue
        break
    else:
        consola.error("Demasiados intentos fallidos. La aplicacion se cierra.")
        log.warning("Autenticacion abortada tras %s intentos", INTENTOS_MAXIMOS)
        return None

    # La sesion se abre aparte del bucle: si Redis esta caido, el problema no
    # son las credenciales y no tiene sentido volver a pedir la contrasena.
    try:
        sesion = contenedor.sesiones.iniciar(usuario.id)
    except LogisticaError as e:
        consola.error(f"Credenciales correctas, pero no se pudo abrir la sesion: {e}")
        consola.aviso("Revisa que Redis este arriba: docker compose up -d redis")
        return None

    consola.exito(f"Bienvenido, {usuario.nombre_completo}.")
    consola.aviso(f"Rol: {rol.descripcion} (nivel {rol.nivel_permisos})")
    consola.aviso(f"Sesion {sesion.id}")
    consola.aviso(f"Vence a las {sesion.fecha_fin.astimezone():%H:%M} si no la cerras antes.")
    return usuario, rol, sesion


def _secciones(contenedor: Contenedor, nivel: int) -> list[Seccion]:
    """Cada seccion declara el nivel de permisos que exige.

    `nivel` se recibe para pasarlo a los submenus que filtran alguna de sus
    propias opciones (el de monitoreo esconde la configuracion de umbrales).
    Asi el criterio sigue siendo uno solo, el de `permisos.opciones_para`.
    """
    return [
        (
            NIVEL_OPERADOR,
            "Clientes",
            lambda: menu_clientes.construir(contenedor.clientes),
        ),
        (
            NIVEL_AUDITOR,
            "Contenedores",
            lambda: menu_contenedores.construir(
                contenedor.contenedores_service, rol_nivel=nivel
            ),
        ),
        (
            NIVEL_AUDITOR,
            "Proveedores",
            lambda: menu_partes.construir(
                contenedor.proveedores_service,
                "Proveedores",
                con_servicio=True,
                rol_nivel=nivel,
            ),
        ),
        (
            NIVEL_AUDITOR,
            "Operadores logisticos",
            lambda: menu_partes.construir(
                contenedor.operadores_service, "Operadores logisticos", rol_nivel=nivel
            ),
        ),
        (
            NIVEL_ADMINISTRADOR,
            "Usuarios, roles y sesiones",
            lambda: menu_usuarios.construir(
                contenedor.usuarios,
                contenedor.clientes,
                contenedor.sesiones,
            ),
        ),
        (
            NIVEL_OPERADOR,
            "Envios y trayectos",
            lambda: menu_envios.construir(
                contenedor.envios,
                contenedor.clientes,
                contenedor.trazabilidad,
                contenedor.contenedores_service,
            ),
        ),
        (
            NIVEL_OPERADOR,
            "Facturacion y cuentas corrientes",
            lambda: menu_facturacion.construir(
                contenedor.facturacion,
                contenedor.clientes,
                contenedor.proveedores_service,
                contenedor.operadores_service,
            ),
        ),
        (
            NIVEL_AUDITOR,
            "Reportes",
            lambda: menu_reportes.construir(contenedor.reportes),
        ),
        (
            NIVEL_OPERADOR,
            "Consultas de la red logistica",
            lambda: menu_grafo.construir(contenedor.consultas_red),
        ),
        (
            NIVEL_OPERADOR,
            "Seguimiento GPS",
            lambda: menu_gps.construir(contenedor.gps),
        ),
        # Estas dos entran con nivel de auditor porque sus consultas son
        # material de auditoria; adentro, cada opcion declara su propio nivel y
        # las filtra el mismo `opciones_para`. Un auditor ve las de lectura, un
        # operador agrega las de operacion y un administrador la configuracion.
        (
            NIVEL_AUDITOR,
            "Solicitudes de reportes (facturables)",
            lambda: menu_solicitudes.construir(
                contenedor.solicitudes,
                contenedor.clientes,
                contenedor.proveedores_service,
                contenedor.operadores_service,
                rol_nivel=nivel,
            ),
        ),
        (
            NIVEL_AUDITOR,
            "Incidentes",
            lambda: menu_incidentes.construir(
                contenedor.incidentes_service, rol_nivel=nivel
            ),
        ),
        (
            NIVEL_AUDITOR,
            "Monitoreo IoT y alertas",
            lambda: menu_monitoreo.construir(contenedor.monitoreo, rol_nivel=nivel),
        ),
        (
            NIVEL_ADMINISTRADOR,
            "Sincronizacion entre motores",
            lambda: menu_sincronizacion.construir(
                contenedor.worker_de_sincronizacion,
                contenedor.chequeo_de_consistencia,
            ),
        ),
    ]


def main() -> int:
    contenedor = Contenedor()
    consola.titulo("Plataforma de Logistica Internacional y Monitoreo IoT")
    consola.aviso("TP Persistencia Poliglota - Ingenieria de Datos II")

    if not _comprobar_base(contenedor):
        return 1

    try:
        credenciales = _autenticar(contenedor)
    except KeyboardInterrupt:
        print()
        consola.aviso("Interrumpido.")
        return 130
    if credenciales is None:
        return 1
    _, rol, sesion = credenciales

    secciones = _secciones(contenedor, rol.nivel_permisos)
    opciones = opciones_para(rol.nivel_permisos, secciones)
    if not opciones:
        consola.error(
            f"El rol {rol.descripcion} (nivel {rol.nivel_permisos}) no tiene acceso a "
            "ninguna seccion de la consola interna."
        )
        _cerrar_sesion(contenedor, sesion)
        return 1

    consola.aviso(f"Ves {len(opciones)} de {len(secciones)} secciones segun tu rol.")

    try:
        consola.menu(f"Menu principal - {rol.descripcion}", opciones, salida="Salir")
    except KeyboardInterrupt:
        print()
        consola.aviso("Interrumpido.")
        return 130
    except LogisticaError as e:
        log.exception("Error no controlado en la aplicacion")
        consola.error(str(e))
        return 1
    finally:
        # La sesion se cierra pase lo que pase: si quedara viva, el TTL la
        # borraria igual, pero una hora despues.
        _cerrar_sesion(contenedor, sesion)

    consola.aviso("Hasta luego.")
    return 0


def _cerrar_sesion(contenedor: Contenedor, sesion: Sesion) -> None:
    try:
        contenedor.sesiones.cerrar(sesion.id)
    except LogisticaError as e:
        log.warning("No se pudo cerrar la sesion %s: %s", sesion.id, e)


if __name__ == "__main__":
    sys.exit(main())
