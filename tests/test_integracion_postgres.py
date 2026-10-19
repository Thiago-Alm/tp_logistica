"""Tests de integracion contra PostgreSQL real.

Se saltean solos si la base no esta disponible, para que `pytest` siga pasando
en una maquina sin Docker levantado. Para correrlos:

    docker compose up -d
    python scripts/aplicar_esquema.py
    pytest tests/test_integracion_postgres.py -v

Cada test limpia lo que crea, asi que se pueden correr muchas veces seguidas
sobre los mismos datos semilla.
"""
from uuid import uuid4

import psycopg
import pytest

from logistica.container import Contenedor
from logistica.domain.cliente import EstadoCliente
from logistica.exceptions import (
    ConflictoDeDatos,
    ErrorDePersistencia,
    NoEncontrado,
    ValidacionError,
)
from logistica.infrastructure.postgres.conexion import armar_dsn

CUIT_DE_PRUEBA = "30-00000001-7"
EMAIL_DE_PRUEBA = "prueba.integracion@ejemplo.com"


@pytest.fixture(scope="module")
def contenedor():
    c = Contenedor(configurar_logging=False)
    try:
        c.usuarios.listar_roles()
    except ErrorDePersistencia:
        pytest.skip("PostgreSQL no disponible: docker compose up -d")
    return c


@pytest.fixture
def cliente_temporal(contenedor):
    """Crea un cliente, lo entrega al test y lo borra al terminar."""
    cliente = contenedor.clientes.alta(
        cuit=CUIT_DE_PRUEBA,
        razon_social="Cliente De Prueba SA",
        email="prueba@ejemplo.com",
        pais="Argentina",
    )
    yield cliente
    # Borrado fisico para dejar la base como estaba. Ningun repositorio lo
    # expone a proposito (las bajas del dominio son logicas, D26), asi que la
    # limpieza se hace con psycopg directo: es infraestructura, no dominio.
    with psycopg.connect(armar_dsn(contenedor.settings), autocommit=True) as conexion:
        conexion.execute("delete from usuario where cliente_id = %s", (cliente.id,))
        conexion.execute("delete from cliente where id = %s", (cliente.id,))


def test_los_datos_semilla_estan_cargados(contenedor):
    assert len(contenedor.clientes.listar()) >= 4
    assert len(contenedor.usuarios.listar_roles()) == 4


def test_alta_y_lectura(contenedor, cliente_temporal):
    leido = contenedor.clientes.obtener(cliente_temporal.id)
    assert leido.razon_social == "Cliente De Prueba SA"
    assert leido.estado is EstadoCliente.ACTIVO
    # La entidad vuelve reconstruida, no como fila: el enum es un enum.
    assert isinstance(leido.estado, EstadoCliente)


def test_el_cuit_es_unico(contenedor, cliente_temporal):
    with pytest.raises(ConflictoDeDatos):
        contenedor.clientes.alta(
            cuit=CUIT_DE_PRUEBA,
            razon_social="Otra SA",
            email="otra@ejemplo.com",
            pais="Argentina",
        )


def test_modificar_persiste(contenedor, cliente_temporal):
    contenedor.clientes.modificar(cliente_temporal.id, razon_social="Cliente Modificado SA")
    assert contenedor.clientes.obtener(cliente_temporal.id).razon_social == "Cliente Modificado SA"


def test_la_baja_es_logica_y_la_fila_sigue_existiendo(contenedor, cliente_temporal):
    contenedor.clientes.baja(cliente_temporal.id)
    leido = contenedor.clientes.obtener(cliente_temporal.id)
    assert leido.estado is EstadoCliente.INACTIVO
    assert leido not in contenedor.clientes.listar(solo_activos=True)
    assert leido.id in [c.id for c in contenedor.clientes.listar()]


def test_obtener_lo_que_no_existe(contenedor):
    with pytest.raises(NoEncontrado):
        contenedor.clientes.obtener(uuid4())


def test_autenticar_usuario_semilla(contenedor):
    usuario = contenedor.usuarios.autenticar("admin@logistica.com", "demo1234")
    assert usuario.es_interno()
    assert usuario.esta_activo()


def test_autenticar_con_contrasena_incorrecta(contenedor):
    with pytest.raises(ValidacionError):
        contenedor.usuarios.autenticar("admin@logistica.com", "incorrecta")


def test_autenticar_email_inexistente_da_el_mismo_error(contenedor):
    """El mensaje no debe revelar si el email existe o no."""
    with pytest.raises(ValidacionError) as sin_email:
        contenedor.usuarios.autenticar("noexiste@ejemplo.com", "loquesea")
    with pytest.raises(ValidacionError) as mal_password:
        contenedor.usuarios.autenticar("admin@logistica.com", "incorrecta")
    assert str(sin_email.value) == str(mal_password.value)


def test_alta_de_usuario_con_rol_inexistente_no_deja_rastro(contenedor):
    """Si el servicio corta, la transaccion se deshace entera (Unit of Work)."""
    with pytest.raises(ValidacionError):
        contenedor.usuarios.alta(
            rol_id=uuid4(),
            nombre="Fantasma",
            apellido="Inexistente",
            email=EMAIL_DE_PRUEBA,
            password="unaclave123",
        )
    assert not any(u.email == EMAIL_DE_PRUEBA for u in contenedor.usuarios.listar())


def test_alta_de_usuario_de_un_cliente(contenedor, cliente_temporal):
    rol = contenedor.usuarios.obtener_rol_por_descripcion("CLIENTE")
    usuario = contenedor.usuarios.alta(
        rol_id=rol.id,
        nombre="Prueba",
        apellido="Integracion",
        email=EMAIL_DE_PRUEBA,
        password="unaclave123",
        cliente_id=cliente_temporal.id,
    )
    assert not usuario.es_interno()
    assert contenedor.usuarios.autenticar(EMAIL_DE_PRUEBA, "unaclave123").id == usuario.id
    assert usuario.id in [u.id for u in contenedor.usuarios.listar_por_cliente(cliente_temporal.id)]


def test_la_contrasena_no_se_guarda_en_claro(contenedor, cliente_temporal):
    rol = contenedor.usuarios.obtener_rol_por_descripcion("CLIENTE")
    usuario = contenedor.usuarios.alta(
        rol_id=rol.id,
        nombre="Prueba",
        apellido="Hash",
        email=EMAIL_DE_PRUEBA,
        password="unaclave123",
        cliente_id=cliente_temporal.id,
    )
    guardado = contenedor.usuarios.obtener(usuario.id).password_hash
    assert "unaclave123" not in guardado
    assert guardado.startswith("pbkdf2_sha256$")


def test_contrasena_demasiado_corta(contenedor, cliente_temporal):
    rol = contenedor.usuarios.obtener_rol_por_descripcion("CLIENTE")
    with pytest.raises(ValidacionError):
        contenedor.usuarios.alta(
            rol_id=rol.id,
            nombre="Prueba",
            apellido="Corta",
            email=EMAIL_DE_PRUEBA,
            password="1234",
            cliente_id=cliente_temporal.id,
        )
