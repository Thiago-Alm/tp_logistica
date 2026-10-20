"""Implementacion de IncidenteRepository sobre MongoDB."""
from typing import Any
from uuid import UUID

from pymongo.database import Database

from logistica.domain.incidente import (
    ESTADOS_ABIERTOS,
    CambioEstado,
    ContextoEnvio,
    EstadoIncidente,
    Incidente,
    SeveridadIncidente,
    TipoIncidente,
)
from logistica.exceptions import NoEncontrado
from logistica.infrastructure.mongo.conexion import traducir_errores
from logistica.repositories.incidente_repository import (
    AgrupacionIncidentes,
    IncidenteRepository,
)

COLECCION = "incidentes"

# Campo del documento por el que se agrupa cada eje. Todos tienen indice
# (ver scripts/mongo/mongo_modelo.js).
_CAMPO_DE_AGRUPACION = {
    AgrupacionIncidentes.PAIS_ORIGEN: "$contexto_envio.pais_origen",
    AgrupacionIncidentes.PAIS_DESTINO: "$contexto_envio.pais_destino",
    AgrupacionIncidentes.CLIENTE: "$contexto_envio.cliente_id",
    AgrupacionIncidentes.ESTADO: "$estado",
    AgrupacionIncidentes.RUTA: "$contexto_envio.ruta",
}


def _a_documento(incidente: Incidente) -> dict[str, Any]:
    """Entidad -> documento. El repositorio es el unico que conoce las dos formas:
    hacia arriba solo circulan entidades (D2)."""
    contexto = incidente.contexto_envio
    return {
        "_id": incidente.id,
        "envio_id": incidente.envio_id,
        "contenedor_id": incidente.contenedor_id,
        "tipo": incidente.tipo.value,
        "severidad": incidente.severidad.value,
        "estado": incidente.estado.value,
        "descripcion": incidente.descripcion,
        "fecha": incidente.fecha,
        "contexto_envio": {
            "cliente_id": contexto.cliente_id,
            "origen": contexto.origen,
            "destino": contexto.destino,
            "pais_origen": contexto.pais_origen,
            "pais_destino": contexto.pais_destino,
            "ruta": contexto.ruta,
        },
        "historial_estados": [
            {"estado": c.estado.value, "fecha": c.fecha, "usuario_id": c.usuario_id}
            for c in incidente.historial_estados
        ],
    }


def _a_incidente(doc: dict[str, Any]) -> Incidente:
    contexto = doc["contexto_envio"]
    return Incidente(
        id=doc["_id"],
        envio_id=doc["envio_id"],
        contenedor_id=doc.get("contenedor_id"),
        tipo=TipoIncidente(doc["tipo"]),
        severidad=SeveridadIncidente(doc["severidad"]),
        estado=EstadoIncidente(doc["estado"]),
        descripcion=doc["descripcion"],
        fecha=doc["fecha"],
        contexto_envio=ContextoEnvio(
            cliente_id=contexto["cliente_id"],
            origen=contexto.get("origen", ""),
            destino=contexto.get("destino", ""),
            pais_origen=contexto["pais_origen"],
            pais_destino=contexto["pais_destino"],
        ),
        historial_estados=[
            CambioEstado(
                estado=EstadoIncidente(c["estado"]),
                fecha=c["fecha"],
                usuario_id=c.get("usuario_id"),
            )
            for c in doc.get("historial_estados", [])
        ],
    )


class MongoIncidenteRepository(IncidenteRepository):
    def __init__(self, base: Database) -> None:
        self._coleccion = base[COLECCION]

    @traducir_errores
    def guardar(self, incidente: Incidente) -> None:
        self._coleccion.insert_one(_a_documento(incidente))

    @traducir_errores
    def actualizar(self, incidente: Incidente) -> None:
        resultado = self._coleccion.replace_one(
            {"_id": incidente.id}, _a_documento(incidente)
        )
        if resultado.matched_count == 0:
            raise NoEncontrado(f"No existe el incidente {incidente.id}")

    @traducir_errores
    def obtener(self, id: UUID) -> Incidente | None:
        doc = self._coleccion.find_one({"_id": id})
        return _a_incidente(doc) if doc else None

    @traducir_errores
    def listar_abiertos(self) -> list[Incidente]:
        estados = [e.value for e in ESTADOS_ABIERTOS]
        docs = self._coleccion.find({"estado": {"$in": estados}}).sort("fecha", -1)
        return [_a_incidente(d) for d in docs]

    @traducir_errores
    def listar_por_envio(self, envio_id: UUID) -> list[Incidente]:
        docs = self._coleccion.find({"envio_id": envio_id}).sort("fecha", -1)
        return [_a_incidente(d) for d in docs]

    @traducir_errores
    def contar_agrupado(
        self, por: AgrupacionIncidentes, limite: int | None = None
    ) -> list[tuple[str, int]]:
        pipeline: list[dict[str, Any]] = [
            {"$group": {"_id": _CAMPO_DE_AGRUPACION[por], "total": {"$sum": 1}}},
            # El desempate por _id hace estable el orden entre grupos iguales.
            {"$sort": {"total": -1, "_id": 1}},
        ]
        if limite is not None:
            pipeline.append({"$limit": limite})
        return [(str(d["_id"]), d["total"]) for d in self._coleccion.aggregate(pipeline)]

    def ranking_de_rutas(self, limite: int = 10) -> list[tuple[str, int]]:
        return self.contar_agrupado(AgrupacionIncidentes.RUTA, limite)
