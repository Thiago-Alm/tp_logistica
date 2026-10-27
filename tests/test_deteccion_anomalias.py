"""Tests de la deteccion de anomalias con repositorios en memoria. No necesitan bases."""
import logging
from datetime import datetime, timezone
from uuid import UUID, uuid4

from logistica.domain.alerta import Alerta, EstadoAlerta
from logistica.domain.lectura import Lectura
from logistica.domain.umbral import MagnitudUmbral, Umbral
from logistica.repositories.alerta_repository import AlertaRepository
from logistica.repositories.umbral_repository import UmbralRepository
from logistica.services.deteccion_anomalias_service import DeteccionAnomaliasService

MOMENTO = datetime(2026, 10, 20, 12, 0, 0, tzinfo=timezone.utc)


class UmbralesEnMemoria(UmbralRepository):
    def __init__(self, *umbrales: Umbral) -> None:
        self._por_clave = {(u.tipo_contenedor, u.magnitud): u for u in umbrales}
        self.consultas = 0

    def guardar(self, umbral: Umbral) -> None:
        self._por_clave[(umbral.tipo_contenedor, umbral.magnitud)] = umbral

    def obtener(self, tipo_contenedor: str, magnitud: MagnitudUmbral) -> Umbral | None:
        self.consultas += 1
        return self._por_clave.get((tipo_contenedor, magnitud))

    def listar(self) -> list[Umbral]:
        return list(self._por_clave.values())


class AlertasEnMemoria(AlertaRepository):
    def __init__(self) -> None:
        self.guardadas: dict[UUID, Alerta] = {}

    def guardar(self, alerta: Alerta) -> bool:
        if alerta.id in self.guardadas:
            return False
        self.guardadas[alerta.id] = alerta
        return True

    def obtener(self, id: UUID) -> Alerta | None:
        return self.guardadas.get(id)

    def listar_abiertas(self) -> list[Alerta]:
        return [a for a in self.guardadas.values() if a.esta_abierta()]

    def listar_por_sensor(self, sensor_id: UUID, limite: int = 50) -> list[Alerta]:
        return [a for a in self.guardadas.values() if a.sensor_id == sensor_id][:limite]


def _umbral() -> Umbral:
    return Umbral(
        id=uuid4(),
        tipo_contenedor="REEFER_40",
        magnitud=MagnitudUmbral.TEMPERATURA,
        minimo=-25.0,
        maximo=-15.0,
        unidad="C",
    )


def _lectura(contenedor_id: UUID, temperatura: float, momento=MOMENTO) -> Lectura:
    return Lectura(
        sensor_id=uuid4(),
        contenedor_id=contenedor_id,
        momento=momento,
        temperatura=temperatura,
        humedad=60.0,
        vibracion=0.2,
        latitud=-34.6,
        longitud=-58.4,
        bateria=90,
    )


def _servicio(umbrales: UmbralRepository, tipos: dict[UUID, str]):
    alertas = AlertasEnMemoria()
    return DeteccionAnomaliasService(umbrales, alertas, tipos.get), alertas


def test_una_lectura_dentro_del_rango_no_genera_alertas():
    contenedor_id = uuid4()
    servicio, alertas = _servicio(UmbralesEnMemoria(_umbral()), {contenedor_id: "REEFER_40"})
    assert servicio.evaluar(_lectura(contenedor_id, -20.0)) == []
    assert alertas.guardadas == {}


def test_una_lectura_fuera_del_rango_crea_la_alerta():
    contenedor_id = uuid4()
    servicio, alertas = _servicio(UmbralesEnMemoria(_umbral()), {contenedor_id: "REEFER_40"})
    lectura = _lectura(contenedor_id, -10.0)

    creadas = servicio.evaluar(lectura)

    assert len(creadas) == 1
    assert alertas.guardadas[creadas[0].id] is creadas[0]
    assert creadas[0].estado is EstadoAlerta.ABIERTA
    assert creadas[0].sensor_id == lectura.sensor_id


def test_evaluar_la_misma_lectura_dos_veces_no_duplica_la_alerta():
    contenedor_id = uuid4()
    servicio, alertas = _servicio(UmbralesEnMemoria(_umbral()), {contenedor_id: "REEFER_40"})
    lectura = _lectura(contenedor_id, -10.0)

    primera = servicio.evaluar(lectura)
    segunda = servicio.evaluar(lectura)

    assert len(primera) == 1
    assert segunda == []
    assert len(alertas.guardadas) == 1


def test_el_umbral_depende_del_tipo_de_contenedor():
    """Los -10 C son anomalia para un REEFER_40 pero normales para un DRY_20."""
    reefer, seco = uuid4(), uuid4()
    seco_umbral = Umbral(
        id=uuid4(), tipo_contenedor="DRY_20", magnitud=MagnitudUmbral.TEMPERATURA,
        minimo=-20.0, maximo=40.0, unidad="C",
    )
    servicio, _ = _servicio(
        UmbralesEnMemoria(_umbral(), seco_umbral), {reefer: "REEFER_40", seco: "DRY_20"}
    )
    assert len(servicio.evaluar(_lectura(reefer, -10.0))) == 1
    assert servicio.evaluar(_lectura(seco, -10.0)) == []


def test_sin_umbral_configurado_no_hay_alerta_y_se_avisa_una_sola_vez(caplog):
    contenedor_id = uuid4()
    servicio, alertas = _servicio(UmbralesEnMemoria(), {contenedor_id: "REEFER_40"})

    with caplog.at_level(logging.WARNING):
        for _ in range(3):
            assert servicio.evaluar(_lectura(contenedor_id, 99.0)) == []

    assert alertas.guardadas == {}
    avisos = [r for r in caplog.records if "No hay umbral" in r.getMessage()]
    assert len(avisos) == 1


def test_un_contenedor_de_tipo_desconocido_no_se_evalua_y_se_avisa_una_sola_vez(caplog):
    servicio, alertas = _servicio(UmbralesEnMemoria(_umbral()), {})
    contenedor_id = uuid4()

    with caplog.at_level(logging.WARNING):
        servicio.evaluar(_lectura(contenedor_id, -10.0))
        servicio.evaluar(_lectura(contenedor_id, -10.0))

    assert alertas.guardadas == {}
    assert len([r for r in caplog.records if "No se conoce el tipo" in r.getMessage()]) == 1
