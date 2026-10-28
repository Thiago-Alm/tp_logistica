"""Simulador de sensores IoT.

Genera lecturas continuas, las guarda en Cassandra con el LecturaRepository y
evalua cada una con la deteccion de anomalias, que crea la alerta en MongoDB
cuando la temperatura sale del umbral configurado (D25, D33, D34).

Uso (con los contenedores arriba y los scripts de Mongo y Cassandra cargados):

    python -m logistica.jobs.simulador_iot --ciclos 60 --intervalo 1 --semilla 42

Con --ciclos 0 corre hasta que se lo corta con Ctrl+C.
"""
import argparse
import json
import logging
import math
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from logistica.config import Settings
from logistica.domain.lectura import Lectura
from logistica.exceptions import ErrorDePersistencia, LogisticaError, ValidacionError
from logistica.repositories.heartbeat_repository import HeartbeatRepository
from logistica.repositories.lectura_repository import LecturaRepository
from logistica.services.deteccion_anomalias_service import DeteccionAnomaliasService

log = logging.getLogger(__name__)

# Rango de temperatura que se simula para un tipo de contenedor sin umbral
# configurado (en ese caso la deteccion avisa que no puede evaluarlo).
RANGO_POR_DEFECTO = (0.0, 40.0)
# Un ciclo que falla se registra y se sigue; si fallan tantos seguidos se aborta.
MAX_ERRORES_SEGUIDOS = 5
# Cada cuantos ciclos exitosos se deja una linea de progreso en el log.
CICLOS_ENTRE_AVISOS = 10
# Punto de partida de los sensores (zona del puerto de Buenos Aires) y paso por ciclo.
LATITUD_INICIAL = -34.60
LONGITUD_INICIAL = -58.37
PASO_GPS = 0.0005


@dataclass
class SensorSimulado:
    sensor_id: UUID
    contenedor_id: UUID
    tipo_contenedor: str
    envio_id: UUID | None = None


@dataclass
class _Estado:
    """Lo que recuerda el generador de cada sensor entre un ciclo y el siguiente."""

    temperatura: float
    humedad: float
    bateria: float
    latitud: float
    longitud: float
    rumbo: float
    anomalia_restante: int = 0
    objetivo: float = 0.0


