"""Monitoreo IoT: lecturas historicas, umbrales configurados y alertas.

Junta tres motores en un solo caso de uso, y la division es la que justifica la
persistencia poliglota:

- la **lectura** es una serie temporal que crece sin parar y se consulta por
  sensor y rango de fechas: Cassandra (D20);
- el **umbral** es una configuracion chica, con forma distinta segun el tipo de
  contenedor: MongoDB (D25);
- la **alerta** es un documento con el detalle de lo que se violo: MongoDB;
- la **ficha del sensor** (modelo, cada cuanto reporta, en que contenedor esta)
  se relaciona con el contenedor: PostgreSQL.
"""
import logging
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from logistica.domain.alerta import Alerta, EstadoAlerta
from logistica.domain.lectura import Lectura
from logistica.domain.sensor import EstadoSensor, Sensor
from logistica.domain.umbral import MagnitudUmbral, Umbral
from logistica.exceptions import NoEncontrado, ValidacionError
from logistica.repositories.alerta_repository import AlertaRepository
from logistica.repositories.lectura_repository import (
    MAX_DIAS_POR_CONSULTA,
    LecturaRepository,
    dias_del_rango,
)
from logistica.repositories.umbral_repository import UmbralRepository
from logistica.repositories.unidad_de_trabajo import UnidadDeTrabajo
from logistica.services.deteccion_anomalias_service import MAGNITUDES_EVALUADAS

log = logging.getLogger(__name__)

LIMITE_ULTIMAS_POR_DEFECTO = 20


@dataclass(frozen=True)
class CoberturaUmbrales:
    """Si cada tipo de contenedor en uso tiene umbral de una magnitud.

    Existe por un error real: los umbrales cubrian 2 de los 7 tipos de
    contenedor, asi que la deteccion salteaba sensores en silencio y nadie se
    enteraba. Una configuracion incompleta es peor que una ausente, porque
    parece que esta funcionando.
    """

    tipo_contenedor: str
    sensores: int
    magnitudes_cubiertas: tuple[str, ...]
    magnitudes_faltantes: tuple[str, ...]

    @property
    def esta_cubierto(self) -> bool:
        return not self.magnitudes_faltantes


