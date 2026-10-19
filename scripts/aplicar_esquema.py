"""Crea el esquema de PostgreSQL y carga los datos de prueba.

    python scripts/aplicar_esquema.py           # solo si la base esta vacia
    python scripts/aplicar_esquema.py --reiniciar   # borra todo y vuelve a crear

Por que hace falta, si docker-compose monta los scripts en
/docker-entrypoint-initdb.d: esa carpeta SOLO se ejecuta la primera vez que se
crea el volumen de datos. Si el volumen ya existia (porque Postgres se levanto
antes de que los scripts estuvieran escritos), los scripts nunca corren y la
base queda vacia sin que nadie se entere.
"""
import sys
from pathlib import Path

import psycopg

from logistica.config import settings
from logistica.infrastructure.postgres.conexion import armar_dsn

RAIZ = Path(__file__).resolve().parent / "postgres"
ARCHIVOS = ["01_schema.sql", "02_datos_prueba.sql"]


def hay_tablas(conexion: psycopg.Connection) -> bool:
    total = conexion.execute(
        "select count(*) from information_schema.tables where table_schema = 'public'"
    ).fetchone()[0]
    return total > 0


def main() -> int:
    reiniciar = "--reiniciar" in sys.argv
    try:
        conexion = psycopg.connect(armar_dsn(settings), autocommit=True, connect_timeout=10)
    except psycopg.Error as error:
        print(f"[ERROR] No se pudo conectar a PostgreSQL: {error}")
        print("        Revisa que los contenedores esten arriba: docker compose up -d")
        return 1

    with conexion:
        if hay_tablas(conexion):
            if not reiniciar:
                print("[AVISO] La base ya tiene tablas. Usa --reiniciar para rehacerla.")
                return 0
            print("Borrando el esquema actual...")
            conexion.execute("drop schema public cascade")
            conexion.execute("create schema public")

        for nombre in ARCHIVOS:
            sql = (RAIZ / nombre).read_text(encoding="utf-8")
            conexion.execute(sql)
            print(f"[OK] {nombre}")

        tablas = conexion.execute(
            "select count(*) from information_schema.tables where table_schema = 'public'"
        ).fetchone()[0]
        print(f"\n{tablas} tablas creadas en la base '{settings.postgres_db}'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
