"""Tests del chequeo de consistencia contra PostgreSQL y Neo4j reales.

Se saltean solos si alguna de las dos bases no esta disponible. Cada test deja
el grafo reconstruido, asi que se pueden correr muchas veces seguidas.
"""
from uuid import UUID, uuid4

import psycopg
import pytest

from logistica.container import Contenedor
from logistica.domain.envio import PrioridadEnvio
from logistica.domain.evento_outbox import TipoAgregado
from logistica.exceptions import ErrorDePersistencia
from logistica.infrastructure.postgres.conexion import armar_dsn
from logistica.sync.consistencia import ETIQUETAS

CLIENTE = UUID("20000000-0000-0000-0000-000000000001")
ORIGEN = UUID("50000000-0000-0000-0000-000000000001")
DESTINO = UUID("50000000-0000-0000-0000-000000000004")


@pytest.fixture(scope="module")
def contenedor():
    c = Contenedor(configurar_logging=False)
    try:
        c.clientes.listar()
        c.proyector_neo4j.ids_de_etiqueta("Cliente")
    except ErrorDePersistencia:
        pytest.skip("PostgreSQL o Neo4j no disponibles: docker compose up -d")
    return c


@pytest.fixture(scope="module", autouse=True)
def grafo_al_dia(contenedor):
    """Deja el grafo reconstruido antes y despues del modulo."""
    contenedor.chequeo_de_consistencia.reconstruir(borrar_antes=True)
    yield
    contenedor.chequeo_de_consistencia.reconstruir(borrar_antes=True)


@pytest.fixture
def envio_temporal(contenedor):
    envio = contenedor.envios.registrar(CLIENTE, ORIGEN, DESTINO, PrioridadEnvio.BAJA)
    yield envio
    with psycopg.connect(armar_dsn(contenedor.settings), autocommit=True) as cx:
        cx.execute("delete from outbox where agregado_id = %s", (envio.id,))
        cx.execute("delete from envio where id = %s", (envio.id,))
    contenedor.chequeo_de_consistencia.reconstruir(borrar_antes=True)


# --- Verificacion -----------------------------------------------------------


def test_un_grafo_al_dia_no_reporta_problemas(contenedor):
    reporte = contenedor.chequeo_de_consistencia.verificar()
    assert not reporte.hay_problemas
    assert all(d.coincide for d in reporte.diferencias)


def test_el_reporte_cubre_todos_los_tipos_del_grafo(contenedor):
    reporte = contenedor.chequeo_de_consistencia.verificar()
    assert {d.agregado for d in reporte.diferencias} == set(ETIQUETAS)


def test_detecta_lo_que_falta_en_el_grafo(contenedor, envio_temporal):
    """El envio se creo via servicio: el evento quedo pendiente y el grafo
    todavia no lo tiene."""
    reporte = contenedor.chequeo_de_consistencia.verificar()
    envios = next(d for d in reporte.diferencias if d.agregado is TipoAgregado.ENVIO)
    assert str(envio_temporal.id) in envios.faltan_en_grafo
    assert reporte.hay_problemas


def test_el_worker_cierra_la_diferencia(contenedor, envio_temporal):
    """Despues de propagar, la diferencia desaparece: es el circuito completo."""
    assert contenedor.chequeo_de_consistencia.verificar().hay_problemas
    contenedor.worker_de_sincronizacion.procesar_tanda()
    reporte = contenedor.chequeo_de_consistencia.verificar()
    envios = next(d for d in reporte.diferencias if d.agregado is TipoAgregado.ENVIO)
    assert str(envio_temporal.id) not in envios.faltan_en_grafo


def test_detecta_un_nodo_fantasma(contenedor):
    """Un nodo que quedo en el grafo sin su fila en PostgreSQL."""
    fantasma = str(uuid4())
    with contenedor.proyector_neo4j._driver.session() as s:
        s.run("CREATE (:Envio {id: $id, estado: 'CREADO'})", id=fantasma)

    reporte = contenedor.chequeo_de_consistencia.verificar()
    envios = next(d for d in reporte.diferencias if d.agregado is TipoAgregado.ENVIO)
    assert fantasma in envios.sobran_en_grafo
    assert reporte.hay_problemas


