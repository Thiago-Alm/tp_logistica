from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from logistica.domain.facturacion import (
    CERO,
    CuentaCorriente,
    EstadoFactura,
    Factura,
    MedioPago,
    MovimientoCuenta,
    Pago,
    TipoMovimiento,
    TitularTipo,
)
from logistica.exceptions import ValidacionError

AHORA = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)


def nueva_factura(**cambios) -> Factura:
    datos = dict(
        id=uuid4(),
        titular_tipo=TitularTipo.CLIENTE,
        titular_id=uuid4(),
        numero_factura="FC-A-0001-00000001",
        fecha_emision=AHORA,
        fecha_vencimiento=AHORA + timedelta(days=15),
        importe_total=Decimal("1500.50"),
    )
    datos.update(cambios)
    return Factura(**datos)


def nueva_cuenta(**cambios) -> CuentaCorriente:
    datos = dict(
        id=uuid4(),
        titular_tipo=TitularTipo.CLIENTE,
        titular_id=uuid4(),
        limite_credito=Decimal("10000"),
    )
    datos.update(cambios)
    return CuentaCorriente(**datos)


def movimiento(tipo, monto, cuenta_id=None) -> MovimientoCuenta:
    return MovimientoCuenta(
        id=uuid4(),
        cuenta_corriente_id=cuenta_id or uuid4(),
        tipo=tipo,
        monto=Decimal(monto),
        descripcion="prueba",
        fecha=AHORA,
    )


# --- Factura ----------------------------------------------------------------


def test_una_factura_nace_emitida():
    assert nueva_factura().estado is EstadoFactura.EMITIDA


def test_el_importe_no_puede_ser_negativo():
    with pytest.raises(ValidacionError):
        nueva_factura(importe_total=Decimal("-1"))


def test_el_vencimiento_no_puede_preceder_a_la_emision():
    with pytest.raises(ValidacionError):
        nueva_factura(fecha_vencimiento=AHORA - timedelta(days=1))


def test_el_numero_es_obligatorio():
    with pytest.raises(ValidacionError):
        nueva_factura(numero_factura="   ")


def test_transiciones_validas_de_factura():
    factura = nueva_factura()
    factura.pasar_a(EstadoFactura.VENCIDA)
    factura.pasar_a(EstadoFactura.PAGADA)
    assert factura.estado is EstadoFactura.PAGADA


def test_una_factura_pagada_es_final():
    """Igual que un envio ENTREGADO (D4): no vuelve atras."""
    factura = nueva_factura()
    factura.pasar_a(EstadoFactura.PAGADA)
    assert factura.estado.es_final()
    with pytest.raises(ValidacionError):
        factura.pasar_a(EstadoFactura.EMITIDA)


def test_una_factura_anulada_no_admite_pagos():
    factura = nueva_factura()
    factura.pasar_a(EstadoFactura.ANULADA)
    assert not factura.esta_pendiente()


def test_detecta_el_vencimiento():
    factura = nueva_factura()
    assert not factura.esta_vencida(AHORA)
    assert factura.esta_vencida(AHORA + timedelta(days=20))


# --- Pago --------------------------------------------------------------------


def test_un_pago_debe_ser_positivo():
    for monto in (Decimal("0"), Decimal("-5")):
        with pytest.raises(ValidacionError):
            Pago(
                id=uuid4(),
                factura_id=uuid4(),
                monto=monto,
                medio_pago=MedioPago.EFECTIVO,
                fecha_pago=AHORA,
            )


# --- Cuenta corriente --------------------------------------------------------


def test_un_debito_baja_el_saldo_y_un_credito_lo_sube():
    """La convencion: el saldo es negativo cuando el titular debe."""
    cuenta = nueva_cuenta()
    cuenta.aplicar(movimiento(TipoMovimiento.DEBITO, "2500.50"))
    assert cuenta.saldo == Decimal("-2500.50")
    assert cuenta.deuda == Decimal("2500.50")

    cuenta.aplicar(movimiento(TipoMovimiento.CREDITO, "2500.50"))
    assert cuenta.saldo == CERO
    assert cuenta.deuda == CERO


def test_la_aritmetica_no_pierde_centavos():
    """D15: con float, 0.1 + 0.2 no da 0.3 y los saldos se desvian."""
    cuenta = nueva_cuenta()
    for _ in range(3):
        cuenta.aplicar(movimiento(TipoMovimiento.DEBITO, "0.1"))
    assert cuenta.saldo == Decimal("-0.3")


def test_credito_disponible_y_limite():
    cuenta = nueva_cuenta(limite_credito=Decimal("1000"))
    cuenta.aplicar(movimiento(TipoMovimiento.DEBITO, "400"))
    assert cuenta.credito_disponible() == Decimal("600")
    assert not cuenta.supera_el_limite(Decimal("600"))
    assert cuenta.supera_el_limite(Decimal("601"))


def test_un_saldo_a_favor_no_cuenta_como_deuda():
    cuenta = nueva_cuenta()
    cuenta.aplicar(movimiento(TipoMovimiento.CREDITO, "500"))
    assert cuenta.saldo == Decimal("500")
    assert cuenta.deuda == CERO


def test_el_limite_no_puede_ser_negativo():
    with pytest.raises(ValidacionError):
        nueva_cuenta(limite_credito=Decimal("-1"))


# --- Movimiento --------------------------------------------------------------


def test_el_monto_de_un_movimiento_es_siempre_positivo():
    """El sentido lo da el tipo, no el signo del monto: si ademas el monto
    pudiera ser negativo, un DEBITO de -100 seria en realidad un credito."""
    with pytest.raises(ValidacionError):
        movimiento(TipoMovimiento.DEBITO, "-100")


def test_un_movimiento_necesita_descripcion():
    with pytest.raises(ValidacionError):
        MovimientoCuenta(
            id=uuid4(),
            cuenta_corriente_id=uuid4(),
            tipo=TipoMovimiento.DEBITO,
            monto=Decimal("10"),
            descripcion="  ",
            fecha=AHORA,
        )


def test_los_signos_de_cada_tipo():
    assert TipoMovimiento.DEBITO.signo() == -1
    assert TipoMovimiento.CREDITO.signo() == 1


def test_todos_los_valores_van_en_mayusculas():
    """D19."""
    for enum in (TitularTipo, EstadoFactura, MedioPago, TipoMovimiento):
        for valor in enum:
            assert valor.value == valor.name == valor.value.upper()
