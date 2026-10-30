"""Menu de ABM de contenedores."""

from logistica.cli import consola
from logistica.cli.permisos import NIVEL_ADMINISTRADOR, NIVEL_AUDITOR, opciones_para
from logistica.domain.contenedor import Contenedor, EstadoContenedor
from logistica.exceptions import LogisticaError
from logistica.services.contenedor_service import TIPOS_CONOCIDOS, ContenedorService


def _mostrar(contenedores: list[Contenedor]) -> None:
    if not contenedores:
        consola.aviso("No hay contenedores para mostrar.")
        return
    consola.tabla(
        ["CODIGO ISO", "TIPO", "CAPACIDAD", "ESTADO"],
        [
            [c.codigo_iso, c.tipo, f"{c.capacidad:.1f}", c.estado.value]
            for c in contenedores
        ],
    )


def _elegir_estado(etiqueta: str) -> EstadoContenedor | None:
    """Solo los estados administrativos: ASIGNADO y EN_TRANSITO los pone el
    envio, no el ABM."""
    disponibles = [e for e in EstadoContenedor if not e.esta_ocupado()]
    consola.aviso(
        f"{etiqueta}: "
        + ", ".join(f"{i}={e.value}" for i, e in enumerate(disponibles, 1))
    )
    texto = consola.pedir(etiqueta).strip()
    if texto.isdigit() and 1 <= int(texto) <= len(disponibles):
        return disponibles[int(texto) - 1]
    try:
        elegido = EstadoContenedor(texto.upper())
    except ValueError:
        consola.error("Estado invalido.")
        return None
    if elegido.esta_ocupado():
        consola.error(f"{elegido.value} lo pone el envio al asignar el contenedor.")
        return None
    return elegido


def construir(servicio: ContenedorService, rol_nivel: int = NIVEL_ADMINISTRADOR) -> None:
    def _buscar() -> Contenedor | None:
        try:
            return servicio.buscar(consola.pedir("Codigo ISO o ID del contenedor"))
        except LogisticaError as error:
            consola.error(str(error))
            return None

    def alta() -> None:
        consola.titulo("Alta de contenedor")
        consola.aviso("El codigo ISO 6346 son 4 letras y 7 digitos: MSKU1234567.")
        consola.aviso("Tipos usados: " + ", ".join(TIPOS_CONOCIDOS))
        codigo = consola.pedir("Codigo ISO")
        tipo = consola.pedir("Tipo")
        try:
            capacidad = float(consola.pedir("Capacidad (toneladas)"))
        except ValueError:
            consola.error("La capacidad tiene que ser un numero.")
            return
        try:
            contenedor = servicio.alta(codigo, tipo, capacidad)
        except LogisticaError as error:
            consola.error(str(error))
            return
        consola.exito(f"Contenedor {contenedor.codigo_iso} dado de alta.")
        consola.aviso(f"ID: {contenedor.id}")

    def listar() -> None:
        consola.titulo("Contenedores")
        try:
            _mostrar(servicio.listar())
        except LogisticaError as error:
            consola.error(str(error))

    def listar_por_estado() -> None:
        consola.titulo("Contenedores por estado")
        estados = list(EstadoContenedor)
        consola.aviso(
            "Estado: " + ", ".join(f"{i}={e.value}" for i, e in enumerate(estados, 1))
        )
        texto = consola.pedir("Estado").strip()
        if texto.isdigit() and 1 <= int(texto) <= len(estados):
            estado = estados[int(texto) - 1]
        else:
            try:
                estado = EstadoContenedor(texto.upper())
            except ValueError:
                consola.error("Estado invalido.")
                return
        try:
            _mostrar(servicio.listar(estado))
        except LogisticaError as error:
            consola.error(str(error))

    def modificar() -> None:
        consola.titulo("Modificar contenedor")
        consola.aviso(
            "El codigo ISO no se modifica: identifica fisicamente al contenedor "
            "y lo referencian sus lecturas y el grafo."
        )
        contenedor = _buscar()
        if contenedor is None:
            return
        consola.aviso(
            f"{contenedor.codigo_iso}: {contenedor.tipo}, "
            f"{contenedor.capacidad:.1f} t. Enter deja el valor actual."
        )
        tipo = consola.pedir(f"Tipo [{contenedor.tipo}]").strip() or None
        texto = consola.pedir(f"Capacidad [{contenedor.capacidad:.1f}]").strip()
        capacidad = None
        if texto:
            try:
                capacidad = float(texto)
            except ValueError:
                consola.error("La capacidad tiene que ser un numero.")
                return
        try:
            actualizado = servicio.modificar(contenedor.id, tipo=tipo, capacidad=capacidad)
        except LogisticaError as error:
            consola.error(str(error))
            return
        consola.exito(
            f"{actualizado.codigo_iso}: {actualizado.tipo}, {actualizado.capacidad:.1f} t."
        )

    def cambiar_estado() -> None:
        consola.titulo("Cambiar el estado de un contenedor")
        contenedor = _buscar()
        if contenedor is None:
            return
        consola.aviso(f"{contenedor.codigo_iso} esta {contenedor.estado.value}.")
        nuevo = _elegir_estado("Nuevo estado")
        if nuevo is None:
            return
        try:
            actualizado = servicio.cambiar_estado(contenedor.id, nuevo)
        except LogisticaError as error:
            consola.error(str(error))
            return
        consola.exito(f"{actualizado.codigo_iso} quedo {actualizado.estado.value}.")

    def baja() -> None:
        consola.titulo("Baja de contenedor")
        consola.aviso(
            "La baja es logica: la fila queda, porque la referencian los envios "
            "en los que viajo y sus lecturas en Cassandra (D26)."
        )
        contenedor = _buscar()
        if contenedor is None:
            return
        if not consola.confirmar(f"Dar de baja a {contenedor.codigo_iso}?"):
            consola.aviso("Cancelado.")
            return
        try:
            servicio.baja(contenedor.id)
        except LogisticaError as error:
            consola.error(str(error))
            return
        consola.exito(f"{contenedor.codigo_iso} quedo en BAJA.")

    secciones = [
        (NIVEL_ADMINISTRADOR, "Alta de contenedor", alta),
        (NIVEL_AUDITOR, "Listar todos", listar),
        (NIVEL_AUDITOR, "Listar por estado", listar_por_estado),
        (NIVEL_ADMINISTRADOR, "Modificar", modificar),
        (NIVEL_ADMINISTRADOR, "Cambiar estado", cambiar_estado),
        (NIVEL_ADMINISTRADOR, "Baja (logica)", baja),
    ]
    consola.menu("Contenedores", opciones_para(rol_nivel, secciones))
