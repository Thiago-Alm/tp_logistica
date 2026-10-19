from datetime import datetime, timezone
from uuid import uuid4

import pytest

from logistica.domain.cliente import Cliente, EstadoCliente
from logistica.domain.rol import Rol
from logistica.domain.usuario import EstadoUsuario, Usuario
from logistica.exceptions import ValidacionError

AHORA = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)


def nuevo_cliente(**cambios) -> Cliente:
    datos = dict(
        id=uuid4(),
        cuit="30-71122334-9",
        razon_social="AgroGlobal Exportaciones SA",
        email="contacto@agroglobal.com",
        pais="Argentina",
        fecha_creacion=AHORA,
    )
    datos.update(cambios)
    return Cliente(**datos)


def nuevo_usuario(**cambios) -> Usuario:
    datos = dict(
        id=uuid4(),
        rol_id=uuid4(),
        nombre="Mariana",
        apellido="Fernandez",
        email="mariana@agroglobal.com",
        password_hash="pbkdf2_sha256$200000$aa$bb",
        fecha_registro=AHORA,
    )
    datos.update(cambios)
    return Usuario(**datos)


# --- Cliente ---------------------------------------------------------------


def test_un_cliente_valido_nace_activo():
    assert nuevo_cliente().estado is EstadoCliente.ACTIVO


@pytest.mark.parametrize("cuit", ["123", "", "30-7112233-9", "3071122334991"])
def test_el_cuit_debe_tener_once_digitos(cuit):
    with pytest.raises(ValidacionError):
        nuevo_cliente(cuit=cuit)


def test_el_cuit_acepta_guiones_o_sin_guiones():
    assert nuevo_cliente(cuit="30711223349").cuit == "30711223349"


def test_la_razon_social_no_puede_estar_vacia():
    with pytest.raises(ValidacionError):
        nuevo_cliente(razon_social="   ")


def test_el_email_debe_tener_arroba():
    with pytest.raises(ValidacionError):
        nuevo_cliente(email="contacto.agroglobal.com")


def test_la_baja_es_logica():
    """No se borra el cliente: queda INACTIVO y conserva sus datos (D26)."""
    cliente = nuevo_cliente()
    cliente.dar_de_baja()
    assert cliente.estado is EstadoCliente.INACTIVO
    assert not cliente.esta_activo()
    assert cliente.razon_social == "AgroGlobal Exportaciones SA"


def test_un_cliente_dado_de_baja_se_puede_reactivar():
    cliente = nuevo_cliente()
    cliente.dar_de_baja()
    cliente.reactivar()
    assert cliente.esta_activo()


# --- Rol -------------------------------------------------------------------


def test_un_rol_valido_se_construye():
    assert Rol(id=uuid4(), descripcion="ADMINISTRADOR", nivel_permisos=100)


@pytest.mark.parametrize("nivel", [0, -1, 101, 500])
def test_el_nivel_de_permisos_va_de_1_a_100(nivel):
    with pytest.raises(ValidacionError):
        Rol(id=uuid4(), descripcion="X", nivel_permisos=nivel)


def test_la_descripcion_del_rol_no_puede_estar_vacia():
    with pytest.raises(ValidacionError):
        Rol(id=uuid4(), descripcion="  ", nivel_permisos=50)


def test_comparar_roles_por_nivel():
    admin = Rol(id=uuid4(), descripcion="ADMINISTRADOR", nivel_permisos=100)
    cliente = Rol(id=uuid4(), descripcion="CLIENTE", nivel_permisos=10)
    assert admin.puede_mas_que(cliente)
    assert not cliente.puede_mas_que(admin)


# --- Usuario ---------------------------------------------------------------


def test_un_usuario_sin_cliente_es_interno():
    assert nuevo_usuario().es_interno()


def test_un_usuario_de_un_cliente_no_es_interno():
    assert not nuevo_usuario(cliente_id=uuid4()).es_interno()


def test_el_usuario_necesita_un_hash_de_contrasena():
    with pytest.raises(ValidacionError):
        nuevo_usuario(password_hash="")


@pytest.mark.parametrize("campo", ["nombre", "apellido"])
def test_nombre_y_apellido_son_obligatorios(campo):
    with pytest.raises(ValidacionError):
        nuevo_usuario(**{campo: "   "})


def test_nombre_completo():
    assert nuevo_usuario().nombre_completo == "Mariana Fernandez"


def test_la_baja_de_usuario_es_logica():
    usuario = nuevo_usuario()
    usuario.dar_de_baja()
    assert usuario.estado is EstadoUsuario.INACTIVO
    assert not usuario.esta_activo()
