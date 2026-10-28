"""Consulta del recorrido GPS de un contenedor."""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from logistica.domain.lectura import Posicion
from logistica.exceptions import NoEncontrado, ValidacionError
from logistica.repositories.lectura_repository import LecturaRepository
from logistica.repositories.unidad_de_trabajo import UnidadDeTrabajo


class GPSService:
    def __init__(
        self,
        lecturas: LecturaRepository,
        unidad_de_trabajo: UnidadDeTrabajo,
    ) -> None:
        self._lecturas = lecturas
        self._uow = unidad_de_trabajo

    def recorrido(
        self,
        contenedor_id: UUID,
        desde: datetime,
        hasta: datetime,
    ) -> list[Posicion]:
        if desde.tzinfo is None or desde.utcoffset() is None:
            raise ValidacionError("La fecha inicial debe incluir zona horaria")

        if hasta.tzinfo is None or hasta.utcoffset() is None:
            raise ValidacionError("La fecha final debe incluir zona horaria")

        desde = desde.astimezone(timezone.utc)
        hasta = hasta.astimezone(timezone.utc)

        if desde > hasta:
            raise ValidacionError(
                "La fecha inicial no puede ser posterior a la final"
            )

        if hasta - desde > timedelta(days=31):
            raise ValidacionError(
                "Consulta un intervalo de hasta 31 dias por vez"
            )

        with self._uow as uow:
            if uow.contenedores.obtener(contenedor_id) is None:
                raise NoEncontrado(f"No existe el contenedor {contenedor_id}")

        return self._lecturas.posiciones_de_contenedor(
            contenedor_id, desde, hasta
        )