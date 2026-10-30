"""ABM de usuarios, roles y sensores: lo que faltaba de cada uno."""
from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from logistica.domain.rol import Rol
from logistica.domain.sensor import EstadoSensor, Sensor, TipoSensor
from logistica.domain.umbral import MagnitudUmbral
from logistica.domain.usuario import EstadoUsuario, Usuario
from logistica.exceptions import ConflictoDeDatos, NoEncontrado, ValidacionError
from logistica.services.monitoreo_service import MonitoreoService
from logistica.services.usuario_service import UsuarioService

AHORA = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)


def nuevo_usuario(**cambios) -> Usuario:
    datos = dict(
        id=uuid4(),
        rol_id=uuid4(),
        nombre="Lucia",
        apellido="Auditora",
        email="lucia@logistica.com",
        password_hash="pbkdf2_sha256$200000$abc$def",
        fecha_registro=AHORA,
    )
    datos.update(cambios)
    return Usuario(**datos)


def nuevo_sensor(**cambios) -> Sensor:
    datos = dict(
        id=uuid4(),
        numero_serie="SN-IOT-2026-001",
        modelo="TempTrack 3000",
        tipo=TipoSensor.TEMPERATURA,
        intervalo_reporte_segundos=60,
        fecha_instalacion=AHORA,
        contenedor_id=uuid4(),
    )
    datos.update(cambios)
    return Sensor(**datos)


def armar_usuarios(usuario=None, rol=None):
    uow = MagicMock()
    uow.__enter__.return_value = uow
    uow.usuarios.obtener.return_value = usuario
    uow.usuarios.obtener_por_email.return_value = None
    uow.roles.obtener.return_value = rol if rol is not None else MagicMock()
    uow.roles.obtener_por_descripcion.return_value = None
    return UsuarioService(uow), uow


def armar_sensores(sensor=None):
    uow = MagicMock()
    uow.__enter__.return_value = uow
    uow.sensores.obtener.return_value = sensor
    uow.sensores.obtener_por_numero_serie.return_value = None
    uow.contenedores.obtener.return_value = MagicMock()
    umbrales = MagicMock()
    return MonitoreoService(MagicMock(), umbrales, MagicMock(), uow), uow, umbrales


# --- Usuarios ----------------------------------------------------------------


def test_modificar_un_usuario_revalida_entero():
    """Un setattr se saltea __post_init__."""
    usuario = nuevo_usuario()
    servicio, uow = armar_usuarios(usuario)
    with pytest.raises(ValidacionError):
        servicio.modificar(usuario.id, email="sin-arroba")
    uow.usuarios.actualizar.assert_not_called()
    uow.commit.assert_not_called()


def test_modificar_no_permite_pisar_el_email_de_otro():
    usuario = nuevo_usuario()
    servicio, uow = armar_usuarios(usuario)
    uow.usuarios.obtener_por_email.return_value = nuevo_usuario(email="otro@x.com")
    with pytest.raises(ConflictoDeDatos):
        servicio.modificar(usuario.id, email="otro@x.com")
    uow.usuarios.actualizar.assert_not_called()


def test_conservar_el_propio_email_no_es_conflicto():
    usuario = nuevo_usuario()
    servicio, uow = armar_usuarios(usuario)
    uow.usuarios.obtener_por_email.return_value = usuario
    actualizado = servicio.modificar(usuario.id, email=usuario.email, nombre="Lu")
    assert actualizado.nombre == "Lu"


def test_modificar_solo_cambia_lo_que_viene_con_valor():
    usuario = nuevo_usuario()
    servicio, _ = armar_usuarios(usuario)
    actualizado = servicio.modificar(usuario.id, nombre="Renombrada", apellido=None)
    assert actualizado.nombre == "Renombrada"
    assert actualizado.apellido == "Auditora"


def test_no_se_asigna_un_rol_inexistente():
    usuario = nuevo_usuario()
    servicio, uow = armar_usuarios(usuario)
    uow.roles.obtener.return_value = None
    with pytest.raises(ValidacionError):
        servicio.modificar(usuario.id, rol_id=uuid4())


def test_la_contrasena_no_se_toca_al_modificar():
    """Tiene su propio metodo: mezclarla con los datos de contacto haria facil
    pisarla sin querer."""
    usuario = nuevo_usuario()
    hash_original = usuario.password_hash
    servicio, _ = armar_usuarios(usuario)
    assert servicio.modificar(usuario.id, nombre="Lu").password_hash == hash_original


def test_reactivar_deshace_la_baja_logica():
    usuario = nuevo_usuario(estado=EstadoUsuario.INACTIVO)
    servicio, uow = armar_usuarios(usuario)
    assert servicio.reactivar(usuario.id).estado is EstadoUsuario.ACTIVO
    uow.usuarios.actualizar.assert_called_once()


