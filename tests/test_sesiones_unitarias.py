"""Regresiones de sesiones, del filtro de permisos y de la puerta de entrada,
sin depender de bases externas."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from redis.exceptions import ConnectionError

from logistica.cli import app, menu_monitoreo, menu_usuarios
from logistica.cli.permisos import (
    NIVEL_ADMINISTRADOR,
    NIVEL_AUDITOR,
    NIVEL_OPERADOR,
    opciones_para,
)
from logistica.domain.sesion import EstadoSesion, Sesion
from logistica.exceptions import ErrorDePersistencia, ValidacionError
from logistica.infrastructure.redis.sesion_repository import RedisSesionRepository
from logistica.services.sesion_service import SesionService

AHORA = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)


def nueva_sesion(**cambios) -> Sesion:
    datos = dict(
        id=uuid4(),
        usuario_id=uuid4(),
        fecha_inicio=AHORA,
        fecha_fin=AHORA + timedelta(hours=1),
    )
    datos.update(cambios)
    return Sesion(**datos)


def sesion_vigente(**cambios) -> Sesion:
    """Una sesion viva contra el reloj real, para los casos que comparan con
    datetime.now()."""
    ahora = datetime.now(timezone.utc)
    return nueva_sesion(fecha_inicio=ahora, fecha_fin=ahora + timedelta(hours=1), **cambios)


# --- Entidad -----------------------------------------------------------------


def test_una_sesion_no_puede_terminar_antes_de_empezar():
    with pytest.raises(ValidacionError):
        nueva_sesion(fecha_fin=AHORA - timedelta(seconds=1))


def test_las_fechas_necesitan_zona_horaria():
    """Sin tzinfo, comparar con datetime.now(timezone.utc) explota."""
    with pytest.raises(ValidacionError):
        nueva_sesion(fecha_inicio=AHORA.replace(tzinfo=None))


def test_una_sesion_vencida_no_esta_activa():
    sesion = nueva_sesion()
    assert sesion.esta_activa(AHORA)
    assert not sesion.esta_activa(AHORA + timedelta(hours=2))


def test_los_segundos_restantes_nunca_son_negativos():
    assert nueva_sesion().segundos_restantes(AHORA + timedelta(days=1)) == 0


def test_los_segundos_restantes_redondean_hacia_arriba():
    """Este numero es el TTL que recibe Redis: truncar mataria la sesion antes
    de su fecha_fin. Con una sesion de 1 segundo, truncar daba 0 apenas el
    reloj avanzaba un microsegundo y `guardar` la rechazaba por vencida."""
    sesion = nueva_sesion(fecha_inicio=AHORA, fecha_fin=AHORA + timedelta(seconds=1))
    un_instante_despues = AHORA + timedelta(microseconds=1)
    assert sesion.segundos_restantes(un_instante_despues) == 1


def test_una_sesion_de_un_segundo_se_puede_guardar():
    """Regresion: el redondeo hacia abajo la hacia nacer vencida."""
    cliente = MagicMock()
    ahora = datetime.now(timezone.utc)
    sesion = nueva_sesion(fecha_inicio=ahora, fecha_fin=ahora + timedelta(seconds=1))
    RedisSesionRepository(cliente).guardar(sesion)
    operacion = cliente.pipeline.return_value.__enter__.return_value
    assert operacion.expire.call_args[0][1] >= 1


def test_todos_los_valores_van_en_mayusculas():
    """D19."""
    for valor in EstadoSesion:
        assert valor.value == valor.name == valor.value.upper()


# --- Servicio ----------------------------------------------------------------


@pytest.mark.parametrize("ttl", [0, -1, True, False, 1.5, "60", None])
def test_ttl_invalido_no_escribe(ttl):
    repositorio = MagicMock()
    with pytest.raises(ValidacionError):
        SesionService(repositorio, ttl)
    repositorio.guardar.assert_not_called()


def test_el_servicio_filtra_las_vencidas_que_redis_no_barrio():
    """El TTL de Redis no es instantaneo: entre que vence y que el motor la
    borra, la clave sigue ahi."""
    repositorio = MagicMock()
    repositorio.listar_activas.return_value = [
        nueva_sesion(
            fecha_inicio=AHORA - timedelta(days=2), fecha_fin=AHORA - timedelta(days=1)
        ),
        sesion_vigente(),
    ]
    assert len(SesionService(repositorio, 3600).listar_activas()) == 1


def test_consultar_una_sesion_vencida_devuelve_none():
    repositorio = MagicMock()
    repositorio.obtener.return_value = nueva_sesion(
        fecha_inicio=AHORA - timedelta(days=2), fecha_fin=AHORA - timedelta(days=1)
    )
    assert SesionService(repositorio, 3600).consultar(uuid4()) is None


def test_iniciar_devuelve_una_entidad_no_un_diccionario():
    """D33: los servicios devuelven entidades de dominio."""
    repositorio = MagicMock()
    usuario_id = uuid4()
    sesion = SesionService(repositorio, 3600).iniciar(usuario_id)
    assert isinstance(sesion, Sesion)
    assert sesion.usuario_id == usuario_id
    repositorio.guardar.assert_called_once_with(sesion)


# --- Repositorio Redis -------------------------------------------------------


def test_no_se_guarda_una_sesion_ya_vencida():
    cliente = MagicMock()
    vencida = nueva_sesion(
        fecha_inicio=AHORA - timedelta(days=2), fecha_fin=AHORA - timedelta(days=1)
    )
    with pytest.raises(ValidacionError):
        RedisSesionRepository(cliente).guardar(vencida)
    cliente.pipeline.assert_not_called()


@pytest.mark.parametrize("operacion", ["guardar", "obtener", "eliminar"])
def test_fallos_redis_se_traducen(operacion):
    """D29: la infraestructura no deja escapar errores del motor."""
    cliente = MagicMock()
    fallo = ConnectionError("Redis no disponible")
    cliente.pipeline.return_value.__enter__.return_value.execute.side_effect = fallo
    cliente.hgetall.side_effect = fallo
    cliente.delete.side_effect = fallo
    repo = RedisSesionRepository(cliente)
    argumentos = (sesion_vigente(),) if operacion == "guardar" else (uuid4(),)
    with pytest.raises(ErrorDePersistencia) as error:
        getattr(repo, operacion)(*argumentos)
    assert error.value.__cause__ is fallo


def test_datos_corruptos_se_traducen():
    cliente = MagicMock()
    cliente.hgetall.return_value = {b"usuario_id": b"\xff"}
    with pytest.raises(ErrorDePersistencia):
        RedisSesionRepository(cliente).obtener(uuid4())


def test_listar_usa_scan_y_tolera_claves_que_vencieron():
    """Entre el SCAN y el HGETALL una clave puede vencer: no debe romper."""
    cliente = MagicMock()
    sesion = nueva_sesion()
    cliente.scan_iter.return_value = iter(
        [f"sesion:{sesion.id}".encode(), f"sesion:{uuid4()}".encode()]
    )
    cliente.pipeline.return_value.__enter__.return_value.execute.return_value = [
        {
            b"usuario_id": str(sesion.usuario_id).encode(),
            b"fecha_inicio": sesion.fecha_inicio.isoformat().encode(),
            b"fecha_fin": sesion.fecha_fin.isoformat().encode(),
            b"estado": b"ACTIVA",
        },
        {},  # vencio entre el SCAN y el HGETALL
    ]
    activas = RedisSesionRepository(cliente).listar_activas()
    assert [s.id for s in activas] == [sesion.id]
    cliente.scan_iter.assert_called_once()
    cliente.keys.assert_not_called()


# --- La puerta de entrada ----------------------------------------------------


def test_sin_credenciales_validas_no_se_abre_sesion(monkeypatch):
    """Tres intentos fallidos y la aplicacion no entrega el menu."""
    contenedor = MagicMock()
    contenedor.usuarios.autenticar.side_effect = ValidacionError(
        "Email o contrasena incorrectos"
    )
    monkeypatch.setattr(app.consola, "pedir", lambda _: "a@b.com")
    monkeypatch.setattr(app, "getpass", lambda _: "clave-equivocada")

    assert app._autenticar(contenedor) is None
    assert contenedor.usuarios.autenticar.call_count == app.INTENTOS_MAXIMOS
    contenedor.sesiones.iniciar.assert_not_called()


def test_con_credenciales_validas_se_abre_la_sesion(monkeypatch):
    contenedor = MagicMock()
    usuario = SimpleNamespace(id=uuid4(), rol_id=uuid4(), nombre_completo="Admin de prueba")
    contenedor.usuarios.autenticar.return_value = usuario
    contenedor.sesiones.iniciar.return_value = sesion_vigente(usuario_id=usuario.id)
    monkeypatch.setattr(app.consola, "pedir", lambda _: "a@b.com")
    monkeypatch.setattr(app, "getpass", lambda _: "clave-correcta")

    assert app._autenticar(contenedor) is not None
    contenedor.sesiones.iniciar.assert_called_once_with(usuario.id)


def test_si_redis_esta_caido_no_se_vuelve_a_pedir_la_clave(monkeypatch):
    """Las credenciales eran correctas: el problema no es el usuario."""
    contenedor = MagicMock()
    contenedor.usuarios.autenticar.return_value = SimpleNamespace(
        id=uuid4(), rol_id=uuid4(), nombre_completo="Admin"
    )
    contenedor.sesiones.iniciar.side_effect = ErrorDePersistencia("Redis no disponible")
    monkeypatch.setattr(app.consola, "pedir", lambda _: "a@b.com")
    monkeypatch.setattr(app, "getpass", lambda _: "clave-correcta")

    assert app._autenticar(contenedor) is None
    assert contenedor.usuarios.autenticar.call_count == 1


@pytest.mark.parametrize("nivel,visibles", [(100, 13), (60, 11), (30, 6), (10, 0)])
def test_el_menu_se_recorta_segun_el_nivel_del_rol(nivel, visibles):
    assert len(opciones_para(nivel, app._secciones(MagicMock(), nivel))) == visibles


def test_las_opciones_visibles_se_renumeran_desde_uno():
    """Si se filtraran sin renumerar, el menu mostraria 1, 5, 8 en vez de 1, 2, 3."""
    nivel = NIVEL_AUDITOR
    opciones = opciones_para(nivel, app._secciones(MagicMock(), nivel))
    assert list(opciones) == ["1", "2", "3", "4", "5", "6"]


def test_el_submenu_usa_el_mismo_filtro_que_el_principal(monkeypatch):
    """Configurar un umbral cambia lo que todo el sistema considera anomalia:
    es de administrador. El criterio no se duplica, se reusa (D42)."""
    capturado = {}
    monkeypatch.setattr(
        menu_monitoreo.consola,
        "menu",
        lambda titulo, opciones: capturado.update(opciones),
    )

    menu_monitoreo.construir(MagicMock(), rol_nivel=NIVEL_OPERADOR)
    etiquetas_operador = [e for e, _ in capturado.values()]
    capturado.clear()
    menu_monitoreo.construir(MagicMock(), rol_nivel=NIVEL_ADMINISTRADOR)
    etiquetas_admin = [e for e, _ in capturado.values()]

    assert "Configurar un umbral" not in etiquetas_operador
    assert "Configurar un umbral" in etiquetas_admin


# --- El menu de sesiones -----------------------------------------------------


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


def test_el_menu_lista_las_sesiones_activas(monkeypatch):
    usuarios, sesiones = MagicMock(), MagicMock()
    sesion = sesion_vigente()
    sesiones.listar_activas.return_value = [sesion]
    usuarios.listar.return_value = [
        SimpleNamespace(id=sesion.usuario_id, nombre_completo="Admin de prueba")
    ]
    tabla = MagicMock()
    monkeypatch.setattr(menu_usuarios.consola, "tabla", tabla)

    error, _ = ejecutar_opcion(monkeypatch, "9", usuarios, sesiones, "")
    error.assert_not_called()
    assert tabla.call_args[0][1][0][1] == "Admin de prueba"


@pytest.mark.parametrize("opcion,metodo", [("9", "listar_activas"), ("10", "cerrar")])
def test_el_menu_controla_la_caida_de_redis(monkeypatch, opcion, metodo):
    usuarios, sesiones = MagicMock(), MagicMock()
    getattr(sesiones, metodo).side_effect = ErrorDePersistencia("Redis no disponible")
    error, exito = ejecutar_opcion(monkeypatch, opcion, usuarios, sesiones, str(uuid4()))
    error.assert_called_once_with("Redis no disponible")
    exito.assert_not_called()
