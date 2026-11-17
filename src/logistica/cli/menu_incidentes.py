"""Menu de incidentes de envios y sus reportes (D12)."""


from logistica.cli import consola
from logistica.cli.permisos import (
    NIVEL_ADMINISTRADOR,
    NIVEL_AUDITOR,
    NIVEL_OPERADOR,
    opciones_para,
)
from logistica.domain.envio import EstadoEnvio
from logistica.domain.incidente import (
    EstadoIncidente,
    Incidente,
    SeveridadIncidente,
    TipoIncidente,
)
from logistica.exceptions import LogisticaError
from logistica.repositories.incidente_repository import AgrupacionIncidentes
from logistica.services.incidente_service import EjePromedio, IncidenteService


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
    servicio: IncidenteService,
    envios,
    clientes,
    rol_nivel: int = NIVEL_ADMINISTRADOR,
) -> None:
    """`envios` y `clientes` estan para poder elegir de una lista en vez de
    tipear UUID (D66)."""

    def _elegir_envio(etiqueta: str = "Numero de envio"):
        """Todos los envios, con el dato suficiente para reconocerlos.

        EnvioService no tiene un `listar()` suelto: se listan por estado, que
        ademas deja la tabla agrupada por estado, que es como uno los busca.
        """
        try:
            nombres = {c.id: c.razon_social for c in clientes.listar()}
            todos = [e for estado in EstadoEnvio for e in envios.listar_por_estado(estado)]
        except LogisticaError as error:
            consola.error(str(error))
            return None
        if not todos:
            consola.aviso("No hay envios cargados.")
            return None
        return consola.elegir_de_tabla(
            todos,
            ["ID", "CLIENTE", "ESTADO", "PRIORIDAD", "CREADO"],
            lambda e: [
                str(e.id)[-12:],
                nombres.get(e.cliente_id, str(e.cliente_id)[-8:])[:24],
                e.estado.value,
                e.prioridad.value,
                f"{e.fecha_creacion.astimezone():%d/%m/%Y}",
            ],
            etiqueta,
        )
    def registrar() -> None:
        consola.titulo("Registrar un incidente")
        envio = _elegir_envio()
        if envio is None:
            return
        envio_id = envio.id

        tipo = _elegir("Tipo", TipoIncidente)
        if tipo is None:
            return
        severidad = _elegir("Severidad", SeveridadIncidente)
        if severidad is None:
            return
        descripcion = consola.pedir("Descripcion")

        # Solo los contenedores de ESE envio: un incidente de otro contenedor
        # no tendria sentido en este envio.
        contenedor_id = None
        try:
            del_envio = envios.listar_contenedores(envio_id)
        except LogisticaError as error:
            consola.error(str(error))
            return
        if not del_envio:
            consola.aviso("El envio no tiene contenedores asignados.")
        elif consola.confirmar("Afecta a un contenedor en particular?"):
            elegido = consola.elegir_de_tabla(
                del_envio,
                ["CODIGO ISO", "TIPO", "ESTADO"],
                lambda c: [c.codigo_iso, c.tipo, c.estado.value],
                "Numero de contenedor",
            )
            if elegido is None:
                return
            contenedor_id = elegido.id

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
        try:
            abiertos = servicio.listar_abiertos()
        except LogisticaError as error:
            consola.error(str(error))
            return
        if not abiertos:
            consola.aviso("No hay incidentes abiertos para cambiar de estado.")
            return
        elegido = consola.elegir_de_tabla(
            abiertos,
            ["ID", "TIPO", "SEVERIDAD", "ESTADO", "DESCRIPCION"],
            lambda i: [
                str(i.id)[-12:],
                i.tipo.value,
                i.severidad.value,
                i.estado.value,
                i.descripcion[:30],
            ],
            "Numero de incidente",
        )
        if elegido is None:
            return
        incidente_id = elegido.id
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
        envio = _elegir_envio()
        if envio is None:
            return
        envio_id = envio.id
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
        eje = _elegir("Agrupar por", EjePromedio)
        if eje is None:
            return
        if eje is EjePromedio.ESTADO:
            consola.aviso(
                "Es el estado del ENVIO, no el del incidente: vive en PostgreSQL "
                "y cambia con el tiempo, por eso no esta en el snapshot (D53)."
            )
        try:
            promedios = servicio.promedio_por(eje)
        except LogisticaError as error:
            consola.error(str(error))
            return
        if not promedios:
            consola.aviso("No hay incidentes cargados.")
            return
        consola.tabla(
            [eje.value, "INCIDENTES", "ENVIOS", "PROMEDIO"],
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
        (NIVEL_AUDITOR, "Contar incidentes por pais, cliente, ruta o estado", contar_por_grupo),
        (NIVEL_AUDITOR, "Promedio de incidentes por pais / estado / cliente", promedio_por_grupo),
    ]
    consola.menu("Incidentes", opciones_para(rol_nivel, secciones))
