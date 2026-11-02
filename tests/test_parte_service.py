"""ABM de proveedores y operadores logisticos, sin bases externas."""
from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from logistica.domain.facturacion import TitularTipo
from logistica.domain.partes import EstadoParte, Operador, Proveedor
from logistica.exceptions import ConflictoDeDatos, NoEncontrado, ValidacionError
from logistica.services.parte_service import OperadorService, ProveedorService

AHORA = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)

COMUNES = dict(
    cuit="30-60111222-1",
    razon_social="Naviera Rio de la Plata SA",
    email="ops@naviera.com",
    pais="Argentina",
)


def nuevo_operador(**cambios) -> Operador:
    datos = dict(id=uuid4(), fecha_creacion=AHORA, **COMUNES)
    datos.update(cambios)
    return Operador(**datos)


def nuevo_proveedor(**cambios) -> Proveedor:
    datos = dict(
        id=uuid4(), fecha_creacion=AHORA, tipo_servicio="ESTIBA_Y_AMARRE", **COMUNES
    )
    datos.update(cambios)
    return Proveedor(**datos)


def armar(clase, existente=None):
    uow = MagicMock()
    uow.__enter__.return_value = uow
    repo = uow.proveedores if clase is ProveedorService else uow.operadores
    repo.obtener_por_cuit.return_value = None
    repo.obtener.return_value = existente
    return clase(uow), repo, uow


# --- Entidades ---------------------------------------------------------------


def test_el_cuit_necesita_once_digitos():
    for cuit in ("123", "30-6011122-1", ""):
        with pytest.raises(ValidacionError):
            nuevo_operador(cuit=cuit)


def test_los_guiones_del_cuit_no_cuentan():
    """30-60111222-1 son 11 digitos mas dos guiones."""
    assert nuevo_operador(cuit="30-60111222-1").cuit == "30-60111222-1"
    assert nuevo_operador(cuit="30601112221").esta_activo()


def test_un_proveedor_sin_tipo_de_servicio_no_es_valido():
    with pytest.raises(ValidacionError):
        nuevo_proveedor(tipo_servicio="   ")


def test_cada_parte_sabe_como_se_identifica_en_su_cuenta_corriente():
    """D41: la cuenta corriente usa titular_tipo + titular_id."""
    assert nuevo_operador().titular_tipo is TitularTipo.OPERADOR
    assert nuevo_proveedor().titular_tipo is TitularTipo.PROVEEDOR


def test_la_baja_es_logica():
    """D26: la fila queda, porque la referencian cuentas y movimientos."""
    operador = nuevo_operador()
    operador.dar_de_baja()
    assert operador.estado is EstadoParte.INACTIVO
    assert not operador.esta_activo()
    operador.reactivar()
    assert operador.esta_activo()


def test_todos_los_valores_van_en_mayusculas():
    """D19."""
    for valor in EstadoParte:
        assert valor.value == valor.name == valor.value.upper()


# --- Servicio ----------------------------------------------------------------


@pytest.mark.parametrize("clase", [OperadorService, ProveedorService])
def test_el_alta_rechaza_un_cuit_repetido(clase):
    """D3: la unicidad no la puede ver la entidad, hace falta consultar."""
    servicio, repo, uow = armar(clase)
    repo.obtener_por_cuit.return_value = MagicMock()
    extra = {"tipo_servicio": "X"} if clase is ProveedorService else {}
    with pytest.raises(ConflictoDeDatos):
        servicio.alta(**COMUNES, **extra)
    repo.guardar.assert_not_called()
    uow.commit.assert_not_called()


@pytest.mark.parametrize("clase", [OperadorService, ProveedorService])
def test_el_alta_guarda_y_confirma(clase):
    servicio, repo, uow = armar(clase)
    extra = {"tipo_servicio": "ESTIBA"} if clase is ProveedorService else {}
    parte = servicio.alta(**COMUNES, **extra)
    repo.guardar.assert_called_once_with(parte)
    uow.commit.assert_called_once()


@pytest.mark.parametrize("clase", [OperadorService, ProveedorService])
def test_el_alta_no_publica_al_outbox(clase):
    """A diferencia del cliente: ni el alta de un proveedor ni la de un
    operador cambian por si solas una relacion del grafo (D37)."""
    servicio, _, uow = armar(clase)
    extra = {"tipo_servicio": "ESTIBA"} if clase is ProveedorService else {}
    servicio.alta(**COMUNES, **extra)
    uow.outbox.guardar.assert_not_called()


def test_modificar_revalida_la_entidad_completa():
    """Un setattr se saltea __post_init__: sin la revalidacion, un email roto
    llegaria a la base."""
    operador = nuevo_operador()
    servicio, repo, uow = armar(OperadorService, existente=operador)
    with pytest.raises(ValidacionError):
        servicio.modificar(operador.id, email="sin-arroba")
    repo.actualizar.assert_not_called()
    uow.commit.assert_not_called()


def test_modificar_solo_cambia_lo_que_viene_con_valor():
    operador = nuevo_operador()
    servicio, repo, _ = armar(OperadorService, existente=operador)
    actualizado = servicio.modificar(operador.id, pais="Uruguay", email=None)
    assert actualizado.pais == "Uruguay"
    assert actualizado.email == COMUNES["email"]
    repo.actualizar.assert_called_once()


def test_modificar_algo_que_no_existe():
    servicio, repo, _ = armar(OperadorService, existente=None)
    with pytest.raises(NoEncontrado):
        servicio.modificar(uuid4(), pais="Chile")
    repo.actualizar.assert_not_called()


def test_la_baja_y_la_reactivacion_persisten():
    operador = nuevo_operador()
    servicio, repo, uow = armar(OperadorService, existente=operador)

    assert servicio.baja(operador.id).estado is EstadoParte.INACTIVO
    assert servicio.reactivar(operador.id).estado is EstadoParte.ACTIVO
    assert repo.actualizar.call_count == 2
    assert uow.commit.call_count == 2


def test_listar_solo_activos_filtra_en_la_base():
    servicio, repo, _ = armar(ProveedorService)
    servicio.listar(solo_activos=True)
    repo.listar.assert_called_once_with(EstadoParte.ACTIVO)
    servicio.listar()
    repo.listar.assert_called_with(None)


def test_buscar_por_cuit_inexistente():
    servicio, repo, _ = armar(OperadorService)
    repo.obtener_por_cuit.return_value = None
    with pytest.raises(NoEncontrado):
        servicio.buscar_por_cuit("30-00000000-0")


def test_cada_servicio_usa_su_propia_tabla():
    """Comparten la logica, no el repositorio."""
    proveedores, repo_prov, uow = armar(ProveedorService)
    proveedores.listar()
    repo_prov.listar.assert_called_once()
    uow.operadores.listar.assert_not_called()
