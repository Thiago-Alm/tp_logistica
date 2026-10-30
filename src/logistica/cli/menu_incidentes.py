"""Menu de incidentes de envios y sus reportes (D12)."""

from uuid import UUID

from logistica.cli import consola
from logistica.cli.permisos import (
    NIVEL_ADMINISTRADOR,
    NIVEL_AUDITOR,
    NIVEL_OPERADOR,
    opciones_para,
)
from logistica.domain.incidente import (
    EstadoIncidente,
    Incidente,
    SeveridadIncidente,
    TipoIncidente,
)
from logistica.exceptions import LogisticaError
from logistica.repositories.incidente_repository import AgrupacionIncidentes
from logistica.services.incidente_service import IncidenteService


def _elegir(etiqueta: str, enum) -> object | None:
    """Pide una opcion de un enum mostrando las que hay, para no tener que
    tipear el valor exacto."""
    valores = list(enum)
    consola.aviso(
        f"{etiqueta}: " + ", ".join(f"{i}={v.value}" for i, v in enumerate(valores, 1))
    )
    texto = consola.pedir(etiqueta).strip()
    if texto.isdigit() and 1 <= int(texto) <= len(valores):
        return valores[int(texto) - 1]
    try:
        return enum(texto.upper())
    except ValueError:
        consola.error(f"{etiqueta} invalido.")
        return None


def _mostrar(incidentes: list[Incidente]) -> None:
    consola.tabla(
        ["ID", "FECHA", "ENVIO", "TIPO", "SEVERIDAD", "ESTADO", "RUTA"],
        [
            [
                str(i.id),
                f"{i.fecha.astimezone():%d/%m %H:%M}",
                str(i.envio_id)[:8],
                i.tipo.value,
                i.severidad.value,
                i.estado.value,
                i.contexto_envio.ruta,
            ]
            for i in incidentes
        ],
    )


