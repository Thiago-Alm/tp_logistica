"""Verifica que las cinco bases del TP respondan, y con que version.

Uso (con el venv activado, desde la raiz del proyecto):

    python scripts/chequear_conexiones.py

Devuelve codigo de salida 0 si las cinco responden, 1 si falla alguna.

Por que mira la version y no solo si conecta: un contenedor puede estar "Up" y
aun asi no ser el que recibe las conexiones, si hay otro servicio ocupando el
mismo puerto en la maquina. La version delata ese caso. Comparar con lo que
declara docker-compose.yml: postgres 16, mongo 7, neo4j 5, redis 7, cassandra 5.
"""
import sys

from logistica.config import settings

ANCHO = 12


def _postgres() -> str:
    import psycopg

    dsn = (
        f"host={settings.postgres_host} port={settings.postgres_port} "
        f"user={settings.postgres_user} password={settings.postgres_password} "
        f"dbname={settings.postgres_db}"
    )
    with psycopg.connect(dsn, connect_timeout=8) as conexion:
        version = conexion.execute("select version()").fetchone()[0]
    return version.split(",")[0]


def _mongo() -> str:
    from pymongo import MongoClient

    cliente = MongoClient(settings.mongo_uri, serverSelectionTimeoutMS=8000)
    try:
        return "MongoDB " + cliente.server_info()["version"]
    finally:
        cliente.close()


def _neo4j() -> str:
    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(
        settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)
    )
    try:
        with driver.session() as sesion:
            fila = sesion.run(
                "call dbms.components() yield name, versions "
                "return name, versions[0] as version"
            ).single()
        return f"{fila['name']} {fila['version']}"
    finally:
        driver.close()


def _redis() -> str:
    import redis

    cliente = redis.Redis(
        host=settings.redis_host, port=settings.redis_port, socket_timeout=8
    )
    try:
        return "Redis " + cliente.info()["redis_version"]
    finally:
        cliente.close()


def _cassandra() -> str:
    from cassandra.cluster import Cluster

    cluster = Cluster(
        [settings.cassandra_host], port=settings.cassandra_port, connect_timeout=15
    )
    try:
        sesion = cluster.connect()
        fila = sesion.execute("select release_version from system.local").one()
        return "Cassandra " + fila.release_version
    finally:
        cluster.shutdown()


PRUEBAS = [
    ("PostgreSQL", _postgres),
    ("MongoDB", _mongo),
    ("Neo4j", _neo4j),
    ("Redis", _redis),
    ("Cassandra", _cassandra),
]


def main() -> int:
    responden = 0
    for nombre, probar in PRUEBAS:
        try:
            print(f"[OK]    {nombre:<{ANCHO}} {probar()}")
            responden += 1
        except Exception as error:  # noqa: BLE001 - se reporta cualquier falla
            print(f"[FALLA] {nombre:<{ANCHO}} {type(error).__name__}: {str(error)[:150]}")

    print(f"\n{responden}/{len(PRUEBAS)} bases responden")
    if responden < len(PRUEBAS):
        print("Revisar: docker compose ps, y que ningun otro servicio ocupe el puerto.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
