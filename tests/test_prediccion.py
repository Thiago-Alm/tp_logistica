"""Prediccion de atrasos: el puntaje, los motivos y la fecha proyectada (D55)."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from logistica.domain.envio import EstadoEnvio
from logistica.domain.incidente import SeveridadIncidente
from logistica.domain.prediccion import (
    CORTE_ALTO,
    CORTE_CRITICO,
    CORTE_MEDIO,
    FactorDeRiesgo,
    NivelRiesgo,
    PrediccionAtraso,
)
from logistica.services.prediccion_service import PrediccionService

AHORA = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
ORIGEN, DESTINO = uuid4(), uuid4()


def tramo(dias_estimada: float, dias_real: float | None = None, orden: int = 1):
    """Un tramo con su llegada estimada a N dias de AHORA (negativo = pasado)."""
    return SimpleNamespace(
        orden=orden,
        fecha_llegada_estimada=AHORA + timedelta(days=dias_estimada),
        fecha_llegada_real=(
            None if dias_real is None else AHORA + timedelta(days=dias_real)
        ),
    )


def envio(estado=EstadoEnvio.EN_TRANSITO):
    return SimpleNamespace(
        id=uuid4(), cliente_id=uuid4(), estado=estado,
        origen_id=ORIGEN, destino_id=DESTINO,
    )


def incidente(severidad=SeveridadIncidente.MEDIA, envio_id=None):
    return SimpleNamespace(envio_id=envio_id or uuid4(), severidad=severidad)


def predecir(tramos, incidentes=(), estado=EstadoEnvio.EN_TRANSITO) -> PrediccionAtraso:
    """Arma el servicio con dobles y devuelve la unica prediccion."""
    el_envio = envio(estado)
    for i in incidentes:
        i.envio_id = el_envio.id

    uow = MagicMock()
    uow.__enter__.return_value = uow
    uow.ubicaciones.listar.return_value = [
        SimpleNamespace(id=ORIGEN, etiqueta="ARBUE"),
        SimpleNamespace(id=DESTINO, etiqueta="NLRTM"),
    ]
    uow.envios.listar_por_estado.side_effect = (
        lambda e: [el_envio] if e is estado else []
    )
    uow.tramos.listar_por_envio.return_value = list(tramos)
    repositorio = MagicMock()
    repositorio.listar_abiertos.return_value = list(incidentes)

    return PrediccionService(repositorio, uow).predecir_atrasos(AHORA)[0]


# --- Nivel de riesgo ---------------------------------------------------------


@pytest.mark.parametrize(
    "puntaje,esperado",
    [
        (0, NivelRiesgo.BAJO),
        (CORTE_MEDIO, NivelRiesgo.MEDIO),
        (CORTE_ALTO - 1, NivelRiesgo.MEDIO),
        (CORTE_ALTO, NivelRiesgo.ALTO),
        (CORTE_CRITICO - 1, NivelRiesgo.ALTO),
        (CORTE_CRITICO, NivelRiesgo.CRITICO),
        (100, NivelRiesgo.CRITICO),
    ],
)
def test_el_nivel_sale_del_puntaje(puntaje, esperado):
    assert NivelRiesgo.desde_puntaje(puntaje) is esperado


def test_solo_alto_y_critico_necesitan_atencion():
    assert not NivelRiesgo.BAJO.necesita_atencion()
    assert not NivelRiesgo.MEDIO.necesita_atencion()
    assert NivelRiesgo.ALTO.necesita_atencion()
    assert NivelRiesgo.CRITICO.necesita_atencion()


def test_todos_los_valores_van_en_mayusculas():
    """D19."""
    for valor in NivelRiesgo:
        assert valor.value == valor.name == valor.value.upper()


# --- Factores ----------------------------------------------------------------


def test_un_envio_al_dia_no_tiene_factores():
    prediccion = predecir([tramo(dias_estimada=5)])
    assert prediccion.factores == ()
    assert prediccion.nivel is NivelRiesgo.BAJO
    assert prediccion.atraso_acumulado == timedelta(0)


def test_un_tramo_que_llego_tarde_suma_y_arrastra_el_atraso():
    """No es una estimacion: paso, y el tiempo perdido se arrastra."""
    prediccion = predecir([tramo(dias_estimada=-10, dias_real=-8)])
    assert prediccion.atraso_acumulado == timedelta(days=2)
    assert "llegaron tarde" in prediccion.motivos[0]


def test_un_tramo_que_llego_a_tiempo_no_suma_atraso():
    prediccion = predecir([tramo(dias_estimada=-10, dias_real=-11)])
    assert prediccion.atraso_acumulado == timedelta(0)
    assert not any("llegaron tarde" in m for m in prediccion.motivos)


def test_el_recorrido_completo_sin_entrega_se_reporta_aparte():
    """Si todos los tramos llegaron, la fecha vencida no dice nada: el envio
    llego y lo que falta es registrar la entrega. Decir "la llegada vencio"
    seria enganoso."""
    prediccion = predecir([tramo(dias_estimada=-10, dias_real=-11)])
    assert "falta registrar la entrega" in prediccion.motivos[0]
    assert not any("llegada estimada vencio" in m for m in prediccion.motivos)


def test_un_tramo_vencido_sin_llegada_cuenta_desde_hoy():
    prediccion = predecir([tramo(dias_estimada=-3)])
    assert prediccion.atraso_acumulado == timedelta(days=3)
    assert any("vencidos sin registrar llegada" in m for m in prediccion.motivos)


def test_los_incidentes_graves_pesan_mas():
    leve = predecir([tramo(5)], [incidente(SeveridadIncidente.BAJA)])
    grave = predecir([tramo(5)], [incidente(SeveridadIncidente.CRITICA)])
    assert grave.puntaje > leve.puntaje
    assert "severidad alta o critica" in grave.motivos[0]


def test_solo_cuentan_los_incidentes_del_envio():
    """`listar_abiertos` trae los de todos los envios: se agrupan por envio."""
    ajeno = incidente()
    ajeno.envio_id = uuid4()
    uow = MagicMock()
    uow.__enter__.return_value = uow
    uow.ubicaciones.listar.return_value = []
    el_envio = envio()
    uow.envios.listar_por_estado.side_effect = (
        lambda e: [el_envio] if e is EstadoEnvio.EN_TRANSITO else []
    )
    uow.tramos.listar_por_envio.return_value = [tramo(5)]
    repositorio = MagicMock()
    repositorio.listar_abiertos.return_value = [ajeno]

    prediccion = PrediccionService(repositorio, uow).predecir_atrasos(AHORA)[0]
    assert prediccion.factores == ()


def test_un_envio_sin_tramos_se_reporta():
    prediccion = predecir([])
    assert prediccion.llegada_estimada is None
    assert prediccion.llegada_proyectada is None
    assert "no tiene tramos" in prediccion.motivos[0]


def test_la_llegada_vencida_suma_aparte_de_los_tramos():
    prediccion = predecir([tramo(dias_estimada=-5)])
    assert any("llegada estimada vencio" in m for m in prediccion.motivos)


# --- Proyeccion --------------------------------------------------------------


def test_la_proyectada_corre_la_estimada_por_el_atraso():
    """El puntaje mide riesgo; el atraso mide tiempo. Mezclarlos daria un
    numero de dias inventado."""
    prediccion = predecir(
        [tramo(dias_estimada=-10, dias_real=-7, orden=1), tramo(dias_estimada=4, orden=2)]
    )
    assert prediccion.atraso_acumulado == timedelta(days=3)
    assert prediccion.llegada_proyectada == prediccion.llegada_estimada + timedelta(days=3)


def test_la_estimada_es_la_del_ultimo_tramo():
    """D7: la llegada del envio es el MAX de sus tramos."""
    prediccion = predecir([tramo(2, orden=1), tramo(9, orden=2), tramo(5, orden=3)])
    assert prediccion.llegada_estimada == AHORA + timedelta(days=9)


# --- Alcance y orden ---------------------------------------------------------


def test_los_envios_terminados_no_se_predicen():
    """Ya se sabe como terminaron."""
    uow = MagicMock()
    uow.__enter__.return_value = uow
    uow.ubicaciones.listar.return_value = []
    uow.envios.listar_por_estado.return_value = []
    repositorio = MagicMock()
    repositorio.listar_abiertos.return_value = []

    PrediccionService(repositorio, uow).predecir_atrasos(AHORA)

    consultados = {c.args[0] for c in uow.envios.listar_por_estado.call_args_list}
    assert EstadoEnvio.ENTREGADO not in consultados
    assert EstadoEnvio.CANCELADO not in consultados


def test_las_predicciones_salen_de_mayor_riesgo_a_menor():
    uow = MagicMock()
    uow.__enter__.return_value = uow
    uow.ubicaciones.listar.return_value = []
    tranquilo, complicado = envio(), envio()
    uow.envios.listar_por_estado.side_effect = (
        lambda e: [tranquilo, complicado] if e is EstadoEnvio.EN_TRANSITO else []
    )
    uow.tramos.listar_por_envio.side_effect = (
        lambda envio_id: [tramo(5)] if envio_id == tranquilo.id else [tramo(-20)]
    )
    repositorio = MagicMock()
    repositorio.listar_abiertos.return_value = []

    predicciones = PrediccionService(repositorio, uow).predecir_atrasos(AHORA)
    assert predicciones[0].envio_id == complicado.id
    assert predicciones[0].puntaje > predicciones[1].puntaje


def test_el_resumen_cuenta_todos_los_niveles():
    """Un nivel en cero es informacion: omitirlo lo haria parecer faltante."""
    uow = MagicMock()
    uow.__enter__.return_value = uow
    uow.ubicaciones.listar.return_value = []
    uow.envios.listar_por_estado.return_value = []
    repositorio = MagicMock()
    repositorio.listar_abiertos.return_value = []

    resumen = PrediccionService(repositorio, uow).resumen_por_nivel(AHORA)
    assert set(resumen) == set(NivelRiesgo)
    assert all(v == 0 for v in resumen.values())


def test_el_puntaje_es_la_suma_de_los_factores():
    prediccion = PrediccionAtraso(
        envio_id=uuid4(), cliente_id=uuid4(), estado="EN_TRANSITO", ruta="A->B",
        llegada_estimada=AHORA, atraso_acumulado=timedelta(0),
        factores=(FactorDeRiesgo("uno", 3), FactorDeRiesgo("dos", 5)),
    )
    assert prediccion.puntaje == 8
    assert prediccion.motivos == ("uno", "dos")
