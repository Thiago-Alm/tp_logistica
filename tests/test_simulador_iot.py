"""Tests del simulador IoT con repositorios en memoria. No necesitan bases."""
import json
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest

from logistica.domain.alerta import Alerta
from logistica.domain.lectura import Lectura, Posicion
from logistica.domain.umbral import MagnitudUmbral, Umbral
from logistica.exceptions import ErrorDePersistencia, ValidacionError
from logistica.jobs.simulador_iot import (
    MAX_ERRORES_SEGUIDOS,
    GeneradorDeLecturas,
    SensorSimulado,
    SimuladorIoT,
    cargar_sensores_desde_json,
)
from logistica.repositories.alerta_repository import AlertaRepository
from logistica.repositories.lectura_repository import LecturaRepository
from logistica.repositories.umbral_repository import UmbralRepository
from logistica.services.deteccion_anomalias_service import DeteccionAnomaliasService

INICIO = datetime(2026, 10, 20, 12, 0, 0, 123456, tzinfo=timezone.utc)
RANGO = (-25.0, -15.0)


class LecturasEnMemoria(LecturaRepository):
    def __init__(self, fallos: set[int] | None = None, siempre_falla: bool = False) -> None:
        self.guardadas: list[Lectura] = []
        self.llamadas = 0
        self._fallos = fallos or set()
        self._siempre_falla = siempre_falla

    def guardar_lote(self, lecturas: list[Lectura]) -> None:
        self.llamadas += 1
        if self._siempre_falla or self.llamadas in self._fallos:
            raise ErrorDePersistencia("Cassandra no responde")
        self.guardadas.extend(lecturas)

    def guardar(self, lectura: Lectura) -> None:
        self.guardar_lote([lectura])

    def listar_por_sensor(self, sensor_id, desde, hasta) -> list[Lectura]:
        return []

    def posiciones_de_contenedor(self, contenedor_id, desde, hasta) -> list[Posicion]:
        return []

    def ultimas(self, sensor_id, cantidad) -> list[Lectura]:
        return []


class UmbralesEnMemoria(UmbralRepository):
    def __init__(self, umbral: Umbral) -> None:
        self._umbral = umbral

    def guardar(self, umbral: Umbral) -> None:
        self._umbral = umbral

    def obtener(self, tipo_contenedor, magnitud) -> Umbral | None:
        return self._umbral if tipo_contenedor == self._umbral.tipo_contenedor else None

    def listar(self) -> list[Umbral]:
        return [self._umbral]


class AlertasEnMemoria(AlertaRepository):
    def __init__(self) -> None:
        self.guardadas: dict[UUID, Alerta] = {}

    def guardar(self, alerta: Alerta) -> bool:
        if alerta.id in self.guardadas:
            return False
        self.guardadas[alerta.id] = alerta
        return True

    def obtener(self, id) -> Alerta | None:
        return self.guardadas.get(id)

    def listar_abiertas(self) -> list[Alerta]:
        return list(self.guardadas.values())

    def listar_por_sensor(self, sensor_id, limite=50) -> list[Alerta]:
        return [a for a in self.guardadas.values() if a.sensor_id == sensor_id]


class Reloj:
    """Cada llamada avanza un segundo."""

    def __init__(self) -> None:
        self._actual = INICIO - timedelta(seconds=1)

    def __call__(self) -> datetime:
        self._actual += timedelta(seconds=1)
        return self._actual


def _temperaturas(lecturas: LecturasEnMemoria) -> list[float]:
    return [lectura.temperatura for lectura in lecturas.guardadas]


def _sensores(cantidad: int = 2) -> list[SensorSimulado]:
    return [SensorSimulado(uuid4(), uuid4(), "REEFER_40") for _ in range(cantidad)]


