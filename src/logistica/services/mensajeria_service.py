"""Mensajeria con clientes, proveedores y operadores logisticos.

Las conversaciones y sus mensajes viven en MongoDB (D57); quienes conversan
—las partes y los usuarios internos— viven en PostgreSQL. No hay clave foranea
entre las dos, asi que que existan lo valida este servicio (D3).
"""
import logging
from datetime import datetime, timezone
from uuid import UUID, uuid4

from logistica.domain.facturacion import TitularTipo
from logistica.domain.mensajeria import (
    AutorMensaje,
    Conversacion,
    ConversacionConMensajes,
    EstadoConversacion,
    Mensaje,
)
from logistica.exceptions import NoEncontrado
from logistica.repositories.conversacion_repository import ConversacionRepository
from logistica.repositories.unidad_de_trabajo import UnidadDeTrabajo

log = logging.getLogger(__name__)


class MensajeriaService:
    def __init__(
        self, conversaciones: ConversacionRepository, unidad_de_trabajo: UnidadDeTrabajo
    ) -> None:
        self._repo = conversaciones
        self._uow = unidad_de_trabajo

    def iniciar(
        self,
        parte_tipo: TitularTipo,
        parte_id: UUID,
        asunto: str,
        cuerpo: str,
        usuario_id: UUID,
        envio_id: UUID | None = None,
    ) -> Conversacion:
        """Abre un hilo con una parte y deja el primer mensaje.

        Una conversacion nace **con** su primer mensaje: un hilo vacio no dice
        nada y habria que limpiarlo despues.
        """
        self._verificar(parte_tipo, parte_id, usuario_id, envio_id)
        ahora = datetime.now(timezone.utc)
        conversacion = Conversacion(
            id=uuid4(),
            parte_tipo=parte_tipo,
            parte_id=parte_id,
            asunto=asunto,
            fecha_inicio=ahora,
            envio_id=envio_id,
        )
        self._repo.guardar(conversacion)
        self._escribir(conversacion, AutorMensaje.INTERNO, usuario_id, cuerpo, ahora)
        log.info(
            "Conversacion abierta con %s %s: %s",
            parte_tipo.value, parte_id, conversacion.asunto,
        )
        return conversacion

    def _verificar(
        self,
        parte_tipo: TitularTipo,
        parte_id: UUID,
        usuario_id: UUID | None,
        envio_id: UUID | None,
    ) -> None:
        with self._uow as uow:
            repositorio = {
                TitularTipo.CLIENTE: uow.clientes,
                TitularTipo.PROVEEDOR: uow.proveedores,
                TitularTipo.OPERADOR: uow.operadores,
            }[parte_tipo]
            if repositorio.obtener(parte_id) is None:
                raise NoEncontrado(
                    f"No existe el {parte_tipo.value.lower()} {parte_id}"
                )
            if usuario_id is not None and uow.usuarios.obtener(usuario_id) is None:
                raise NoEncontrado(f"No existe el usuario {usuario_id}")
            if envio_id is not None and uow.envios.obtener(envio_id) is None:
                raise NoEncontrado(f"No existe el envio {envio_id}")

    def responder(
        self, conversacion_id: UUID, cuerpo: str, usuario_id: UUID
    ) -> Conversacion:
        """Respuesta de la empresa."""
        conversacion = self.obtener(conversacion_id)
        conversacion.admite_mensajes()
        with self._uow as uow:
            if uow.usuarios.obtener(usuario_id) is None:
                raise NoEncontrado(f"No existe el usuario {usuario_id}")
        self._escribir(
            conversacion,
            AutorMensaje.INTERNO,
            usuario_id,
            cuerpo,
            datetime.now(timezone.utc),
        )
        return conversacion

    def registrar_mensaje_de_la_parte(
        self, conversacion_id: UUID, cuerpo: str
    ) -> Conversacion:
        """Mensaje entrante, el que manda el cliente o el operador.

        En un sistema real entraria por un correo o una API; aca se carga desde
        el menu, que es lo que permite demostrar el ida y vuelta completo. Nace
        **sin leer**: es lo que hace que la bandeja de pendientes signifique algo.
        """
        conversacion = self.obtener(conversacion_id)
        conversacion.admite_mensajes()
        self._escribir(
            conversacion, AutorMensaje.PARTE, None, cuerpo, datetime.now(timezone.utc)
        )
        return conversacion

    def _escribir(
        self,
        conversacion: Conversacion,
        autor: AutorMensaje,
        autor_id: UUID | None,
        cuerpo: str,
        momento: datetime,
    ) -> None:
        """Guarda el mensaje y actualiza el hilo.

        Son dos escrituras en dos colecciones y **no comparten transaccion**.
        Si fallara la segunda, el mensaje quedaria guardado y el contador de
        pendientes corto. Se acepta porque el dato que importa -el mensaje- es
        el que se escribe primero: el contador se puede recalcular, un mensaje
        perdido no.
        """
        mensaje = Mensaje(
            id=uuid4(),
            conversacion_id=conversacion.id,
            autor=autor,
            autor_id=autor_id,
            cuerpo=cuerpo,
            momento=momento,
            # Lo que escribe la empresa ya lo leyo quien lo escribio.
            leido=autor is AutorMensaje.INTERNO,
        )
        self._repo.guardar_mensaje(mensaje)
        conversacion.registrar_actividad(momento, de_la_parte=mensaje.es_de_la_parte())
        self._repo.actualizar(conversacion)

    def marcar_leidos(self, conversacion_id: UUID) -> int:
        """Marca como leidos los mensajes de la parte. Devuelve cuantos eran."""
        conversacion = self.obtener(conversacion_id)
        cuantos = self._repo.marcar_mensajes_leidos(conversacion_id)
        conversacion.marcar_leida()
        self._repo.actualizar(conversacion)
        return cuantos

    def cerrar(self, conversacion_id: UUID) -> Conversacion:
        conversacion = self.obtener(conversacion_id)
        conversacion.cerrar()
        self._repo.actualizar(conversacion)
        return conversacion

    def reabrir(self, conversacion_id: UUID) -> Conversacion:
        conversacion = self.obtener(conversacion_id)
        conversacion.reabrir()
        self._repo.actualizar(conversacion)
        return conversacion

    # -- Consultas ------------------------------------------------------------

    def obtener(self, conversacion_id: UUID) -> Conversacion:
        conversacion = self._repo.obtener(conversacion_id)
        if conversacion is None:
            raise NoEncontrado(f"No existe la conversacion {conversacion_id}")
        return conversacion

    def ver_hilo(self, conversacion_id: UUID) -> ConversacionConMensajes:
        """La conversacion con sus mensajes. Son dos lecturas porque son dos
        colecciones: el servicio las compone, como `EnvioConTramos` (D6)."""
        conversacion = self.obtener(conversacion_id)
        return ConversacionConMensajes(
            conversacion=conversacion,
            mensajes=self._repo.listar_mensajes(conversacion_id),
        )

    def listar(self, solo_abiertas: bool = False) -> list[Conversacion]:
        return self._repo.listar(
            EstadoConversacion.ABIERTA if solo_abiertas else None
        )

    def listar_por_parte(self, parte_id: UUID) -> list[Conversacion]:
        return self._repo.listar_por_parte(parte_id)

    def listar_por_envio(self, envio_id: UUID) -> list[Conversacion]:
        return self._repo.listar_por_envio(envio_id)

    def listar_con_pendientes(self) -> list[Conversacion]:
        """La bandeja de entrada: lo que el operador tiene que mirar hoy."""
        return self._repo.listar_con_pendientes()