# --- Roles -------------------------------------------------------------------


def test_el_alta_de_rol_normaliza_la_descripcion():
    servicio, uow = armar_usuarios()
    rol = servicio.alta_rol("  supervisor  ", 45)
    assert rol.descripcion == "SUPERVISOR"
    uow.roles.guardar.assert_called_once_with(rol)


def test_no_se_repite_la_descripcion_de_un_rol():
    servicio, uow = armar_usuarios()
    uow.roles.obtener_por_descripcion.return_value = MagicMock()
    with pytest.raises(ConflictoDeDatos):
        servicio.alta_rol("OPERADOR", 60)
    uow.roles.guardar.assert_not_called()


@pytest.mark.parametrize("nivel", [0, -5, 101, 200])
def test_el_nivel_de_permisos_va_de_1_a_100(nivel):
    servicio, uow = armar_usuarios()
    with pytest.raises(ValidacionError):
        servicio.alta_rol("NUEVO", nivel)
    uow.roles.guardar.assert_not_called()


def test_modificar_un_rol_revalida_el_nivel():
    rol = Rol(id=uuid4(), descripcion="OPERADOR", nivel_permisos=60)
    servicio, uow = armar_usuarios()
    uow.roles.obtener.return_value = rol
    with pytest.raises(ValidacionError):
        servicio.modificar_rol(rol.id, nivel_permisos=500)
    uow.roles.actualizar.assert_not_called()


def test_modificar_un_rol_no_choca_consigo_mismo():
    rol = Rol(id=uuid4(), descripcion="OPERADOR", nivel_permisos=60)
    servicio, uow = armar_usuarios()
    uow.roles.obtener.return_value = rol
    uow.roles.obtener_por_descripcion.return_value = rol
    assert servicio.modificar_rol(rol.id, descripcion="operador").nivel_permisos == 60


def test_contar_usuarios_por_rol():
    rol_id = uuid4()
    servicio, uow = armar_usuarios()
    uow.usuarios.listar.return_value = [
        nuevo_usuario(rol_id=rol_id),
        nuevo_usuario(rol_id=rol_id),
        nuevo_usuario(rol_id=uuid4()),
    ]
    assert servicio.contar_usuarios_por_rol(rol_id) == 2


# --- Sensores ----------------------------------------------------------------


def test_el_alta_de_sensor_normaliza_el_numero_de_serie():
    servicio, uow, _ = armar_sensores()
    sensor = servicio.alta_sensor("sn-iot-2026-007", "TempX", TipoSensor.TEMPERATURA, 60)
    assert sensor.numero_serie == "SN-IOT-2026-007"
    assert not sensor.esta_instalado()
    uow.sensores.guardar.assert_called_once_with(sensor)


def test_el_numero_de_serie_no_se_repite():
    servicio, uow, _ = armar_sensores()
    uow.sensores.obtener_por_numero_serie.return_value = nuevo_sensor()
    with pytest.raises(ConflictoDeDatos):
        servicio.alta_sensor("SN-IOT-2026-001", "TempX", TipoSensor.GPS, 60)
    uow.sensores.guardar.assert_not_called()


def test_no_se_da_de_alta_en_un_contenedor_inexistente():
    servicio, uow, _ = armar_sensores()
    uow.contenedores.obtener.return_value = None
    with pytest.raises(NoEncontrado):
        servicio.alta_sensor("SN-X", "TempX", TipoSensor.GPS, 60, contenedor_id=uuid4())
    uow.sensores.guardar.assert_not_called()


def test_modificar_un_sensor_revalida_el_intervalo():
    sensor = nuevo_sensor()
    servicio, uow, _ = armar_sensores(sensor)
    with pytest.raises(ValidacionError):
        servicio.modificar_sensor(sensor.id, intervalo_reporte_segundos=0)
    uow.sensores.actualizar.assert_not_called()


def test_no_se_instala_un_sensor_que_ya_esta_en_otro_contenedor():
    sensor = nuevo_sensor()
    servicio, uow, _ = armar_sensores(sensor)
    with pytest.raises(ConflictoDeDatos):
        servicio.instalar_sensor(sensor.id, uuid4())
    uow.sensores.actualizar.assert_not_called()


def test_reinstalar_en_el_mismo_contenedor_es_valido():
    sensor = nuevo_sensor()
    servicio, uow, _ = armar_sensores(sensor)
    servicio.instalar_sensor(sensor.id, sensor.contenedor_id)
    uow.sensores.actualizar.assert_called_once()