class GeneradorDeLecturas:
    """Produce lecturas verosimiles. Con una semilla, la secuencia se puede repetir.

    La temperatura vuelve hacia el centro del rango del umbral con algo de ruido,
    y de vez en cuando se inyecta una anomalia: durante `duracion_anomalia` ciclos
    el valor queda fuera del rango (D34).
    """

    def __init__(
        self,
        sensores: list[SensorSimulado],
        rangos: dict[str, tuple[float, float]],
        semilla: int | None = None,
        probabilidad_anomalia: float = 0.02,
        duracion_anomalia: int = 3,
    ) -> None:
        if not 0.0 <= probabilidad_anomalia <= 1.0:
            raise ValidacionError("La probabilidad de anomalia tiene que estar entre 0 y 1")
        if duracion_anomalia < 1:
            raise ValidacionError("La duracion de la anomalia tiene que ser de al menos 1 ciclo")
        self._azar = random.Random(semilla)
        self._rangos = rangos
        self._probabilidad = probabilidad_anomalia
        self._duracion = duracion_anomalia
        self._estados = {s.sensor_id: self._estado_inicial(s) for s in sensores}

    def _rango(self, sensor: SensorSimulado) -> tuple[float, float]:
        return self._rangos.get(sensor.tipo_contenedor, RANGO_POR_DEFECTO)

    def _estado_inicial(self, sensor: SensorSimulado) -> _Estado:
        minimo, maximo = self._rango(sensor)
        return _Estado(
            temperatura=(minimo + maximo) / 2,
            humedad=60.0,
            bateria=100.0 - self._azar.uniform(0.0, 20.0),
            latitud=LATITUD_INICIAL + self._azar.uniform(-0.01, 0.01),
            longitud=LONGITUD_INICIAL + self._azar.uniform(-0.01, 0.01),
            rumbo=self._azar.uniform(0.0, 2 * math.pi),
        )

    def siguiente(self, sensor: SensorSimulado, momento: datetime) -> Lectura:
        estado = self._estados[sensor.sensor_id]
        self._avanzar_temperatura(sensor, estado)
        estado.humedad = min(max(estado.humedad + self._azar.gauss(0.0, 1.0), 30.0), 90.0)
        estado.bateria = max(0.0, estado.bateria - self._azar.uniform(0.0, 0.05))
        estado.rumbo += self._azar.gauss(0.0, 0.1)
        estado.latitud += PASO_GPS * math.cos(estado.rumbo)
        estado.longitud += PASO_GPS * math.sin(estado.rumbo)
        return Lectura(
            sensor_id=sensor.sensor_id,
            contenedor_id=sensor.contenedor_id,
            momento=momento,
            temperatura=round(estado.temperatura, 2),
            humedad=round(estado.humedad, 1),
            vibracion=round(abs(self._azar.gauss(0.2, 0.05)), 3),
            latitud=round(estado.latitud, 6),
            longitud=round(estado.longitud, 6),
            bateria=int(estado.bateria),
            envio_id=sensor.envio_id,
        )

    def _avanzar_temperatura(self, sensor: SensorSimulado, estado: _Estado) -> None:
        minimo, maximo = self._rango(sensor)
        centro, mitad = (minimo + maximo) / 2, (maximo - minimo) / 2

        if estado.anomalia_restante == 0 and self._azar.random() < self._probabilidad:
            estado.anomalia_restante = self._duracion
            desvio = mitad * self._azar.uniform(0.5, 1.5)
            # Es mas probable pasarse por arriba (corte de frio) que por abajo.
            estado.objetivo = maximo + desvio if self._azar.random() < 0.7 else minimo - desvio

        if estado.anomalia_restante > 0:
            estado.anomalia_restante -= 1
            estado.temperatura = estado.objetivo + self._azar.gauss(0.0, mitad * 0.05)
            return

        # Funcionamiento normal: vuelve hacia el centro, con ruido, sin salirse del
        # rango (queda un margen del 5 % para que el redondeo no cruce el limite).
        ruido = self._azar.gauss(0.0, mitad / 6)
        temperatura = estado.temperatura + 0.3 * (centro - estado.temperatura) + ruido
        margen = mitad * 0.05
        estado.temperatura = min(max(temperatura, minimo + margen), maximo - margen)


@dataclass
class Resumen:
    ciclos: int = 0
    lecturas: int = 0
    alertas: int = 0
    errores: int = 0


