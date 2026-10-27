"""Tests de facturacion contra PostgreSQL real.

Lo que se verifica es la propiedad central: emitir una factura son tres
escrituras atomicas (factura, movimiento y saldo). Si una fallara, el estado de
cuenta dejaria de cuadrar.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import psycopg
import pytest

from logistica.container import Contenedor
from logistica.domain.envio import EstadoEnvio, PrioridadEnvio
from logistica.domain.facturacion import EstadoFactura, MedioPago, TitularTipo
from logistica.domain.tramo import MedioTransporte
from logistica.exceptions import (
    ConflictoDeDatos,
    ErrorDePersistencia,
    NoEncontrado,
    ValidacionError,
)
from logistica.infrastructure.postgres.conexion import armar_dsn

CLIENTE = UUID("20000000-0000-0000-0000-000000000001")
PROVEEDOR = UUID("40000000-0000-0000-0000-000000000002")
ORIGEN = UUID("50000000-0000-0000-0000-000000000001")
DESTINO = UUID("50000000-0000-0000-0000-000000000004")
VEHICULO = UUID("60000000-0000-0000-0000-000000000001")


@pytest.fixture(scope="module")
def contenedor():
    c = Contenedor(configurar_logging=False)
    try:
        c.facturacion.listar_cuentas()
    except ErrorDePersistencia:
        pytest.skip("PostgreSQL no disponible: docker compose up -d")
    return c


def _limpiar(contenedor, facturas=(), envios=(), cuentas=()):
    with psycopg.connect(armar_dsn(contenedor.settings), autocommit=True) as cx:
        for fid in facturas:
            cx.execute("delete from movimiento_cuenta where factura_id = %s", (fid,))
            cx.execute("delete from pago where factura_id = %s", (fid,))
            cx.execute("delete from factura where id = %s", (fid,))
        for eid in envios:
            cx.execute(
                "delete from movimiento_cuenta where factura_id in "
                "(select id from factura where envio_id = %s)", (eid,))
            cx.execute("delete from factura where envio_id = %s", (eid,))
            cx.execute(
                "delete from outbox where agregado_id = %s or agregado_id in "
                "(select id from tramo where envio_id = %s)", (eid, eid))
            cx.execute("delete from envio where id = %s", (eid,))
        for cid in cuentas:
            cx.execute("delete from movimiento_cuenta where cuenta_corriente_id = %s", (cid,))
            cx.execute("delete from cuenta_corriente where id = %s", (cid,))


@pytest.fixture
def cuenta_temporal(contenedor):
    """Un proveedor con cuenta propia, para no ensuciar los datos semilla."""
    cuenta = contenedor.facturacion.abrir_cuenta(
        TitularTipo.PROVEEDOR, PROVEEDOR, Decimal("20000")
    )
    yield cuenta
    _limpiar(contenedor, cuentas=[cuenta.id])


# --- La propiedad central ---------------------------------------------------


def test_emitir_mueve_factura_movimiento_y_saldo_juntos(contenedor, cuenta_temporal):
    servicio = contenedor.facturacion
    factura = servicio.emitir(
        TitularTipo.PROVEEDOR, PROVEEDOR, Decimal("1500.50"), "Servicios"
    )
    estado = servicio.estado_de_cuenta(TitularTipo.PROVEEDOR, PROVEEDOR)

    assert estado.cuenta.saldo == Decimal("-1500.50")
    assert len(estado.movimientos) == 1
    assert estado.movimientos[0].factura_id == factura.id
    assert estado.saldo_coincide


def test_si_la_emision_falla_no_queda_nada(contenedor, cuenta_temporal):
    """Facturar por encima del limite corta antes del commit: no debe quedar ni
    la factura, ni el movimiento, ni el saldo cambiado."""
    servicio = contenedor.facturacion
    antes = servicio.estado_de_cuenta(TitularTipo.PROVEEDOR, PROVEEDOR)

    with pytest.raises(ConflictoDeDatos):
        servicio.emitir(TitularTipo.PROVEEDOR, PROVEEDOR, Decimal("999999"), "Exceso")

    despues = servicio.estado_de_cuenta(TitularTipo.PROVEEDOR, PROVEEDOR)
    assert despues.cuenta.saldo == antes.cuenta.saldo
    assert len(despues.movimientos) == len(antes.movimientos)


def test_los_saldos_semilla_cuadran(contenedor):
    """Control de integridad sobre los datos de prueba."""
    assert contenedor.facturacion.verificar_saldos() == []


# --- Pagos -------------------------------------------------------------------


def test_un_pago_parcial_no_cierra_la_factura(contenedor, cuenta_temporal):
    servicio = contenedor.facturacion
    factura = servicio.emitir(TitularTipo.PROVEEDOR, PROVEEDOR, Decimal("1000"), "x")
    servicio.registrar_pago(factura.id, Decimal("400"), MedioPago.TRANSFERENCIA)

    assert servicio.obtener_factura(factura.id).estado is EstadoFactura.EMITIDA
    estado = servicio.estado_de_cuenta(TitularTipo.PROVEEDOR, PROVEEDOR)
    assert estado.cuenta.saldo == Decimal("-600")


def test_el_pago_total_cierra_la_factura(contenedor, cuenta_temporal):
    servicio = contenedor.facturacion
    factura = servicio.emitir(TitularTipo.PROVEEDOR, PROVEEDOR, Decimal("1000"), "x")
    servicio.registrar_pago(factura.id, Decimal("600"), MedioPago.EFECTIVO)
    servicio.registrar_pago(factura.id, Decimal("400"), MedioPago.EFECTIVO)

    assert servicio.obtener_factura(factura.id).estado is EstadoFactura.PAGADA
    estado = servicio.estado_de_cuenta(TitularTipo.PROVEEDOR, PROVEEDOR)
    assert estado.cuenta.saldo == Decimal("0")
    assert estado.saldo_coincide


def test_no_se_puede_pagar_de_mas(contenedor, cuenta_temporal):
    servicio = contenedor.facturacion
    factura = servicio.emitir(TitularTipo.PROVEEDOR, PROVEEDOR, Decimal("500"), "x")
    with pytest.raises(ValidacionError):
        servicio.registrar_pago(factura.id, Decimal("500.01"), MedioPago.EFECTIVO)


def test_no_se_puede_pagar_una_factura_anulada(contenedor, cuenta_temporal):
    servicio = contenedor.facturacion
    factura = servicio.emitir(TitularTipo.PROVEEDOR, PROVEEDOR, Decimal("500"), "x")
    servicio.anular(factura.id, "error de carga")
    with pytest.raises(ValidacionError):
        servicio.registrar_pago(factura.id, Decimal("100"), MedioPago.EFECTIVO)


# --- Anulacion ---------------------------------------------------------------


def test_anular_agrega_un_asiento_en_vez_de_borrar(contenedor, cuenta_temporal):
    """El libro mayor solo se agrega: corregir es otro asiento, no una edicion."""
    servicio = contenedor.facturacion
    factura = servicio.emitir(TitularTipo.PROVEEDOR, PROVEEDOR, Decimal("800"), "x")
    antes = servicio.estado_de_cuenta(TitularTipo.PROVEEDOR, PROVEEDOR)

    servicio.anular(factura.id, "duplicada")
    despues = servicio.estado_de_cuenta(TitularTipo.PROVEEDOR, PROVEEDOR)

    assert len(despues.movimientos) == len(antes.movimientos) + 1
    assert despues.cuenta.saldo == Decimal("0")
    assert despues.saldo_coincide
    assert servicio.obtener_factura(factura.id).estado is EstadoFactura.ANULADA


# --- Facturacion de envios ---------------------------------------------------


@pytest.fixture
def envio_entregado(contenedor):
    envio = contenedor.envios.registrar(CLIENTE, ORIGEN, DESTINO, PrioridadEnvio.MEDIA)
    salida = datetime.now(timezone.utc)
    contenedor.envios.agregar_tramo(
        envio.id, VEHICULO, MedioTransporte.MARITIMO, ORIGEN, DESTINO,
        salida, salida + timedelta(days=5), Decimal("1200.25"),
    )
    contenedor.envios.agregar_tramo(
        envio.id, VEHICULO, MedioTransporte.MARITIMO, DESTINO, ORIGEN,
        salida, salida + timedelta(days=9), Decimal("800.50"),
    )
    contenedor.envios.cambiar_estado(envio.id, EstadoEnvio.EN_TRANSITO)
    contenedor.envios.entregar(envio.id)
    yield envio
    _limpiar(contenedor, envios=[envio.id])
    # Devolver el saldo del cliente a como estaba.
    with psycopg.connect(armar_dsn(contenedor.settings), autocommit=True) as cx:
        cx.execute(
            """update cuenta_corriente c
               set saldo = coalesce((
                   select sum(case when m.tipo = 'CREDITO' then m.monto else -m.monto end)
                   from movimiento_cuenta m where m.cuenta_corriente_id = c.id), 0)
               where c.titular_id = %s""",
            (CLIENTE,),
        )


def test_facturar_un_envio_suma_sus_tramos(contenedor, envio_entregado):
    factura = contenedor.facturacion.facturar_envio(envio_entregado.id)
    assert factura.importe_total == Decimal("2000.75")
    assert factura.envio_id == envio_entregado.id


def test_facturar_dos_veces_el_mismo_envio_no_duplica(contenedor, envio_entregado):
    """Es lo que hace idempotente a la facturacion automatica."""
    contenedor.facturacion.facturar_envio(envio_entregado.id)
    assert contenedor.facturacion.facturar_envio(envio_entregado.id) is None


def test_no_se_factura_un_envio_sin_entregar(contenedor):
    envio = contenedor.envios.registrar(CLIENTE, ORIGEN, DESTINO)
    try:
        with pytest.raises(ValidacionError):
            contenedor.facturacion.facturar_envio(envio.id)
    finally:
        _limpiar(contenedor, envios=[envio.id])


def test_un_envio_inexistente(contenedor):
    with pytest.raises(NoEncontrado):
        contenedor.facturacion.facturar_envio(uuid4())


# --- Procesos periodicos ------------------------------------------------------


def test_la_facturacion_automatica_es_idempotente(contenedor, envio_entregado):
    servicio = contenedor.facturacion
    primera = servicio.facturar_entregados()
    assert any(f.envio_id == envio_entregado.id for f in primera)
    assert servicio.facturar_entregados() == []


def test_el_cierre_marca_las_vencidas(contenedor, cuenta_temporal):
    servicio = contenedor.facturacion
    vieja = datetime.now(timezone.utc) - timedelta(days=60)
    factura = servicio.emitir(
        TitularTipo.PROVEEDOR, PROVEEDOR, Decimal("300"), "x", momento=vieja
    )
    resultado = servicio.cerrar_mes()

    assert resultado.facturas_vencidas >= 1
    assert servicio.obtener_factura(factura.id).estado is EstadoFactura.VENCIDA


def test_una_factura_vencida_todavia_se_puede_cobrar(contenedor, cuenta_temporal):
    servicio = contenedor.facturacion
    vieja = datetime.now(timezone.utc) - timedelta(days=60)
    factura = servicio.emitir(
        TitularTipo.PROVEEDOR, PROVEEDOR, Decimal("300"), "x", momento=vieja
    )
    servicio.cerrar_mes()
    servicio.registrar_pago(factura.id, Decimal("300"), MedioPago.TRANSFERENCIA)
    assert servicio.obtener_factura(factura.id).estado is EstadoFactura.PAGADA


# --- Titular polimorfico ------------------------------------------------------


def test_no_se_puede_facturar_a_un_titular_inexistente(contenedor):
    with pytest.raises(ValidacionError):
        contenedor.facturacion.emitir(
            TitularTipo.OPERADOR, uuid4(), Decimal("100"), "x"
        )


def test_no_se_puede_abrir_dos_cuentas_al_mismo_titular(contenedor, cuenta_temporal):
    with pytest.raises(ConflictoDeDatos):
        contenedor.facturacion.abrir_cuenta(
            TitularTipo.PROVEEDOR, PROVEEDOR, Decimal("1000")
        )


def test_no_se_factura_a_un_titular_sin_cuenta(contenedor):
    """La cuenta tiene que existir antes: no se crea sola al facturar."""
    with pytest.raises(NoEncontrado):
        contenedor.facturacion.emitir(
            TitularTipo.PROVEEDOR,
            UUID("40000000-0000-0000-0000-000000000003"),
            Decimal("100"),
            "x",
        )
