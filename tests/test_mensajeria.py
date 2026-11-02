"""Mensajeria con las partes (D57): el hilo, la bandeja y lo que no se puede."""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from logistica.domain.facturacion import TitularTipo
from logistica.domain.mensajeria import (
    LARGO_MAXIMO_CUERPO,
    AutorMensaje,
    Conversacion,
    EstadoConversacion,
    Mensaje,
)
from logistica.exceptions import NoEncontrado, ValidacionError
from logistica.services.mensajeria_service import MensajeriaService

AHORA = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)


def nueva_conversacion(**cambios) -> Conversacion:
    datos = dict(
        id=uuid4(),
        parte_tipo=TitularTipo.CLIENTE,
        parte_id=uuid4(),
        asunto="Demora del envio",
        fecha_inicio=AHORA,
    )
    datos.update(cambios)
    return Conversacion(**datos)


def nuevo_mensaje(**cambios) -> Mensaje:
    datos = dict(
        id=uuid4(),
        conversacion_id=uuid4(),
        autor=AutorMensaje.PARTE,
        cuerpo="Necesito la nueva fecha",
        momento=AHORA,
    )
    datos.update(cambios)
    return Mensaje(**datos)


def armar(conversacion=None):
    uow = MagicMock()
    uow.__enter__.return_value = uow
    repositorio = MagicMock()
    repositorio.obtener.return_value = conversacion
    return MensajeriaService(repositorio, uow), repositorio, uow


# --- Entidades ---------------------------------------------------------------


def test_un_mensaje_no_puede_estar_vacio():
    for cuerpo in ("", "   ", "\n"):
        with pytest.raises(ValidacionError):
            nuevo_mensaje(cuerpo=cuerpo)


def test_un_mensaje_tiene_largo_maximo():
    nuevo_mensaje(cuerpo="x" * LARGO_MAXIMO_CUERPO)
    with pytest.raises(ValidacionError):
        nuevo_mensaje(cuerpo="x" * (LARGO_MAXIMO_CUERPO + 1))


def test_un_mensaje_interno_dice_quien_lo_escribio():
    """De la parte no hace falta: la parte es la conversacion."""
    with pytest.raises(ValidacionError):
        nuevo_mensaje(autor=AutorMensaje.INTERNO, autor_id=None)
    nuevo_mensaje(autor=AutorMensaje.INTERNO, autor_id=uuid4())
    nuevo_mensaje(autor=AutorMensaje.PARTE, autor_id=None)


def test_la_conversacion_necesita_asunto():
    with pytest.raises(ValidacionError):
        nueva_conversacion(asunto="   ")


def test_la_actividad_arranca_en_la_fecha_de_inicio():
    """Se guarda ademas de derivarse: es por donde se ordenan los hilos, y con
    los mensajes en otra coleccion derivarla obligaria a leerlos todos."""
    assert nueva_conversacion().actividad == AHORA


def test_una_conversacion_cerrada_no_admite_mensajes():
    conversacion = nueva_conversacion()
    conversacion.admite_mensajes()
    conversacion.cerrar()
    with pytest.raises(ValidacionError):
        conversacion.admite_mensajes()
    conversacion.reabrir()
    conversacion.admite_mensajes()


def test_solo_los_mensajes_de_la_parte_cuentan_como_pendientes():
    """Los que escribio la empresa ya los leyo quien los escribio."""
    conversacion = nueva_conversacion()
    conversacion.registrar_actividad(AHORA, de_la_parte=False)
    assert conversacion.sin_leer == 0
    conversacion.registrar_actividad(AHORA, de_la_parte=True)
    conversacion.registrar_actividad(AHORA, de_la_parte=True)
    assert conversacion.sin_leer == 2
    assert conversacion.tiene_pendientes
    conversacion.marcar_leida()
    assert not conversacion.tiene_pendientes


def test_todos_los_valores_van_en_mayusculas():
    """D19."""
    for enum in (AutorMensaje, EstadoConversacion):
        for valor in enum:
            assert valor.value == valor.name == valor.value.upper()


# --- Iniciar -----------------------------------------------------------------


def test_una_conversacion_nace_con_su_primer_mensaje():
    """Un hilo vacio no dice nada y habria que limpiarlo despues."""
    servicio, repositorio, _ = armar()
    conversacion = servicio.iniciar(
        TitularTipo.CLIENTE, uuid4(), "Demora", "Buen dia", uuid4()
    )
    repositorio.guardar.assert_called_once_with(conversacion)
    repositorio.guardar_mensaje.assert_called_once()
    assert repositorio.guardar_mensaje.call_args[0][0].autor is AutorMensaje.INTERNO


def test_el_primer_mensaje_nace_leido():
    servicio, repositorio, _ = armar()
    servicio.iniciar(TitularTipo.CLIENTE, uuid4(), "Demora", "Buen dia", uuid4())
    assert repositorio.guardar_mensaje.call_args[0][0].leido is True


@pytest.mark.parametrize(
    "tipo,atributo",
    [
        (TitularTipo.CLIENTE, "clientes"),
        (TitularTipo.PROVEEDOR, "proveedores"),
        (TitularTipo.OPERADOR, "operadores"),
    ],
)
def test_la_parte_tiene_que_existir_en_postgres(tipo, atributo):
    """Las conversaciones estan en MongoDB y las partes en PostgreSQL: no hay
    clave foranea que lo garantice (D3)."""
    servicio, repositorio, uow = armar()
    getattr(uow, atributo).obtener.return_value = None
    with pytest.raises(NoEncontrado):
        servicio.iniciar(tipo, uuid4(), "Asunto", "Hola", uuid4())
    repositorio.guardar.assert_not_called()


