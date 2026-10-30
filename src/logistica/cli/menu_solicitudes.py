"""Menu de solicitud, generacion y facturacion de reportes parametrizados."""

from datetime import datetime

from logistica.cli import consola
from logistica.cli.permisos import NIVEL_ADMINISTRADOR, NIVEL_AUDITOR, opciones_para
from logistica.domain.facturacion import TitularTipo
from logistica.domain.solicitud_reporte import (
    CATALOGO,
    EstadoSolicitud,
    SolicitudReporte,
)
from logistica.exceptions import LogisticaError
from logistica.services.incidente_service import EjePromedio
from logistica.services.solicitud_reporte_service import SolicitudReporteService


def _mostrar(solicitudes: list[SolicitudReporte]) -> None:
    if not solicitudes:
        consola.aviso("No hay solicitudes para mostrar.")
        return
    consola.tabla(
        ["ID", "REPORTE", "TITULAR", "COSTO", "ESTADO", "FILAS"],
        [
            [
                str(s.id),
                s.especificacion.etiqueta[:34],
                s.titular_tipo.value,
                f"{s.costo:.2f}",
                s.estado.value,
                "-" if s.filas is None else str(s.filas),
            ]
            for s in solicitudes
        ],
    )


def _elegir_de(valores: list, etiqueta: str, texto=str):
    consola.aviso(
        f"{etiqueta}: " + ", ".join(f"{i}={texto(v)}" for i, v in enumerate(valores, 1))
    )
    elegido = consola.pedir(etiqueta).strip()
    if elegido.isdigit() and 1 <= int(elegido) <= len(valores):
        return valores[int(elegido) - 1]
    consola.error(f"{etiqueta} invalido.")
    return None


def _pedir_fecha(etiqueta: str) -> tuple[bool, datetime | None]:
    """Devuelve (valida, fecha). Enter deja la fecha en None, que para los
    reportes significa "sin limite por ese lado"."""
    texto = consola.pedir(f"{etiqueta} (Enter para no acotar)").strip()
    if not texto:
        return True, None
    try:
        return True, datetime.fromisoformat(texto)
    except ValueError:
        consola.error("Fecha invalida. Usa 2026-01-01 o 2026-01-01T08:00:00-03:00.")
        return False, None


