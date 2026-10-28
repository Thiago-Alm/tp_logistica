"""Cache de reportes en Redis (D44): la cache es un atajo, nunca una dependencia.

Las pruebas del servicio usan una cache en memoria y una UnidadDeTrabajo falsa
que cuenta cuantas veces se consulto PostgreSQL. Las del repositorio van contra
un Redis real y se saltean si no esta arriba.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from redis import Redis
from redis.exceptions import ConnectionError, TimeoutError

from logistica.config import settings
from logistica.domain.envio import EstadoEnvio
from logistica.domain.reportes import (
    ConteoEnviosPorEstado,
    ConteoEnviosPorPais,
    VolumenPorCliente,
)
from logistica.domain.tramo import MedioTransporte
from logistica.exceptions import ErrorDePersistencia, ValidacionError
from logistica.infrastructure.redis.cache_reportes_repository import (
    RedisCacheReportesRepository,
)
from logistica.repositories.cache_reportes_repository import CacheReportesRepository
from logistica.services.reporte_service import ReporteService

DESDE = datetime(2026, 10, 1, tzinfo=timezone.utc)
HASTA = datetime(2026, 10, 31, tzinfo=timezone.utc)


class _CacheEnMemoria(CacheReportesRepository):
    def __init__(self, falla_lectura=False, falla_escritura=False):
        self.datos = {}
        self.ttls = {}
        self._falla_lectura = falla_lectura
        self._falla_escritura = falla_escritura

    def obtener(self, clave):
        if self._falla_lectura:
            raise ErrorDePersistencia("Redis caido")
        return self.datos.get(clave)

    def guardar(self, clave, contenido, ttl_segundos):
        if self._falla_escritura:
            raise ErrorDePersistencia("Redis caido")
        self.datos[clave] = contenido
        self.ttls[clave] = ttl_segundos


class _ReportesEnvio:
    def __init__(self):
        self.consultas = 0
        self.por_estado = [ConteoEnviosPorEstado(EstadoEnvio.ENTREGADO, 3)]
        self.promedio = timedelta(days=4, hours=6, microseconds=15)
        self.ranking = [VolumenPorCliente(uuid4(), "AgroGlobal", Decimal("12.345"))]

    def envios_por_pais(self, desde, hasta):
        self.consultas += 1
        return [ConteoEnviosPorPais("Brasil", 2)]

    def envios_por_estado(self, desde, hasta):
        self.consultas += 1
        return self.por_estado

    def tiempo_promedio_de_entrega(self, desde, hasta):
        self.consultas += 1
        return self.promedio

    def ranking_clientes_por_volumen(self, limite, desde, hasta):
        self.consultas += 1
        return self.ranking


class _Tramos:
    def __init__(self):
        self.consultas = 0

    def costo_por_medio_de_transporte(self):
        self.consultas += 1
        return {MedioTransporte.MARITIMO: Decimal("1500.10")}


class _Uow:
    def __init__(self):
        self.reportes_envio = _ReportesEnvio()
        self.tramos = _Tramos()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _servicio(cache):
    uow = _Uow()
    return ReporteService(uow, cache=cache), uow


# --- El atajo ----------------------------------------------------------------


def test_la_segunda_consulta_sale_de_la_cache():
    cache = _CacheEnMemoria()
    servicio, uow = _servicio(cache)

    primera = servicio.envios_por_estado(DESDE, HASTA)
    segunda = servicio.envios_por_estado(DESDE, HASTA)

    assert primera == segunda
    assert uow.reportes_envio.consultas == 1


def test_parametros_distintos_no_comparten_clave():
    cache = _CacheEnMemoria()
    servicio, uow = _servicio(cache)

    servicio.envios_por_estado(DESDE, HASTA)
    servicio.envios_por_estado(DESDE, HASTA + timedelta(days=1))

    assert uow.reportes_envio.consultas == 2
    assert len(cache.datos) == 2


def test_la_clave_es_versionada_y_vence_en_60_segundos():
    cache = _CacheEnMemoria()
    servicio, _ = _servicio(cache)
    servicio.envios_por_estado(DESDE, HASTA)

    [clave] = cache.datos
    assert clave.startswith("cache:reportes:v1:envios_por_estado:")
    assert cache.ttls[clave] == 60


def test_envios_por_pais_tambien_se_cachea():
    cache = _CacheEnMemoria()
    servicio, uow = _servicio(cache)

    servicio.envios_por_pais(DESDE, HASTA)
    assert servicio.envios_por_pais(DESDE, HASTA) == [ConteoEnviosPorPais("Brasil", 2)]
    assert uow.reportes_envio.consultas == 1


# --- Los tipos vuelven como objetos del dominio -------------------------------


def test_el_volumen_vuelve_como_decimal_sin_perder_precision():
    servicio, uow = _servicio(_CacheEnMemoria())
    servicio.ranking_clientes_por_volumen(5, DESDE, HASTA)
    [fila] = servicio.ranking_clientes_por_volumen(5, DESDE, HASTA)

    assert fila == uow.reportes_envio.ranking[0]
    assert isinstance(fila.volumen, Decimal)


def test_la_duracion_vuelve_como_timedelta_exacto():
    servicio, uow = _servicio(_CacheEnMemoria())
    servicio.tiempo_promedio_de_entrega(DESDE, HASTA)
    assert servicio.tiempo_promedio_de_entrega(DESDE, HASTA) == uow.reportes_envio.promedio


def test_los_costos_vuelven_con_su_enumeracion_y_decimal():
    servicio, uow = _servicio(_CacheEnMemoria())
    servicio.costos_por_tipo_de_transporte()
    costos = servicio.costos_por_tipo_de_transporte()

    assert costos == {MedioTransporte.MARITIMO: Decimal("1500.10")}
    assert uow.tramos.consultas == 1


def test_el_estado_vuelve_como_enumeracion():
    servicio, _ = _servicio(_CacheEnMemoria())
    servicio.envios_por_estado(DESDE, HASTA)
    [fila] = servicio.envios_por_estado(DESDE, HASTA)
    assert fila.estado is EstadoEnvio.ENTREGADO


# --- Se cachea tambien "no hay datos" ------------------------------------------


def test_una_lista_vacia_tambien_se_cachea():
    servicio, uow = _servicio(_CacheEnMemoria())
    uow.reportes_envio.por_estado = []

    assert servicio.envios_por_estado(DESDE, HASTA) == []
    assert servicio.envios_por_estado(DESDE, HASTA) == []
    assert uow.reportes_envio.consultas == 1


def test_un_promedio_none_tambien_se_cachea():
    servicio, uow = _servicio(_CacheEnMemoria())
    uow.reportes_envio.promedio = None

    assert servicio.tiempo_promedio_de_entrega(DESDE, HASTA) is None
    assert servicio.tiempo_promedio_de_entrega(DESDE, HASTA) is None
    assert uow.reportes_envio.consultas == 1


# --- La cache nunca rompe el reporte -------------------------------------------


def test_si_falla_la_lectura_se_consulta_postgres():
    servicio, uow = _servicio(_CacheEnMemoria(falla_lectura=True))
    assert servicio.envios_por_estado(DESDE, HASTA) == uow.reportes_envio.por_estado
    assert servicio.envios_por_pais(DESDE, HASTA) == [ConteoEnviosPorPais("Brasil", 2)]


def test_si_falla_la_escritura_el_reporte_se_devuelve_igual():
    servicio, uow = _servicio(_CacheEnMemoria(falla_escritura=True))
    assert servicio.envios_por_estado(DESDE, HASTA) == uow.reportes_envio.por_estado
    assert servicio.envios_por_pais(DESDE, HASTA) == [ConteoEnviosPorPais("Brasil", 2)]


@pytest.mark.parametrize(
    "contenido",
    ["no es json", '{"no": "es lista"}', '[{"estado": "INVENTADO", "cantidad": 1}]',
     '[{"estado": "ENTREGADO", "cantidad": -1}]'],
)
def test_un_contenido_invalido_en_la_cache_se_ignora(contenido):
    cache = _CacheEnMemoria()
    servicio, uow = _servicio(cache)
    servicio.envios_por_estado(DESDE, HASTA)
    [clave] = cache.datos
    cache.datos[clave] = contenido

    assert servicio.envios_por_estado(DESDE, HASTA) == uow.reportes_envio.por_estado
    assert uow.reportes_envio.consultas == 2


def test_sin_cache_el_servicio_funciona_igual():
    servicio = ReporteService(_Uow())
    assert servicio.envios_por_estado(DESDE, HASTA)


# --- Repositorio contra Redis real ---------------------------------------------


@pytest.fixture
def cache_redis():
    cliente = Redis(
        host=settings.redis_host, port=settings.redis_port,
        socket_connect_timeout=1, socket_timeout=1,
    )
    clave = f"cache:reportes:test:{uuid4()}"
    try:
        try:
            cliente.ping()
        except (ConnectionError, TimeoutError):
            pytest.skip("Redis no disponible: docker compose up -d redis")
        yield RedisCacheReportesRepository(cliente), cliente, clave
    finally:
        cliente.delete(clave)
        cliente.close()


def test_guarda_y_lee_texto_con_vencimiento(cache_redis):
    repositorio, cliente, clave = cache_redis
    repositorio.guardar(clave, '[{"pais": "Perú"}]', ttl_segundos=60)

    assert repositorio.obtener(clave) == '[{"pais": "Perú"}]'
    assert 0 < cliente.ttl(clave) <= 60


def test_una_clave_inexistente_devuelve_none(cache_redis):
    repositorio, _, clave = cache_redis
    assert repositorio.obtener(clave) is None


@pytest.mark.parametrize("ttl", [0, -1, True, 1.5])
def test_el_vencimiento_tiene_que_ser_un_entero_positivo(cache_redis, ttl):
    repositorio, cliente, clave = cache_redis
    with pytest.raises(ValidacionError):
        repositorio.guardar(clave, "x", ttl_segundos=ttl)
    assert cliente.exists(clave) == 0
