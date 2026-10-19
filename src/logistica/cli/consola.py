"""Utilidades de la consola: leer datos y mostrar tablas.

Separado de los menus para que cada menu se ocupe solo de su caso de uso.
"""
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")

ANCHO = 78


def titulo(texto: str) -> None:
    print()
    print("=" * ANCHO)
    print(f"  {texto}")
    print("=" * ANCHO)


def aviso(texto: str) -> None:
    print(f"  {texto}")


def error(texto: str) -> None:
    print(f"  [ERROR] {texto}")


def exito(texto: str) -> None:
    print(f"  [OK] {texto}")


def pedir(etiqueta: str, obligatorio: bool = True) -> str:
    """Devuelve cadena vacia si el campo es opcional y el usuario no escribe."""
    sufijo = "" if obligatorio else " (opcional)"
    while True:
        valor = input(f"  {etiqueta}{sufijo}: ").strip()
        if valor or not obligatorio:
            return valor
        error("Este dato es obligatorio.")


def pedir_opcional(etiqueta: str) -> str | None:
    valor = pedir(etiqueta, obligatorio=False)
    return valor or None


def confirmar(pregunta: str) -> bool:
    return input(f"  {pregunta} [s/N]: ").strip().lower() in ("s", "si", "sí")


def tabla(encabezados: list[str], filas: list[list[str]]) -> None:
    if not filas:
        aviso("(sin resultados)")
        return
    anchos = [len(e) for e in encabezados]
    for fila in filas:
        for i, celda in enumerate(fila):
            anchos[i] = max(anchos[i], len(celda))
    linea = "  " + "  ".join(e.ljust(anchos[i]) for i, e in enumerate(encabezados))
    print(linea)
    print("  " + "  ".join("-" * a for a in anchos))
    for fila in filas:
        print("  " + "  ".join(c.ljust(anchos[i]) for i, c in enumerate(fila)))
    print(f"\n  {len(filas)} fila(s)")


def menu(
    encabezado: str,
    opciones: dict[str, tuple[str, Callable[[], None]]],
    salida: str = "Volver",
) -> None:
    """Muestra un menu y lo repite hasta que se elige la opcion 0 (volver).

    `opciones` mapea la tecla a (etiqueta, funcion).
    """
    while True:
        titulo(encabezado)
        for tecla, (etiqueta, _) in opciones.items():
            print(f"   {tecla}. {etiqueta}")
        print(f"   0. {salida}")
        eleccion = input("\n  Opcion: ").strip()
        if eleccion == "0":
            return
        if eleccion not in opciones:
            error("Opcion invalida.")
            continue
        opciones[eleccion][1]()
