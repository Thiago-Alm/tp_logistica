"""ABM de contenedores y las operaciones de contenedores de un envio."""
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from logistica.domain.contenedor import Contenedor, EstadoContenedor
from logistica.domain.envio import EstadoEnvio
from logistica.exceptions import ConflictoDeDatos, NoEncontrado, ValidacionError
from logistica.services.contenedor_service import ContenedorService


def nuevo_contenedor(**cambios) -> Contenedor:
    datos = dict(
        id=uuid4(),
        codigo_iso="MSKU1234567",
        tipo="DRY_40",
        capacidad=28.0,
        estado=EstadoContenedor.DISPONIBLE,
    )
    datos.update(cambios)
    return Contenedor(**datos)


def armar(existente=None):
    uow = MagicMock()
    uow.__enter__.return_value = uow
    uow.contenedores.obtener.return_value = existente
    uow.contenedores.obtener_por_codigo.return_value = None
    return ContenedorService(uow), uow


# --- Alta --------------------------------------------------------------------


def test_el_alta_normaliza_el_codigo_y_el_tipo():
    servicio, uow = armar()
    contenedor = servicio.alta("msku1234567", "dry_40", 28.0)
    assert contenedor.codigo_iso == "MSKU1234567"
    assert contenedor.tipo == "DRY_40"
    uow.contenedores.guardar.assert_called_once_with(contenedor)


def test_el_alta_publica_al_outbox_en_la_misma_transaccion():
    """D34: el contenedor es un nodo del grafo."""
    servicio, uow = armar()
    servicio.alta("MSKU1234567", "DRY_40", 28.0)
    uow.outbox.guardar.assert_called_once()
    uow.commit.assert_called_once()


def test_el_codigo_iso_no_se_repite():
    servicio, uow = armar()
    uow.contenedores.obtener_por_codigo.return_value = nuevo_contenedor()
    with pytest.raises(ConflictoDeDatos):
        servicio.alta("MSKU1234567", "DRY_40", 28.0)
    uow.contenedores.guardar.assert_not_called()


def test_el_codigo_iso_tiene_once_caracteres():
    servicio, _ = armar()
    with pytest.raises(ValidacionError):
        servicio.alta("CORTO", "DRY_40", 28.0)


def test_la_capacidad_tiene_que_ser_positiva():
    servicio, _ = armar()
    for capacidad in (0.0, -5.0):
        with pytest.raises(ValidacionError):
            servicio.alta("MSKU1234567", "DRY_40", capacidad)


# --- Modificacion y estado ---------------------------------------------------


def test_modificar_revalida_la_entidad_completa():
    contenedor = nuevo_contenedor()
    servicio, uow = armar(contenedor)
    with pytest.raises(ValidacionError):
        servicio.modificar(contenedor.id, capacidad=-1.0)
    uow.contenedores.actualizar.assert_not_called()
    uow.commit.assert_not_called()


def test_el_abm_no_puede_poner_los_estados_que_pone_el_envio():
    """ASIGNADO y EN_TRANSITO los escribe EnvioService junto con la fila de
    envio_contenedor, en la misma transaccion (D28). Ponerlos desde el ABM
    dejaria un contenedor ocupado sin ningun envio que lo tenga."""
    servicio, uow = armar(nuevo_contenedor())
    for estado in (EstadoContenedor.ASIGNADO, EstadoContenedor.EN_TRANSITO):
        with pytest.raises(ValidacionError):
            servicio.cambiar_estado(uuid4(), estado)
    uow.contenedores.actualizar.assert_not_called()


def test_no_se_cambia_el_estado_de_un_contenedor_ocupado():
    ocupado = nuevo_contenedor(estado=EstadoContenedor.EN_TRANSITO)
    servicio, uow = armar(ocupado)
    with pytest.raises(ConflictoDeDatos):
        servicio.cambiar_estado(ocupado.id, EstadoContenedor.EN_MANTENIMIENTO)
    uow.contenedores.actualizar.assert_not_called()


def test_la_baja_es_logica():
    """D26: la fila queda, la referencian los envios y las lecturas."""
    contenedor = nuevo_contenedor()
    servicio, uow = armar(contenedor)
    assert servicio.baja(contenedor.id).estado is EstadoContenedor.BAJA
    uow.contenedores.actualizar.assert_called_once()


def test_buscar_por_codigo_o_por_uuid():
    contenedor = nuevo_contenedor()
    servicio, uow = armar(contenedor)
    assert servicio.buscar(str(contenedor.id)) is contenedor

    uow.contenedores.obtener.return_value = None
    uow.contenedores.obtener_por_codigo.return_value = contenedor
    assert servicio.buscar("msku1234567") is contenedor
    uow.contenedores.obtener_por_codigo.assert_called_with("MSKU1234567")


def test_buscar_algo_que_no_existe():
    servicio, uow = armar(None)
    uow.contenedores.obtener_por_codigo.return_value = None
    with pytest.raises(NoEncontrado):
        servicio.buscar("NOEXISTE123")


# --- Contenedores de un envio ------------------------------------------------


def armar_envios(envio=None, contenedor=None):
    from logistica.services.envio_service import EnvioService

    uow = MagicMock()
    uow.__enter__.return_value = uow
    uow.envios.obtener.return_value = envio
    uow.contenedores.obtener.return_value = contenedor
    uow.envios.desasociar_contenedor.return_value = True
    return EnvioService(uow), uow


def envio_en(estado: EstadoEnvio):
    envio = MagicMock()
    envio.estado = estado
    return envio


@pytest.mark.parametrize(
    "estado", [EstadoEnvio.EN_TRANSITO, EstadoEnvio.EN_PUERTO, EstadoEnvio.ENTREGADO]
)
def test_no_se_saca_un_contenedor_de_un_envio_que_ya_salio(estado):
    """Lo que viajo ya viajo: sacarlo falsearia el historico."""
    servicio, uow = armar_envios(envio_en(estado), nuevo_contenedor())
    with pytest.raises(ConflictoDeDatos):
        servicio.desasignar_contenedor(uuid4(), uuid4())
    uow.envios.desasociar_contenedor.assert_not_called()


def test_sacar_un_contenedor_lo_devuelve_a_disponible():
    contenedor = nuevo_contenedor(estado=EstadoContenedor.ASIGNADO)
    servicio, uow = armar_envios(envio_en(EstadoEnvio.CREADO), contenedor)

    vuelto = servicio.desasignar_contenedor(uuid4(), contenedor.id)

    assert vuelto.estado is EstadoContenedor.DISPONIBLE
    uow.contenedores.actualizar.assert_called_once_with(contenedor)
    uow.outbox.guardar.assert_called_once()
    uow.commit.assert_called_once()


def test_sacar_no_pisa_un_estado_administrativo():
    """EN_MANTENIMIENTO o BAJA no los revierte una desasignacion."""
    contenedor = nuevo_contenedor(estado=EstadoContenedor.EN_MANTENIMIENTO)
    servicio, uow = armar_envios(envio_en(EstadoEnvio.CREADO), contenedor)

    vuelto = servicio.desasignar_contenedor(uuid4(), contenedor.id)

    assert vuelto.estado is EstadoContenedor.EN_MANTENIMIENTO
    uow.contenedores.actualizar.assert_not_called()


def test_sacar_un_contenedor_que_no_estaba_asignado():
    servicio, uow = armar_envios(envio_en(EstadoEnvio.CREADO), nuevo_contenedor())
    uow.envios.desasociar_contenedor.return_value = False
    with pytest.raises(NoEncontrado):
        servicio.desasignar_contenedor(uuid4(), uuid4())
    uow.commit.assert_not_called()
