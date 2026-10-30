"""Implementacion de AlertaRepository sobre MongoDB."""
from typing import Any
from uuid import UUID

from pymongo.database import Database

from logistica.domain.alerta import (
    ESTADOS_ABIERTOS_ALERTA,
    Alerta,
    DetalleAlerta,
    EstadoAlerta,
    SeveridadAlerta,
    TipoAlerta,
)
from logistica.exceptions import NoEncontrado
from logistica.infrastructure.mongo.conexion import traducir_errores
from logistica.repositories.alerta_repository import AlertaRepository

COLECCION = "alertas"


def _a_documento(alerta: Alerta) -> dict[str, Any]:
    """Entidad -> documento. Solo el repositorio conoce las dos formas (D2)."""
    doc: dict[str, Any] = {
        "_id": alerta.id,
        "tipo": alerta.tipo.value,
        "sensor_id": alerta.sensor_id,
        "contenedor_id": alerta.contenedor_id,
        "envio_id": alerta.envio_id,
        "evento_id": alerta.evento_id,
        "estado": alerta.estado.value,
        "severidad": alerta.severidad.value,
        "fecha": alerta.fecha,
    }
    if alerta.detalle is not None:
        doc["detalle"] = {
            "valor": float(alerta.detalle.valor),
            "umbral": float(alerta.detalle.umbral),
            "momento_lectura": alerta.detalle.momento_lectura,
        }
    return doc


def _a_alerta(doc: dict[str, Any]) -> Alerta:
    detalle = doc.get("detalle")
    return Alerta(
        id=doc["_id"],
        tipo=TipoAlerta(doc["tipo"]),
        sensor_id=doc["sensor_id"],
        severidad=SeveridadAlerta(doc["severidad"]),
        fecha=doc["fecha"],
        detalle=(
            DetalleAlerta(
                valor=detalle["valor"],
                umbral=detalle["umbral"],
                momento_lectura=detalle["momento_lectura"],
            )
            if detalle
            else None
        ),
        contenedor_id=doc.get("contenedor_id"),
        envio_id=doc.get("envio_id"),
        evento_id=doc.get("evento_id"),
        estado=EstadoAlerta(doc["estado"]),
    )


class MongoAlertaRepository(AlertaRepository):
    def __init__(self, base: Database) -> None:
        self._coleccion = base[COLECCION]

    @traducir_errores
    def guardar(self, alerta: Alerta) -> bool:
        doc = _a_documento(alerta)
        id_alerta = doc.pop("_id")
        # $setOnInsert: si la alerta ya existe, no se toca nada. upserted_id solo
        # viene cargado cuando el documento se creo en esta llamada.
        resultado = self._coleccion.update_one(
            {"_id": id_alerta}, {"$setOnInsert": doc}, upsert=True
        )
        return resultado.upserted_id is not None

    @traducir_errores
    def actualizar(self, alerta: Alerta) -> None:
        resultado = self._coleccion.replace_one(
            {"_id": alerta.id}, _a_documento(alerta)
        )
        if resultado.matched_count == 0:
            raise NoEncontrado(f"No existe la alerta {alerta.id}")

    @traducir_errores
    def obtener(self, id: UUID) -> Alerta | None:
        doc = self._coleccion.find_one({"_id": id})
        return _a_alerta(doc) if doc else None

    @traducir_errores
    def listar_abiertas(self) -> list[Alerta]:
        estados = [e.value for e in ESTADOS_ABIERTOS_ALERTA]
        docs = self._coleccion.find({"estado": {"$in": estados}}).sort("fecha", -1)
        return [_a_alerta(d) for d in docs]

    @traducir_errores
    def listar_por_sensor(self, sensor_id: UUID, limite: int = 50) -> list[Alerta]:
        docs = self._coleccion.find({"sensor_id": sensor_id}).sort("fecha", -1).limit(limite)
        return [_a_alerta(d) for d in docs]