def test_el_usuario_que_escribe_tiene_que_existir():
    servicio, repositorio, uow = armar()
    uow.usuarios.obtener.return_value = None
    with pytest.raises(NoEncontrado):
        servicio.iniciar(TitularTipo.CLIENTE, uuid4(), "Asunto", "Hola", uuid4())
    repositorio.guardar.assert_not_called()


def test_el_envio_tiene_que_existir_si_se_indica():
    servicio, repositorio, uow = armar()
    uow.envios.obtener.return_value = None
    with pytest.raises(NoEncontrado):
        servicio.iniciar(
            TitularTipo.CLIENTE, uuid4(), "Asunto", "Hola", uuid4(), envio_id=uuid4()
        )
    repositorio.guardar.assert_not_called()


# --- Escribir ----------------------------------------------------------------


def test_un_mensaje_de_la_parte_nace_sin_leer():
    """Es lo que hace que la bandeja de pendientes signifique algo."""
    conversacion = nueva_conversacion()
    servicio, repositorio, _ = armar(conversacion)

    servicio.registrar_mensaje_de_la_parte(conversacion.id, "Necesito la fecha")

    mensaje = repositorio.guardar_mensaje.call_args[0][0]
    assert mensaje.autor is AutorMensaje.PARTE
    assert mensaje.leido is False
    assert conversacion.sin_leer == 1


def test_responder_no_suma_pendientes():
    conversacion = nueva_conversacion()
    servicio, repositorio, _ = armar(conversacion)
    servicio.responder(conversacion.id, "La fecha es el martes", uuid4())
    assert conversacion.sin_leer == 0
    assert repositorio.guardar_mensaje.call_args[0][0].leido is True


def test_escribir_actualiza_la_actividad():
    conversacion = nueva_conversacion()
    servicio, repositorio, _ = armar(conversacion)
    anterior = conversacion.actividad

    servicio.registrar_mensaje_de_la_parte(conversacion.id, "Hola")

    assert conversacion.actividad > anterior
    repositorio.actualizar.assert_called_once_with(conversacion)


def test_el_mensaje_se_guarda_antes_que_el_hilo():
    """Son dos escrituras sin transaccion compartida. El mensaje va primero
    porque es el dato que importa: el contador se puede recalcular, un mensaje
    perdido no."""
    conversacion = nueva_conversacion()
    servicio, repositorio, _ = armar(conversacion)
    orden = []
    repositorio.guardar_mensaje.side_effect = lambda m: orden.append("mensaje")
    repositorio.actualizar.side_effect = lambda c: orden.append("hilo")

    servicio.registrar_mensaje_de_la_parte(conversacion.id, "Hola")
    assert orden == ["mensaje", "hilo"]


@pytest.mark.parametrize("metodo", ["responder", "registrar_mensaje_de_la_parte"])
def test_no_se_escribe_en_una_conversacion_cerrada(metodo):
    conversacion = nueva_conversacion(estado=EstadoConversacion.CERRADA)
    servicio, repositorio, _ = armar(conversacion)
    argumentos = (conversacion.id, "Hola")
    if metodo == "responder":
        argumentos += (uuid4(),)
    with pytest.raises(ValidacionError):
        getattr(servicio, metodo)(*argumentos)
    repositorio.guardar_mensaje.assert_not_called()


def test_escribir_en_una_conversacion_inexistente():
    servicio, _, _ = armar(None)
    with pytest.raises(NoEncontrado):
        servicio.registrar_mensaje_de_la_parte(uuid4(), "Hola")


# --- Leer --------------------------------------------------------------------


def test_marcar_leidos_limpia_el_contador_y_la_base():
    conversacion = nueva_conversacion(sin_leer=3)
    servicio, repositorio, _ = armar(conversacion)
    repositorio.marcar_mensajes_leidos.return_value = 3

    assert servicio.marcar_leidos(conversacion.id) == 3
    assert conversacion.sin_leer == 0
    repositorio.marcar_mensajes_leidos.assert_called_once_with(conversacion.id)
    repositorio.actualizar.assert_called_once_with(conversacion)


def test_ver_el_hilo_compone_las_dos_colecciones():
    """Como EnvioConTramos (D6): la conversacion no carga sus mensajes."""
    conversacion = nueva_conversacion()
    servicio, repositorio, _ = armar(conversacion)
    mensajes = [
        nuevo_mensaje(conversacion_id=conversacion.id, momento=AHORA),
        nuevo_mensaje(
            conversacion_id=conversacion.id, momento=AHORA + timedelta(minutes=5)
        ),
    ]
    repositorio.listar_mensajes.return_value = mensajes

    hilo = servicio.ver_hilo(conversacion.id)
    assert hilo.conversacion is conversacion
    assert hilo.mensajes == mensajes
    assert hilo.ultimo is mensajes[-1]


def test_la_bandeja_filtra_en_la_base():
    """Recorrer todas las conversaciones en memoria seria leer de mas."""
    servicio, repositorio, _ = armar()
    servicio.listar_con_pendientes()
    repositorio.listar_con_pendientes.assert_called_once()


def test_listar_solo_abiertas_filtra_por_estado():
    servicio, repositorio, _ = armar()
    servicio.listar(solo_abiertas=True)
    repositorio.listar.assert_called_once_with(EstadoConversacion.ABIERTA)
    servicio.listar()
    repositorio.listar.assert_called_with(None)
