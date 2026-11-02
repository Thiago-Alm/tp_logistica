"""Prediccion de atrasos y riesgos de los envios en curso.

Cruza PostgreSQL —envios, tramos, ubicaciones— con MongoDB —incidentes
abiertos— para armar, por cada envio que todavia no termino, un puntaje de
riesgo con sus motivos y una fecha de llegada proyectada (D55).
"""
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from uuid import UUID

from logistica.domain.envio import EstadoEnvio
from logistica.domain.incidente import SeveridadIncidente
from logistica.domain.prediccion import (
    PUNTOS_INCIDENTE_ABIERTO,
    PUNTOS_INCIDENTE_GRAVE,
    PUNTOS_LLEGADA_VENCIDA,
    PUNTOS_RECORRIDO_COMPLETO_SIN_ENTREGA,
    PUNTOS_SIN_TRAMOS,
    PUNTOS_TRAMO_LLEGADO_TARDE,
    PUNTOS_TRAMO_VENCIDO,
    FactorDeRiesgo,
    NivelRiesgo,
    PrediccionAtraso,
)
from logistica.repositories.incidente_repository import IncidenteRepository
from logistica.repositories.unidad_de_trabajo import UnidadDeTrabajo

log = logging.getLogger(__name__)

SIN_ATRASO = timedelta(0)

# Los estados finales no se predicen: ya se sabe como terminaron.
ESTADOS_EN_CURSO = tuple(e for e in EstadoEnvio if not e.es_final())

SEVERIDADES_GRAVES = (SeveridadIncidente.ALTA, SeveridadIncidente.CRITICA)