class MonitoreoService:
    def __init__(
        self,
        lecturas: LecturaRepository,
        umbrales: UmbralRepository,
        alertas: AlertaRepository,
        unidad_de_trabajo: UnidadDeTrabajo,
    ) -> None:
        self._lecturas = lecturas
        self._umbrales = umbrales
        self._alertas = alertas
        self._uow = unidad_de_trabajo

    # -- Sensores (PostgreSQL) -----------------------------------------------

    def listar_sensores(self, solo_activos: bool = False) -> list[Sensor]:
        with self._uow as uow:
            return uow.sensores.listar(EstadoSensor.ACTIVO if solo_activos else None)

    def listar_sensores_de_contenedor(self, contenedor_id: UUID) -> list[Sensor]:
        with self._uow as uow:
            if uow.contenedores.obtener(contenedor_id) is None:
                raise NoEncontrado(f"No existe el contenedor {contenedor_id}")
            return uow.sensores.listar_por_contenedor(contenedor_id)

    def buscar_sensor(self, texto: str) -> Sensor:
        """Resuelve un sensor por su numero de serie o su UUID.

        Igual que el contenedor en D45: el numero de serie es lo que esta
        impreso en el equipo, el UUID es interno.
        """
        texto = texto.strip()
        with self._uow as uow:
            try:
                sensor = uow.sensores.obtener(UUID(texto))
            except ValueError:
                sensor = uow.sensores.obtener_por_numero_serie(texto.upper())
        if sensor is None:
            raise NoEncontrado(f"No existe un sensor con ID o numero de serie {texto!r}")
        return sensor

    # -- Lecturas (Cassandra) -------------------------------------------------

    def historico(
        self, sensor_id: UUID, desde: datetime, hasta: datetime
    ) -> list[Lectura]:
        """Consulta historica de las lecturas de un sensor en un rango.

        El tope de dias sale del contrato del repositorio, igual que en el
        recorrido GPS (D45): cada dia es una particion de Cassandra.
        """
        self._validar_rango(desde, hasta)
        with self._uow as uow:
            if uow.sensores.obtener(sensor_id) is None:
                raise NoEncontrado(f"No existe el sensor {sensor_id}")
        return self._lecturas.listar_por_sensor(sensor_id, desde, hasta)

    def ultimas_lecturas(
        self, sensor_id: UUID, cantidad: int = LIMITE_ULTIMAS_POR_DEFECTO
    ) -> list[Lectura]:
        """Las ultimas mediciones de un sensor, sin tener que elegir un rango."""
        if cantidad <= 0:
            raise ValidacionError("La cantidad de lecturas tiene que ser positiva")
        return self._lecturas.ultimas(sensor_id, cantidad)

    @staticmethod
    def _validar_rango(desde: datetime, hasta: datetime) -> None:
        if desde.tzinfo is None or hasta.tzinfo is None:
            raise ValidacionError("Las fechas de la consulta deben tener zona horaria")
        if desde > hasta:
            raise ValidacionError("La fecha inicial no puede ser posterior a la final")
        dias = len(dias_del_rango(desde, hasta))
        if dias > MAX_DIAS_POR_CONSULTA:
            raise ValidacionError(
                f"El rango abarca {dias} dias; el maximo por consulta es "
                f"{MAX_DIAS_POR_CONSULTA}. Pedilo por tramos."
            )

    # -- Umbrales (MongoDB) ---------------------------------------------------

    def listar_umbrales(self) -> list[Umbral]:
        return self._umbrales.listar()

    def configurar_umbral(self, umbral: Umbral) -> None:
        """Alta o modificacion de un umbral. El rango lo valida la entidad."""
        self._umbrales.guardar(umbral)
        log.info(
            "Umbral de %s para %s: [%s, %s] %s",
            umbral.magnitud.value,
            umbral.tipo_contenedor,
            umbral.minimo,
            umbral.maximo,
            umbral.unidad,
        )

    def cobertura_de_umbrales(self) -> list[CoberturaUmbrales]:
        """Control de integridad: que tipos de contenedor con sensores quedan
        sin umbral configurado.

        Cruza los tres motores que participan de la deteccion: los sensores y
        el tipo de su contenedor salen de PostgreSQL, los umbrales de MongoDB.
        """
        configurados: dict[str, set[MagnitudUmbral]] = {}
        for umbral in self._umbrales.listar():
            configurados.setdefault(umbral.tipo_contenedor, set()).add(umbral.magnitud)

        with self._uow as uow:
            tipos = {c.id: c.tipo for c in uow.contenedores.listar()}
            sensores = uow.sensores.listar(EstadoSensor.ACTIVO)

        por_tipo: dict[str, int] = {}
        for sensor in sensores:
            tipo = tipos.get(sensor.contenedor_id) if sensor.contenedor_id else None
            if tipo is not None:
                por_tipo[tipo] = por_tipo.get(tipo, 0) + 1

        resultado = []
        for tipo, cantidad in sorted(por_tipo.items()):
            tiene = configurados.get(tipo, set())
            resultado.append(
                CoberturaUmbrales(
                    tipo_contenedor=tipo,
                    sensores=cantidad,
                    # Solo las magnitudes que la deteccion compara: marcar
                    # como faltante un umbral que nadie consulta seria ruido.
                    magnitudes_cubiertas=tuple(
                        sorted(m.value for m in MAGNITUDES_EVALUADAS if m in tiene)
                    ),
                    magnitudes_faltantes=tuple(
                        sorted(m.value for m in MAGNITUDES_EVALUADAS if m not in tiene)
                    ),
                )
            )
        return resultado

    # -- Alertas (MongoDB) ----------------------------------------------------

    def listar_alertas_abiertas(self) -> list[Alerta]:
        """Reporte "Alertas generadas": ABIERTA y RECONOCIDA."""
        return self._alertas.listar_abiertas()

    def listar_alertas_de_sensor(
        self, sensor_id: UUID, limite: int = 50
    ) -> list[Alerta]:
        if limite <= 0:
            raise ValidacionError("El limite tiene que ser positivo")
        return self._alertas.listar_por_sensor(sensor_id, limite)

    def cambiar_estado_alerta(
        self, alerta_id: UUID, destino: EstadoAlerta
    ) -> Alerta:
        """Reconocer o cerrar una alerta.

        La alerta no tiene mapa de transiciones como el incidente o el envio
        (D4): sus tres estados son una secuencia lineal, asi que la unica regla
        es que una alerta CERRADA no vuelve atras.
        """
        alerta = self._alertas.obtener(alerta_id)
        if alerta is None:
            raise NoEncontrado(f"No existe la alerta {alerta_id}")
        if alerta.estado is EstadoAlerta.CERRADA:
            raise ValidacionError("Una alerta CERRADA es final")
        if destino is alerta.estado:
            raise ValidacionError(f"La alerta ya esta {destino.value}")
        alerta.estado = destino
        self._alertas.actualizar(alerta)
        return alerta
