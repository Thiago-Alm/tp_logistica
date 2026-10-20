"""Tests de integracion de IncidenteRepository contra MongoDB.

Necesitan el contenedor de Mongo arriba y la base `logistica` creada con
scripts/mongo/mongo_modelo.js (para probar tambien los validadores). Si no hay
conexion o falta la coleccion, se saltean.
"""
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from logistica.config import settings
from logistica.domain.incidente import (
    ContextoEnvio,
    EstadoIncidente,
    Incidente,
    SeveridadIncidente,
    TipoIncidente,
)
from logistica.exceptions import ErrorDePersistencia, NoEncontrado, ValidacionError
from logistica.infrastructure.mongo.conexion import cerrar, conectar, traducir_errores
from logistica.infrastructure.mongo.incidente_repository import MongoIncidenteRepository
from logistica.repositories.incidente_repository import AgrupacionIncidentes

FECHA = datetime(2026, 10, 19, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def base():
    try:
        b = conectar(settings)
    except ErrorDePersistencia:
        pytest.skip("MongoDB no esta disponible")
    if "incidentes" not in b.list_collection_names():
        pytest.skip("Falta la coleccion: aplicar scripts/mongo/mongo_modelo.js")
    yield b
    cerrar(b)


@pytest.fixture
def creados(base):
    """Ids que crea el test: se borran al terminar."""
    ids: list = []
    yield ids
    base["incidentes"].delete_many({"_id": {"$in": ids}})


@pytest.fixture
def repo(base):
    return MongoIncidenteRepository(base)


def _incidente(creados, origen="BUE", destino="HAM", envio_id=None, **cambios) -> Incidente:
    datos = dict(
        id=uuid4(),
        envio_id=envio_id or uuid4(),
        contenedor_id=uuid4(),
        tipo=TipoIncidente.TEMPERATURA,
        severidad=SeveridadIncidente.ALTA,
        descripcion="Pico de temperatura",
        fecha=FECHA,
        contexto_envio=ContextoEnvio(
            cliente_id=uuid4(),
            origen=origen,
            destino=destino,
            pais_origen="Argentina",
            pais_destino="Alemania",
        ),
    )
    datos.update(cambios)
    incidente = Incidente(**datos)
    creados.append(incidente.id)
    return incidente


def test_guardar_y_obtener_devuelve_la_misma_entidad(repo, creados):
    original = _incidente(creados)
    repo.guardar(original)
    assert repo.obtener(original.id) == original


def test_obtener_un_incidente_inexistente_devuelve_none(repo):
    assert repo.obtener(uuid4()) is None


def test_actualizar_persiste_el_cambio_de_estado_y_su_historial(repo, creados):
    incidente = _incidente(creados)
    repo.guardar(incidente)

    incidente.pasar_a(EstadoIncidente.EN_ANALISIS, usuario_id=uuid4())
    repo.actualizar(incidente)

    leido = repo.obtener(incidente.id)
    assert leido.estado is EstadoIncidente.EN_ANALISIS
    assert [c.estado for c in leido.historial_estados] == [
        EstadoIncidente.ABIERTO,
        EstadoIncidente.EN_ANALISIS,
    ]


def test_actualizar_un_incidente_inexistente_lanza_no_encontrado(repo, creados):
    with pytest.raises(NoEncontrado):
        repo.actualizar(_incidente(creados))


def test_listar_abiertos_incluye_abierto_y_en_analisis_y_excluye_el_resto(repo, creados):
    abierto = _incidente(creados)
    en_analisis = _incidente(creados, estado=EstadoIncidente.EN_ANALISIS)
    resuelto = _incidente(creados, estado=EstadoIncidente.RESUELTO)
    cerrado = _incidente(creados, estado=EstadoIncidente.CERRADO)
    for i in (abierto, en_analisis, resuelto, cerrado):
        repo.guardar(i)

    ids = {i.id for i in repo.listar_abiertos()}
    assert abierto.id in ids and en_analisis.id in ids
    assert resuelto.id not in ids and cerrado.id not in ids


def test_listar_por_envio(repo, creados):
    envio_id = uuid4()
    uno = _incidente(creados, envio_id=envio_id)
    dos = _incidente(creados, envio_id=envio_id)
    otro = _incidente(creados)
    for i in (uno, dos, otro):
        repo.guardar(i)
    assert {i.id for i in repo.listar_por_envio(envio_id)} == {uno.id, dos.id}


def test_ranking_de_rutas_cuenta_y_ordena(repo, creados):
    # Rutas unicas por test: la base tiene otros incidentes de prueba.
    ruta_a = (uuid4().hex[:6], uuid4().hex[:6])
    ruta_b = (uuid4().hex[:6], uuid4().hex[:6])
    for _ in range(2):
        repo.guardar(_incidente(creados, origen=ruta_a[0], destino=ruta_a[1]))
    repo.guardar(_incidente(creados, origen=ruta_b[0], destino=ruta_b[1]))

    ranking = repo.ranking_de_rutas(limite=1000)
    totales = {fila.ruta: fila.cantidad for fila in ranking}
    clave_a, clave_b = f"{ruta_a[0]}->{ruta_a[1]}", f"{ruta_b[0]}->{ruta_b[1]}"
    assert totales[clave_a] == 2
    assert totales[clave_b] == 1
    rutas = [fila.ruta for fila in ranking]
    assert rutas.index(clave_a) < rutas.index(clave_b)


def test_contar_agrupado_por_cliente_devuelve_el_uuid_como_texto(repo, creados):
    incidente = _incidente(creados)
    repo.guardar(incidente)
    conteos = repo.contar_agrupado(AgrupacionIncidentes.CLIENTE)
    totales = {fila.grupo: fila.cantidad for fila in conteos}
    assert totales[str(incidente.contexto_envio.cliente_id)] == 1


def test_el_validador_de_la_coleccion_rechaza_un_documento_invalido(base, creados):
    """Comprueba que los validadores de scripts/mongo estan activos y que el error
    de Mongo se traduce a un error del dominio."""
    id_invalido = uuid4()
    creados.append(id_invalido)

    @traducir_errores
    def insertar_invalido():
        base["incidentes"].insert_one({"_id": id_invalido, "tipo": "NO_EXISTE"})

    with pytest.raises(ValidacionError):
        insertar_invalido()
