"""Si un menu dice que Enter hace algo, Enter tiene que hacer algo.

`consola.pedir` es obligatorio por defecto: con la entrada vacia vuelve a
preguntar, para siempre. Varias opciones ofrecian "Enter para el valor por
defecto" usando esa version, asi que Enter no avanzaba nunca.

Lo encontro Thiago usando la aplicacion, no los tests: la pasada automatica
reemplazaba `consola.pedir` por un doble, y eso salteaba justo el bucle que
estaba roto. **Un doble que reemplaza lo que falla no puede encontrar la
falla.** Por eso este test mira el codigo fuente en vez de ejecutarlo.
"""
import re
from pathlib import Path

import pytest

CLI = Path(__file__).resolve().parent.parent / "src" / "logistica" / "cli"

# consola.pedir("...")  o  consola.pedir(f"...")  con lo que venga despues.
LLAMADA = re.compile(r'consola\.pedir\(\s*(f?"[^"]*")((?:[^()]|\([^()]*\))*)\)')

# Una etiqueta promete que la entrada vacia sirve si nombra al Enter, o si
# muestra el valor actual entre corchetes ("Pais [Argentina]").
def promete_vacio(etiqueta: str) -> bool:
    return "Enter" in etiqueta or "[" in etiqueta


def llamadas_de_los_menus():
    for ruta in sorted(CLI.glob("menu_*.py")):
        texto = ruta.read_text(encoding="utf-8")
        # Se juntan las lineas para encontrar tambien las llamadas partidas.
        plano = re.sub(r"\n\s*", " ", texto)
        for coincidencia in LLAMADA.finditer(plano):
            yield ruta.name, coincidencia.group(1), coincidencia.group(2)


def test_hay_llamadas_para_revisar():
    """Si el regex deja de encontrar nada, el test pasaria por vacio."""
    assert len(list(llamadas_de_los_menus())) > 20


@pytest.mark.parametrize(
    "archivo,etiqueta,resto",
    [
        (a, e, r)
        for a, e, r in llamadas_de_los_menus()
        if promete_vacio(e)
    ],
)
def test_lo_que_promete_enter_acepta_vacio(archivo, etiqueta, resto):
    assert "obligatorio=False" in resto, (
        f"{archivo}: la etiqueta {etiqueta} dice que la entrada vacia sirve, "
        "pero consola.pedir es obligatorio por defecto y va a volver a "
        "preguntar para siempre. Agregale obligatorio=False."
    )


# No se verifica el otro sentido -que lo no prometido sea obligatorio- porque
# `consola.pedir` agrega " (opcional)" solo cuando no lo es: el usuario siempre
# se entera, diga lo que diga la etiqueta. La regla que importa es la de
# arriba, y va en un solo sentido.
