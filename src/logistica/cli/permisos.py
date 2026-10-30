"""Niveles de permiso y el filtro de opciones segun el rol (D42).

Vive aparte para que el menu principal y los submenus usen EL MISMO criterio:
si cada menu decidiera por su cuenta con un `if nivel >= ...`, el control
quedaria repartido y seria imposible auditarlo de un vistazo.
"""
from collections.abc import Callable

# Son los niveles de la tabla `rol` de PostgreSQL.
NIVEL_ADMINISTRADOR = 100
NIVEL_OPERADOR = 60
NIVEL_AUDITOR = 30
NIVEL_CLIENTE = 10

# (nivel minimo, etiqueta, accion)
Seccion = tuple[int, str, Callable[[], None]]


def opciones_para(
    nivel: int, secciones: list[Seccion]
) -> dict[str, tuple[str, Callable[[], None]]]:
    """Deja solo lo que el nivel alcanza y lo renumera desde 1.

    Lo que no alcanza no se muestra: si figurara deshabilitado, le estaria
    contando a cualquiera que entre que existe y que hay detras. Y se renumera
    porque un menu con huecos (1, 3, 5) se lee como un error.
    """
    permitidas = [
        (etiqueta, accion) for minimo, etiqueta, accion in secciones if nivel >= minimo
    ]
    return {str(i): entrada for i, entrada in enumerate(permitidas, start=1)}