def _armar(sensores=None, probabilidad=0.0, duracion=3, semilla=7, lecturas=None):
    sensores = _sensores() if sensores is None else sensores
    umbral = Umbral(
        id=uuid4(), tipo_contenedor="REEFER_40", magnitud=MagnitudUmbral.TEMPERATURA,
        minimo=RANGO[0], maximo=RANGO[1], unidad="C",
    )
    lecturas = lecturas if lecturas is not None else LecturasEnMemoria()
    alertas = AlertasEnMemoria()
    tipos = {s.contenedor_id: s.tipo_contenedor for s in sensores}
    deteccion = DeteccionAnomaliasService(UmbralesEnMemoria(umbral), alertas, tipos.get)
    generador = GeneradorDeLecturas(
        sensores, {"REEFER_40": RANGO}, semilla=semilla,
        probabilidad_anomalia=probabilidad, duracion_anomalia=duracion,
    )
    simulador = SimuladorIoT(
        lecturas, deteccion, generador, sensores, reloj=Reloj(), dormir=lambda segundos: None
    )
    return simulador, lecturas, alertas


def test_genera_una_lectura_por_sensor_y_por_ciclo():
    simulador, lecturas, _ = _armar(_sensores(3))
    resumen = simulador.ejecutar(ciclos=4)
    assert resumen.ciclos == 4
    assert resumen.lecturas == 12
    assert len(lecturas.guardadas) == 12


def test_los_momentos_estan_en_utc_con_milisegundos_y_avanzan():
    simulador, lecturas, _ = _armar(_sensores(1))
    simulador.ejecutar(ciclos=3)
    momentos = [lectura.momento for lectura in lecturas.guardadas]
    assert all(m.tzinfo is not None and m.utcoffset() == timedelta(0) for m in momentos)
    assert all(m.microsecond % 1000 == 0 for m in momentos)  # lo que Cassandra guarda
    assert momentos == sorted(momentos)
    assert len(set(momentos)) == 3


def test_sin_anomalias_todas_las_lecturas_quedan_dentro_del_rango_y_no_hay_alertas():
    simulador, lecturas, alertas = _armar(probabilidad=0.0)
    resumen = simulador.ejecutar(ciclos=200)
    assert resumen.alertas == 0
    assert alertas.guardadas == {}
    assert all(RANGO[0] <= lectura.temperatura <= RANGO[1] for lectura in lecturas.guardadas)


def test_con_anomalias_se_crean_alertas_y_su_valor_esta_fuera_del_rango():
    simulador, _, alertas = _armar(probabilidad=1.0, duracion=2)
    resumen = simulador.ejecutar(ciclos=5)
    assert resumen.alertas > 0
    assert resumen.alertas == len(alertas.guardadas)
    for alerta in alertas.guardadas.values():
        assert not RANGO[0] <= alerta.detalle.valor <= RANGO[1]
        assert alerta.detalle.umbral in RANGO


def test_la_misma_semilla_repite_la_misma_secuencia():
    sensores = _sensores(2)
    a, lecturas_a, _ = _armar(sensores, probabilidad=0.3, semilla=42)
    b, lecturas_b, _ = _armar(sensores, probabilidad=0.3, semilla=42)
    a.ejecutar(ciclos=30)
    b.ejecutar(ciclos=30)
    assert _temperaturas(lecturas_a) == _temperaturas(lecturas_b)


def test_otra_semilla_da_otra_secuencia():
    sensores = _sensores(1)
    a, lecturas_a, _ = _armar(sensores, probabilidad=0.3, semilla=1)
    b, lecturas_b, _ = _armar(sensores, probabilidad=0.3, semilla=2)
    a.ejecutar(ciclos=30)
    b.ejecutar(ciclos=30)
    assert _temperaturas(lecturas_a) != _temperaturas(lecturas_b)


def test_la_posicion_se_mueve_y_la_bateria_no_sube():
    simulador, lecturas, _ = _armar(_sensores(1))
    simulador.ejecutar(ciclos=20)
    primera, ultima = lecturas.guardadas[0], lecturas.guardadas[-1]
    assert (primera.latitud, primera.longitud) != (ultima.latitud, ultima.longitud)
    baterias = [lectura.bateria for lectura in lecturas.guardadas]
    assert baterias == sorted(baterias, reverse=True)


def test_el_envio_del_sensor_viaja_en_la_lectura():
    envio_id = uuid4()
    sensores = [SensorSimulado(uuid4(), uuid4(), "REEFER_40", envio_id=envio_id)]
    simulador, lecturas, _ = _armar(sensores)
    simulador.ejecutar(ciclos=1)
    assert lecturas.guardadas[0].envio_id == envio_id


