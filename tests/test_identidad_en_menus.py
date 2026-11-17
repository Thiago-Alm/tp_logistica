"""Nadie elige de una lista quien hizo una accion: la hace quien inicio sesion.

Los menus de mensajeria y de solicitudes preguntaban "Usuario que escribe" y
"Usuario que lo pide" con la lista de usuarios activos, estando ya logueado.
Eso permitia firmar un mensaje en nombre de otro, y dejaba un registro de
autoria que no significaba nada (D65).

El test lee el codigo en vez de ejecutarlo, como test_menus_opcionales: lo que
hay que impedir es que la pregunta vuelva, no una salida concreta.
"""
import re
from pathlib import Path

import pytest

CLI = Path(__file__).resolve().parent.parent / "src" / "logistica" / "cli"

# Etiquetas que delatan que se esta eligiendo al autor de una accion.
PROHIBIDAS = re.compile(r'"Usuario que [^"]*"')


@pytest.mark.parametrize("ruta", sorted(CLI.glob("menu_*.py")), ids=lambda r: r.name)
def test_ningun_menu_pregunta_quien_hace_la_accion(ruta):
    encontradas = PROHIBIDAS.findall(ruta.read_text(encoding="utf-8"))
    assert not encontradas, (
        f"{ruta.name} pregunta {encontradas}: el usuario ya inicio sesion. "
        "Usa `usuario_actual` en vez de pedir que lo elijan de una lista."
    )


def test_la_aplicacion_conserva_el_usuario_autenticado():
    """`_autenticar` devuelve el usuario; descartarlo era el origen del
    problema: el resto de la aplicacion dejaba de saber quien estaba."""
    texto = (CLI / "app.py").read_text(encoding="utf-8")
    assert "usuario, rol, sesion = credenciales" in texto
    assert "_, rol, sesion = credenciales" not in texto
