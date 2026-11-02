"""Menu de mensajeria con clientes, proveedores y operadores logisticos."""

from uuid import UUID

from logistica.cli import consola
from logistica.cli.permisos import NIVEL_AUDITOR, NIVEL_OPERADOR, opciones_para
from logistica.domain.facturacion import TitularTipo
from logistica.domain.mensajeria import Conversacion
from logistica.exceptions import LogisticaError
from logistica.services.mensajeria_service import MensajeriaService


def _elegir_de(valores: list, etiqueta: str, texto=str):
    consola.aviso(
        f"{etiqueta}: " + ", ".join(f"{i}={texto(v)}" for i, v in enumerate(valores, 1))
    )
    elegido = consola.pedir(etiqueta).strip()
    if elegido.isdigit() and 1 <= int(elegido) <= len(valores):
        return valores[int(elegido) - 1]
    consola.error(f"{etiqueta} invalido.")
    return None


def construir(
    servicio: MensajeriaService,
    clientes,
    proveedores,
    operadores,
    usuarios,
    rol_nivel: int = NIVEL_OPERADOR,
) -> None:
    partes_por_tipo = {
        TitularTipo.CLIENTE: clientes,
        TitularTipo.PROVEEDOR: proveedores,
        TitularTipo.OPERADOR: operadores,
    }

    def _nombres() -> dict:
        nombres = {}
        for servicio_parte in partes_por_tipo.values():
            try:
                for parte in servicio_parte.listar():
                    nombres[parte.id] = parte.razon_social
            except LogisticaError:
                continue
        return nombres

    def _mostrar(conversaciones: list[Conversacion]) -> None:
        if not conversaciones:
            consola.aviso("No hay conversaciones para mostrar.")
            return
        nombres = _nombres()
        consola.tabla(
            ["ID", "ASUNTO", "PARTE", "CON", "ESTADO", "SIN LEER", "ACTIVIDAD"],
            [
                [
                    str(c.id),
                    c.asunto[:26],
                    c.parte_tipo.value,
                    nombres.get(c.parte_id, str(c.parte_id)[-12:])[:22],
                    c.estado.value,
                    str(c.sin_leer) if c.sin_leer else "-",
                    f"{c.actividad.astimezone():%d/%m %H:%M}" if c.actividad else "-",
                ]
                for c in conversaciones
            ],
        )

    def _elegir_conversacion(conversaciones: list[Conversacion]) -> Conversacion | None:
        if not conversaciones:
            consola.aviso("No hay conversaciones.")
            return None
        _mostrar(conversaciones)
        texto = consola.pedir("ID de la conversacion (o un fragmento)").strip().lower()
        if not texto:
            consola.error("Hace falta un ID.")
            return None
        encontrada = next(
            (c for c in conversaciones if texto in str(c.id).lower()), None
        )
        if encontrada is None:
            consola.error("No se encontro esa conversacion.")
        return encontrada

    def _elegir_usuario():
        try:
            lista = usuarios.listar(solo_activos=True)
        except LogisticaError as error:
            consola.error(str(error))
            return None
        if not lista:
            consola.error("No hay usuarios activos.")
            return None
        return _elegir_de(lista, "Usuario que escribe", lambda u: u.nombre_completo)

    def iniciar() -> None:
        consola.titulo("Abrir una conversacion con una parte")
        tipo = _elegir_de(list(TitularTipo), "Tipo de parte", lambda t: t.value)
        if tipo is None:
            return
        try:
            partes = partes_por_tipo[tipo].listar()
        except LogisticaError as error:
            consola.error(str(error))
            return
        if not partes:
            consola.error(f"No hay {tipo.value.lower()}es cargados.")
            return
        parte = _elegir_de(partes, "Parte", lambda p: p.razon_social)
        if parte is None:
            return

        asunto = consola.pedir("Asunto")
        cuerpo = consola.pedir("Mensaje")
        texto_envio = consola.pedir("ID del envio (Enter si es general)").strip()
        envio_id = None
        if texto_envio:
            try:
                envio_id = UUID(texto_envio)
            except ValueError:
                consola.error("El ID del envio no es valido.")
                return
        usuario = _elegir_usuario()
        if usuario is None:
            return

        try:
            conversacion = servicio.iniciar(
                tipo, parte.id, asunto, cuerpo, usuario.id, envio_id
            )
        except LogisticaError as error:
            consola.error(str(error))
            return
        consola.exito(f"Conversacion abierta con {parte.razon_social}.")
        consola.aviso(f"ID: {conversacion.id}")

    def ver_hilo() -> None:
        consola.titulo("Ver una conversacion")
        try:
            conversacion = _elegir_conversacion(servicio.listar())
            if conversacion is None:
                return
            hilo = servicio.ver_hilo(conversacion.id)
        except LogisticaError as error:
            consola.error(str(error))
            return

        consola.aviso(f"{hilo.conversacion.asunto} ({hilo.conversacion.estado.value})")
        if hilo.conversacion.envio_id:
            consola.aviso(f"Sobre el envio {hilo.conversacion.envio_id}")
        consola.tabla(
            ["MOMENTO", "DE", "MENSAJE", "LEIDO"],
            [
                [
                    f"{m.momento.astimezone():%d/%m %H:%M}",
                    m.autor.value,
                    m.cuerpo[:60],
                    "si" if m.leido else "NO",
                ]
                for m in hilo.mensajes
            ],
        )

    def responder() -> None:
        consola.titulo("Responder a una parte")
        try:
            conversacion = _elegir_conversacion(servicio.listar(solo_abiertas=True))
            if conversacion is None:
                return
            cuerpo = consola.pedir("Respuesta")
            usuario = _elegir_usuario()
            if usuario is None:
                return
            servicio.responder(conversacion.id, cuerpo, usuario.id)
        except LogisticaError as error:
            consola.error(str(error))
            return
        consola.exito("Respuesta enviada.")

    def registrar_entrante() -> None:
        consola.titulo("Registrar un mensaje de la parte")
        consola.aviso(
            "En un sistema real entraria por un correo o una API. Se carga a "
            "mano para poder ver el ida y vuelta completo."
        )
        try:
            conversacion = _elegir_conversacion(servicio.listar(solo_abiertas=True))
            if conversacion is None:
                return
            cuerpo = consola.pedir("Mensaje de la parte")
            servicio.registrar_mensaje_de_la_parte(conversacion.id, cuerpo)
        except LogisticaError as error:
            consola.error(str(error))
            return
        consola.exito("Mensaje registrado. Queda sin leer.")

    def pendientes() -> None:
        consola.titulo("Bandeja de entrada")
        consola.aviso("Conversaciones con mensajes de la parte sin leer.")
        try:
            conversaciones = servicio.listar_con_pendientes()
        except LogisticaError as error:
            consola.error(str(error))
            return
        if not conversaciones:
            consola.exito("No hay mensajes pendientes.")
            return
        _mostrar(conversaciones)

    def marcar_leidos() -> None:
        consola.titulo("Marcar una conversacion como leida")
        try:
            conversacion = _elegir_conversacion(servicio.listar_con_pendientes())
            if conversacion is None:
                return
            cuantos = servicio.marcar_leidos(conversacion.id)
        except LogisticaError as error:
            consola.error(str(error))
            return
        consola.exito(f"{cuantos} mensaje(s) marcados como leidos.")

    def listar() -> None:
        consola.titulo("Conversaciones")
        try:
            _mostrar(servicio.listar())
        except LogisticaError as error:
            consola.error(str(error))

    def por_parte() -> None:
        consola.titulo("Conversaciones con una parte")
        tipo = _elegir_de(list(TitularTipo), "Tipo de parte", lambda t: t.value)
        if tipo is None:
            return
        try:
            partes = partes_por_tipo[tipo].listar()
            parte = _elegir_de(partes, "Parte", lambda p: p.razon_social)
            if parte is None:
                return
            _mostrar(servicio.listar_por_parte(parte.id))
        except LogisticaError as error:
            consola.error(str(error))

    def cerrar_o_reabrir() -> None:
        consola.titulo("Cerrar o reabrir una conversacion")
        try:
            conversacion = _elegir_conversacion(servicio.listar())
            if conversacion is None:
                return
            if conversacion.esta_abierta:
                actualizada = servicio.cerrar(conversacion.id)
            else:
                actualizada = servicio.reabrir(conversacion.id)
        except LogisticaError as error:
            consola.error(str(error))
            return
        consola.exito(f"La conversacion quedo {actualizada.estado.value}.")

    secciones = [
        (NIVEL_OPERADOR, "Bandeja de entrada (sin leer)", pendientes),
        (NIVEL_AUDITOR, "Listar conversaciones", listar),
        (NIVEL_AUDITOR, "Ver una conversacion", ver_hilo),
        (NIVEL_OPERADOR, "Abrir una conversacion", iniciar),
        (NIVEL_OPERADOR, "Responder a una parte", responder),
        (NIVEL_OPERADOR, "Registrar un mensaje de la parte", registrar_entrante),
        (NIVEL_OPERADOR, "Marcar como leida", marcar_leidos),
        (NIVEL_AUDITOR, "Conversaciones con una parte", por_parte),
        (NIVEL_OPERADOR, "Cerrar o reabrir una conversacion", cerrar_o_reabrir),
    ]
    consola.menu("Mensajeria con las partes", opciones_para(rol_nivel, secciones))
