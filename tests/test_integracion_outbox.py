"""Tests de integracion del Outbox contra PostgreSQL real.

Lo que se verifica aca es la propiedad que justifica todo el patron: el evento
y el dato se escriben en la misma transaccion, asi que o estan los dos o no
esta ninguno.
"""
from uuid import UUID, uuid4

import psycopg
import pytest

from logistica.container import Contenedor
from logistica.domain.envio import EstadoEnvio, PrioridadEnvio
from logistica.domain.evento_outbox import TipoAgregado, TipoEvento
from logistica.exceptions import ErrorDePersistencia, ValidacionError
from logistica.infrastructure.postgres.conexion import armar_dsn

CLIENTE = UUID("20000000-0000-0000-0000-000000000001")
ORIGEN = UUID("50000000-0000-0000-0000-000000000001")
DESTINO = UUID("50000000-0000-0000-0000-000000000004")
CUIT_PRUEBA = "30-00000002-4"


@pytest.fixture(scope="module")
def contenedor():
    c = Contenedor(configurar_logging=False)
    try:
        c.clientes.listar()
    except ErrorDePersistencia:
        pytest.skip("PostgreSQL no disponible: docker compose up -d")
    return c


@pytest.fixture
def limpiar(contenedor):
    """Guarda que crear y lo borra al final, junto con sus eventos."""
    creados: dict[str, list] = {"clientes": [], "envios": []}
    yield creados
    with psycopg.connect(armar_dsn(contenedor.settings), autocommit=True) as cx:
        for envio_id in creados["envios"]:
            cx.execute("delete from outbox where agregado_id = %s", (envio_id,))
            cx.execute(
                "delete from outbox where agregado_id in "
                "(select id from tramo where envio_id = %s)",
                (envio_id,),
            )
            cx.execute("delete from envio_contenedor where envio_id = %s", (envio_id,))
            cx.execute("delete from envio where id = %s", (envio_id,))
        for cliente_id in creados["clientes"]:
            cx.execute("delete from outbox where agregado_id = %s", (cliente_id,))
            cx.execute("delete from cliente where id = %s", (cliente_id,))


def _eventos_de(contenedor, agregado_id) -> list:
    with contenedor.unidad_de_trabajo as uow:
        pendientes = uow.outbox.tomar_pendientes(limite=500)
    return [e for e in pendientes if e.agregado_id == agregado_id]


# --- La propiedad central ---------------------------------------------------


def test_el_alta_de_cliente_encola_un_evento(contenedor, limpiar):
    cliente = contenedor.clientes.alta(
        cuit=CUIT_PRUEBA, razon_social="Outbox SA", email="o@x.com", pais="Argentina"
    )
    limpiar["clientes"].append(cliente.id)

    eventos = _eventos_de(contenedor, cliente.id)
    assert len(eventos) == 1
    assert eventos[0].agregado_tipo is TipoAgregado.CLIENTE
    assert eventos[0].evento_tipo is TipoEvento.CREADO
    assert eventos[0].payload["razon_social"] == "Outbox SA"
    assert not eventos[0].procesado


def test_si_el_alta_falla_no_queda_el_evento(contenedor, limpiar):
    """ESTA es la prueba del patron.

    El alta de un envio con un cliente inexistente corta antes del commit. Si
    el evento se escribiera fuera de la transaccion, quedaria un evento
    huerfano apuntando a un envio que nunca existio.
    """
    with contenedor.unidad_de_trabajo as uow:
        antes = uow.outbox.contar_pendientes()

    cliente_fantasma = uuid4()
    with pytest.raises(ValidacionError):
        contenedor.envios.registrar(cliente_fantasma, ORIGEN, DESTINO)

    with contenedor.unidad_de_trabajo as uow:
        assert uow.outbox.contar_pendientes() == antes


def test_una_transicion_invalida_tampoco_deja_evento(contenedor, limpiar):
    envio = contenedor.envios.registrar(CLIENTE, ORIGEN, DESTINO)
    limpiar["envios"].append(envio.id)
    assert len(_eventos_de(contenedor, envio.id)) == 1  # solo el CREADO

    with pytest.raises(ValidacionError):
        contenedor.envios.entregar(envio.id)  # CREADO no puede ir a ENTREGADO

    assert len(_eventos_de(contenedor, envio.id)) == 1  # sigue habiendo uno solo


# --- Orden y contenido ------------------------------------------------------


def test_los_eventos_de_un_envio_llegan_en_orden(contenedor, limpiar):
    """Si el CREADO llegara despues del ESTADO_CAMBIADO, el grafo quedaria con
    el estado viejo."""
    envio = contenedor.envios.registrar(CLIENTE, ORIGEN, DESTINO, PrioridadEnvio.ALTA)
    limpiar["envios"].append(envio.id)
    contenedor.envios.cambiar_estado(envio.id, EstadoEnvio.EN_TRANSITO)
    contenedor.envios.cambiar_estado(envio.id, EstadoEnvio.EN_PUERTO)

    eventos = _eventos_de(contenedor, envio.id)
    assert [e.evento_tipo for e in eventos] == [
        TipoEvento.CREADO,
        TipoEvento.ESTADO_CAMBIADO,
        TipoEvento.ESTADO_CAMBIADO,
    ]
    assert eventos[-1].payload["estado"] == "EN_PUERTO"


def test_la_baja_viaja_como_cambio_de_estado_y_no_como_borrado(contenedor, limpiar):
    """D26: el proyector no debe borrar el nodo, o el grafo pierde el historico."""
    cliente = contenedor.clientes.alta(
        cuit=CUIT_PRUEBA, razon_social="Baja SA", email="b@x.com", pais="Argentina"
    )
    limpiar["clientes"].append(cliente.id)
    contenedor.clientes.baja(cliente.id)

    eventos = _eventos_de(contenedor, cliente.id)
    assert eventos[-1].evento_tipo is TipoEvento.DADO_DE_BAJA
    assert eventos[-1].payload["estado"] == "INACTIVO"


def test_el_payload_no_pierde_precision_en_el_costo(contenedor, limpiar):
    """D15: el Decimal viaja como texto, no como float."""
    from datetime import datetime, timedelta, timezone
    from decimal import Decimal

    envio = contenedor.envios.registrar(CLIENTE, ORIGEN, DESTINO)
    limpiar["envios"].append(envio.id)
    salida = datetime.now(timezone.utc)
    contenedor.envios.agregar_tramo(
        envio_id=envio.id,
        vehiculo_id=UUID("60000000-0000-0000-0000-000000000001"),
        medio_transporte=__import__(
            "logistica.domain.tramo", fromlist=["MedioTransporte"]
        ).MedioTransporte.MARITIMO,
        origen_id=ORIGEN,
        destino_id=DESTINO,
        fecha_salida=salida,
        fecha_llegada_estimada=salida + timedelta(days=3),
        costo=Decimal("1234.56"),
    )
    with contenedor.unidad_de_trabajo as uow:
        pendientes = uow.outbox.tomar_pendientes(limite=500)
    tramos = [e for e in pendientes if e.agregado_tipo is TipoAgregado.TRAMO]
    costo = tramos[-1].payload["costo"]
    assert costo == "1234.56"
    assert Decimal(costo) == Decimal("1234.56")


def test_los_pendientes_vienen_del_mas_viejo_al_mas_nuevo(contenedor):
    with contenedor.unidad_de_trabajo as uow:
        pendientes = uow.outbox.tomar_pendientes(limite=500)
    fechas = [e.fecha_creacion for e in pendientes]
    assert fechas == sorted(fechas)