def test_desinstalar_deja_el_sensor_sin_contenedor():
    sensor = nuevo_sensor()
    servicio, uow, _ = armar_sensores(sensor)
    assert not servicio.desinstalar_sensor(sensor.id).esta_instalado()
    uow.sensores.actualizar.assert_called_once()


def test_no_se_desinstala_un_sensor_que_no_esta_instalado():
    sensor = nuevo_sensor(contenedor_id=None)
    servicio, uow, _ = armar_sensores(sensor)
    with pytest.raises(ValidacionError):
        servicio.desinstalar_sensor(sensor.id)
    uow.sensores.actualizar.assert_not_called()


def test_cambiar_el_estado_lo_saca_del_control_de_inactividad():
    """D43: solo los ACTIVO se esperan reportando."""
    sensor = nuevo_sensor()
    servicio, _, _ = armar_sensores(sensor)
    actualizado = servicio.cambiar_estado_sensor(sensor.id, EstadoSensor.EN_MANTENIMIENTO)
    assert not actualizado.esta_monitoreado()


# --- Umbrales ----------------------------------------------------------------


def test_eliminar_un_umbral_que_no_existe():
    servicio, _, umbrales = armar_sensores()
    umbrales.eliminar.return_value = False
    with pytest.raises(NoEncontrado):
        servicio.eliminar_umbral("REEFER_40", MagnitudUmbral.TEMPERATURA)


def test_eliminar_un_umbral_normaliza_el_tipo():
    servicio, _, umbrales = armar_sensores()
    umbrales.eliminar.return_value = True
    servicio.eliminar_umbral("  reefer_40  ", MagnitudUmbral.TEMPERATURA)
    umbrales.eliminar.assert_called_once_with("REEFER_40", MagnitudUmbral.TEMPERATURA)


# --- Busqueda en el menu de usuarios -----------------------------------------


def _menu_usuarios(monkeypatch, usuarios_listados, entrada, opcion):
    """Ejecuta una opcion del menu de usuarios con una entrada dada."""
    from logistica.cli import menu_usuarios

    servicio = MagicMock()
    servicio.listar.return_value = usuarios_listados
    servicio.listar_roles.return_value = []
    error = MagicMock()
    monkeypatch.setattr(menu_usuarios.consola, "pedir", lambda _: entrada)
    monkeypatch.setattr(menu_usuarios.consola, "error", error)
    monkeypatch.setattr(menu_usuarios.consola, "confirmar", lambda _: True)
    monkeypatch.setattr(menu_usuarios.consola, "titulo", lambda *_: None)
    monkeypatch.setattr(menu_usuarios.consola, "aviso", lambda *_: None)
    monkeypatch.setattr(menu_usuarios.consola, "exito", lambda *_: None)
    monkeypatch.setattr(menu_usuarios.consola, "tabla", lambda *_: None)
    monkeypatch.setattr(
        menu_usuarios.consola, "menu", lambda titulo, opciones: opciones[opcion][1]()
    )
    menu_usuarios.construir(servicio, MagicMock(), MagicMock())
    return servicio, error


def test_una_entrada_vacia_no_da_de_baja_a_nadie(monkeypatch):
    """Regresion: `"" in str(id)` es verdadero para todos, asi que la busqueda
    se quedaba con el primero y apretar Enter daba de baja a un usuario
    cualquiera. Lo encontro una pasada completa de la aplicacion."""
    servicio, error = _menu_usuarios(
        monkeypatch, [nuevo_usuario(), nuevo_usuario()], "", "4"
    )
    servicio.baja.assert_not_called()
    error.assert_called_once()


def test_un_fragmento_ambiguo_no_elige_uno(monkeypatch):
    """Los ids de la semilla comparten prefijo: un fragmento corto coincide con
    varios y elegir el primero seria elegir al azar."""
    comun = "aaaaaaaa"
    servicio, error = _menu_usuarios(
        monkeypatch,
        [
            nuevo_usuario(id=UUID(f"{comun}-0000-4000-8000-000000000001")),
            nuevo_usuario(id=UUID(f"{comun}-0000-4000-8000-000000000002")),
        ],
        comun,
        "4",
    )
    servicio.baja.assert_not_called()
    assert "coinciden" in error.call_args[0][0]


def test_el_email_completo_identifica_sin_ambiguedad(monkeypatch):
    buscado = nuevo_usuario(email="lucia@logistica.com")
    otro = nuevo_usuario(email="carlos@logistica.com")
    servicio, error = _menu_usuarios(
        monkeypatch, [otro, buscado], "LUCIA@logistica.com", "4"
    )
    servicio.baja.assert_called_once_with(buscado.id)
    error.assert_not_called()
