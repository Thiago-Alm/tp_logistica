"""Implementacion de ReporteEnvioRepository sobre PostgreSQL.

Cada metodo es una agregacion SQL. Esto es lo que se justifico al elegir un
motor relacional para los reportes: agrupar y sumar sobre datos ya consolidados
es la operacion para la que el optimizador esta hecho.

Todos los metodos aceptan un rango opcional sobre `envio.fecha_creacion`,
porque el enunciado pide reportes parametrizados.
"""
from datetime import datetime, timedelta

import psycopg

from logistica.domain.envio import EstadoEnvio
from logistica.domain.reportes import (
    ConteoEnviosPorCliente,
    ConteoEnviosPorEstado,
    ConteoEnviosPorPais,
    TiemposDeEnvioPorCliente,
    VolumenPorCliente,
)
from logistica.infrastructure.postgres.conexion import traducir_errores
from logistica.repositories.reporte_envio_repository import ReporteEnvioRepository


def _rango(desde: datetime | None, hasta: datetime | None) -> tuple[str, list]:
    """Arma el filtro de fechas y sus parametros.

    Se construye asi, y no interpolando valores en el SQL, para que las fechas
    viajen siempre como parametros: interpolar texto en una consulta es la via
    de entrada de una inyeccion SQL.
    """
    condiciones: list[str] = []
    parametros: list = []
    if desde is not None:
        condiciones.append("e.fecha_creacion >= %s")
        parametros.append(desde)
    if hasta is not None:
        condiciones.append("e.fecha_creacion <= %s")
        parametros.append(hasta)
    sql = (" and " + " and ".join(condiciones)) if condiciones else ""
    return sql, parametros


class PostgresReporteEnvioRepository(ReporteEnvioRepository):
    def __init__(self, conexion: psycopg.Connection) -> None:
        self._conexion = conexion

    # --- Reportes operativos ---------------------------------------------

    @traducir_errores
    def envios_por_pais(
        self, desde: datetime | None = None, hasta: datetime | None = None
    ) -> list[ConteoEnviosPorPais]:
        filtro, parametros = _rango(desde, hasta)
        filas = self._conexion.execute(
            f"""select u.pais, count(*)
                from envio e
                join ubicacion u on u.id = e.destino_id
                where true {filtro}
                group by u.pais
                order by count(*) desc, u.pais""",
            parametros,
        ).fetchall()
        return [ConteoEnviosPorPais(pais=f[0], cantidad=f[1]) for f in filas]

    @traducir_errores
    def envios_por_estado(
        self, desde: datetime | None = None, hasta: datetime | None = None
    ) -> list[ConteoEnviosPorEstado]:
        filtro, parametros = _rango(desde, hasta)
        filas = self._conexion.execute(
            f"""select e.estado, count(*)
                from envio e
                where true {filtro}
                group by e.estado
                order by count(*) desc, e.estado""",
            parametros,
        ).fetchall()
        return [
            ConteoEnviosPorEstado(estado=EstadoEnvio(f[0]), cantidad=f[1]) for f in filas
        ]

    @traducir_errores
    def envios_por_cliente(
        self, desde: datetime | None = None, hasta: datetime | None = None
    ) -> list[ConteoEnviosPorCliente]:
        filtro, parametros = _rango(desde, hasta)
        filas = self._conexion.execute(
            f"""select c.id, c.razon_social, count(*)
                from envio e
                join cliente c on c.id = e.cliente_id
                where true {filtro}
                group by c.id, c.razon_social
                order by count(*) desc, c.razon_social""",
            parametros,
        ).fetchall()
        return [
            ConteoEnviosPorCliente(cliente_id=f[0], razon_social=f[1], cantidad=f[2])
            for f in filas
        ]

    # --- Reportes analiticos ---------------------------------------------

    @traducir_errores
    def tiempos_de_envio_por_cliente(
        self, desde: datetime | None = None, hasta: datetime | None = None
    ) -> list[TiemposDeEnvioPorCliente]:
        """Solo cuentan los envios ENTREGADOS: uno en curso todavia no tiene
        duracion. Los clientes sin entregas aparecen con minimo y maximo nulos,
        gracias al LEFT JOIN y a la condicion dentro del ON."""
        filtro, parametros = _rango(desde, hasta)
        filas = self._conexion.execute(
            f"""select c.id, c.razon_social,
                       min(e.fecha_llegada_real - e.fecha_creacion),
                       max(e.fecha_llegada_real - e.fecha_creacion)
                from cliente c
                left join envio e
                       on e.cliente_id = c.id
                      and e.estado = 'ENTREGADO' {filtro}
                group by c.id, c.razon_social
                order by c.razon_social""",
            parametros,
        ).fetchall()
        return [
            TiemposDeEnvioPorCliente(
                cliente_id=f[0], razon_social=f[1], minimo=f[2], maximo=f[3]
            )
            for f in filas
        ]

    @traducir_errores
    def tiempo_promedio_de_entrega(
        self, desde: datetime | None = None, hasta: datetime | None = None
    ) -> timedelta | None:
        filtro, parametros = _rango(desde, hasta)
        fila = self._conexion.execute(
            f"""select avg(e.fecha_llegada_real - e.fecha_creacion)
                from envio e
                where e.estado = 'ENTREGADO' {filtro}""",
            parametros,
        ).fetchone()
        return fila[0] if fila else None

    @traducir_errores
    def ranking_clientes_por_volumen(
        self,
        limite: int = 10,
        desde: datetime | None = None,
        hasta: datetime | None = None,
    ) -> list[VolumenPorCliente]:
        """El volumen transportado se mide sumando la capacidad de los
        contenedores asignados a los envios del cliente, via envio_contenedor."""
        filtro, parametros = _rango(desde, hasta)
        filas = self._conexion.execute(
            f"""select c.id, c.razon_social, coalesce(sum(co.capacidad), 0)
                from cliente c
                join envio e on e.cliente_id = c.id
                join envio_contenedor ec on ec.envio_id = e.id
                join contenedor co on co.id = ec.contenedor_id
                where true {filtro}
                group by c.id, c.razon_social
                order by sum(co.capacidad) desc
                limit %s""",
            [*parametros, limite],
        ).fetchall()
        return [
            VolumenPorCliente(cliente_id=f[0], razon_social=f[1], volumen=f[2])
            for f in filas
        ]