class PrediccionService:
    def __init__(
        self, incidentes: IncidenteRepository, unidad_de_trabajo: UnidadDeTrabajo
    ) -> None:
        self._incidentes = incidentes
        self._uow = unidad_de_trabajo

    def predecir_atrasos(
        self, momento: datetime | None = None
    ) -> list[PrediccionAtraso]:
        """Una prediccion por cada envio en curso, de mayor riesgo a menor.

        Se devuelven **todos**, incluidos los de riesgo BAJO: saber que un
        envio no tiene senales de atraso es tan util como saber que las tiene,
        y filtrar aca obligaria a adivinar que umbral quiere quien consulta.
        """
        ahora = momento or datetime.now(timezone.utc)
        incidentes_por_envio = self._incidentes_abiertos_por_envio()

        predicciones = []
        with self._uow as uow:
            ubicaciones = {u.id: u.etiqueta for u in uow.ubicaciones.listar()}
            for estado in ESTADOS_EN_CURSO:
                for envio in uow.envios.listar_por_estado(estado):
                    tramos = uow.tramos.listar_por_envio(envio.id)
                    predicciones.append(
                        self._predecir(
                            envio,
                            tramos,
                            incidentes_por_envio.get(envio.id, []),
                            ubicaciones,
                            ahora,
                        )
                    )

        predicciones.sort(key=lambda p: (p.puntaje, p.atraso_acumulado), reverse=True)
        criticos = sum(1 for p in predicciones if p.nivel.necesita_atencion())
        log.info(
            "Prediccion de atrasos: %s envios en curso, %s necesitan atencion",
            len(predicciones), criticos,
        )
        return predicciones

    def _incidentes_abiertos_por_envio(self) -> dict[UUID, list]:
        """Una sola consulta a MongoDB para todos los envios.

        `listar_abiertos()` ya existe y trae el envio_id de cada incidente, asi
        que agruparlos aca evita una consulta por envio.
        """
        por_envio: dict[UUID, list] = defaultdict(list)
        for incidente in self._incidentes.listar_abiertos():
            por_envio[incidente.envio_id].append(incidente)
        return por_envio

    @staticmethod
    def _predecir(envio, tramos, incidentes, ubicaciones, ahora) -> PrediccionAtraso:
        factores: list[FactorDeRiesgo] = []
        atraso = SIN_ATRASO

        # 1. Tramos que ya llegaron tarde. Esto no es una estimacion: paso, y
        #    el tiempo perdido se arrastra a los tramos que faltan.
        tarde = [
            t
            for t in tramos
            if t.fecha_llegada_real is not None
            and t.fecha_llegada_real > t.fecha_llegada_estimada
        ]
        for tramo in tarde:
            atraso = max(atraso, tramo.fecha_llegada_real - tramo.fecha_llegada_estimada)
        if tarde:
            factores.append(
                FactorDeRiesgo(
                    f"{len(tarde)} tramo(s) llegaron tarde "
                    f"(peor atraso: {_en_horas(atraso)})",
                    PUNTOS_TRAMO_LLEGADO_TARDE * len(tarde),
                )
            )

        # 2. Tramos vencidos sin llegada: estan tarde ahora mismo.
        vencidos = [
            t
            for t in tramos
            if t.fecha_llegada_real is None and t.fecha_llegada_estimada < ahora
        ]
        for tramo in vencidos:
            atraso = max(atraso, ahora - tramo.fecha_llegada_estimada)
        if vencidos:
            factores.append(
                FactorDeRiesgo(
                    f"{len(vencidos)} tramo(s) vencidos sin registrar llegada",
                    PUNTOS_TRAMO_VENCIDO * len(vencidos),
                )
            )

        # 3. Incidentes abiertos, pesados por severidad.
        if incidentes:
            graves = [i for i in incidentes if i.severidad in SEVERIDADES_GRAVES]
            puntos = PUNTOS_INCIDENTE_ABIERTO * len(incidentes)
            puntos += PUNTOS_INCIDENTE_GRAVE * len(graves)
            detalle = f"{len(incidentes)} incidente(s) abiertos"
            if graves:
                detalle += f", {len(graves)} de severidad alta o critica"
            factores.append(FactorDeRiesgo(detalle, puntos))

        # 4. La fecha de llegada del envio ya paso **y todavia falta recorrido**.
        #    Si todos los tramos ya llegaron, la fecha vencida no dice nada: el
        #    envio llego y lo que falta es registrar la entrega, que es el
        #    factor 5. Decir "la llegada vencio" en ese caso seria enganoso.
        estimada = max((t.fecha_llegada_estimada for t in tramos), default=None)
        if tramos and not vencidos and all(t.fecha_llegada_real is not None for t in tramos):
            factores.append(
                FactorDeRiesgo(
                    f"Todos los tramos llegaron pero el envio sigue {envio.estado.value}: "
                    "falta registrar la entrega",
                    PUNTOS_RECORRIDO_COMPLETO_SIN_ENTREGA,
                )
            )
        elif estimada is not None and estimada < ahora:
            factores.append(
                FactorDeRiesgo(
                    f"La llegada estimada vencio hace {_en_horas(ahora - estimada)}",
                    PUNTOS_LLEGADA_VENCIDA,
                )
            )

        # 5. Sin tramos no hay recorrido ni fecha: no se puede prometer nada.
        if not tramos:
            factores.append(
                FactorDeRiesgo(
                    "El envio no tiene tramos cargados: no hay fecha que cumplir",
                    PUNTOS_SIN_TRAMOS,
                )
            )

        return PrediccionAtraso(
            envio_id=envio.id,
            cliente_id=envio.cliente_id,
            estado=envio.estado.value,
            ruta=_ruta(envio, ubicaciones),
            llegada_estimada=estimada,
            atraso_acumulado=atraso,
            factores=tuple(factores),
        )

    def resumen_por_nivel(
        self, momento: datetime | None = None
    ) -> dict[NivelRiesgo, int]:
        """Cuantos envios en curso hay en cada nivel de riesgo.

        Es el reporte de analisis predictivo: la foto de la operacion, sin la
        lista envio por envio.
        """
        predicciones = self.predecir_atrasos(momento)
        return {
            nivel: sum(1 for p in predicciones if p.nivel is nivel)
            for nivel in NivelRiesgo
        }


def _ruta(envio, ubicaciones: dict) -> str:
    origen = ubicaciones.get(envio.origen_id, "?")
    destino = ubicaciones.get(envio.destino_id, "?")
    return f"{origen}->{destino}"


def _en_horas(delta: timedelta) -> str:
    """En horas y no en dias: un atraso de 18 horas redondeado a dias se lee
    como 0 y parece que no hubo atraso."""
    horas = int(delta.total_seconds() // 3600)
    if horas < 24:
        return f"{horas} h"
    return f"{horas // 24} d {horas % 24} h"
