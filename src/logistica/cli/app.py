"""Punto de entrada de la aplicacion de consola.

    python -m logistica
"""
import logging
import sys

from logistica.cli import (
    consola,
    menu_clientes,
    menu_envios,
    menu_reportes,
    menu_sincronizacion,
    menu_usuarios,
)
from logistica.container import Contenedor
from logistica.exceptions import ErrorDePersistencia, LogisticaError

log = logging.getLogger(__name__)


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


def main() -> int:
    contenedor = Contenedor()
    consola.titulo("Plataforma de Logistica Internacional y Monitoreo IoT")
    consola.aviso("TP Persistencia Poliglota - Ingenieria de Datos II")

    if not _comprobar_base(contenedor):
        return 1

    try:
        consola.menu(
            "Menu principal",
            {
                "1": ("Clientes", lambda: menu_clientes.construir(contenedor.clientes)),
                "2": (
                    "Usuarios y roles",
                    lambda: menu_usuarios.construir(contenedor.usuarios, contenedor.clientes),
                ),
                "3": (
                    "Envios y trayectos",
                    lambda: menu_envios.construir(
                        contenedor.envios,
                        contenedor.clientes,
                        contenedor.trazabilidad,
                    ),
                ),
                "4": ("Reportes", lambda: menu_reportes.construir(contenedor.reportes)),
                "5": (
                    "Sincronizacion entre motores",
                    lambda: menu_sincronizacion.construir(
                        contenedor.worker_de_sincronizacion,
                        contenedor.chequeo_de_consistencia,
                    ),
                ),
            },
            salida="Salir",
        )
    except KeyboardInterrupt:
        print()
        consola.aviso("Interrumpido.")
        return 130
    except LogisticaError as e:
        log.exception("Error no controlado en la aplicacion")
        consola.error(str(e))
        return 1

    consola.aviso("Hasta luego.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
