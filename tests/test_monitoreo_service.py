"""MonitoreoService: lecturas, umbrales, alertas y el control de cobertura.

Sin bases externas: los tres repositorios y la UnidadDeTrabajo son dobles.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from logistica.domain.alerta import Alerta, EstadoAlerta, SeveridadAlerta, TipoAlerta
from logistica.domain.sensor import EstadoSensor, Sensor, TipoSensor
from logistica.domain.umbral import MagnitudUmbral, Umbral
from logistica.exceptions import NoEncontrado, ValidacionError
from logistica.services.monitoreo_service import MonitoreoService

AHORA = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)


def nuevo_sensor(**cambios) -> Sensor:
    datos = dict(
        id=uuid4(),
        numero_serie="SN-IOT-2026-001",
        modelo="TempTrack 3000",
        tipo=TipoSensor.TEMPERATURA,
        intervalo_reporte_segundos=60,
        fecha_instalacion=AHORA,
        contenedor_id=uuid4(),
    )
    datos.update(cambios)
    return Sensor(**datos)


def nueva_alerta(**cambios) -> Alerta:
    datos = dict(
        id=uuid4(),
        tipo=TipoAlerta.TEMPERATURA,
        sensor_id=uuid4(),
        severidad=SeveridadAlerta.ALTA,
        fecha=AHORA,
    )
    datos.update(cambios)
    return Alerta(**datos)


def armar(sensor=None):
    uow = MagicMock()
    uow.__enter__.return_value = uow
    uow.sensores.obtener.return_value = sensor if sensor is not None else nuevo_sensor()
    uow.contenedores.obtener.return_value = MagicMock()
    lecturas, umbrales, alertas = MagicMock(), MagicMock(), MagicMock()
    servicio = MonitoreoService(lecturas, umbrales, alertas, uow)
    return servicio, lecturas, umbrales, alertas, uow


# --- Entidad Sensor ----------------------------------------------------------


def test_el_intervalo_de_reporte_debe_ser_positivo():
    for intervalo in (0, -30):
        with pytest.raises(ValidacionError):
            nuevo_sensor(intervalo_reporte_segundos=intervalo)


def test_un_sensor_sin_contenedor_no_esta_instalado():
    assert not nuevo_sensor(contenedor_id=None).esta_instalado()


def test_solo_los_activos_se_esperan_reportando():
    """D43: la deteccion de inactividad solo mira los ACTIVO."""
    assert nuevo_sensor().esta_monitoreado()
    for estado in (EstadoSensor.INACTIVO, EstadoSensor.EN_MANTENIMIENTO, EstadoSensor.BAJA):
        assert not nuevo_sensor(estado=estado).esta_monitoreado()


def test_todos_los_valores_van_en_mayusculas():
    """D19."""
    for enum in (TipoSensor, EstadoSensor):
        for valor in enum:
            assert valor.value == valor.name == valor.value.upper()


# --- Lecturas ----------------------------------------------------------------


def test_el_historico_exige_zona_horaria():
    servicio, lecturas, _, _, _ = armar()
    with pytest.raises(ValidacionError):
        servicio.historico(uuid4(), AHORA.replace(tzinfo=None), AHORA)
    lecturas.listar_por_sensor.assert_not_called()


def test_el_historico_rechaza_un_rango_invertido():
    servicio, lecturas, _, _, _ = armar()
    with pytest.raises(ValidacionError):
        servicio.historico(uuid4(), AHORA, AHORA - timedelta(days=1))
    lecturas.listar_por_sensor.assert_not_called()


def test_el_historico_rechaza_mas_dias_que_el_contrato():
    """El tope lo fija el repositorio porque cada dia es una particion (D45)."""
    servicio, lecturas, _, _, _ = armar()
    with pytest.raises(ValidacionError) as error:
        servicio.historico(uuid4(), AHORA - timedelta(days=40), AHORA)
    assert "41 dias" in str(error.value)
    lecturas.listar_por_sensor.assert_not_called()


def test_el_historico_de_un_sensor_inexistente():
    servicio, lecturas, _, _, uow = armar()
    uow.sensores.obtener.return_value = None
    with pytest.raises(NoEncontrado):
        servicio.historico(uuid4(), AHORA - timedelta(days=1), AHORA)
    lecturas.listar_por_sensor.assert_not_called()


def test_las_ultimas_lecturas_exigen_una_cantidad_positiva():
    servicio, lecturas, _, _, _ = armar()
    for cantidad in (0, -5):
        with pytest.raises(ValidacionError):
            servicio.ultimas_lecturas(uuid4(), cantidad)
    lecturas.ultimas.assert_not_called()


def test_se_busca_un_sensor_por_numero_de_serie_o_uuid():
    sensor = nuevo_sensor()
    servicio, _, _, _, uow = armar(sensor)

    assert servicio.buscar_sensor(str(sensor.id)) is sensor
    uow.sensores.obtener_por_numero_serie.return_value = sensor
    assert servicio.buscar_sensor("sn-iot-2026-001") is sensor
    # El numero de serie se normaliza a mayusculas antes de consultar.
    uow.sensores.obtener_por_numero_serie.assert_called_with("SN-IOT-2026-001")


def test_buscar_un_sensor_que_no_existe():
    servicio, _, _, _, uow = armar()
    uow.sensores.obtener.return_value = None
    uow.sensores.obtener_por_numero_serie.return_value = None
    with pytest.raises(NoEncontrado):
        servicio.buscar_sensor("SN-NO-EXISTE")


# --- Umbrales y cobertura ----------------------------------------------------


def test_un_umbral_invertido_no_se_guarda():
    servicio, _, umbrales, _, _ = armar()
    with pytest.raises(ValidacionError):
        servicio.configurar_umbral(
            Umbral(
                id=uuid4(),
                tipo_contenedor="REEFER_40",
                magnitud=MagnitudUmbral.TEMPERATURA,
                minimo=10.0,
                maximo=-5.0,
                unidad="C",
            )
        )
    umbrales.guardar.assert_not_called()


def test_la_cobertura_detecta_un_tipo_sin_umbral():
    """El error que dio origen a este control: los umbrales cubrian 2 de 7
    tipos, la deteccion salteaba sensores y nadie se enteraba."""
    servicio, _, umbrales, _, uow = armar()
    umbrales.listar.return_value = [
        Umbral(
            id=uuid4(),
            tipo_contenedor="REEFER_40",
            magnitud=MagnitudUmbral.TEMPERATURA,
            minimo=-25.0,
            maximo=-15.0,
            unidad="C",
        )
    ]
    reefer, seco = uuid4(), uuid4()
    uow.contenedores.listar.return_value = [
        MagicMock(id=reefer, tipo="REEFER_40"),
        MagicMock(id=seco, tipo="DRY_40"),
    ]
    uow.sensores.listar.return_value = [
        nuevo_sensor(contenedor_id=reefer),
        nuevo_sensor(contenedor_id=seco),
    ]

    cobertura = {c.tipo_contenedor: c for c in servicio.cobertura_de_umbrales()}
    assert cobertura["REEFER_40"].esta_cubierto
    assert not cobertura["DRY_40"].esta_cubierto
    assert cobertura["DRY_40"].magnitudes_faltantes == ("TEMPERATURA",)


def test_la_cobertura_solo_mira_las_magnitudes_que_la_deteccion_evalua():
    """Marcar HUMEDAD como faltante seria ruido: nadie consulta ese umbral."""
    servicio, _, umbrales, _, uow = armar()
    contenedor = uuid4()
    umbrales.listar.return_value = [
        Umbral(
            id=uuid4(),
            tipo_contenedor="REEFER_40",
            magnitud=MagnitudUmbral.TEMPERATURA,
            minimo=-25.0,
            maximo=-15.0,
            unidad="C",
        )
    ]
    uow.contenedores.listar.return_value = [MagicMock(id=contenedor, tipo="REEFER_40")]
    uow.sensores.listar.return_value = [nuevo_sensor(contenedor_id=contenedor)]

    cobertura = servicio.cobertura_de_umbrales()[0]
    assert cobertura.magnitudes_faltantes == ()
    assert "HUMEDAD" not in cobertura.magnitudes_cubiertas


def test_la_cobertura_ignora_sensores_sin_contenedor():
    servicio, _, umbrales, _, uow = armar()
    umbrales.listar.return_value = []
    uow.contenedores.listar.return_value = []
    uow.sensores.listar.return_value = [nuevo_sensor(contenedor_id=None)]
    assert servicio.cobertura_de_umbrales() == []


# --- Alertas -----------------------------------------------------------------


def test_reconocer_una_alerta_la_actualiza_y_no_la_vuelve_a_insertar():
    """`guardar` es un insert-if-not-exists: si se usara, el cambio de estado
    no se guardaria y la alerta quedaria igual."""
    alerta = nueva_alerta()
    servicio, _, _, alertas, _ = armar()
    alertas.obtener.return_value = alerta

    actualizada = servicio.cambiar_estado_alerta(alerta.id, EstadoAlerta.RECONOCIDA)

    assert actualizada.estado is EstadoAlerta.RECONOCIDA
    alertas.actualizar.assert_called_once_with(alerta)
    alertas.guardar.assert_not_called()


def test_una_alerta_cerrada_es_final():
    alerta = nueva_alerta(estado=EstadoAlerta.CERRADA)
    servicio, _, _, alertas, _ = armar()
    alertas.obtener.return_value = alerta
    with pytest.raises(ValidacionError):
        servicio.cambiar_estado_alerta(alerta.id, EstadoAlerta.ABIERTA)
    alertas.actualizar.assert_not_called()


def test_no_se_cambia_una_alerta_al_estado_que_ya_tiene():
    alerta = nueva_alerta(estado=EstadoAlerta.RECONOCIDA)
    servicio, _, _, alertas, _ = armar()
    alertas.obtener.return_value = alerta
    with pytest.raises(ValidacionError):
        servicio.cambiar_estado_alerta(alerta.id, EstadoAlerta.RECONOCIDA)
    alertas.actualizar.assert_not_called()


def test_cambiar_el_estado_de_una_alerta_inexistente():
    servicio, _, _, alertas, _ = armar()
    alertas.obtener.return_value = None
    with pytest.raises(NoEncontrado):
        servicio.cambiar_estado_alerta(uuid4(), EstadoAlerta.CERRADA)


def test_las_alertas_de_un_sensor_exigen_un_limite_positivo():
    servicio, _, _, alertas, _ = armar()
    with pytest.raises(ValidacionError):
        servicio.listar_alertas_de_sensor(uuid4(), limite=0)
    alertas.listar_por_sensor.assert_not_called()


# --- Detecciones a pedido ----------------------------------------------------


def test_el_control_de_sensores_resuelve_el_numero_de_serie():
    """La deteccion devuelve solo el UUID: el numero de serie sale de
    PostgreSQL y es lo unico que le sirve a quien mira la pantalla."""
    from logistica.services.deteccion_inactividad_service import ResultadoInactividad

    sensor = nuevo_sensor()
    uow = MagicMock()
    uow.__enter__.return_value = uow
    uow.sensores.listar.return_value = [sensor]
    inactividad = MagicMock()
    inactividad.verificar.return_value = [
        ResultadoInactividad(sensor.id, "INACTIVO", 300.0),
        ResultadoInactividad(uuid4(), "SIN_DATOS", None),
    ]
    servicio = MonitoreoService(
        MagicMock(), MagicMock(), MagicMock(), uow, deteccion_inactividad=inactividad
    )

    estados = servicio.controlar_sensores()
    assert estados[0].numero_serie == sensor.numero_serie
    # El que no esta en PostgreSQL cae al UUID en vez de romper.
    assert estados[1].numero_serie == str(estados[1].sensor_id)
    assert all(e.es_problema for e in estados)


def test_un_sensor_que_reporta_a_tiempo_no_es_problema():
    from logistica.services.deteccion_inactividad_service import ResultadoInactividad

    sensor = nuevo_sensor()
    uow = MagicMock()
    uow.__enter__.return_value = uow
    uow.sensores.listar.return_value = [sensor]
    inactividad = MagicMock()
    inactividad.verificar.return_value = [
        ResultadoInactividad(sensor.id, "ACTIVO", 12.0)
    ]
    servicio = MonitoreoService(
        MagicMock(), MagicMock(), MagicMock(), uow, deteccion_inactividad=inactividad
    )
    assert not servicio.controlar_sensores()[0].es_problema


def test_la_deteccion_a_pedido_solo_evalua_sensores_instalados():
    """Un sensor sin contenedor no tiene tipo contra el que comparar."""
    instalado = nuevo_sensor()
    suelto = nuevo_sensor(contenedor_id=None)
    uow = MagicMock()
    uow.__enter__.return_value = uow
    uow.sensores.listar.return_value = [instalado, suelto]
    lecturas = MagicMock()
    lecturas.ultimas.return_value = [MagicMock()]
    anomalias = MagicMock()
    anomalias.evaluar.return_value = []

    servicio = MonitoreoService(
        lecturas, MagicMock(), MagicMock(), uow, deteccion_anomalias=anomalias
    )
    resumen = servicio.detectar_anomalias(lecturas_por_sensor=5)

    assert resumen.sensores_evaluados == 1
    lecturas.ultimas.assert_called_once_with(instalado.id, 5)


def test_la_deteccion_a_pedido_informa_las_alertas_nuevas():
    sensor = nuevo_sensor()
    alerta = nueva_alerta()
    uow = MagicMock()
    uow.__enter__.return_value = uow
    uow.sensores.listar.return_value = [sensor]
    lecturas = MagicMock()
    lecturas.ultimas.return_value = [MagicMock(), MagicMock()]
    anomalias = MagicMock()
    # La primera lectura genera alerta; la segunda ya la tenia (idempotencia).
    anomalias.evaluar.side_effect = [[alerta], []]

    servicio = MonitoreoService(
        lecturas, MagicMock(), MagicMock(), uow, deteccion_anomalias=anomalias
    )
    resumen = servicio.detectar_anomalias()

    assert resumen.lecturas_evaluadas == 2
    assert resumen.cantidad_nuevas == 1
    assert resumen.alertas_nuevas == (alerta,)


def test_las_detecciones_avisan_si_no_estan_disponibles():
    """Son opcionales porque el planificador las arma por su cuenta."""
    servicio = MonitoreoService(MagicMock(), MagicMock(), MagicMock(), MagicMock())
    with pytest.raises(ValidacionError):
        servicio.controlar_sensores()
    with pytest.raises(ValidacionError):
        servicio.detectar_anomalias()


def test_la_deteccion_a_pedido_exige_una_cantidad_positiva():
    servicio = MonitoreoService(
        MagicMock(), MagicMock(), MagicMock(), MagicMock(), deteccion_anomalias=MagicMock()
    )
    with pytest.raises(ValidacionError):
        servicio.detectar_anomalias(lecturas_por_sensor=0)
