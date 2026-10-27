"""Tests de la trazabilidad contra Cassandra y PostgreSQL reales.

Verifican el circuito completo: un cambio de estado del envio deja su evento en
el Outbox, el worker lo proyecta a Cassandra y queda en la traza.
"""
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import psycopg
import pytest

from logistica.container import Contenedor
from logistica.domain.envio import EstadoEnvio, PrioridadEnvio
from logistica.domain.evento_logistico import TipoEventoLogistico
from logistica.exceptions import ErrorDePersistencia, NoEncontrado, ValidacionError
from logistica.infrastructure.postgres.conexion import armar_dsn

CLIENTE = UUID("20000000-0000-0000-0000-000000000001")
ORIGEN = UUID("50000000-0000-0000-0000-000000000001")
DESTINO = UUID("50000000-0000-0000-0000-000000000004")
CONTENEDOR = UUID("70000000-0000-0000-0000-000000000004")


@pytest.fixture(scope="module")
def contenedor():
    c = Contenedor(configurar_logging=False)
    try:
        c.clientes.listar()
        c.eventos_logisticos.historial_de_envio(uuid4())
    except ErrorDePersistencia:
        pytest.skip("PostgreSQL o Cassandra no disponibles: docker compose up -d")
    return c


@pytest.fixture
def envio(contenedor):
    """Crea un envio y borra su rastro en los tres motores al terminar."""
    creado = contenedor.envios.registrar(CLIENTE, ORIGEN, DESTINO, PrioridadEnvio.MEDIA)
    yield creado
    with psycopg.connect(armar_dsn(contenedor.settings), autocommit=True) as cx:
        cx.execute("delete from outbox where agregado_id = %s", (creado.id,))
        cx.execute("delete from envio_contenedor where envio_id = %s", (creado.id,))
        cx.execute(
            "update contenedor set estado = 'DISPONIBLE' where id = %s", (CONTENEDOR,)
        )
        cx.execute("delete from envio where id = %s", (creado.id,))
    contenedor.sesion_cassandra.execute(
        "delete from eventos_por_envio where envio_id = %s", (creado.id,)
    )
    ahora = datetime.now(timezone.utc)
    for mes in {(ahora - timedelta(days=d)).strftime("%Y-%m") for d in (0, 31)}:
        contenedor.sesion_cassandra.execute(
            "delete from eventos_por_contenedor where contenedor_id = %s and anio_mes = %s",
            (CONTENEDOR, mes),
        )


# --- El circuito completo ---------------------------------------------------


def test_el_alta_no_escribe_la_traza_hasta_que_corre_el_worker(contenedor, envio):
    """La traza no se escribe desde el servicio: va por el Outbox (D40)."""
    assert contenedor.trazabilidad.historial(envio.id) == []
    contenedor.worker_de_sincronizacion.procesar_tanda()
    assert len(contenedor.trazabilidad.historial(envio.id)) == 1


def test_cada_cambio_de_estado_deja_su_evento(contenedor, envio):
    contenedor.envios.cambiar_estado(envio.id, EstadoEnvio.EN_TRANSITO)
    contenedor.envios.cambiar_estado(envio.id, EstadoEnvio.EN_PUERTO)
    contenedor.envios.entregar(envio.id)
    contenedor.worker_de_sincronizacion.procesar_tanda()

    tipos = [e.tipo for e in contenedor.trazabilidad.historial(envio.id)]
    assert tipos == [
        TipoEventoLogistico.CARGA_INICIADA,
        TipoEventoLogistico.EN_TRANSITO,
        TipoEventoLogistico.EN_PUERTO,
        TipoEventoLogistico.ENTREGADO,
    ]


def test_el_historial_viene_en_orden_cronologico(contenedor, envio):
    contenedor.envios.cambiar_estado(envio.id, EstadoEnvio.EN_TRANSITO)
    contenedor.worker_de_sincronizacion.procesar_tanda()
    momentos = [e.momento_utc for e in contenedor.trazabilidad.historial(envio.id)]
    assert momentos == sorted(momentos)


