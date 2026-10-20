"""Carga el lote de sensores en PostgreSQL."""

import json
import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv


def main():
    raiz = Path(__file__).resolve().parent.parent
    load_dotenv(raiz / ".env")

    archivo = raiz / "scripts" / "datos_generados" / "sensores.json"

    with archivo.open(encoding="utf-8") as entrada:
        sensores = json.load(entrada)

    insertados = 0

    with psycopg.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        dbname=os.getenv("POSTGRES_DB", "logistica"),
        user=os.getenv("POSTGRES_USER", "logistica"),
        password=os.environ["POSTGRES_PASSWORD"],
    ) as conexion, conexion.cursor() as cursor:
        for sensor in sensores:
            cursor.execute(
                """
                    INSERT INTO sensor (
                        id,
                        contenedor_id,
                        numero_serie,
                        modelo,
                        tipo,
                        intervalo_reporte_segundos,
                        estado
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                (
                    sensor["id"],
                    sensor["contenedor_id"],
                    sensor["numero_serie"],
                    sensor["modelo"],
                    sensor["tipo"],
                    sensor["intervalo_reporte_segundos"],
                    sensor["estado"],
                ),
            )
            insertados += cursor.rowcount

    print(f"Sensores nuevos insertados: {insertados}")


if __name__ == "__main__":
    main()