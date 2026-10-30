"""IncidenteService: el snapshot del envio y los promedios que cruzan motores.

Sin bases externas: la UnidadDeTrabajo y el repositorio de incidentes son dobles.
"""
from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from logistica.domain.envio import Envio, EstadoEnvio, PrioridadEnvio
from logistica.domain.incidente import (
    EstadoIncidente,
    SeveridadIncidente,
    TipoIncidente,
)
from logistica.domain.reportes import ConteoIncidentes
from logistica.domain.ubicacion import TipoUbicacion, Ubicacion
from logistica.exceptions import NoEncontrado, ValidacionError
from logistica.repositories.incidente_repository import AgrupacionIncidentes
from logistica.services.incidente_service import IncidenteService

AHORA = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)

CLIENTE_ID = uuid4()
ORIGEN = Ubicacion(
    id=uuid4(),
    nombre="Puerto de Buenos Aires",
    tipo=TipoUbicacion.PUERTO,
    ciudad="Buenos Aires",
    pais="Argentina",
    codigo_locode="ARBUE",
)
DESTINO = Ubicacion(
    id=uuid4(),
    nombre="Puerto de Rotterdam",
    tipo=TipoUbicacion.PUERTO,
    ciudad="Rotterdam",
    pais="Holanda",
    codigo_locode="NLRTM",
)


def nuevo_envio() -> Envio:
    return Envio(
        id=uuid4(),
        cliente_id=CLIENTE_ID,
        origen_id=ORIGEN.id,
        destino_id=DESTINO.id,
        estado=EstadoEnvio.EN_TRANSITO,
        prioridad=PrioridadEnvio.MEDIA,
        fecha_creacion=AHORA,
    )


def armar(envio=None, ubicaciones=True):
    """Devuelve (servicio, repositorio, uow) con la UnidadDeTrabajo como doble.

    El `__enter__` devuelve el propio mock para que `with self._uow as uow`
    entregue los repositorios configurados.
    """
    uow = MagicMock()
    uow.__enter__.return_value = uow
    uow.envios.obtener.return_value = envio if envio is not None else nuevo_envio()
    uow.contenedores.obtener.return_value = MagicMock()
    uow.ubicaciones.obtener.side_effect = (
        (lambda id: {ORIGEN.id: ORIGEN, DESTINO.id: DESTINO}.get(id))
        if ubicaciones
        else (lambda id: None)
    )
    repositorio = MagicMock()
    return IncidenteService(repositorio, uow), repositorio, uow


# --- Alta y snapshot ---------------------------------------------------------


def test_el_alta_congela_el_contexto_del_envio():
    """D12: el incidente guarda donde estaba el envio cuando ocurrio."""
    envio = nuevo_envio()
    servicio, repositorio, _ = armar(envio)

    incidente = servicio.registrar(
        envio.id,
        TipoIncidente.DEMORA,
        SeveridadIncidente.ALTA,
        "Demora en aduana",
    )

    contexto = incidente.contexto_envio
    assert contexto.cliente_id == CLIENTE_ID
    assert contexto.ruta == "ARBUE->NLRTM"
    assert contexto.pais_origen == "Argentina"
    assert contexto.pais_destino == "Holanda"
    repositorio.guardar.assert_called_once_with(incidente)


def test_la_ruta_usa_el_locode_y_no_el_nombre():
    """Es lo que indexa MongoDB para el ranking: corto y univoco."""
    servicio, _, _ = armar()
    incidente = servicio.registrar(
        uuid4(), TipoIncidente.ROBO, SeveridadIncidente.CRITICA, "Robo"
    )
    assert "Puerto" not in incidente.contexto_envio.ruta


def test_un_envio_inexistente_no_genera_incidente():
    servicio, repositorio, uow = armar()
    uow.envios.obtener.return_value = None
    with pytest.raises(NoEncontrado):
        servicio.registrar(uuid4(), TipoIncidente.OTRO, SeveridadIncidente.BAJA, "x")
    repositorio.guardar.assert_not_called()


def test_si_falta_una_ubicacion_no_se_guarda_un_snapshot_a_medias():
    """Un contexto incompleto ensuciaria el ranking de rutas para siempre."""
    servicio, repositorio, _ = armar(ubicaciones=False)
    with pytest.raises(NoEncontrado):
        servicio.registrar(uuid4(), TipoIncidente.OTRO, SeveridadIncidente.BAJA, "x")
    repositorio.guardar.assert_not_called()


def test_un_contenedor_inexistente_no_genera_incidente():
    servicio, repositorio, uow = armar()
    uow.contenedores.obtener.return_value = None
    with pytest.raises(NoEncontrado):
        servicio.registrar(
            uuid4(),
            TipoIncidente.DANO_CARGA,
            SeveridadIncidente.ALTA,
            "Carga danada",
            contenedor_id=uuid4(),
        )
    repositorio.guardar.assert_not_called()


# --- Cambio de estado --------------------------------------------------------


