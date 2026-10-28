"""Regresiones de sesiones y su menu sin depender de bases externas."""
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from redis.exceptions import ConnectionError

from logistica.cli import menu_usuarios
from logistica.exceptions import ErrorDePersistencia, ValidacionError
from logistica.infrastructure.redis.sesion_repository import RedisSesionRepository
from logistica.services.sesion_service import SesionService


@pytest.mark.parametrize("ttl", [0, -1, True, False, 1.5, "60", None])
def test_ttl_invalido_no_escribe(ttl):
    cliente = MagicMock()
    repositorio = RedisSesionRepository(cliente)
    with pytest.raises(ValueError):
        SesionService(repositorio, ttl)
    with pytest.raises(ValueError):
        repositorio.guardar(uuid4(), uuid4(), "inicio", "fin", ttl)
    cliente.pipeline.assert_not_called()


@pytest.mark.parametrize("operacion", ["guardar", "obtener", "eliminar"])
def test_fallos_redis_se_traducen(operacion):
    cliente = MagicMock()
    fallo = ConnectionError("Redis no disponible")
    cliente.pipeline.return_value.__enter__.return_value.execute.side_effect = fallo
    cliente.hgetall.side_effect = fallo
    cliente.delete.side_effect = fallo
    repo = RedisSesionRepository(cliente)
    argumentos = (uuid4(), uuid4(), "inicio", "fin", 60) if operacion == "guardar" else (uuid4(),)
    with pytest.raises(ErrorDePersistencia) as error:
        getattr(repo, operacion)(*argumentos)
    assert error.value.__cause__ is fallo


def test_datos_no_decodificables_se_traducen():
    cliente = MagicMock()
    cliente.hgetall.return_value = {b"usuario_id": b"\xff"}
    with pytest.raises(ErrorDePersistencia):
        RedisSesionRepository(cliente).obtener(uuid4())


def ejecutar_opcion(monkeypatch, opcion, usuarios, sesiones, entrada):
    monkeypatch.setattr(menu_usuarios.consola, "pedir", lambda _: entrada)
    monkeypatch.setattr(menu_usuarios, "getpass", lambda _: "clave-de-prueba")
    error = MagicMock()
    exito = MagicMock()
    monkeypatch.setattr(menu_usuarios.consola, "error", error)
    monkeypatch.setattr(menu_usuarios.consola, "exito", exito)
    monkeypatch.setattr(
        menu_usuarios.consola, "menu", lambda titulo, opciones: opciones[opcion][1]()
    )
    menu_usuarios.construir(usuarios, MagicMock(), sesiones)
    return error, exito


def test_credenciales_invalidas_no_crean_sesion(monkeypatch):
    usuarios, sesiones = MagicMock(), MagicMock()
    usuarios.autenticar.side_effect = ValidacionError("Credenciales invalidas")
    error, exito = ejecutar_opcion(monkeypatch, "4", usuarios, sesiones, "a@b.com")
    sesiones.iniciar.assert_not_called()
    error.assert_called_once_with("Credenciales invalidas")
    exito.assert_not_called()


def test_login_crea_sesion_del_usuario_autenticado(monkeypatch):
    usuarios, sesiones = MagicMock(), MagicMock()
    usuario = SimpleNamespace(id=uuid4(), nombre_completo="Usuario de prueba")
    usuarios.autenticar.return_value = usuario
    error, exito = ejecutar_opcion(monkeypatch, "4", usuarios, sesiones, "a@b.com")
    sesiones.iniciar.assert_called_once_with(usuario.id)
    error.assert_not_called()
    exito.assert_called_once()


@pytest.mark.parametrize("opcion,metodo", [("4", "iniciar"), ("6", "cerrar")])
def test_menu_controla_caida_redis(monkeypatch, opcion, metodo):
    usuarios, sesiones = MagicMock(), MagicMock()
    getattr(sesiones, metodo).side_effect = ErrorDePersistencia("Redis no disponible")
    error, exito = ejecutar_opcion(monkeypatch, opcion, usuarios, sesiones, str(uuid4()))
    error.assert_called_once_with("Redis no disponible")
    exito.assert_not_called()