def construir(
    servicio: SolicitudReporteService,
    clientes,
    proveedores,
    operadores,
    rol_nivel: int = NIVEL_ADMINISTRADOR,
) -> None:
    partes_por_tipo = {
        TitularTipo.CLIENTE: clientes,
        TitularTipo.PROVEEDOR: proveedores,
        TitularTipo.OPERADOR: operadores,
    }

    def _buscar(etiqueta: str = "ID de la solicitud") -> SolicitudReporte | None:
        texto = consola.pedir(etiqueta).strip().lower()
        if not texto:
            consola.error("Hace falta un ID.")
            return None
        try:
            solicitudes = servicio.listar()
        except LogisticaError as error:
            consola.error(str(error))
            return None
        encontrada = next(
            (s for s in solicitudes if texto in str(s.id).lower()), None
        )
        if encontrada is None:
            consola.error("No se encontro esa solicitud.")
        return encontrada

    def solicitar() -> None:
        consola.titulo("Solicitar un reporte")
        consola.aviso(
            "El precio queda congelado en la solicitud: si manana cambia la "
            "tarifa, se factura lo que se cotizo hoy."
        )
        tipos = list(CATALOGO)
        tipo = _elegir_de(tipos, "Reporte", lambda t: CATALOGO[t].etiqueta)
        if tipo is None:
            return
        especificacion = CATALOGO[tipo]
        consola.aviso(f"{especificacion.etiqueta}: {especificacion.precio}")

        tipo_titular = _elegir_de(list(TitularTipo), "Tipo de titular", lambda t: t.value)
        if tipo_titular is None:
            return
        try:
            partes = partes_por_tipo[tipo_titular].listar()
        except LogisticaError as error:
            consola.error(str(error))
            return
        if not partes:
            consola.error(f"No hay {tipo_titular.value.lower()}es cargados.")
            return
        parte = _elegir_de(partes, "Titular", lambda p: p.razon_social)
        if parte is None:
            return

        parametros: dict = {}
        if especificacion.acepta_rango:
            for clave, etiqueta in (("desde", "Desde"), ("hasta", "Hasta")):
                valida, fecha = _pedir_fecha(etiqueta)
                if not valida:
                    return
                if fecha is not None:
                    parametros[clave] = fecha
        if especificacion.acepta_limite:
            texto = consola.pedir("Limite (Enter para 10)").strip()
            if texto:
                try:
                    parametros["limite"] = int(texto)
                except ValueError:
                    consola.error("El limite tiene que ser un numero entero.")
                    return
        if especificacion.acepta_eje:
            eje = _elegir_de(list(EjePromedio), "Eje", lambda e: e.value)
            if eje is None:
                return
            parametros["eje"] = eje.value

        try:
            solicitud = servicio.solicitar(
                tipo, tipo_titular, parte.id, parametros
            )
        except LogisticaError as error:
            consola.error(str(error))
            return
        consola.exito(
            f"Solicitud registrada por {solicitud.costo}. Todavia no se calculo nada."
        )
        consola.aviso(f"ID: {solicitud.id}")

    def generar() -> None:
        consola.titulo("Generar un reporte solicitado")
        try:
            pendientes = servicio.listar(EstadoSolicitud.SOLICITADA)
        except LogisticaError as error:
            consola.error(str(error))
            return
        if not pendientes:
            consola.aviso("No hay solicitudes pendientes de generar.")
            return
        _mostrar(pendientes)
        solicitud = _buscar()
        if solicitud is None:
            return
        try:
            resultado = servicio.generar(solicitud.id)
        except LogisticaError as error:
            consola.error(str(error))
            return
        consola.exito(f"{resultado.solicitud.filas} fila(s) generadas.")
        if resultado.filas:
            consola.tabla(
                ["RESULTADO"], [[str(fila)] for fila in resultado.filas]
            )
        consola.aviso(
            f"Queda pendiente de facturar por {resultado.solicitud.costo}."
        )

    def facturar() -> None:
        consola.titulo("Facturar un reporte generado")
        consola.aviso(
            "La factura, el movimiento y el saldo se escriben en una sola "
            "transaccion (D41)."
        )
        try:
            pendientes = servicio.listar_pendientes_de_facturar()
        except LogisticaError as error:
            consola.error(str(error))
            return
        if not pendientes:
            consola.aviso("No hay reportes generados pendientes de facturar.")
            return
        _mostrar(pendientes)
        solicitud = _buscar()
        if solicitud is None:
            return
        try:
            factura = servicio.facturar(solicitud.id)
        except LogisticaError as error:
            consola.error(str(error))
            return
        consola.exito(
            f"Factura {factura.numero_factura} por {factura.importe_total} emitida."
        )

    def cancelar() -> None:
        consola.titulo("Cancelar una solicitud")
        consola.aviso(
            "Una solicitud ya facturada no se cancela: hay un movimiento en la "
            "cuenta corriente, y revertirlo es otro asiento (D41)."
        )
        solicitud = _buscar()
        if solicitud is None:
            return
        try:
            servicio.cancelar(solicitud.id)
        except LogisticaError as error:
            consola.error(str(error))
            return
        consola.exito("Solicitud cancelada.")

    def listar() -> None:
        consola.titulo("Solicitudes de reportes")
        try:
            _mostrar(servicio.listar())
        except LogisticaError as error:
            consola.error(str(error))

    def listar_por_titular() -> None:
        consola.titulo("Solicitudes de un titular")
        tipo_titular = _elegir_de(list(TitularTipo), "Tipo de titular", lambda t: t.value)
        if tipo_titular is None:
            return
        try:
            partes = partes_por_tipo[tipo_titular].listar()
            parte = _elegir_de(partes, "Titular", lambda p: p.razon_social)
            if parte is None:
                return
            _mostrar(servicio.listar_por_titular(parte.id))
        except LogisticaError as error:
            consola.error(str(error))

    def tarifario() -> None:
        consola.titulo("Tarifario de reportes")
        consola.aviso(
            "Un reporte analitico cuesta mas que uno operativo: agrega sobre "
            "todo el historico en vez de contar lo que hay hoy."
        )
        consola.tabla(
            ["REPORTE", "TIPO", "PRECIO", "PARAMETROS"],
            [
                [
                    e.etiqueta,
                    "analitico" if e.analitico else "operativo",
                    f"{e.precio:.2f}",
                    ", ".join(
                        p
                        for p, acepta in (
                            ("rango", e.acepta_rango),
                            ("limite", e.acepta_limite),
                            ("eje", e.acepta_eje),
                        )
                        if acepta
                    )
                    or "ninguno",
                ]
                for e in CATALOGO.values()
            ],
        )

    secciones = [
        (NIVEL_AUDITOR, "Tarifario de reportes", tarifario),
        (NIVEL_AUDITOR, "Solicitar un reporte", solicitar),
        (NIVEL_AUDITOR, "Generar un reporte solicitado", generar),
        (NIVEL_ADMINISTRADOR, "Facturar un reporte generado", facturar),
        (NIVEL_AUDITOR, "Listar solicitudes", listar),
        (NIVEL_AUDITOR, "Solicitudes de un titular", listar_por_titular),
        (NIVEL_ADMINISTRADOR, "Cancelar una solicitud", cancelar),
    ]
    consola.menu("Solicitudes de reportes", opciones_para(rol_nivel, secciones))
