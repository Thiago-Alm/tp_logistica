"""Implementacion de ConsistenciaRepository sobre PostgreSQL."""
from typing import Any
from uuid import UUID

import psycopg

from logistica.domain.evento_outbox import TipoAgregado
from logistica.infrastructure.postgres.conexion import traducir_errores
from logistica.repositories.consistencia_repository import ConsistenciaRepository

# Tabla de la que sale cada tipo de agregado.
TABLAS = {
    TipoAgregado.CLIENTE: "cliente",
    TipoAgregado.OPERADOR: "operador",
    TipoAgregado.PROVEEDOR: "proveedor",
    TipoAgregado.UBICACION: "ubicacion",
    TipoAgregado.VEHICULO: "vehiculo",
    TipoAgregado.CONTENEDOR: "contenedor",
    TipoAgregado.ENVIO: "envio",
    TipoAgregado.TRAMO: "tramo",
}

# Una consulta por tipo, devolviendo exactamente los campos del payload que
# espera el proyector. Los UUID y los Decimal se pasan a texto, igual que en
# sync/eventos.py, para que la resincronizacion y la propagacion por eventos
# produzcan el mismo resultado.
PROYECCION = {
    TipoAgregado.CLIENTE: """
        select id::text, razon_social, cuit, pais, estado from cliente""",
    TipoAgregado.OPERADOR: """
        select id::text, razon_social, pais, estado from operador""",
    TipoAgregado.UBICACION: """
        select id::text, nombre, tipo, pais, latitud::text, longitud::text
        from ubicacion""",
    TipoAgregado.VEHICULO: """
        select id::text, operador_id::text, identificacion, tipo,
               medio_transporte, estado
        from vehiculo""",
    TipoAgregado.CONTENEDOR: """
        select id::text, codigo_iso, tipo, estado from contenedor""",
    TipoAgregado.ENVIO: """
        select id::text, cliente_id::text, origen_id::text, destino_id::text,
               estado, prioridad, fecha_creacion::text
        from envio""",
    TipoAgregado.TRAMO: """
        select id::text, envio_id::text, vehiculo_id::text, origen_id::text,
               destino_id::text, orden, medio_transporte, costo::text
        from tramo""",
}


class PostgresConsistenciaRepository(ConsistenciaRepository):
    def __init__(self, conexion: psycopg.Connection) -> None:
        self._conexion = conexion

    @traducir_errores
    def ids_de(self, agregado: TipoAgregado) -> set[UUID]:
        tabla = TABLAS[agregado]
        filas = self._conexion.execute(f"select id from {tabla}").fetchall()
        return {f[0] for f in filas}

    @traducir_errores
    def filas_para_proyectar(self, agregado: TipoAgregado) -> list[dict[str, Any]]:
        consulta = PROYECCION.get(agregado)
        if consulta is None:
            return []
        with self._conexion.cursor() as cursor:
            cursor.execute(consulta)
            nombres = [c.name for c in cursor.description]
            return [dict(zip(nombres, fila, strict=True)) for fila in cursor.fetchall()]

    @traducir_errores
    def asignaciones_de_contenedores(self) -> list[dict[str, Any]]:
        filas = self._conexion.execute(
            """select envio_id::text, contenedor_id::text
               from envio_contenedor
               order by fecha_asignacion"""
        ).fetchall()
        return [{"envio_id": f[0], "contenedor_id": f[1]} for f in filas]