def test_un_ciclo_que_falla_se_registra_y_la_simulacion_sigue():
    simulador, lecturas, _ = _armar(lecturas=LecturasEnMemoria(fallos={2}))
    resumen = simulador.ejecutar(ciclos=4)
    assert resumen.errores == 1
    assert resumen.ciclos == 4
    assert len(lecturas.guardadas) == 3 * 2  # tres ciclos buenos, dos sensores


def test_si_fallan_muchos_ciclos_seguidos_se_aborta():
    simulador, lecturas, _ = _armar(lecturas=LecturasEnMemoria(siempre_falla=True))
    with pytest.raises(ErrorDePersistencia):
        simulador.ejecutar(ciclos=50)
    assert lecturas.llamadas == MAX_ERRORES_SEGUIDOS


def test_los_errores_no_seguidos_no_abortan():
    fallos = {1, 3, 5, 7}  # alternados: nunca hay dos seguidos
    simulador, _, _ = _armar(lecturas=LecturasEnMemoria(fallos=fallos))
    resumen = simulador.ejecutar(ciclos=8)
    assert resumen.errores == 4


def test_se_guarda_antes_de_evaluar():
    """Si la alerta apuntara a una lectura no guardada, quedaria colgada."""
    fallida = LecturasEnMemoria(siempre_falla=True)
    simulador, lecturas, alertas = _armar(probabilidad=1.0, lecturas=fallida)
    with pytest.raises(ErrorDePersistencia):
        simulador.ejecutar(ciclos=10)
    assert alertas.guardadas == {}


def test_no_se_puede_simular_sin_sensores():
    with pytest.raises(ValidacionError):
        _armar(sensores=[])[0]


@pytest.mark.parametrize("probabilidad", [-0.1, 1.5])
def test_la_probabilidad_de_anomalia_debe_estar_entre_0_y_1(probabilidad):
    with pytest.raises(ValidacionError):
        GeneradorDeLecturas(_sensores(1), {}, probabilidad_anomalia=probabilidad)


def test_un_tipo_sin_rango_usa_el_rango_por_defecto():
    sensor = SensorSimulado(uuid4(), uuid4(), "TIPO_NUEVO")
    generador = GeneradorDeLecturas([sensor], {}, semilla=1, probabilidad_anomalia=0.0)
    lectura = generador.siguiente(sensor, INICIO)
    assert 0.0 <= lectura.temperatura <= 40.0


# -- carga de sensores desde un archivo ---------------------------------------


def test_cargar_sensores_desde_json(tmp_path):
    sensor_id, contenedor_id, envio_id = uuid4(), uuid4(), uuid4()
    archivo = tmp_path / "sensores.json"
    archivo.write_text(
        json.dumps(
            [
                {"sensor_id": str(sensor_id), "contenedor_id": str(contenedor_id),
                 "tipo_contenedor": "REEFER_40", "envio_id": str(envio_id)},
                {"sensor_id": str(uuid4()), "contenedor_id": str(uuid4()),
                 "tipo_contenedor": "DRY_20"},
            ]
        ),
        encoding="utf-8",
    )
    sensores = cargar_sensores_desde_json(archivo)
    assert len(sensores) == 2
    assert sensores[0] == SensorSimulado(sensor_id, contenedor_id, "REEFER_40", envio_id)
    assert sensores[1].envio_id is None


@pytest.mark.parametrize(
    "contenido",
    ["no es json", "[]", '[{"sensor_id": "no-es-un-uuid"}]', '[{"sensor_id": "x"}]'],
)
def test_un_archivo_de_sensores_invalido_lanza_validacion_error(tmp_path, contenido):
    archivo = tmp_path / "sensores.json"
    archivo.write_text(contenido, encoding="utf-8")
    with pytest.raises(ValidacionError):
        cargar_sensores_desde_json(archivo)


def test_un_archivo_inexistente_lanza_validacion_error(tmp_path):
    with pytest.raises(ValidacionError):
        cargar_sensores_desde_json(tmp_path / "no_existe.json")
