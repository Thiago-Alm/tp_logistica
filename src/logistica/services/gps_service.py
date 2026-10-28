"""Consulta del recorrido GPS de un contenedor."""

from datetime import datetime, timezone
from uuid import UUID

from logistica.domain.contenedor import Contenedor
from logistica.domain.lectura import Posicion
from logistica.exceptions import NoEncontrado, ValidacionError
from logistica.repositories.lectura_repository import (
    MAX_DIAS_POR_CONSULTA,
    LecturaRepository,
    dias_del_rango,
)
from logistica.repositories.unidad_de_trabajo import UnidadDeTrabajo


class GPSService:
    def __init__(
        self,
        lecturas: LecturaRepository,
        unidad_de_trabajo: UnidadDeTrabajo,
    ) -> None:
        self._lecturas = lecturas
        self._uow = unidad_de_trabajo

    def buscar_contenedor(self, texto: str) -> Contenedor:
        """Resuelve un contenedor por su codigo ISO (MAEU1122334) o su UUID.

        El codigo ISO esta impreso en el contenedor real y es lo que tiene a
        mano un operador; el UUID es interno. `obtener_por_codigo` existe en el
        repositorio desde el principio, asi que no hace falta nada nuevo."""
        texto = texto.strip()
        contenedor = None
        with self._uow as uow:
            try:
                contenedor = uow.contenedores.obtener(UUID(texto))
            except ValueError:
                contenedor = uow.contenedores.obtener_por_codigo(texto.upper())
        if contenedor is None:
            raise NoEncontrado(f"No existe un contenedor con ID o codigo {texto!r}")
        return contenedor

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

        # El tope sale del contrato del repositorio, no de un literal: se
        # cuentan dias de calendario, igual que las particiones que hay que
        # leer. Medir tiempo transcurrido daria dos limites distintos y pedir
        # "los ultimos 31 dias" pasaria aca para que lo rechace el motor (D45).
        dias = len(dias_del_rango(desde, hasta))
        if dias > MAX_DIAS_POR_CONSULTA:
            raise ValidacionError(
                f"El rango abarca {dias} dias; el maximo por consulta es "
                f"{MAX_DIAS_POR_CONSULTA}. Pedilo por tramos."
            )

        with self._uow as uow:
            if uow.contenedores.obtener(contenedor_id) is None:
                raise NoEncontrado(f"No existe el contenedor {contenedor_id}")

        return self._lecturas.posiciones_de_contenedor(
            contenedor_id, desde, hasta
        )