def test_reprocesar_no_duplica_la_traza(contenedor, envio):
    """El evento_id se deriva del id del evento del Outbox, asi que reprocesar
    pisa la misma fila en vez de agregar otra (D35)."""
    contenedor.envios.cambiar_estado(envio.id, EstadoEnvio.EN_TRANSITO)
    contenedor.worker_de_sincronizacion.procesar_tanda()
    antes = len(contenedor.trazabilidad.historial(envio.id))

    with psycopg.connect(armar_dsn(contenedor.settings), autocommit=True) as cx:
        cx.execute(
            "update outbox set procesado = false, fecha_procesado = null "
            "where agregado_id = %s",
            (envio.id,),
        )
    contenedor.worker_de_sincronizacion.procesar_tanda()
    assert len(contenedor.trazabilidad.historial(envio.id)) == antes


def test_un_envio_sin_eventos_devuelve_vacio(contenedor):
    assert contenedor.trazabilidad.historial(uuid4()) == []
    assert contenedor.trazabilidad.ultimo_evento(uuid4()) is None


# --- Eventos manuales -------------------------------------------------------


def test_registrar_un_evento_manual(contenedor, envio):
    evento = contenedor.trazabilidad.registrar(
        envio.id,
        TipoEventoLogistico.ADUANA,
        "Retenido para inspeccion",
        ubicacion_id=DESTINO,
        ubicacion_nombre="Puerto de Rotterdam",
    )
    historial = contenedor.trazabilidad.historial(envio.id)
    assert evento.id in [e.id for e in historial]
    # El id y el nombre de la ubicacion se guardan los dos (D21).
    guardado = next(e for e in historial if e.id == evento.id)
    assert guardado.ubicacion_id == DESTINO
    assert guardado.ubicacion_nombre == "Puerto de Rotterdam"


def test_no_se_puede_cargar_a_mano_un_tipo_automatico(contenedor, envio):
    """Si se pudiera, la traza tendria dos entradas para el mismo hecho."""
    for tipo in (TipoEventoLogistico.ENTREGADO, TipoEventoLogistico.EN_TRANSITO):
        with pytest.raises(ValidacionError):
            contenedor.trazabilidad.registrar(envio.id, tipo, "a mano")


def test_no_se_puede_registrar_en_un_envio_inexistente(contenedor):
    with pytest.raises(NoEncontrado):
        contenedor.trazabilidad.registrar(
            uuid4(), TipoEventoLogistico.RETRASO, "demora"
        )


def test_el_ultimo_evento_es_el_mas_reciente(contenedor, envio):
    contenedor.worker_de_sincronizacion.procesar_tanda()
    contenedor.trazabilidad.registrar(
        envio.id, TipoEventoLogistico.RETRASO, "Demora por congestion"
    )
    assert contenedor.trazabilidad.ultimo_evento(envio.id).tipo is TipoEventoLogistico.RETRASO


# --- Recorrido del contenedor -----------------------------------------------


def test_la_asignacion_queda_en_el_recorrido_del_contenedor(contenedor, envio):
    """Es la segunda tabla: misma escritura, otra clave de particion."""
    contenedor.envios.asignar_contenedor(envio.id, CONTENEDOR)
    contenedor.worker_de_sincronizacion.procesar_tanda()

    movimientos = contenedor.trazabilidad.recorrido_de_contenedor(CONTENEDOR)
    assert envio.id in [m.envio_id for m in movimientos]


def test_el_recorrido_viene_en_orden_cronologico(contenedor, envio):
    contenedor.envios.asignar_contenedor(envio.id, CONTENEDOR)
    contenedor.worker_de_sincronizacion.procesar_tanda()
    movimientos = contenedor.trazabilidad.recorrido_de_contenedor(CONTENEDOR)
    momentos = [m.momento_utc for m in movimientos]
    assert momentos == sorted(momentos)


def test_un_rango_demasiado_largo_se_rechaza(contenedor):
    """La particion lleva bucket mensual: un rango abierto dispararia una
    consulta por cada mes."""
    hasta = datetime.now(timezone.utc)
    with pytest.raises(ValidacionError):
        contenedor.trazabilidad.recorrido_de_contenedor(
            CONTENEDOR, desde=hasta - timedelta(days=365 * 5), hasta=hasta
        )
