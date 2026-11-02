"""Menu de ABM de proveedores y de operadores logisticos.

Un solo menu para los dos, parametrizado: tienen la misma forma y las mismas
operaciones. `tipo_servicio` es lo unico propio del proveedor, y la columna
aparece solo cuando corresponde.
"""

from uuid import UUID

from logistica.cli import consola
from logistica.cli.permisos import NIVEL_ADMINISTRADOR, NIVEL_AUDITOR, opciones_para
from logistica.domain.partes import ParteComercial
from logistica.exceptions import LogisticaError
from logistica.services.parte_service import ServicioDeParte


def _columnas(con_servicio: bool) -> list[str]:
    base = ["ID", "CUIT", "RAZON SOCIAL", "EMAIL", "PAIS", "ESTADO"]
    return [*base, "TIPO DE SERVICIO"] if con_servicio else base


def _fila(parte: ParteComercial, con_servicio: bool) -> list[str]:
    fila = [
        # El ultimo grupo del UUID, no el primero: los ids de los datos
        # semilla comparten prefijo (30000000-0000-...), asi que recortar por
        # delante los dejaria a todos iguales. Las operaciones aceptan el CUIT
        # o este mismo fragmento.
        str(parte.id)[-12:],
        parte.cuit,
        parte.razon_social,
        parte.email,
        parte.pais,
        parte.estado.value,
    ]
    if con_servicio:
        fila.append(parte.tipo_servicio)
    return fila


def construir(
    servicio: ServicioDeParte,
    titulo: str,
    con_servicio: bool = False,
    rol_nivel: int = NIVEL_ADMINISTRADOR,
) -> None:
    """`con_servicio` agrega el campo `tipo_servicio`, que solo tiene el
    proveedor."""

    def _mostrar(partes: list[ParteComercial]) -> None:
        if not partes:
            consola.aviso(f"No hay {titulo.lower()} para mostrar.")
            return
        consola.tabla(
            _columnas(con_servicio), [_fila(p, con_servicio) for p in partes]
        )

    def _buscar(etiqueta: str) -> ParteComercial | None:
        """Acepta el UUID completo, el CUIT, o un fragmento del id.

        Se prueban en ese orden en vez de adivinar el formato: un CUIT y un
        UUID se parecen lo suficiente (digitos y guiones) como para que
        cualquier regla se equivoque con alguno.
        """
        texto = consola.pedir(etiqueta).strip()
        if not texto:
            consola.error("Hace falta un CUIT o un ID.")
            return None

        try:
            return servicio.obtener(UUID(texto))
        except (ValueError, LogisticaError):
            pass
        try:
            return servicio.buscar_por_cuit(texto)
        except LogisticaError:
            pass

        try:
            partes = servicio.listar()
        except LogisticaError as error:
            consola.error(str(error))
            return None
        encontrada = next(
            (p for p in partes if texto.lower() in str(p.id).lower()), None
        )
        if encontrada is None:
            consola.error("No se encontro con ese CUIT ni con ese ID.")
        return encontrada

    def alta() -> None:
        consola.titulo(f"Alta de {servicio.singular}")
        datos = {
            "cuit": consola.pedir("CUIT (11 digitos)"),
            "razon_social": consola.pedir("Razon social"),
            "email": consola.pedir("Email"),
            "pais": consola.pedir("Pais"),
            "telefono": consola.pedir("Telefono (Enter para omitir)").strip() or None,
        }
        if con_servicio:
            datos["tipo_servicio"] = consola.pedir(
                "Tipo de servicio (ESTIBA_Y_AMARRE, BUNKERING...)"
            )
        try:
            parte = servicio.alta(**datos)
        except LogisticaError as error:
            consola.error(str(error))
            return
        consola.exito(f"{parte.razon_social} dado de alta.")
        consola.aviso(f"ID: {parte.id}")

    def listar() -> None:
        consola.titulo(titulo)
        try:
            _mostrar(servicio.listar())
        except LogisticaError as error:
            consola.error(str(error))

    def listar_activos() -> None:
        consola.titulo(f"{titulo} activos")
        try:
            _mostrar(servicio.listar(solo_activos=True))
        except LogisticaError as error:
            consola.error(str(error))

    def modificar() -> None:
        consola.titulo(f"Modificar {servicio.singular}")
        parte = _buscar("CUIT o ID")
        if parte is None:
            return
        consola.aviso(f"{parte.razon_social} ({parte.cuit}). Enter deja el valor actual.")
        cambios = {
            "razon_social": consola.pedir(f"Razon social [{parte.razon_social}]").strip()
            or None,
            "email": consola.pedir(f"Email [{parte.email}]").strip() or None,
            "pais": consola.pedir(f"Pais [{parte.pais}]").strip() or None,
            "telefono": consola.pedir(f"Telefono [{parte.telefono or '-'}]").strip()
            or None,
        }
        if con_servicio:
            cambios["tipo_servicio"] = consola.pedir(
                f"Tipo de servicio [{parte.tipo_servicio}]"
            ).strip() or None
        try:
            actualizada = servicio.modificar(parte.id, **cambios)
        except LogisticaError as error:
            consola.error(str(error))
            return
        consola.exito(f"{actualizada.razon_social} actualizado.")

    def baja() -> None:
        consola.titulo(f"Baja de {servicio.singular}")
        consola.aviso("La baja es logica: la fila queda, con estado INACTIVO (D26).")
        parte = _buscar("CUIT o ID")
        if parte is None:
            return
        if not consola.confirmar(f"Dar de baja a {parte.razon_social}?"):
            consola.aviso("Cancelado.")
            return
        try:
            servicio.baja(parte.id)
        except LogisticaError as error:
            consola.error(str(error))
            return
        consola.exito(f"{parte.razon_social} quedo INACTIVO.")

    def reactivar() -> None:
        consola.titulo(f"Reactivar {servicio.singular}")
        parte = _buscar("CUIT o ID")
        if parte is None:
            return
        try:
            servicio.reactivar(parte.id)
        except LogisticaError as error:
            consola.error(str(error))
            return
        consola.exito(f"{parte.razon_social} quedo ACTIVO.")

    secciones = [
        (NIVEL_ADMINISTRADOR, f"Alta de {servicio.singular}", alta),
        (NIVEL_AUDITOR, "Listar todos", listar),
        (NIVEL_AUDITOR, "Listar solo activos", listar_activos),
        (NIVEL_ADMINISTRADOR, "Modificar", modificar),
        (NIVEL_ADMINISTRADOR, "Baja (logica)", baja),
        (NIVEL_ADMINISTRADOR, "Reactivar", reactivar),
    ]
    consola.menu(titulo, opciones_para(rol_nivel, secciones))