def test_el_cambio_de_estado_pasa_por_el_dominio_y_se_persiste():
    servicio, repositorio, _ = armar()
    incidente = servicio.registrar(
        uuid4(), TipoIncidente.DEMORA, SeveridadIncidente.MEDIA, "Demora"
    )
    repositorio.obtener.return_value = incidente

    actualizado = servicio.cambiar_estado(incidente.id, EstadoIncidente.EN_ANALISIS)

    assert actualizado.estado is EstadoIncidente.EN_ANALISIS
    assert len(actualizado.historial_estados) == 2
    repositorio.actualizar.assert_called_once_with(incidente)


def test_una_transicion_invalida_no_se_persiste():
    servicio, repositorio, _ = armar()
    incidente = servicio.registrar(
        uuid4(), TipoIncidente.DEMORA, SeveridadIncidente.MEDIA, "Demora"
    )
    incidente.pasar_a(EstadoIncidente.RESUELTO)
    incidente.pasar_a(EstadoIncidente.CERRADO)
    repositorio.obtener.return_value = incidente
    repositorio.actualizar.reset_mock()

    with pytest.raises(ValidacionError):
        servicio.cambiar_estado(incidente.id, EstadoIncidente.ABIERTO)
    repositorio.actualizar.assert_not_called()


def test_cambiar_el_estado_de_un_incidente_inexistente():
    servicio, repositorio, _ = armar()
    repositorio.obtener.return_value = None
    with pytest.raises(NoEncontrado):
        servicio.cambiar_estado(uuid4(), EstadoIncidente.RESUELTO)


# --- Reportes ----------------------------------------------------------------


def test_el_ranking_rechaza_un_limite_no_positivo():
    servicio, repositorio, _ = armar()
    for limite in (0, -1):
        with pytest.raises(ValidacionError):
            servicio.ranking_de_rutas(limite)
    repositorio.ranking_de_rutas.assert_not_called()


def test_el_conteo_por_cliente_resuelve_la_razon_social():
    """MongoDB guarda el UUID; la razon social vive en PostgreSQL (D2)."""
    servicio, repositorio, uow = armar()
    repositorio.contar_agrupado.return_value = [
        ConteoIncidentes(grupo=str(CLIENTE_ID), cantidad=3)
    ]
    uow.clientes.listar.return_value = [
        MagicMock(id=CLIENTE_ID, razon_social="AgroGlobal SA")
    ]

    conteos = servicio.contar_por(AgrupacionIncidentes.CLIENTE)
    assert conteos[0].grupo == "AgroGlobal SA"
    assert conteos[0].cantidad == 3


def test_el_promedio_cruza_mongo_y_postgres():
    servicio, repositorio, uow = armar()
    repositorio.contar_agrupado.return_value = [
        ConteoIncidentes(grupo="Holanda", cantidad=4)
    ]
    uow.envios.listar_por_pais_destino.return_value = [MagicMock()] * 8

    promedios = servicio.promedio_por(AgrupacionIncidentes.PAIS_DESTINO)
    assert promedios[0].incidentes == 4
    assert promedios[0].envios == 8
    assert promedios[0].promedio == 0.5


@pytest.mark.parametrize(
    "eje",
    [
        AgrupacionIncidentes.ESTADO,
        AgrupacionIncidentes.RUTA,
        AgrupacionIncidentes.PAIS_ORIGEN,
    ],
)
def test_no_se_promedia_por_un_eje_sin_denominador(eje):
    """ESTADO agrupa por el estado del INCIDENTE, que no es un estado de envio:
    "incidentes ABIERTO / envios ABIERTO" no existe. Antes esto se filtraba y
    explotaba con un ValueError de Python al construir EstadoEnvio."""
    servicio, repositorio, _ = armar()
    with pytest.raises(ValidacionError):
        servicio.promedio_por(eje)
    repositorio.contar_agrupado.assert_not_called()


def test_cero_envios_no_divide_por_cero():
    servicio, repositorio, uow = armar()
    repositorio.contar_agrupado.return_value = [
        ConteoIncidentes(grupo="Holanda", cantidad=2)
    ]
    uow.envios.listar_por_pais_destino.return_value = []
    assert servicio.promedio_por(AgrupacionIncidentes.PAIS_DESTINO)[0].promedio == 0.0


def test_un_cliente_guardado_con_basura_se_denuncia():
    servicio, repositorio, _ = armar()
    repositorio.contar_agrupado.return_value = [
        ConteoIncidentes(grupo="no-es-un-uuid", cantidad=1)
    ]
    with pytest.raises(ValidacionError):
        servicio.promedio_por(AgrupacionIncidentes.CLIENTE)


def test_el_promedio_ordena_de_mayor_a_menor():
    servicio, repositorio, uow = armar()
    repositorio.contar_agrupado.return_value = [
        ConteoIncidentes(grupo="Holanda", cantidad=2),
        ConteoIncidentes(grupo="Brasil", cantidad=9),
    ]
    uow.envios.listar_por_pais_destino.return_value = [MagicMock()] * 3

    promedios = servicio.promedio_por(AgrupacionIncidentes.PAIS_DESTINO)
    assert [p.grupo for p in promedios] == ["Brasil", "Holanda"]
