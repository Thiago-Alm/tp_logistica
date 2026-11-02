"""Solicitud, generacion y facturacion de reportes parametrizados.

Es el caso de uso que ata los tres modulos del sistema:

1. la **solicitud** se guarda en MongoDB, porque sus parametros cambian segun
   el reporte (D54);
2. el **reporte** se calcula en PostgreSQL o en MongoDB, segun cual sea;
3. la **factura** se emite en PostgreSQL, dentro de la transaccion de la cuenta
   corriente (D41).

Los tres pasos son operaciones separadas a proposito: ver "Por que no es un
solo metodo" en `generar()`.
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from logistica.domain.facturacion import Factura, TitularTipo
from logistica.domain.solicitud_reporte import (
    CATALOGO,
    EstadoSolicitud,
    SolicitudReporte,
    TipoReporte,
)
from logistica.exceptions import ConflictoDeDatos, NoEncontrado, ValidacionError
from logistica.repositories.solicitud_reporte_repository import (
    SolicitudReporteRepository,
)
from logistica.repositories.unidad_de_trabajo import UnidadDeTrabajo
from logistica.services.incidente_service import EjePromedio

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReporteGenerado:
    """El resultado de generar una solicitud: la solicitud actualizada y las
    filas que produjo, para mostrarlas sin volver a consultar."""

    solicitud: SolicitudReporte
    filas: list[Any]


class SolicitudReporteService:
    def __init__(
        self,
        solicitudes: SolicitudReporteRepository,
        unidad_de_trabajo: UnidadDeTrabajo,
        reportes,
        incidentes,
        facturacion,
        envios,
    ) -> None:
        self._solicitudes = solicitudes
        self._uow = unidad_de_trabajo
        self._reportes = reportes
        self._incidentes = incidentes
        self._facturacion = facturacion
        self._envios = envios

    # -- Solicitar ------------------------------------------------------------

    def solicitar(
        self,
        tipo: TipoReporte,
        usuario_id: UUID,
        titular_tipo: TitularTipo,
        titular_id: UUID,
        parametros: dict[str, Any] | None = None,
    ) -> SolicitudReporte:
        """Registra el pedido y le pone precio. Todavia no calcula nada.

        El precio queda **congelado en la solicitud**, como el contexto de un
        incidente (D12): si manana cambia la tarifa, lo que se factura es lo
        que se cotizo cuando el titular lo pidio.
        """
        especificacion = CATALOGO[tipo]
        solicitud = SolicitudReporte(
            id=uuid4(),
            tipo=tipo,
            usuario_id=usuario_id,
            titular_tipo=titular_tipo,
            titular_id=titular_id,
            fecha_solicitud=datetime.now(timezone.utc),
            costo=especificacion.precio,
            parametros=parametros or {},
        )
        self._verificar(usuario_id, titular_tipo, titular_id)
        self._solicitudes.guardar(solicitud)
        log.info(
            "Reporte %s solicitado por %s %s (%s)",
            tipo.value, titular_tipo.value, titular_id, solicitud.costo,
        )
        return solicitud

    def _verificar(
        self, usuario_id: UUID, titular_tipo: TitularTipo, titular_id: UUID
    ) -> None:
        """El usuario y el titular viven en PostgreSQL y la solicitud en
        MongoDB: no hay clave foranea que lo garantice, asi que lo valida el
        servicio (D3, D41)."""
        with self._uow as uow:
            if uow.usuarios.obtener(usuario_id) is None:
                raise NoEncontrado(f"No existe el usuario {usuario_id}")
            repositorio = {
                TitularTipo.CLIENTE: uow.clientes,
                TitularTipo.PROVEEDOR: uow.proveedores,
                TitularTipo.OPERADOR: uow.operadores,
            }[titular_tipo]
            if repositorio.obtener(titular_id) is None:
                raise NoEncontrado(
                    f"No existe el {titular_tipo.value.lower()} {titular_id}"
                )

    # -- Generar --------------------------------------------------------------

    def generar(self, solicitud_id: UUID) -> ReporteGenerado:
        """Calcula el reporte y guarda cuantas filas dio.

        **Por que no es un solo metodo con `solicitar`:** porque son dos cosas
        que pueden fallar por separado y en momentos distintos. El pedido queda
        registrado aunque el calculo falle -y se puede reintentar-, y queda la
        traza de que se pidio aunque despues se cancele. Juntarlos haria que un
        error de PostgreSQL borrara el pedido del titular.
        """
        solicitud = self._obtener(solicitud_id)
        if solicitud.estado is not EstadoSolicitud.SOLICITADA:
            raise ConflictoDeDatos(
                f"La solicitud esta {solicitud.estado.value}: solo se genera una "
                "SOLICITADA"
            )

        filas = self._calcular(solicitud)
        solicitud.marcar_generada(len(filas), datetime.now(timezone.utc))
        self._solicitudes.actualizar(solicitud)
        log.info(
            "Reporte %s generado: %s fila(s)", solicitud.tipo.value, solicitud.filas
        )
        return ReporteGenerado(solicitud=solicitud, filas=filas)

    def _calcular(self, solicitud: SolicitudReporte) -> list[Any]:
        """Despacha al servicio que sabe calcular cada reporte.

        Este servicio no consulta las bases por su cuenta: reusa los servicios
        que ya tienen cada reporte resuelto y cacheado (D44). Lo suyo es el
        ciclo de vida del pedido, no la consulta.
        """
        p = solicitud.parametros
        desde, hasta = p.get("desde"), p.get("hasta")
        tipo = solicitud.tipo

        if tipo is TipoReporte.ENVIOS_POR_PAIS:
            return list(self._reportes.envios_por_pais(desde, hasta))
        if tipo is TipoReporte.ENVIOS_POR_ESTADO:
            return list(self._reportes.envios_por_estado(desde, hasta))
        if tipo is TipoReporte.ENVIOS_POR_CLIENTE:
            return list(self._reportes.envios_por_cliente(desde, hasta))
        if tipo is TipoReporte.ENVIOS_DEMORADOS:
            return list(self._envios.listar_demorados())
        if tipo is TipoReporte.INCIDENTES_ABIERTOS:
            return list(self._incidentes.listar_abiertos())
        if tipo is TipoReporte.TIEMPOS_POR_CLIENTE:
            return list(self._reportes.tiempos_de_envio_por_cliente(desde, hasta))
        if tipo is TipoReporte.TIEMPO_PROMEDIO_ENTREGA:
            promedio = self._reportes.tiempo_promedio_de_entrega(desde, hasta)
            # Devuelve un solo valor, no una lista: se envuelve para que
            # "cuantas filas dio" signifique lo mismo en todos los reportes.
            return [] if promedio is None else [promedio]
        if tipo is TipoReporte.RANKING_CLIENTES_VOLUMEN:
            return list(
                self._reportes.ranking_clientes_por_volumen(
                    p.get("limite", 10), desde, hasta
                )
            )
        if tipo is TipoReporte.COSTOS_POR_TRANSPORTE:
            return list(self._reportes.costos_por_tipo_de_transporte().items())
        if tipo is TipoReporte.RANKING_RUTAS_INCIDENTES:
            return list(self._incidentes.ranking_de_rutas(p.get("limite", 10)))
        if tipo is TipoReporte.PROMEDIO_INCIDENTES:
            eje = EjePromedio(p.get("eje", EjePromedio.PAIS.value))
            return list(self._incidentes.promedio_por(eje))

        raise ValidacionError(f"No se sabe calcular el reporte {tipo.value}")

    # -- Facturar -------------------------------------------------------------

    def facturar(self, solicitud_id: UUID) -> Factura:
        """Emite la factura del reporte y la imputa a la cuenta corriente.

        La factura la emite `FacturacionService`, que mete las tres escrituras
        -factura, movimiento y saldo- en una sola transaccion (D41). Este
        servicio solo agrega el cuarto paso: marcar la solicitud como facturada
        en MongoDB.

        **Ese cuarto paso queda afuera de la transaccion**, porque MongoDB y
        PostgreSQL no comparten una. Si fallara, quedaria una factura emitida y
        una solicitud en GENERADA: por eso `listar_pendientes_de_facturar()`
        existe y el menu la ofrece, para encontrar justo ese caso.
        """
        solicitud = self._obtener(solicitud_id)
        if not solicitud.esta_pendiente_de_facturar():
            raise ConflictoDeDatos(
                f"La solicitud esta {solicitud.estado.value}: solo se factura una "
                "GENERADA"
            )

        factura = self._facturacion.emitir(
            solicitud.titular_tipo,
            solicitud.titular_id,
            solicitud.costo,
            f"Reporte: {solicitud.especificacion.etiqueta}",
        )
        solicitud.marcar_facturada(factura.id)
        self._solicitudes.actualizar(solicitud)
        log.info(
            "Reporte %s facturado: %s", solicitud.tipo.value, factura.numero_factura
        )
        return factura

    def cancelar(self, solicitud_id: UUID) -> SolicitudReporte:
        """Una solicitud facturada no se cancela: ya hay un movimiento en la
        cuenta corriente, y revertirlo es otro asiento (D41)."""
        solicitud = self._obtener(solicitud_id)
        solicitud.pasar_a(EstadoSolicitud.CANCELADA)
        self._solicitudes.actualizar(solicitud)
        return solicitud

    # -- Consultas ------------------------------------------------------------

    def listar(self, estado: EstadoSolicitud | None = None) -> list[SolicitudReporte]:
        return self._solicitudes.listar(estado)

    def listar_pendientes_de_facturar(self) -> list[SolicitudReporte]:
        return self._solicitudes.listar(EstadoSolicitud.GENERADA)

    def listar_por_titular(self, titular_id: UUID) -> list[SolicitudReporte]:
        return self._solicitudes.listar_por_titular(titular_id)

    def _obtener(self, solicitud_id: UUID) -> SolicitudReporte:
        solicitud = self._solicitudes.obtener(solicitud_id)
        if solicitud is None:
            raise NoEncontrado(f"No existe la solicitud {solicitud_id}")
        return solicitud