def construir(
    servicio: IncidenteService, rol_nivel: int = NIVEL_ADMINISTRADOR
) -> None:
    def registrar() -> None:
        consola.titulo("Registrar un incidente")
        texto = consola.pedir("ID del envio").strip()
        try:
            envio_id = UUID(texto)
        except ValueError:
            consola.error("El ID del envio no es valido.")
            return

        tipo = _elegir("Tipo", TipoIncidente)
        if tipo is None:
            return
        severidad = _elegir("Severidad", SeveridadIncidente)
        if severidad is None:
            return
        descripcion = consola.pedir("Descripcion")

        texto_contenedor = consola.pedir("ID del contenedor (Enter si no aplica)").strip()
        contenedor_id = None
        if texto_contenedor:
            try:
                contenedor_id = UUID(texto_contenedor)
            except ValueError:
                consola.error("El ID del contenedor no es valido.")
                return

        try:
            incidente = servicio.registrar(
                envio_id, tipo, severidad, descripcion, contenedor_id
            )
        except LogisticaError as error:
            consola.error(str(error))
            return
        consola.exito(f"Incidente {incidente.id} registrado.")
        consola.aviso(
            f"Contexto congelado: {incidente.contexto_envio.ruta} "
            f"({incidente.contexto_envio.pais_origen} -> "
            f"{incidente.contexto_envio.pais_destino})"
        )

    def cambiar_estado() -> None:
        consola.titulo("Cambiar el estado de un incidente")
        texto = consola.pedir("ID del incidente").strip()
        try:
            incidente_id = UUID(texto)
        except ValueError:
            consola.error("El ID del incidente no es valido.")
            return
        destino = _elegir("Nuevo estado", EstadoIncidente)
        if destino is None:
            return
        try:
            incidente = servicio.cambiar_estado(incidente_id, destino)
        except LogisticaError as error:
            consola.error(str(error))
            return
        consola.exito(f"El incidente quedo {incidente.estado.value}.")
        consola.tabla(
            ["MOMENTO", "ESTADO"],
            [
                [f"{c.fecha.astimezone():%d/%m %H:%M}", c.estado.value]
                for c in incidente.historial_estados
            ],
        )

    def listar_abiertos() -> None:
        consola.titulo("Incidentes abiertos")
        consola.aviso("Cuentan como abiertos los ABIERTO y los EN_ANALISIS.")
        try:
            incidentes = servicio.listar_abiertos()
        except LogisticaError as error:
            consola.error(str(error))
            return
        if not incidentes:
            consola.aviso("No hay incidentes abiertos.")
            return
        _mostrar(incidentes)

    def listar_por_envio() -> None:
        consola.titulo("Incidentes de un envio")
        texto = consola.pedir("ID del envio").strip()
        try:
            envio_id = UUID(texto)
        except ValueError:
            consola.error("El ID del envio no es valido.")
            return
        try:
            incidentes = servicio.listar_por_envio(envio_id)
        except LogisticaError as error:
            consola.error(str(error))
            return
        if not incidentes:
            consola.aviso("Ese envio no tiene incidentes.")
            return
        _mostrar(incidentes)

    def ranking_de_rutas() -> None:
        consola.titulo("Ranking de rutas con mas incidentes")
        consola.aviso(
            "Se resuelve entero en MongoDB: cada incidente guarda la ruta en su "
            "snapshot, asi que no hace falta reconstruirla desde el grafo (D12)."
        )
        try:
            ranking = servicio.ranking_de_rutas()
        except LogisticaError as error:
            consola.error(str(error))
            return
        if not ranking:
            consola.aviso("No hay incidentes cargados.")
            return
        consola.tabla(
            ["#", "RUTA", "INCIDENTES"],
            [
                [str(i), r.ruta, str(r.cantidad)]
                for i, r in enumerate(ranking, start=1)
            ],
        )

    def contar_por_grupo() -> None:
        consola.titulo("Incidentes por grupo")
        agrupacion = _elegir("Agrupar por", AgrupacionIncidentes)
        if agrupacion is None:
            return
        try:
            conteos = servicio.contar_por(agrupacion)
        except LogisticaError as error:
            consola.error(str(error))
            return
        if not conteos:
            consola.aviso("No hay incidentes cargados.")
            return
        consola.tabla(
            [agrupacion.value, "INCIDENTES"],
            [[c.grupo, str(c.cantidad)] for c in conteos],
        )

    def promedio_por_grupo() -> None:
        consola.titulo("Promedio de incidentes por envio")
        consola.aviso(
            "MongoDB cuenta los incidentes y PostgreSQL los envios: el promedio "
            "no lo puede responder ninguna de las dos bases sola."
        )
        agrupacion = _elegir("Agrupar por", AgrupacionIncidentes)
        if agrupacion is None:
            return
        try:
            promedios = servicio.promedio_por(agrupacion)
        except LogisticaError as error:
            consola.error(str(error))
            return
        if not promedios:
            consola.aviso("No hay incidentes cargados.")
            return
        consola.tabla(
            [agrupacion.value, "INCIDENTES", "ENVIOS", "PROMEDIO"],
            [
                [p.grupo, str(p.incidentes), str(p.envios), f"{p.promedio:.2f}"]
                for p in promedios
            ],
        )

    # Registrar un incidente y moverlo de estado es operacion; consultarlos y
    # sacar los reportes es material de auditoria.
    secciones = [
        (NIVEL_OPERADOR, "Registrar un incidente", registrar),
        (NIVEL_AUDITOR, "Incidentes abiertos", listar_abiertos),
        (NIVEL_AUDITOR, "Incidentes de un envio", listar_por_envio),
        (NIVEL_OPERADOR, "Cambiar el estado de un incidente", cambiar_estado),
        (NIVEL_AUDITOR, "Ranking de rutas con mas incidentes", ranking_de_rutas),
        (NIVEL_AUDITOR, "Incidentes por pais, cliente, estado o ruta", contar_por_grupo),
        (NIVEL_AUDITOR, "Promedio de incidentes por envio", promedio_por_grupo),
    ]
    consola.menu("Incidentes", opciones_para(rol_nivel, secciones))
