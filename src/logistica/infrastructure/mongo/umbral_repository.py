"""Implementacion de UmbralRepository sobre MongoDB."""
from typing import Any

from pymongo.database import Database

from logistica.domain.umbral import MagnitudUmbral, Umbral
from logistica.infrastructure.mongo.conexion import traducir_errores
from logistica.repositories.umbral_repository import UmbralRepository

COLECCION = "umbrales"


def _a_documento(umbral: Umbral) -> dict[str, Any]:
    """Entidad -> documento. Solo el repositorio conoce las dos formas (D2)."""
    return {
        "_id": umbral.id,
        "tipo_contenedor": umbral.tipo_contenedor,
        "magnitud": umbral.magnitud.value,
        # float(): el validador pide un numero y Mongo guarda un int de Python como int.
        "minimo": float(umbral.minimo),
        "maximo": float(umbral.maximo),
        "unidad": umbral.unidad,
        "descripcion": umbral.descripcion,
    }


def _a_umbral(doc: dict[str, Any]) -> Umbral:
    return Umbral(
        id=doc["_id"],
        tipo_contenedor=doc["tipo_contenedor"],
        magnitud=MagnitudUmbral(doc["magnitud"]),
        minimo=doc["minimo"],
        maximo=doc["maximo"],
        unidad=doc["unidad"],
        descripcion=doc.get("descripcion", ""),
    )


class MongoUmbralRepository(UmbralRepository):
    def __init__(self, base: Database) -> None:
        self._coleccion = base[COLECCION]

    @traducir_errores
    def guardar(self, umbral: Umbral) -> None:
        # Se reemplaza por _id. Si ya hay otro umbral para el mismo tipo y magnitud
        # con otro id, el indice unico lo rechaza (DuplicateKeyError -> ConflictoDeDatos).
        self._coleccion.replace_one({"_id": umbral.id}, _a_documento(umbral), upsert=True)

    @traducir_errores
    def obtener(self, tipo_contenedor: str, magnitud: MagnitudUmbral) -> Umbral | None:
        doc = self._coleccion.find_one(
            {"tipo_contenedor": tipo_contenedor, "magnitud": magnitud.value}
        )
        return _a_umbral(doc) if doc else None

    @traducir_errores
    def eliminar(self, tipo_contenedor: str, magnitud: MagnitudUmbral) -> bool:
        resultado = self._coleccion.delete_one(
            {"tipo_contenedor": tipo_contenedor, "magnitud": magnitud.value}
        )
        return resultado.deleted_count > 0

    @traducir_errores
    def listar(self) -> list[Umbral]:
        docs = self._coleccion.find().sort([("tipo_contenedor", 1), ("magnitud", 1)])
        return [_a_umbral(d) for d in docs]