def test_el_reporte_cuenta_los_pendientes(contenedor):
    reporte = contenedor.chequeo_de_consistencia.verificar()
    with contenedor.unidad_de_trabajo as uow:
        assert reporte.eventos_pendientes == uow.outbox.contar_pendientes()


# --- Reconstruccion ---------------------------------------------------------


def test_reconstruir_rearma_el_grafo_desde_cero(contenedor):
    """El grafo es redundante por diseno: si se pierde entero, se reconstruye.

    Esa propiedad es la que permite tratar su sincronizacion como eventual sin
    comprometer la correccion del sistema.
    """
    contenedor.proyector_neo4j.borrar_todo()
    assert contenedor.proyector_neo4j.ids_de_etiqueta("Envio") == set()

    contenedor.chequeo_de_consistencia.reconstruir()
    assert not contenedor.chequeo_de_consistencia.verificar().hay_problemas


def test_reconstruir_con_borrado_elimina_los_fantasmas(contenedor):
    """MERGE agrega y corrige, pero no borra: para sacar un sobrante hay que
    vaciar el grafo antes."""
    fantasma = str(uuid4())
    with contenedor.proyector_neo4j._driver.session() as s:
        s.run("CREATE (:Envio {id: $id})", id=fantasma)

    contenedor.chequeo_de_consistencia.reconstruir(borrar_antes=False)
    assert fantasma in contenedor.proyector_neo4j.ids_de_etiqueta("Envio")

    contenedor.chequeo_de_consistencia.reconstruir(borrar_antes=True)
    assert fantasma not in contenedor.proyector_neo4j.ids_de_etiqueta("Envio")


def test_reconstruir_es_idempotente(contenedor):
    contenedor.chequeo_de_consistencia.reconstruir(borrar_antes=True)
    primero = {e: len(contenedor.proyector_neo4j.ids_de_etiqueta(e)) for e in ETIQUETAS.values()}
    contenedor.chequeo_de_consistencia.reconstruir()
    segundo = {e: len(contenedor.proyector_neo4j.ids_de_etiqueta(e)) for e in ETIQUETAS.values()}
    assert primero == segundo


def test_reconstruir_devuelve_lo_que_proyecto(contenedor):
    proyectados = contenedor.chequeo_de_consistencia.reconstruir()
    with contenedor.unidad_de_trabajo as uow:
        for agregado, cantidad in proyectados.items():
            assert cantidad == len(uow.consistencia.ids_de(agregado))


# --- Las consultas del enunciado sobre el grafo reconstruido ----------------


def test_ruta_completa_de_un_envio(contenedor):
    with contenedor.proyector_neo4j._driver.session() as s:
        tramos = s.run(
            """MATCH (e:Envio {id: $id})-[:TIENE_TRAMO]->(t:Tramo)
               MATCH (t)-[:DESDE]->(a:Ubicacion), (t)-[:HASTA]->(b:Ubicacion)
               RETURN t.orden AS orden, a.nombre AS desde, b.nombre AS hasta
               ORDER BY t.orden""",
            id="a0000000-0000-0000-0000-000000000001",
        ).data()
    assert [t["orden"] for t in tramos] == [1, 2]
    assert tramos[0]["hasta"] == tramos[1]["desde"]  # el recorrido es continuo


def test_red_cliente_operador_envio(contenedor):
    """Los tres saltos que justifican Neo4j: Envio -> Tramo -> Vehiculo <- Operador."""
    with contenedor.proyector_neo4j._driver.session() as s:
        filas = s.run(
            """MATCH (c:Cliente)-[:SOLICITA]->(e:Envio)-[:TIENE_TRAMO]->(:Tramo)
                     -[:UTILIZA]->(:Vehiculo)<-[:OPERA]-(o:Operador)
               RETURN DISTINCT c.razon_social AS cliente, o.razon_social AS operador"""
        ).data()
    assert filas
    assert all(f["cliente"] and f["operador"] for f in filas)


def test_historial_de_movimientos_de_un_contenedor(contenedor):
    with contenedor.proyector_neo4j._driver.session() as s:
        filas = s.run(
            """MATCH (co:Contenedor {id: $id})<-[:INCLUYE]-(e:Envio)
               RETURN e.id AS envio, e.estado AS estado""",
            id="70000000-0000-0000-0000-000000000001",
        ).data()
    # Ese contenedor viajo en dos envios distintos (relacion N:M historica).
    assert len(filas) == 2