class SimuladorIoT:
    def __init__(
        self,
        lecturas: LecturaRepository,
        deteccion: DeteccionAnomaliasService,
        generador: GeneradorDeLecturas,
        sensores: list[SensorSimulado],
        reloj: Callable[[], datetime] | None = None,
        dormir: Callable[[float], None] = time.sleep,
        heartbeat: HeartbeatRepository | None = None,
    ) -> None:
        if not sensores:
            raise ValidacionError("No hay sensores para simular")
        self._lecturas = lecturas
        self._deteccion = deteccion
        self._generador = generador
        self._sensores = sensores
        self._heartbeat = heartbeat
        # Se inyectan el reloj y la espera para poder probar sin esperar de verdad.
        self._reloj = reloj or (lambda: datetime.now(timezone.utc))
        self._dormir = dormir

    def un_ciclo(self) -> tuple[int, int]:
        """Una lectura por sensor: se guardan juntas y despues se evalua cada una.

        Se guarda ANTES de evaluar, asi la alerta nunca apunta a una lectura que no
        quedo persistida. Devuelve (lecturas generadas, alertas creadas).
        """
        momento = self._reloj()
        # Cassandra guarda milisegundos: se recorta aca para que lo guardado
        # coincida exactamente con lo que se evalua.
        momento = momento.replace(microsecond=momento.microsecond // 1000 * 1000)
        lecturas = [self._generador.siguiente(s, momento) for s in self._sensores]
        self._lecturas.guardar_lote(lecturas)
        if self._heartbeat is not None:
            for lectura in lecturas:
                try:
                    self._heartbeat.registrar(
                        lectura.sensor_id,
                        lectura.momento.timestamp(),
                    )
                except ErrorDePersistencia as error:
                    log.error("No se pudo registrar el heartbeat: %s", error)
        alertas = sum(len(self._deteccion.evaluar(lectura)) for lectura in lecturas)
        return len(lecturas), alertas

    def ejecutar(self, ciclos: int = 0, intervalo: float = 1.0) -> Resumen:
        """Corre `ciclos` ciclos (0 = hasta Ctrl+C), esperando `intervalo` segundos."""
        resumen = Resumen()
        errores_seguidos = 0
        try:
            while ciclos == 0 or resumen.ciclos < ciclos:
                try:
                    lecturas, alertas = self.un_ciclo()
                except ErrorDePersistencia as error:
                    resumen.errores += 1
                    errores_seguidos += 1
                    log.error(
                        "Fallo el ciclo %d (%d seguidos): %s",
                        resumen.ciclos + 1,
                        errores_seguidos,
                        error,
                    )
                    if errores_seguidos >= MAX_ERRORES_SEGUIDOS:
                        raise
                else:
                    errores_seguidos = 0
                    resumen.lecturas += lecturas
                    resumen.alertas += alertas
                resumen.ciclos += 1
                if resumen.ciclos % CICLOS_ENTRE_AVISOS == 0:
                    log.info(
                        "%d ciclos: %d lecturas, %d alertas",
                        resumen.ciclos,
                        resumen.lecturas,
                        resumen.alertas,
                    )
                if ciclos == 0 or resumen.ciclos < ciclos:
                    self._dormir(intervalo)
        except KeyboardInterrupt:
            log.info("Simulador detenido por el usuario")
        return resumen


# -- Origen de los sensores ------------------------------------------------------

# Consulta directa a PostgreSQL: todavia no existe un SensorRepository. Si los
# nombres de tabla o columna no coinciden con el esquema, se ajusta aca o se usa
# --sensores-json. Cuando exista el repositorio, se reemplaza (D34).
# El envio sale de un LEFT JOIN: un contenedor DISPONIBLE o EN_MANTENIMIENTO no
# esta en ningun envio y su lectura guarda envio_id NULL. Cuando esta en varios
# (historico), vale el ultimo asignado que todavia no termino: ENTREGADO y
# CANCELADO son finales (EstadoEnvio.es_final), asi que no son "el envio actual".
SQL_SENSORES = """select s.id, s.contenedor_id, c.tipo, activo.envio_id
                  from sensor s
                  join contenedor c on c.id = s.contenedor_id
                  left join (
                      select distinct on (ec.contenedor_id)
                             ec.contenedor_id, ec.envio_id
                      from envio_contenedor ec
                      join envio e on e.id = ec.envio_id
                      where e.estado not in ('ENTREGADO', 'CANCELADO')
                      order by ec.contenedor_id, ec.fecha_asignacion desc
                  ) activo on activo.contenedor_id = s.contenedor_id
                  order by s.id"""


def cargar_sensores_desde_postgres(settings: Settings) -> list[SensorSimulado]:
    # Import perezoso: los tests del simulador no necesitan psycopg ni una base.
    from logistica.infrastructure.postgres.conexion import conectar, traducir_errores

    @traducir_errores
    def consultar() -> list[Any]:
        with conectar(settings) as conexion:
            return conexion.execute(SQL_SENSORES).fetchall()

    sensores = [
        SensorSimulado(
            sensor_id=fila[0],
            contenedor_id=fila[1],
            tipo_contenedor=fila[2],
            envio_id=fila[3],
        )
        for fila in consultar()
    ]
    if not sensores:
        raise ValidacionError("PostgreSQL no devolvio ningun sensor con contenedor")
    return sensores


def cargar_sensores_desde_json(ruta: str | Path) -> list[SensorSimulado]:
    """Lista de sensores desde un archivo JSON:

    [{"sensor_id": "...", "contenedor_id": "...", "tipo_contenedor": "REEFER_40",
      "envio_id": "..."}]    (envio_id es opcional)
    """
    try:
        datos = json.loads(Path(ruta).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValidacionError(f"No se pudo leer {ruta}: {error}") from error
    try:
        sensores = [
            SensorSimulado(
                sensor_id=UUID(d["sensor_id"]),
                contenedor_id=UUID(d["contenedor_id"]),
                tipo_contenedor=d["tipo_contenedor"],
                envio_id=UUID(d["envio_id"]) if d.get("envio_id") else None,
            )
            for d in datos
        ]
    except (KeyError, ValueError, TypeError) as error:
        raise ValidacionError(f"Sensor mal formado en {ruta}: {error!r}") from error
    if not sensores:
        raise ValidacionError(f"{ruta} no tiene sensores")
    return sensores


# -- Linea de comandos -----------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Simulador de sensores IoT")
    parser.add_argument("--ciclos", type=int, default=0, help="0 = hasta Ctrl+C")
    parser.add_argument("--intervalo", type=float, default=1.0, help="segundos entre ciclos")
    parser.add_argument("--semilla", type=int, default=None, help="para repetir la secuencia")
    parser.add_argument("--probabilidad-anomalia", type=float, default=0.02)
    parser.add_argument("--duracion-anomalia", type=int, default=3)
    parser.add_argument("--sensores-json", default=None, help="en vez de leerlos de PostgreSQL")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    # Imports perezosos: arman las conexiones solo cuando se ejecuta de verdad.
    from logistica.container import Contenedor
    from logistica.domain.umbral import MagnitudUmbral

    contenedor = Contenedor()
    try:
        sensores = (
            cargar_sensores_desde_json(args.sensores_json)
            if args.sensores_json
            else cargar_sensores_desde_postgres(contenedor.settings)
        )
        # El rango que se simula sale del umbral configurado de cada tipo.
        rangos: dict[str, tuple[float, float]] = {}
        for tipo in {s.tipo_contenedor for s in sensores}:
            umbral = contenedor.umbrales.obtener(tipo, MagnitudUmbral.TEMPERATURA)
            if umbral is None:
                log.warning(
                    "Sin umbral de temperatura para %s: se simula %s", tipo, RANGO_POR_DEFECTO
                )
            else:
                rangos[tipo] = (umbral.minimo, umbral.maximo)

        tipos = {s.contenedor_id: s.tipo_contenedor for s in sensores}
        deteccion = DeteccionAnomaliasService(
            contenedor.umbrales, contenedor.alertas, tipo_de_contenedor=tipos.get
        )
        generador = GeneradorDeLecturas(
            sensores,
            rangos,
            semilla=args.semilla,
            probabilidad_anomalia=args.probabilidad_anomalia,
            duracion_anomalia=args.duracion_anomalia,
        )
        simulador = SimuladorIoT(
            contenedor.lecturas,
            deteccion,
            generador,
            sensores,
            heartbeat=contenedor.heartbeat,
        )
        log.info("Simulando %d sensores (Ctrl+C para detener)", len(sensores))
        resumen = simulador.ejecutar(ciclos=args.ciclos, intervalo=args.intervalo)
    except LogisticaError as error:
        log.error("%s", error)
        return 1
    log.info(
        "Listo: %d ciclos, %d lecturas, %d alertas, %d ciclos con error",
        resumen.ciclos,
        resumen.lecturas,
        resumen.alertas,
        resumen.errores,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
