"""Solicitud, generacion y facturacion de reportes parametrizados (D54)."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from logistica.domain.facturacion import TitularTipo
from logistica.domain.solicitud_reporte import (
    CATALOGO,
    PRECIO_ANALITICO,
    PRECIO_OPERATIVO,
    EstadoSolicitud,
    SolicitudReporte,
    TipoReporte,
)
from logistica.exceptions import ConflictoDeDatos, NoEncontrado, ValidacionError
from logistica.services.solicitud_reporte_service import SolicitudReporteService

AHORA = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)


def nueva_solicitud(**cambios) -> SolicitudReporte:
    datos = dict(
        id=uuid4(),
        tipo=TipoReporte.ENVIOS_POR_PAIS,
        titular_tipo=TitularTipo.CLIENTE,
        titular_id=uuid4(),
        fecha_solicitud=AHORA,
        costo=PRECIO_OPERATIVO,
    )
    datos.update(cambios)
    return SolicitudReporte(**datos)


def armar(solicitud=None):
    uow = MagicMock()
    uow.__enter__.return_value = uow
    repositorio = MagicMock()
    repositorio.obtener.return_value = solicitud
    servicio = SolicitudReporteService(
        repositorio,
        uow,
        reportes=MagicMock(),
        incidentes=MagicMock(),
        facturacion=MagicMock(),
        envios=MagicMock(),
    )
    return servicio, repositorio, uow


# --- Entidad -----------------------------------------------------------------


def test_cada_reporte_acepta_solo_sus_parametros():
    """Pedir un limite a un reporte que no lo usa es un error del pedido."""
    with pytest.raises(ValidacionError):
        nueva_solicitud(
            tipo=TipoReporte.COSTOS_POR_TRANSPORTE, parametros={"limite": 5}
        )


def test_el_rango_invertido_se_rechaza():
    with pytest.raises(ValidacionError):
        nueva_solicitud(parametros={"desde": AHORA, "hasta": AHORA - timedelta(days=1)})


@pytest.mark.parametrize("limite", [0, -1, "diez", 2.5])
def test_el_limite_tiene_que_ser_un_entero_positivo(limite):
    with pytest.raises(ValidacionError):
        nueva_solicitud(
            tipo=TipoReporte.RANKING_RUTAS_INCIDENTES, parametros={"limite": limite}
        )


def test_un_reporte_analitico_cuesta_mas_que_uno_operativo():
    assert CATALOGO[TipoReporte.ENVIOS_POR_PAIS].precio == PRECIO_OPERATIVO
    assert CATALOGO[TipoReporte.COSTOS_POR_TRANSPORTE].precio == PRECIO_ANALITICO
    assert PRECIO_ANALITICO > PRECIO_OPERATIVO


def test_el_costo_no_puede_ser_negativo():
    with pytest.raises(ValidacionError):
        nueva_solicitud(costo=Decimal("-1"))


def test_una_solicitud_facturada_es_final():
    solicitud = nueva_solicitud()
    solicitud.marcar_generada(5, AHORA)
    solicitud.marcar_facturada(uuid4())
    assert solicitud.estado.es_final()
    with pytest.raises(ValidacionError):
        solicitud.pasar_a(EstadoSolicitud.CANCELADA)


def test_no_se_genera_dos_veces():
    solicitud = nueva_solicitud()
    solicitud.marcar_generada(5, AHORA)
    with pytest.raises(ValidacionError):
        solicitud.marcar_generada(5, AHORA)


def test_todos_los_valores_van_en_mayusculas():
    """D19."""
    for enum in (TipoReporte, EstadoSolicitud):
        for valor in enum:
            assert valor.value == valor.name == valor.value.upper()


def test_el_catalogo_cubre_todos_los_tipos():
    """Un tipo sin especificacion reventaria al validar la solicitud."""
    assert set(CATALOGO) == set(TipoReporte)


# --- Solicitar ---------------------------------------------------------------


def test_solicitar_congela_el_precio_y_no_calcula_nada():
    """Como el contexto de un incidente (D12): si manana cambia la tarifa, se
    factura lo que se cotizo hoy."""
    servicio, repositorio, _ = armar()
    solicitud = servicio.solicitar(
        TipoReporte.COSTOS_POR_TRANSPORTE, TitularTipo.CLIENTE, uuid4()
    )
    assert solicitud.costo == PRECIO_ANALITICO
    assert solicitud.estado is EstadoSolicitud.SOLICITADA
    assert solicitud.filas is None
    repositorio.guardar.assert_called_once_with(solicitud)


@pytest.mark.parametrize(
    "titular,atributo",
    [
        (TitularTipo.CLIENTE, "clientes"),
        (TitularTipo.PROVEEDOR, "proveedores"),
        (TitularTipo.OPERADOR, "operadores"),
    ],
)
def test_el_titular_tiene_que_existir_en_postgres(titular, atributo):
    """No hay clave foranea: la solicitud vive en MongoDB y el titular en
    PostgreSQL (D3, D41)."""
    servicio, repositorio, uow = armar()
    getattr(uow, atributo).obtener.return_value = None
    with pytest.raises(NoEncontrado):
        servicio.solicitar(TipoReporte.ENVIOS_POR_PAIS, titular, uuid4())
    repositorio.guardar.assert_not_called()


# --- Generar -----------------------------------------------------------------


def test_generar_guarda_cuantas_filas_dio():
    solicitud = nueva_solicitud()
    servicio, repositorio, _ = armar(solicitud)
    servicio._reportes.envios_por_pais.return_value = [1, 2, 3]

    resultado = servicio.generar(solicitud.id)

    assert resultado.solicitud.estado is EstadoSolicitud.GENERADA
    assert resultado.solicitud.filas == 3
    assert resultado.filas == [1, 2, 3]
    repositorio.actualizar.assert_called_once_with(solicitud)


def test_no_se_genera_una_solicitud_ya_generada():
    solicitud = nueva_solicitud()
    solicitud.marcar_generada(3, AHORA)
    servicio, repositorio, _ = armar(solicitud)
    with pytest.raises(ConflictoDeDatos):
        servicio.generar(solicitud.id)
    repositorio.actualizar.assert_not_called()


def test_generar_una_solicitud_inexistente():
    servicio, _, _ = armar(None)
    with pytest.raises(NoEncontrado):
        servicio.generar(uuid4())


def test_el_promedio_sin_resultado_cuenta_cero_filas():
    """El tiempo promedio devuelve un valor solo, no una lista: se envuelve
    para que "cuantas filas dio" signifique lo mismo en todos los reportes."""
    solicitud = nueva_solicitud(tipo=TipoReporte.TIEMPO_PROMEDIO_ENTREGA)
    servicio, _, _ = armar(solicitud)
    servicio._reportes.tiempo_promedio_de_entrega.return_value = None
    assert servicio.generar(solicitud.id).solicitud.filas == 0


def test_el_servicio_reusa_los_reportes_que_ya_existen():
    """No consulta las bases por su cuenta: lo suyo es el ciclo de vida del
    pedido, no la consulta (y asi aprovecha la cache de D44)."""
    solicitud = nueva_solicitud(
        tipo=TipoReporte.RANKING_CLIENTES_VOLUMEN, parametros={"limite": 3}
    )
    servicio, _, _ = armar(solicitud)
    servicio._reportes.ranking_clientes_por_volumen.return_value = []

    servicio.generar(solicitud.id)

    servicio._reportes.ranking_clientes_por_volumen.assert_called_once_with(3, None, None)


# --- Facturar ----------------------------------------------------------------


def test_facturar_emite_y_marca_la_solicitud():
    solicitud = nueva_solicitud()
    solicitud.marcar_generada(4, AHORA)
    servicio, repositorio, _ = armar(solicitud)
    factura = MagicMock(id=uuid4())
    servicio._facturacion.emitir.return_value = factura

    emitida = servicio.facturar(solicitud.id)

    assert emitida is factura
    assert solicitud.estado is EstadoSolicitud.FACTURADA
    assert solicitud.factura_id == factura.id
    servicio._facturacion.emitir.assert_called_once()
    # El importe facturado es el congelado en la solicitud, no la tarifa de hoy.
    assert servicio._facturacion.emitir.call_args[0][2] == solicitud.costo
    repositorio.actualizar.assert_called_once_with(solicitud)


def test_no_se_factura_una_solicitud_sin_generar():
    solicitud = nueva_solicitud()
    servicio, _, _ = armar(solicitud)
    with pytest.raises(ConflictoDeDatos):
        servicio.facturar(solicitud.id)
    servicio._facturacion.emitir.assert_not_called()


def test_no_se_factura_dos_veces():
    solicitud = nueva_solicitud()
    solicitud.marcar_generada(4, AHORA)
    solicitud.marcar_facturada(uuid4())
    servicio, _, _ = armar(solicitud)
    with pytest.raises(ConflictoDeDatos):
        servicio.facturar(solicitud.id)
    servicio._facturacion.emitir.assert_not_called()


def test_las_pendientes_de_facturar_son_las_generadas():
    """Existe para encontrar las que quedaron a medias: la factura esta en
    PostgreSQL y la solicitud en MongoDB, y no comparten transaccion."""
    servicio, repositorio, _ = armar()
    servicio.listar_pendientes_de_facturar()
    repositorio.listar.assert_called_once_with(EstadoSolicitud.GENERADA)


def test_cancelar_una_solicitud_facturada_no_se_puede():
    solicitud = nueva_solicitud()
    solicitud.marcar_generada(1, AHORA)
    solicitud.marcar_facturada(uuid4())
    servicio, repositorio, _ = armar(solicitud)
    with pytest.raises(ValidacionError):
        servicio.cancelar(solicitud.id)
    repositorio.actualizar.assert_not_called()


# --- Contra MongoDB real -----------------------------------------------------


@pytest.fixture
def repositorio_mongo():
    """Usa la conexion del proyecto, no un MongoClient crudo: `conectar` fija
    uuidRepresentation="standard", y sin eso pymongo rechaza un uuid.UUID."""
    from logistica.config import settings
    from logistica.exceptions import ErrorDePersistencia
    from logistica.infrastructure.mongo.conexion import cerrar, conectar
    from logistica.infrastructure.mongo.solicitud_reporte_repository import (
        COLECCION,
        MongoSolicitudReporteRepository,
    )

    try:
        base = conectar(settings)
    except ErrorDePersistencia:
        pytest.skip("MongoDB no disponible: docker compose up -d mongo")
    creadas: list = []
    try:
        yield MongoSolicitudReporteRepository(base), creadas
    finally:
        if creadas:
            base[COLECCION].delete_many({"_id": {"$in": creadas}})
        cerrar(base)


def test_el_costo_vuelve_como_decimal_y_no_pierde_centavos(repositorio_mongo):
    """D15: un float perderia centavos. Se guarda como texto y vuelve a Decimal."""
    repositorio, creadas = repositorio_mongo
    solicitud = nueva_solicitud(costo=Decimal("450.55"))
    creadas.append(solicitud.id)

    repositorio.guardar(solicitud)
    leida = repositorio.obtener(solicitud.id)

    assert isinstance(leida.costo, Decimal)
    assert leida.costo == Decimal("450.55")


def test_los_parametros_sobreviven_la_ida_y_vuelta(repositorio_mongo):
    repositorio, creadas = repositorio_mongo
    solicitud = nueva_solicitud(
        tipo=TipoReporte.RANKING_CLIENTES_VOLUMEN, parametros={"limite": 7}
    )
    creadas.append(solicitud.id)

    repositorio.guardar(solicitud)
    assert repositorio.obtener(solicitud.id).parametros == {"limite": 7}


def test_actualizar_una_solicitud_inexistente(repositorio_mongo):
    repositorio, _ = repositorio_mongo
    with pytest.raises(NoEncontrado):
        repositorio.actualizar(nueva_solicitud())
