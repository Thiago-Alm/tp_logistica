"""Tests de integracion de UmbralRepository y AlertaRepository contra MongoDB.

Necesitan el contenedor de Mongo arriba y la base `logistica` creada con
scripts/mongo/mongo_modelo.js y scripts/mongo/mongo_umbrales.js (para probar tambien
los validadores y los indices unicos). Si no hay conexion o faltan las colecciones,
se saltean.
"""
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from logistica.config import settings
from logistica.domain.alerta import Alerta, EstadoAlerta, TipoAlerta
from logistica.domain.lectura import Lectura
from logistica.domain.umbral import MagnitudUmbral, Umbral
from logistica.exceptions import ConflictoDeDatos, ErrorDePersistencia
from logistica.infrastructure.mongo.alerta_repository import MongoAlertaRepository
from logistica.infrastructure.mongo.conexion import cerrar, conectar
from logistica.infrastructure.mongo.umbral_repository import MongoUmbralRepository

MOMENTO = datetime(2026, 10, 20, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def base():
    try:
        b = conectar(settings)
    except ErrorDePersistencia:
        pytest.skip("MongoDB no esta disponible")
    faltan = {"umbrales", "alertas"} - set(b.list_collection_names())
    if faltan:
        pytest.skip(f"Faltan colecciones {sorted(faltan)}: aplicar los scripts de scripts/mongo")
    yield b
    cerrar(b)


@pytest.fixture
def umbrales_creados(base):
    ids: list = []
    yield ids
    base["umbrales"].delete_many({"_id": {"$in": ids}})


@pytest.fixture
def alertas_creadas(base):
    ids: list = []
    yield ids
    base["alertas"].delete_many({"_id": {"$in": ids}})


def _umbral(umbrales_creados, tipo="DRY_20", magnitud=MagnitudUmbral.HUMEDAD, **cambios) -> Umbral:
    # Se usan combinaciones que la semilla no carga (solo trae TEMPERATURA), para no
    # pisar los umbrales reales.
    datos = dict(
        id=uuid4(), tipo_contenedor=tipo, magnitud=magnitud, minimo=30.0, maximo=70.0,
        unidad="%", descripcion="prueba",
    )
    datos.update(cambios)
    umbral = Umbral(**datos)
    umbrales_creados.append(umbral.id)
    return umbral


def _alerta(alertas_creadas, temperatura=-10.0, momento=MOMENTO) -> Alerta:
    lectura = Lectura(
        sensor_id=uuid4(), contenedor_id=uuid4(), momento=momento, temperatura=temperatura,
        humedad=60.0, vibracion=0.2, latitud=-34.6, longitud=-58.4, bateria=90, envio_id=uuid4(),
    )
    umbral = Umbral(
        id=uuid4(), tipo_contenedor="REEFER_40", magnitud=MagnitudUmbral.TEMPERATURA,
        minimo=-25.0, maximo=-15.0, unidad="C",
    )
    alerta = Alerta.por_umbral(lectura, TipoAlerta.TEMPERATURA, temperatura, umbral)
    alertas_creadas.append(alerta.id)
    return alerta


# -- Umbrales ----------------------------------------------------------------


def test_guardar_y_obtener_un_umbral(base, umbrales_creados):
    repo = MongoUmbralRepository(base)
    original = _umbral(umbrales_creados)
    repo.guardar(original)
    assert repo.obtener("DRY_20", MagnitudUmbral.HUMEDAD) == original


def test_guardar_dos_veces_el_mismo_umbral_lo_actualiza(base, umbrales_creados):
    repo = MongoUmbralRepository(base)
    original = _umbral(umbrales_creados)
    repo.guardar(original)
    original.maximo = 80.0
    repo.guardar(original)
    assert repo.obtener("DRY_20", MagnitudUmbral.HUMEDAD).maximo == 80.0


def test_obtener_un_umbral_inexistente_devuelve_none(base):
    assert MongoUmbralRepository(base).obtener("DRY_20", MagnitudUmbral.VIBRACION) is None


def test_no_puede_haber_dos_umbrales_para_el_mismo_tipo_y_magnitud(base, umbrales_creados):
    repo = MongoUmbralRepository(base)
    repo.guardar(_umbral(umbrales_creados))
    with pytest.raises(ConflictoDeDatos):
        repo.guardar(_umbral(umbrales_creados))  # otro id, misma combinacion


def test_la_semilla_trae_el_umbral_de_temperatura_de_un_reefer(base):
    umbral = MongoUmbralRepository(base).obtener("REEFER_40", MagnitudUmbral.TEMPERATURA)
    if umbral is None:
        pytest.skip("Falta cargar scripts/mongo/mongo_umbrales.js")
    assert umbral.minimo < umbral.maximo


# -- Alertas -----------------------------------------------------------------


def test_guardar_y_obtener_una_alerta_devuelve_la_misma_entidad(base, alertas_creadas):
    repo = MongoAlertaRepository(base)
    original = _alerta(alertas_creadas)
    assert repo.guardar(original) is True
    assert repo.obtener(original.id) == original


def test_guardar_dos_veces_la_misma_alerta_no_la_duplica(base, alertas_creadas):
    repo = MongoAlertaRepository(base)
    alerta = _alerta(alertas_creadas)
    assert repo.guardar(alerta) is True
    assert repo.guardar(alerta) is False
    assert base["alertas"].count_documents({"_id": alerta.id}) == 1


def test_una_alerta_sin_envio_ni_detalle_tambien_se_guarda(base, alertas_creadas):
    repo = MongoAlertaRepository(base)
    original = _alerta(alertas_creadas)
    original.envio_id = None
    original.detalle = None
    assert repo.guardar(original) is True
    assert repo.obtener(original.id) == original


def test_listar_abiertas_excluye_las_cerradas(base, alertas_creadas):
    repo = MongoAlertaRepository(base)
    abierta, cerrada = _alerta(alertas_creadas), _alerta(alertas_creadas)
    cerrada.estado = EstadoAlerta.CERRADA
    repo.guardar(abierta)
    repo.guardar(cerrada)
    ids = {a.id for a in repo.listar_abiertas()}
    assert abierta.id in ids
    assert cerrada.id not in ids


def test_listar_por_sensor_devuelve_la_mas_reciente_primero(base, alertas_creadas):
    repo = MongoAlertaRepository(base)
    vieja = _alerta(alertas_creadas, momento=MOMENTO)
    nueva = _alerta(alertas_creadas, momento=MOMENTO.replace(hour=15))
    # Las dos del mismo sensor.
    nueva.sensor_id = vieja.sensor_id
    repo.guardar(vieja)
    repo.guardar(nueva)
    assert [a.id for a in repo.listar_por_sensor(vieja.sensor_id)] == [nueva.id, vieja.id]
