"""Casos de uso de facturacion, pagos y cuentas corrientes.

Requisitos que cubre: "facturacion automatica", "registro de pagos", "gestion
de cuentas corrientes" y el proceso periodico de "cierre mensual de cuentas
corrientes".

Es la parte del sistema donde la Unidad de Trabajo deja de ser una formalidad:
emitir una factura son TRES escrituras que tienen que ocurrir todas o ninguna
(la factura, el movimiento de cuenta y el saldo). Si quedara a medias, el
estado de cuenta de un titular dejaria de cuadrar y no habria forma de saber
cual es el valor correcto (D41).
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from logistica.domain.envio import EstadoEnvio
from logistica.domain.evento_outbox import TipoAgregado
from logistica.domain.facturacion import (
    CERO,
    CuentaCorriente,
    DetalleFactura,
    EstadoFactura,
    Factura,
    MedioPago,
    MovimientoCuenta,
    Pago,
    TipoMovimiento,
    TitularTipo,
)
from logistica.exceptions import ConflictoDeDatos, NoEncontrado, ValidacionError
from logistica.repositories.unidad_de_trabajo import UnidadDeTrabajo

DIAS_DE_VENCIMIENTO = 15

# Para verificar que exista un titular que no es cliente. Se usa el
# repositorio de consistencia porque operadores y proveedores no tienen
# repositorio propio: nadie los administra desde la aplicacion todavia.
_AGREGADO = {
    TitularTipo.PROVEEDOR: TipoAgregado.PROVEEDOR,
    TitularTipo.OPERADOR: TipoAgregado.OPERADOR,
}

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class LineaDeFactura:
    """Una factura con lo que ya se cobro de ella."""

    factura: Factura
    pagado: Decimal

    @property
    def pendiente(self) -> Decimal:
        """Lo que falta cobrar. Una factura anulada no deja nada pendiente:
        dejo de existir como deuda, aunque la fila se conserve (D26)."""
        if self.factura.estado is EstadoFactura.ANULADA:
            return CERO
        return self.factura.importe_total - self.pagado


@dataclass(frozen=True)
class ResumenDeFacturas:
    """Las facturas de un titular, cada una con su detalle, mas los totales.

    Los totales se calculan aca y no en el menu: sumar plata es una decision
    (que entra y que no), no una tarea de presentacion. Las anuladas quedan
    listadas -son parte del historial- pero no suman.
    """

    lineas: list[LineaDeFactura]

    @property
    def total_facturado(self) -> Decimal:
        return sum(
            (
                x.factura.importe_total
                for x in self.lineas
                if x.factura.estado is not EstadoFactura.ANULADA
            ),
            CERO,
        )

    @property
    def total_cobrado(self) -> Decimal:
        return sum((x.pagado for x in self.lineas), CERO)

    @property
    def total_pendiente(self) -> Decimal:
        return sum((x.pendiente for x in self.lineas), CERO)

    @property
    def total_anulado(self) -> Decimal:
        return sum(
            (
                x.factura.importe_total
                for x in self.lineas
                if x.factura.estado is EstadoFactura.ANULADA
            ),
            CERO,
        )


@dataclass(frozen=True)
class EstadoDeCuenta:
    """Resultado compuesto: la cuenta con sus movimientos y su deuda."""

    cuenta: CuentaCorriente
    movimientos: list[MovimientoCuenta]
    facturas_pendientes: list[Factura]

    @property
    def saldo_coincide(self) -> bool:
        """Si el saldo guardado coincide con la suma de los movimientos."""
        suma = sum((m.monto * m.tipo.signo() for m in self.movimientos), CERO)
        return suma == self.cuenta.saldo


@dataclass(frozen=True)
class ResultadoDeCierre:
    """Que paso en el cierre mensual."""

    cuentas_revisadas: int = 0
    facturas_vencidas: int = 0
    cuentas_con_deuda: int = 0
    deuda_total: Decimal = CERO

    def __str__(self) -> str:
        return (
            f"cuentas={self.cuentas_revisadas} vencidas={self.facturas_vencidas} "
            f"con_deuda={self.cuentas_con_deuda} deuda_total={self.deuda_total}"
        )


class FacturacionService:
    def __init__(self, unidad_de_trabajo: UnidadDeTrabajo) -> None:
        self._uow = unidad_de_trabajo

    # --- Cuentas corrientes ----------------------------------------------

    def abrir_cuenta(
        self,
        titular_tipo: TitularTipo,
        titular_id: UUID,
        limite_credito: Decimal = CERO,
    ) -> CuentaCorriente:
        with self._uow as uow:
            self._verificar_titular(uow, titular_tipo, titular_id)
            if uow.cuentas.obtener_por_titular(titular_tipo, titular_id) is not None:
                raise ConflictoDeDatos(
                    f"El titular {titular_tipo.value} {titular_id} ya tiene cuenta"
                )
            cuenta = CuentaCorriente(
                id=uuid4(),
                titular_tipo=titular_tipo,
                titular_id=titular_id,
                limite_credito=limite_credito,
            )
            uow.cuentas.guardar(cuenta)
            uow.commit()
        log.info("Cuenta abierta para %s %s", titular_tipo.value, titular_id)
        return cuenta

    def cambiar_limite(
        self,
        titular_tipo: TitularTipo,
        titular_id: UUID,
        nuevo_limite: Decimal,
    ) -> CuentaCorriente:
        """Cambia el tope de credito de una cuenta por cobrar.

        No se puede bajar por debajo de lo que el titular ya debe: el limite
        acota cuanto puede deber, y dejarlo con una deuda mayor que su tope
        seria aceptar un estado que la emision nunca habria permitido. Para eso
        esta el cobro, no el limite.

        Una cuenta por pagar no lleva tope (D62), asi que cambiarselo no
        significa nada y se rechaza en vez de guardar un numero que nadie mira.
        """
        if nuevo_limite < CERO:
            raise ValidacionError(
                f"El limite de credito no puede ser negativo: {nuevo_limite}"
            )
        with self._uow as uow:
            cuenta = uow.cuentas.obtener_por_titular(titular_tipo, titular_id)
            if cuenta is None:
                raise NoEncontrado(
                    f"El titular {titular_tipo.value} {titular_id} no tiene cuenta"
                )
            if not cuenta.tiene_limite():
                raise ConflictoDeDatos(
                    f"Una cuenta de {titular_tipo.value} es por pagar y no lleva "
                    f"limite de credito (D62)"
                )
            if nuevo_limite < cuenta.deuda:
                raise ConflictoDeDatos(
                    f"El titular debe {cuenta.deuda}: el limite no puede quedar "
                    f"por debajo. Registra el cobro primero"
                )
            anterior = cuenta.limite_credito
            cuenta.limite_credito = nuevo_limite
            cuenta.validar()
            uow.cuentas.actualizar(cuenta)
            uow.commit()
        log.info(
            "Limite de %s %s: %s -> %s",
            titular_tipo.value, titular_id, anterior, nuevo_limite,
        )
        return cuenta

    def estado_de_cuenta(
        self,
        titular_tipo: TitularTipo,
        titular_id: UUID,
        desde: datetime | None = None,
        hasta: datetime | None = None,
    ) -> EstadoDeCuenta:
        with self._uow as uow:
            cuenta = uow.cuentas.obtener_por_titular(titular_tipo, titular_id)
            if cuenta is None:
                raise NoEncontrado(
                    f"El titular {titular_tipo.value} {titular_id} no tiene cuenta"
                )
            movimientos = uow.movimientos.listar_por_cuenta(cuenta.id, desde, hasta)
            pendientes = [
                f
                for f in uow.facturas.listar_por_titular(titular_tipo, titular_id)
                if f.esta_pendiente()
            ]
        return EstadoDeCuenta(cuenta, movimientos, pendientes)

    # --- Facturacion ------------------------------------------------------

    def emitir(
        self,
        titular_tipo: TitularTipo,
        titular_id: UUID,
        importe: Decimal,
        descripcion: str,
        envio_id: UUID | None = None,
        momento: datetime | None = None,
        detalles: list[tuple[str, Decimal]] | None = None,
    ) -> Factura:
        """Emite una factura y la imputa a la cuenta corriente del titular.

        `detalles` son las lineas de la factura, como (descripcion, importe).
        **El total sale de sumarlas**: si se pasan, `importe` se ignora. Si no
        se pasan, la factura queda con una sola linea hecha de `importe` y
        `descripcion`, para que **ninguna factura exista sin detalle** (D69).

        Las cuatro escrituras van en la misma transaccion. Si el commit falla,
        no queda ni la factura, ni sus detalles, ni el movimiento, ni el saldo
        cambiado.
        """
        lineas = detalles if detalles else [(descripcion, importe)]
        for texto, monto in lineas:
            if monto <= CERO:
                raise ValidacionError(
                    f"El importe de '{texto}' debe ser positivo: {monto}"
                )
        importe = sum((monto for _, monto in lineas), CERO)
        if importe <= CERO:
            raise ValidacionError(f"El importe a facturar debe ser positivo: {importe}")
        momento = momento or datetime.now(timezone.utc)

        with self._uow as uow:
            self._verificar_titular(uow, titular_tipo, titular_id)
            cuenta = uow.cuentas.obtener_por_titular(titular_tipo, titular_id)
            if cuenta is None:
                raise NoEncontrado(
                    f"El titular {titular_tipo.value} {titular_id} no tiene cuenta "
                    f"corriente: hay que abrirla antes de facturarle"
                )
            if cuenta.supera_el_limite(importe):
                raise ConflictoDeDatos(
                    f"Facturar {importe} deja al titular en {cuenta.deuda + importe}, "
                    f"por encima de su limite de credito de {cuenta.limite_credito}"
                )

            factura = Factura(
                id=uuid4(),
                titular_tipo=titular_tipo,
                titular_id=titular_id,
                envio_id=envio_id,
                numero_factura=uow.facturas.proximo_numero(),
                fecha_emision=momento,
                fecha_vencimiento=momento + timedelta(days=DIAS_DE_VENCIMIENTO),
                importe_total=importe,
            )
            movimiento = MovimientoCuenta(
                id=uuid4(),
                cuenta_corriente_id=cuenta.id,
                factura_id=factura.id,
                tipo=TipoMovimiento.DEBITO,
                monto=importe,
                descripcion=f"Emision {factura.numero_factura}: {descripcion}",
                fecha=momento,
            )
            cuenta.aplicar(movimiento)

            uow.facturas.guardar(factura)
            uow.facturas.guardar_detalles(
                [
                    DetalleFactura(
                        id=uuid4(),
                        factura_id=factura.id,
                        orden=i,
                        descripcion=texto,
                        importe=monto,
                    )
                    for i, (texto, monto) in enumerate(lineas, 1)
                ]
            )
            uow.movimientos.guardar(movimiento)
            uow.cuentas.actualizar(cuenta)
            uow.commit()

        log.info(
            "Factura %s emitida a %s por %s",
            factura.numero_factura, titular_id, importe,
        )
        return factura

    def facturar_envio(
        self, envio_id: UUID, momento: datetime | None = None
    ) -> Factura | None:
        """Factura un envio entregado, sumando el costo de sus tramos.

        Devuelve None si el envio ya estaba facturado: esa es la condicion que
        hace idempotente a la facturacion automatica, y por eso se consulta
        antes de calcular nada.
        """
        with self._uow as uow:
            envio = uow.envios.obtener(envio_id)
            if envio is None:
                raise NoEncontrado(f"No existe el envio {envio_id}")
            if envio.estado is not EstadoEnvio.ENTREGADO:
                raise ValidacionError(
                    f"Solo se factura un envio ENTREGADO "
                    f"(el {envio_id} esta en {envio.estado.value})"
                )
            if uow.facturas.obtener_por_envio(envio_id) is not None:
                log.debug("El envio %s ya tenia factura", envio_id)
                return None
            tramos = uow.tramos.listar_por_envio(envio_id)
            cliente_id = envio.cliente_id

        if not tramos:
            raise ValidacionError(
                f"El envio {envio_id} no tiene tramos: no hay nada que facturar"
            )
        # Un detalle por tramo: es exactamente lo que compone el importe, y asi
        # la factura explica sola de donde sale su total (D69).
        return self.emitir(
            TitularTipo.CLIENTE,
            cliente_id,
            CERO,  # lo define la suma de los detalles
            f"Envio {envio_id} ({len(tramos)} tramos)",
            envio_id=envio_id,
            momento=momento,
            detalles=[
                (f"Tramo {t.orden} ({t.medio_transporte.value})", t.costo)
                for t in sorted(tramos, key=lambda x: x.orden)
            ],
        )

    def anular(self, factura_id: UUID, motivo: str) -> Factura:
        """Anula una factura y revierte su imputacion con un movimiento en
        sentido contrario.

        No se borra el movimiento original: el libro mayor solo se agrega, y
        corregir un error es otro asiento, no una edicion.
        """
        momento = datetime.now(timezone.utc)
        with self._uow as uow:
            factura = self._obtener_factura(uow, factura_id)
            factura.pasar_a(EstadoFactura.ANULADA)
            cuenta = self._cuenta_de(uow, factura)

            reverso = MovimientoCuenta(
                id=uuid4(),
                cuenta_corriente_id=cuenta.id,
                factura_id=factura.id,
                tipo=TipoMovimiento.CREDITO,
                monto=factura.importe_total,
                descripcion=f"Anulacion {factura.numero_factura}: {motivo}",
                fecha=momento,
            )
            cuenta.aplicar(reverso)

            uow.facturas.actualizar(factura)
            uow.movimientos.guardar(reverso)
            uow.cuentas.actualizar(cuenta)
            uow.commit()
        log.info("Factura %s anulada: %s", factura.numero_factura, motivo)
        return factura

    # --- Pagos ------------------------------------------------------------

    def registrar_pago(
        self,
        factura_id: UUID,
        monto: Decimal,
        medio_pago: MedioPago,
        referencia: str | None = None,
        momento: datetime | None = None,
    ) -> Pago:
        """Registra un pago e imputa el credito a la cuenta.

        Admite pagos parciales: la factura pasa a PAGADA solo cuando la suma de
        los pagos alcanza el importe total.
        """
        momento = momento or datetime.now(timezone.utc)
        with self._uow as uow:
            factura = self._obtener_factura(uow, factura_id)
            if not factura.esta_pendiente():
                raise ValidacionError(
                    f"La factura {factura.numero_factura} esta {factura.estado.value}: "
                    f"no admite pagos"
                )
            pagado = uow.pagos.total_pagado(factura_id)
            pendiente = factura.importe_total - pagado
            if monto > pendiente:
                raise ValidacionError(
                    f"El pago de {monto} supera lo que resta de la factura "
                    f"{factura.numero_factura}: {pendiente}"
                )

            cuenta = self._cuenta_de(uow, factura)
            pago = Pago(
                id=uuid4(),
                factura_id=factura_id,
                monto=monto,
                medio_pago=medio_pago,
                fecha_pago=momento,
                referencia_transaccion=referencia,
            )
            movimiento = MovimientoCuenta(
                id=uuid4(),
                cuenta_corriente_id=cuenta.id,
                pago_id=pago.id,
                factura_id=factura_id,
                tipo=TipoMovimiento.CREDITO,
                monto=monto,
                descripcion=f"Cobro {factura.numero_factura} ({medio_pago.value})",
                fecha=momento,
            )
            cuenta.aplicar(movimiento)

            uow.pagos.guardar(pago)
            uow.movimientos.guardar(movimiento)
            uow.cuentas.actualizar(cuenta)
            if pagado + monto >= factura.importe_total:
                factura.pasar_a(EstadoFactura.PAGADA)
                uow.facturas.actualizar(factura)
            uow.commit()

        log.info("Pago de %s registrado en %s", monto, factura.numero_factura)
        return pago

    # --- Procesos periodicos ----------------------------------------------

    def facturar_entregados(self, momento: datetime | None = None) -> list[Factura]:
        """Proceso periodico: factura todos los envios entregados sin factura.

        Es idempotente porque `facturar_envio` devuelve None si el envio ya
        tenia una: correrlo dos veces el mismo dia no duplica nada. Aun asi el
        planificador lo ejecuta bajo un lock de Redis (D14), porque dos
        instancias simultaneas podrian leer antes de que la otra escriba.
        """
        with self._uow as uow:
            entregados = [e.id for e in uow.envios.listar_por_estado(EstadoEnvio.ENTREGADO)]

        emitidas: list[Factura] = []
        for envio_id in entregados:
            try:
                factura = self.facturar_envio(envio_id, momento)
            except (ValidacionError, ConflictoDeDatos) as error:
                # Un envio que no se puede facturar no frena a los demas.
                log.warning("No se facturo el envio %s: %s", envio_id, error)
                continue
            if factura is not None:
                emitidas.append(factura)

        if emitidas:
            log.info("Facturacion automatica: %s facturas emitidas", len(emitidas))
        return emitidas

    def cerrar_mes(self, momento: datetime | None = None) -> ResultadoDeCierre:
        """Proceso periodico: marca las facturas vencidas y resume las cuentas.

        No "cierra" el saldo poniendolo en cero: el saldo es continuo y la
        deuda no desaparece a fin de mes. Lo que hace el cierre es reconocer
        las facturas cuyo vencimiento paso y dejar el resumen del periodo.
        """
        momento = momento or datetime.now(timezone.utc)
        with self._uow as uow:
            vencidas = uow.facturas.listar_vencidas(momento)
            for factura in vencidas:
                factura.pasar_a(EstadoFactura.VENCIDA)
                uow.facturas.actualizar(factura)

            cuentas = uow.cuentas.listar()
            con_deuda = [c for c in cuentas if c.deuda > CERO]
            uow.commit()

        resultado = ResultadoDeCierre(
            cuentas_revisadas=len(cuentas),
            facturas_vencidas=len(vencidas),
            cuentas_con_deuda=len(con_deuda),
            deuda_total=sum((c.deuda for c in con_deuda), CERO),
        )
        log.info("Cierre mensual: %s", resultado)
        return resultado

    # --- Consultas --------------------------------------------------------

    def obtener_factura(self, factura_id: UUID) -> Factura:
        with self._uow as uow:
            return self._obtener_factura(uow, factura_id)

    def listar_facturas(
        self, titular_tipo: TitularTipo, titular_id: UUID
    ) -> list[Factura]:
        with self._uow as uow:
            return uow.facturas.listar_por_titular(titular_tipo, titular_id)

    def detalles_de(self, factura_id: UUID) -> list[DetalleFactura]:
        """Las lineas que componen el total de una factura."""
        with self._uow as uow:
            if uow.facturas.obtener(factura_id) is None:
                raise NoEncontrado(f"No existe la factura {factura_id}")
            return uow.facturas.listar_detalles(factura_id)

    def resumen_de_facturas(
        self, titular_tipo: TitularTipo, titular_id: UUID
    ) -> ResumenDeFacturas:
        """Las facturas del titular, cada una con lo cobrado, y los totales.

        Se resuelve en una sola transaccion: las facturas y los pagos de cada
        una se leen juntos, para que el total no pueda quedar calculado sobre
        una foto a medias.
        """
        with self._uow as uow:
            facturas = uow.facturas.listar_por_titular(titular_tipo, titular_id)
            lineas = [
                LineaDeFactura(
                    factura=f, pagado=Decimal(uow.pagos.total_pagado(f.id))
                )
                for f in facturas
            ]
        return ResumenDeFacturas(lineas)

    def listar_cuentas(self) -> list[CuentaCorriente]:
        with self._uow as uow:
            return uow.cuentas.listar()

    def verificar_saldos(self) -> list[tuple[CuentaCorriente, Decimal]]:
        """Control de integridad: compara cada saldo guardado con la suma de sus
        movimientos. Devuelve solo las cuentas que no cuadran (D41)."""
        diferencias: list[tuple[CuentaCorriente, Decimal]] = []
        with self._uow as uow:
            for cuenta in uow.cuentas.listar():
                calculado = uow.movimientos.saldo_calculado(cuenta.id)
                if calculado != cuenta.saldo:
                    diferencias.append((cuenta, calculado))
        if diferencias:
            log.error("Hay %s cuentas con el saldo descuadrado", len(diferencias))
        return diferencias

    # --- Ayudas internas --------------------------------------------------

    @staticmethod
    def _obtener_factura(uow: UnidadDeTrabajo, factura_id: UUID) -> Factura:
        factura = uow.facturas.obtener(factura_id)
        if factura is None:
            raise NoEncontrado(f"No existe la factura {factura_id}")
        return factura

    @staticmethod
    def _cuenta_de(uow: UnidadDeTrabajo, factura: Factura) -> CuentaCorriente:
        cuenta = uow.cuentas.obtener_por_titular(
            factura.titular_tipo, factura.titular_id
        )
        if cuenta is None:
            raise NoEncontrado(
                f"La factura {factura.numero_factura} apunta a un titular sin cuenta"
            )
        return cuenta

    @staticmethod
    def _verificar_titular(
        uow: UnidadDeTrabajo, titular_tipo: TitularTipo, titular_id: UUID
    ) -> None:
        """titular_id es una referencia polimorfica y no admite clave foranea:
        que el titular exista lo valida el servicio (supuesto 4, D3)."""
        if titular_tipo is TitularTipo.CLIENTE:
            existe = uow.clientes.obtener(titular_id) is not None
        else:
            existe = titular_id in uow.consistencia.ids_de(_AGREGADO[titular_tipo])
        if not existe:
            raise ValidacionError(
                f"No existe el {titular_tipo.value.lower()} {titular_id}"
            )
