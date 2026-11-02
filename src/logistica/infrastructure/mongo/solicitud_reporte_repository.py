"""Implementacion de SolicitudReporteRepository sobre MongoDB."""
from decimal import Decimal
from typing import Any
from uuid import UUID

from pymongo.database import Database

from logistica.domain.facturacion import TitularTipo
from logistica.domain.solicitud_reporte import (
    EstadoSolicitud,
    SolicitudReporte,
    TipoReporte,
)
from logistica.exceptions import NoEncontrado
from logistica.infrastructure.mongo.conexion import traducir_errores
from logistica.repositories.solicitud_reporte_repository import (
    SolicitudReporteRepository,
)

COLECCION = "reportes"


def _a_documento(solicitud: SolicitudReporte) -> dict[str, Any]:
    """Entidad -> documento. Solo el repositorio conoce las dos formas (D2)."""
    return {
        "_id": solicitud.id,
        "tipo": solicitud.tipo.value,
        "usuario_id": solicitud.usuario_id,
        "titular_tipo": solicitud.titular_tipo.value,
        "titular_id": solicitud.titular_id,
        "fecha_solicitud": solicitud.fecha_solicitud,
        # str(): BSON no tiene Decimal nativo en el driver sin configurarlo, y
        # un float perderia centavos (D15). El texto vuelve a Decimal al leer.
        "costo": str(solicitud.costo),
        "parametros": solicitud.parametros,
        "estado": solicitud.estado.value,
        "filas": solicitud.filas,
        "fecha_generacion": solicitud.fecha_generacion,
        "factura_id": solicitud.factura_id,
    }


def _a_solicitud(doc: dict[str, Any]) -> SolicitudReporte:
    return SolicitudReporte(
        id=doc["_id"],
        tipo=TipoReporte(doc["tipo"]),
        usuario_id=doc["usuario_id"],
        titular_tipo=TitularTipo(doc["titular_tipo"]),
        titular_id=doc["titular_id"],
        fecha_solicitud=doc["fecha_solicitud"],
        costo=Decimal(doc["costo"]),
        parametros=doc.get("parametros") or {},
        estado=EstadoSolicitud(doc["estado"]),
        filas=doc.get("filas"),
        fecha_generacion=doc.get("fecha_generacion"),
        factura_id=doc.get("factura_id"),
    )


class MongoSolicitudReporteRepository(SolicitudReporteRepository):
    def __init__(self, base: Database) -> None:
        self._coleccion = base[COLECCION]

    @traducir_errores
    def guardar(self, solicitud: SolicitudReporte) -> None:
        self._coleccion.insert_one(_a_documento(solicitud))

    @traducir_errores
    def actualizar(self, solicitud: SolicitudReporte) -> None:
        resultado = self._coleccion.replace_one(
            {"_id": solicitud.id}, _a_documento(solicitud)
        )
        if resultado.matched_count == 0:
            raise NoEncontrado(f"No existe la solicitud {solicitud.id}")

    @traducir_errores
    def obtener(self, id: UUID) -> SolicitudReporte | None:
        doc = self._coleccion.find_one({"_id": id})
        return _a_solicitud(doc) if doc else None

    @traducir_errores
    def listar(self, estado: EstadoSolicitud | None = None) -> list[SolicitudReporte]:
        filtro = {} if estado is None else {"estado": estado.value}
        docs = self._coleccion.find(filtro).sort("fecha_solicitud", -1)
        return [_a_solicitud(d) for d in docs]

    @traducir_errores
    def listar_por_titular(self, titular_id: UUID) -> list[SolicitudReporte]:
        docs = self._coleccion.find({"titular_id": titular_id}).sort(
            "fecha_solicitud", -1
        )
        return [_a_solicitud(d) for d in docs]
