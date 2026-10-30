"""Implementacion de ConversacionRepository sobre MongoDB.

Dos colecciones: `conversaciones` y `mensajes`, con los mensajes referenciando
su hilo por `conversacion_id` (D57).
"""
from typing import Any
from uuid import UUID

from pymongo.database import Database

from logistica.domain.facturacion import TitularTipo
from logistica.domain.mensajeria import (
    AutorMensaje,
    Conversacion,
    EstadoConversacion,
    Mensaje,
)
from logistica.exceptions import NoEncontrado
from logistica.infrastructure.mongo.conexion import traducir_errores
from logistica.repositories.conversacion_repository import ConversacionRepository

CONVERSACIONES = "conversaciones"
MENSAJES = "mensajes"


def _a_documento(conversacion: Conversacion) -> dict[str, Any]:
    """Entidad -> documento. Solo el repositorio conoce las dos formas (D2)."""
    return {
        "_id": conversacion.id,
        "parte_tipo": conversacion.parte_tipo.value,
        "parte_id": conversacion.parte_id,
        "asunto": conversacion.asunto,
        "envio_id": conversacion.envio_id,
        "estado": conversacion.estado.value,
        "creada_en": conversacion.fecha_inicio,
        "actividad": conversacion.actividad,
        "sin_leer": conversacion.sin_leer,
    }


def _a_conversacion(doc: dict[str, Any]) -> Conversacion:
    return Conversacion(
        id=doc["_id"],
        parte_tipo=TitularTipo(doc["parte_tipo"]),
        parte_id=doc["parte_id"],
        asunto=doc["asunto"],
        fecha_inicio=doc["creada_en"],
        envio_id=doc.get("envio_id"),
        estado=EstadoConversacion(doc["estado"]),
        actividad=doc.get("actividad"),
        sin_leer=doc.get("sin_leer", 0),
    )


def _a_documento_mensaje(mensaje: Mensaje) -> dict[str, Any]:
    return {
        "_id": mensaje.id,
        "conversacion_id": mensaje.conversacion_id,
        "autor": mensaje.autor.value,
        "autor_id": mensaje.autor_id,
        "cuerpo": mensaje.cuerpo,
        "fecha": mensaje.momento,
        "leido": mensaje.leido,
    }


def _a_mensaje(doc: dict[str, Any]) -> Mensaje:
    return Mensaje(
        id=doc["_id"],
        conversacion_id=doc["conversacion_id"],
        autor=AutorMensaje(doc["autor"]),
        autor_id=doc.get("autor_id"),
        cuerpo=doc["cuerpo"],
        momento=doc["fecha"],
        leido=doc.get("leido", False),
    )


class MongoConversacionRepository(ConversacionRepository):
    def __init__(self, base: Database) -> None:
        self._conversaciones = base[CONVERSACIONES]
        self._mensajes = base[MENSAJES]

    @traducir_errores
    def guardar(self, conversacion: Conversacion) -> None:
        self._conversaciones.insert_one(_a_documento(conversacion))

    @traducir_errores
    def actualizar(self, conversacion: Conversacion) -> None:
        resultado = self._conversaciones.replace_one(
            {"_id": conversacion.id}, _a_documento(conversacion)
        )
        if resultado.matched_count == 0:
            raise NoEncontrado(f"No existe la conversacion {conversacion.id}")

    @traducir_errores
    def obtener(self, id: UUID) -> Conversacion | None:
        doc = self._conversaciones.find_one({"_id": id})
        return _a_conversacion(doc) if doc else None

    @traducir_errores
    def listar(self, estado: EstadoConversacion | None = None) -> list[Conversacion]:
        filtro = {} if estado is None else {"estado": estado.value}
        return self._buscar(filtro)

    @traducir_errores
    def listar_por_parte(self, parte_id: UUID) -> list[Conversacion]:
        return self._buscar({"parte_id": parte_id})

    @traducir_errores
    def listar_por_envio(self, envio_id: UUID) -> list[Conversacion]:
        return self._buscar({"envio_id": envio_id})

    @traducir_errores
    def listar_con_pendientes(self) -> list[Conversacion]:
        return self._buscar({"sin_leer": {"$gt": 0}})

    def _buscar(self, filtro: dict) -> list[Conversacion]:
        docs = self._conversaciones.find(filtro).sort("actividad", -1)
        return [_a_conversacion(d) for d in docs]

    @traducir_errores
    def guardar_mensaje(self, mensaje: Mensaje) -> None:
        self._mensajes.insert_one(_a_documento_mensaje(mensaje))

    @traducir_errores
    def listar_mensajes(self, conversacion_id: UUID) -> list[Mensaje]:
        docs = self._mensajes.find({"conversacion_id": conversacion_id}).sort("fecha", 1)
        return [_a_mensaje(d) for d in docs]

    @traducir_errores
    def marcar_mensajes_leidos(self, conversacion_id: UUID) -> int:
        resultado = self._mensajes.update_many(
            {
                "conversacion_id": conversacion_id,
                "autor": AutorMensaje.PARTE.value,
                "leido": False,
            },
            {"$set": {"leido": True}},
        )
        return resultado.modified_count
