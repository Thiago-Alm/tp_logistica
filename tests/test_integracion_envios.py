"""Tests de integracion de envios, tramos y reportes contra PostgreSQL real.

Se saltean solos si la base no esta disponible. Requieren los datos semilla:

    docker compose up -d && python scripts/aplicar_esquema.py
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import psycopg
import pytest

from logistica.container import Contenedor
from logistica.domain.contenedor import EstadoContenedor
from logistica.domain.envio import EstadoEnvio, PrioridadEnvio
from logistica.domain.tramo import MedioTransporte
from logistica.exceptions import (
    ConflictoDeDatos,
    ErrorDePersistencia,
    NoEncontrado,
    ValidacionError,
)
from logistica.infrastructure.postgres.conexion import armar_dsn

# Ids de scripts/postgres/02_datos_prueba.sql
CLIENTE = UUID("20000000-0000-0000-0000-000000000001")
ORIGEN = UUID("50000000-0000-0000-0000-000000000001")  # Puerto de Buenos Aires
DESTINO = UUID("50000000-0000-0000-0000-000000000004")  # Rotterdam
ESCALA = UUID("50000000-0000-0000-0000-000000000003")  # Santos
VEHICULO = UUID("60000000-0000-0000-0000-000000000001")
CONTENEDOR_LIBRE = UUID("70000000-0000-0000-0000-000000000004")  # DISPONIBLE
CONTENEDOR_OCUPADO = UUID("70000000-0000-0000-0000-000000000001")  # EN_TRANSITO


@pytest.fixture(scope="module")
def contenedor():
    c = Contenedor(configurar_logging=False)
    try:
        c.clientes.listar()
    except ErrorDePersistencia:
        pytest.skip("PostgreSQL no disponible: docker compose up -d")
    return c


@pytest.fixture
def envio_temporal(contenedor):
    """Crea un envio y borra todo su rastro al terminar."""
    envio = contenedor.envios.registrar(CLIENTE, ORIGEN, DESTINO, PrioridadEnvio.ALTA)
    yield envio
    with psycopg.connect(armar_dsn(contenedor.settings), autocommit=True) as cx:
        cx.execute("delete from envio_contenedor where envio_id = %s", (envio.id,))
        cx.execute(
            "update contenedor set estado = 'DISPONIBLE' where id = %s",
            (CONTENEDOR_LIBRE,),
        )
        cx.execute("delete from envio where id = %s", (envio.id,))  # tramo cae en cascada


# --- Alta y ciclo de vida ---------------------------------------------------


def test_registrar_un_envio(contenedor, envio_temporal):
    leido = contenedor.envios.obtener(envio_temporal.id)
    assert leido.estado is EstadoEnvio.CREADO
    assert leido.prioridad is PrioridadEnvio.ALTA
    assert leido.fecha_llegada_real is None


def test_no_se_puede_registrar_para_un_cliente_inexistente(contenedor):
    with pytest.raises(ValidacionError):
        contenedor.envios.registrar(uuid4(), ORIGEN, DESTINO)


def test_origen_y_destino_iguales_los_frena_el_dominio(contenedor):
    with pytest.raises(ValidacionError):
        contenedor.envios.registrar(CLIENTE, ORIGEN, ORIGEN)


def test_ciclo_de_estados_completo(contenedor, envio_temporal):
    contenedor.envios.cambiar_estado(envio_temporal.id, EstadoEnvio.EN_TRANSITO)
    contenedor.envios.cambiar_estado(envio_temporal.id, EstadoEnvio.EN_PUERTO)
    entregado = contenedor.envios.entregar(envio_temporal.id)
    assert entregado.estado is EstadoEnvio.ENTREGADO
    assert entregado.fecha_llegada_real is not None


def test_una_transicion_invalida_no_llega_a_la_base(contenedor, envio_temporal):
    """CREADO no puede pasar a ENTREGADO: lo frena el dominio (D4)."""
    with pytest.raises(ValidacionError):
        contenedor.envios.entregar(envio_temporal.id)
    assert contenedor.envios.obtener(envio_temporal.id).estado is EstadoEnvio.CREADO


def test_envio_inexistente(contenedor):
    with pytest.raises(NoEncontrado):
        contenedor.envios.obtener(uuid4())


# --- Tramos -----------------------------------------------------------------


def _agregar_tramo(contenedor, envio_id, origen, destino, dias_hasta_llegar, costo):
    salida = datetime.now(timezone.utc)
    return contenedor.envios.agregar_tramo(
        envio_id=envio_id,
        vehiculo_id=VEHICULO,
        medio_transporte=MedioTransporte.MARITIMO,
        origen_id=origen,
        destino_id=destino,
        fecha_salida=salida,
        fecha_llegada_estimada=salida + timedelta(days=dias_hasta_llegar),
        costo=costo,
    )


def test_el_orden_de_los_tramos_se_calcula_solo(contenedor, envio_temporal):
    primero = _agregar_tramo(contenedor, envio_temporal.id, ORIGEN, ESCALA, 5, Decimal("1500.00"))
    segundo = _agregar_tramo(contenedor, envio_temporal.id, ESCALA, DESTINO, 12, Decimal("4200.00"))
    assert (primero.orden, segundo.orden) == (1, 2)


def test_obtener_con_tramos_compone_los_dos_repositorios(contenedor, envio_temporal):
    _agregar_tramo(contenedor, envio_temporal.id, ORIGEN, ESCALA, 5, Decimal("1500.00"))
    _agregar_tramo(contenedor, envio_temporal.id, ESCALA, DESTINO, 12, Decimal("4200.00"))
    detalle = contenedor.envios.obtener_con_tramos(envio_temporal.id)
    assert [t.orden for t in detalle.tramos] == [1, 2]
    assert detalle.costo_total == Decimal("5700.00")
    assert detalle.llegada_estimada == detalle.tramos[1].fecha_llegada_estimada


def test_un_envio_sin_tramos_no_tiene_llegada_estimada(contenedor, envio_temporal):
    detalle = contenedor.envios.obtener_con_tramos(envio_temporal.id)
    assert detalle.tramos == []
    assert detalle.llegada_estimada is None
    assert not detalle.esta_demorado(datetime.now(timezone.utc))


def test_completar_un_tramo(contenedor, envio_temporal):
    tramo = _agregar_tramo(contenedor, envio_temporal.id, ORIGEN, ESCALA, 5, Decimal("1500.00"))
    llegada = tramo.fecha_salida + timedelta(days=4)
    assert contenedor.envios.completar_tramo(tramo.id, llegada).esta_completado()


# --- Contenedores -----------------------------------------------------------


def test_asignar_un_contenedor_disponible(contenedor, envio_temporal):
    asignado = contenedor.envios.asignar_contenedor(envio_temporal.id, CONTENEDOR_LIBRE)
    assert asignado.estado is EstadoContenedor.ASIGNADO


def test_no_se_puede_asignar_un_contenedor_ocupado(contenedor, envio_temporal):
    """La regla del supuesto 1 la valida el servicio, no la base (D3)."""
    with pytest.raises(ConflictoDeDatos):
        contenedor.envios.asignar_contenedor(envio_temporal.id, CONTENEDOR_OCUPADO)


# --- Reportes ---------------------------------------------------------------


def test_envios_por_pais(contenedor):
    filas = contenedor.reportes.envios_por_pais()
    paises = {f.pais: f.cantidad for f in filas}
    assert paises["Holanda"] >= 1
    assert all(f.cantidad > 0 for f in filas)


def test_envios_por_estado_usa_el_enum(contenedor):
    filas = contenedor.reportes.envios_por_estado()
    assert all(isinstance(f.estado, EstadoEnvio) for f in filas)
    assert sum(f.cantidad for f in filas) >= 6


def test_envios_por_cliente_trae_la_razon_social(contenedor):
    filas = contenedor.reportes.envios_por_cliente()
    assert any(f.razon_social.startswith("AgroGlobal") for f in filas)


def test_envios_demorados(contenedor):
    """El envio 4 de los datos semilla esta demorado a proposito.

    Se consulta con la hora real y no con una fecha fija: desde que las fechas
    de la semilla son relativas a CURRENT_TIMESTAMP (D56), "hoy" siempre cae en
    el mismo punto del timeline.
    """
    demorados = contenedor.envios.listar_demorados(datetime.now(timezone.utc))
    assert UUID("a0000000-0000-0000-0000-000000000004") in [e.id for e in demorados]
    assert all(e.estado not in (EstadoEnvio.ENTREGADO, EstadoEnvio.CANCELADO) for e in demorados)


def test_tiempo_promedio_de_entrega(contenedor):
    assert contenedor.reportes.tiempo_promedio_de_entrega() > timedelta(0)


def test_tiempos_por_cliente_incluye_clientes_sin_entregas(contenedor):
    """El LEFT JOIN debe devolver tambien a los clientes que nunca entregaron."""
    filas = contenedor.reportes.tiempos_de_envio_por_cliente()
    assert len(filas) >= 4
    assert any(f.minimo is None for f in filas)
    assert any(f.minimo is not None for f in filas)


def test_ranking_de_clientes_por_volumen_viene_ordenado(contenedor):
    filas = contenedor.reportes.ranking_clientes_por_volumen(limite=3)
    volumenes = [f.volumen for f in filas]
    assert volumenes == sorted(volumenes, reverse=True)


def test_costos_por_tipo_de_transporte(contenedor):
    costos = contenedor.reportes.costos_por_tipo_de_transporte()
    assert MedioTransporte.MARITIMO in costos
    assert all(isinstance(k, MedioTransporte) for k in costos)
    assert all(v > 0 for v in costos.values())


def test_los_reportes_aceptan_rango_de_fechas(contenedor):
    """Reportes parametrizados: un rango vacio no devuelve nada."""
    lejano = datetime(2000, 1, 1, tzinfo=timezone.utc)
    assert contenedor.reportes.envios_por_pais(desde=lejano, hasta=lejano) == []
    assert len(contenedor.reportes.envios_por_pais()) > 0
