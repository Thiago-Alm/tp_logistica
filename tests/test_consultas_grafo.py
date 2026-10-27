"""Tests de las tres consultas avanzadas del enunciado, sobre Neo4j real.

Se saltean solos si las bases no estan disponibles. El grafo se reconstruye
desde PostgreSQL antes de correrlos, asi que no dependen de que el worker haya
propagado nada.
"""
from uuid import UUID, uuid4

import pytest

from logistica.container import Contenedor
from logistica.exceptions import ErrorDePersistencia

# Ids de scripts/postgres/02_datos_prueba.sql
ENVIO_ENTREGADO = UUID("a0000000-0000-0000-0000-000000000001")  # 2 tramos maritimos
CLIENTE = UUID("20000000-0000-0000-0000-000000000001")  # AgroGlobal, 3 envios
CONTENEDOR = UUID("70000000-0000-0000-0000-000000000001")  # viajo en 2 envios


@pytest.fixture(scope="module")
def contenedor():
    c = Contenedor(configurar_logging=False)
    try:
        c.clientes.listar()
        c.proyector_neo4j.ids_de_etiqueta("Envio")
    except ErrorDePersistencia:
        pytest.skip("PostgreSQL o Neo4j no disponibles: docker compose up -d")
    c.chequeo_de_consistencia.reconstruir(borrar_antes=True)
    return c


# --- Ruta completa de un envio ---------------------------------------------


def test_la_ruta_viene_ordenada_y_es_continua(contenedor):
    tramos = contenedor.consultas_grafo.ruta_de_envio(ENVIO_ENTREGADO)
    assert [t.orden for t in tramos] == [1, 2]
    # El destino de un tramo es el origen del siguiente: el recorrido no tiene saltos.
    assert tramos[0].destino == tramos[1].origen


def test_la_ruta_trae_el_vehiculo_y_el_medio(contenedor):
    tramos = contenedor.consultas_grafo.ruta_de_envio(ENVIO_ENTREGADO)
    assert all(t.medio_transporte == "MARITIMO" for t in tramos)
    assert all(t.vehiculo for t in tramos)


def test_un_envio_inexistente_devuelve_vacio(contenedor):
    """Una consulta sin resultados no es un error: devuelve una lista vacia."""
    assert contenedor.consultas_grafo.ruta_de_envio(uuid4()) == []


# --- Red cliente - operador - envio ----------------------------------------


def test_la_red_recorre_los_tres_saltos(contenedor):
    """Envio -> Tramo -> Vehiculo <- Operador. Es el camino que justifica Neo4j:
    en SQL seria un join de cuatro tablas."""
    relaciones = contenedor.consultas_grafo.red_de_cliente(CLIENTE)
    assert relaciones
    assert all(r.cliente_id == str(CLIENTE) for r in relaciones)
    assert any(r.operador for r in relaciones)


def test_la_red_devuelve_mas_de_un_operador_por_cliente(contenedor):
    """Un cliente puede operar con varias navieras o transportistas."""
    relaciones = contenedor.consultas_grafo.red_de_cliente(CLIENTE)
    operadores = {r.operador for r in relaciones if r.operador}
    assert len(operadores) >= 2


def test_un_cliente_inexistente_devuelve_vacio(contenedor):
    assert contenedor.consultas_grafo.red_de_cliente(uuid4()) == []


# --- Movimientos de un contenedor ------------------------------------------


def test_los_movimientos_atraviesan_varios_envios(contenedor):
    """El contenedor 001 viajo en dos envios distintos: la relacion N:M es
    historica, y el historial tiene que cubrir los dos."""
    movimientos = contenedor.consultas_grafo.movimientos_de_contenedor(CONTENEDOR)
    assert movimientos
    assert len({m.envio_id for m in movimientos}) >= 2


def test_los_movimientos_traen_origen_y_destino(contenedor):
    movimientos = contenedor.consultas_grafo.movimientos_de_contenedor(CONTENEDOR)
    assert all(m.origen and m.destino for m in movimientos)
    assert all(m.contenedor_id == str(CONTENEDOR) for m in movimientos)


def test_un_contenedor_sin_envios_devuelve_vacio(contenedor):
    assert contenedor.consultas_grafo.movimientos_de_contenedor(uuid4()) == []


def test_el_grafo_no_tiene_la_relacion_recorre(contenedor):
    """Regresion: la consulta de movimientos usaba Contenedor-RECORRE->Tramo,
    que ningun proyector crea, con lo cual devolvia siempre vacio sin avisar.
    Ahora va por Contenedor <- INCLUYE - Envio -> TIENE_TRAMO (D37)."""
    with contenedor.proyector_neo4j._driver.session() as sesion:
        total = sesion.run("MATCH ()-[r:RECORRE]->() RETURN count(r) AS n").single()["n"]
    assert total == 0
    assert contenedor.consultas_grafo.movimientos_de_contenedor(CONTENEDOR)
