"""Carga el lote de contenedores en PostgreSQL."""

import json
import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv


def main():
    raiz = Path(__file__).resolve().parent.parent
    load_dotenv(raiz / ".env")

    archivo = raiz / "scripts" / "datos_generados" / "contenedores.json"
    with archivo.open(encoding="utf-8") as entrada:
        contenedores = json.load(entrada)

    insertados = 0

    with psycopg.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        dbname=os.getenv("POSTGRES_DB", "logistica"),
        user=os.getenv("POSTGRES_USER", "logistica"),
        password=os.environ["POSTGRES_PASSWORD"],
    ) as conexion, conexion.cursor() as cursor:
        for contenedor in contenedores:
            cursor.execute(
                """
                    INSERT INTO contenedor
                        (id, codigo_iso, tipo, capacidad, estado)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                (
                    contenedor["id"],
                    contenedor["codigo_iso"],
                    contenedor["tipo"],
                    contenedor["capacidad"],
                    contenedor["estado"],
                ),
            )
            insertados += cursor.rowcount

    print(f"Contenedores nuevos insertados: {insertados}")


if __name__ == "__main__":
    main()