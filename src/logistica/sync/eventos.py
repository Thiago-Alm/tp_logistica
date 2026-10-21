"""Construccion de los eventos que viajan por el Outbox.

Vive aca y no dentro de cada servicio por dos motivos:

1. El payload es un contrato. Lo escribe el servicio y lo lee el proyector; si
   cada servicio inventara su propia forma, cada proyector tendria que conocer
   todas. Teniendolo en un solo modulo, el contrato se cambia en un solo lugar.
2. El payload NO es la entidad serializada entera. Lleva solo lo que los
   destinos necesitan para construir el nodo o el documento. Mandar la entidad
   completa acoplaria el grafo a cambios de PostgreSQL que no le importan.
"""
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from logistica.domain.cliente import Cliente
from logistica.domain.contenedor import Contenedor
from logistica.domain.envio import Envio
from logistica.domain.evento_outbox import EventoOutbox, TipoAgregado, TipoEvento, nuevo_evento
from logistica.domain.tramo import Tramo


def _texto(valor: Any) -> Any:
    """UUID, datetime y Decimal no son JSON. Se guardan como texto.

    Los Decimal van como texto y no como float a proposito: convertirlos a
    float reintroduciria el error de redondeo que D15 evita.
    """
    if isinstance(valor, (UUID, datetime)):
        return str(valor)
    if isinstance(valor, Decimal):
        return str(valor)
    return valor


def _limpiar(datos: dict[str, Any]) -> dict[str, Any]:
    return {clave: _texto(valor) for clave, valor in datos.items()}


# --- Cliente ---------------------------------------------------------------


def cliente_creado(cliente: Cliente, momento: datetime) -> EventoOutbox:
    return nuevo_evento(
        TipoAgregado.CLIENTE,
        cliente.id,
        TipoEvento.CREADO,
        _limpiar({
            "id": cliente.id,
            "razon_social": cliente.razon_social,
            "cuit": cliente.cuit,
            "pais": cliente.pais,
            "estado": cliente.estado.value,
        }),
        momento,
    )


def cliente_actualizado(cliente: Cliente, momento: datetime) -> EventoOutbox:
    evento = cliente_creado(cliente, momento)
    evento.evento_tipo = TipoEvento.ACTUALIZADO
    return evento


def cliente_dado_de_baja(cliente: Cliente, momento: datetime) -> EventoOutbox:
    """La baja viaja como cambio de estado, no como borrado (D26).

    Si el proyector borrara el nodo, el grafo perderia las relaciones
    historicas del cliente con sus envios.
    """
    return nuevo_evento(
        TipoAgregado.CLIENTE,
        cliente.id,
        TipoEvento.DADO_DE_BAJA,
        _limpiar({"id": cliente.id, "estado": cliente.estado.value}),
        momento,
    )


# --- Envio -----------------------------------------------------------------


def envio_creado(envio: Envio, momento: datetime) -> EventoOutbox:
    return nuevo_evento(
        TipoAgregado.ENVIO,
        envio.id,
        TipoEvento.CREADO,
        _limpiar({
            "id": envio.id,
            "cliente_id": envio.cliente_id,
            "origen_id": envio.origen_id,
            "destino_id": envio.destino_id,
            "estado": envio.estado.value,
            "prioridad": envio.prioridad.value,
            "fecha_creacion": envio.fecha_creacion,
        }),
        momento,
    )


def envio_cambio_de_estado(envio: Envio, momento: datetime) -> EventoOutbox:
    return nuevo_evento(
        TipoAgregado.ENVIO,
        envio.id,
        TipoEvento.ESTADO_CAMBIADO,
        _limpiar({
            "id": envio.id,
            "estado": envio.estado.value,
            "fecha_llegada_real": envio.fecha_llegada_real,
        }),
        momento,
    )


def contenedor_asignado(
    envio_id: UUID, contenedor_id: UUID, momento: datetime
) -> EventoOutbox:
    """El agregado es el ENVIO y no el contenedor: la relacion la crea el envio,
    y asi los eventos de un mismo envio quedan ordenados entre si."""
    return nuevo_evento(
        TipoAgregado.ENVIO,
        envio_id,
        TipoEvento.CONTENEDOR_ASIGNADO,
        _limpiar({"envio_id": envio_id, "contenedor_id": contenedor_id}),
        momento,
    )


# --- Tramo -----------------------------------------------------------------


def tramo_creado(tramo: Tramo, momento: datetime) -> EventoOutbox:
    return nuevo_evento(
        TipoAgregado.TRAMO,
        tramo.id,
        TipoEvento.CREADO,
        _limpiar({
            "id": tramo.id,
            "envio_id": tramo.envio_id,
            "vehiculo_id": tramo.vehiculo_id,
            "origen_id": tramo.origen_id,
            "destino_id": tramo.destino_id,
            "orden": tramo.orden,
            "medio_transporte": tramo.medio_transporte.value,
            "costo": tramo.costo,
        }),
        momento,
    )


# --- Contenedor ------------------------------------------------------------


def contenedor_creado(contenedor: Contenedor, momento: datetime) -> EventoOutbox:
    return nuevo_evento(
        TipoAgregado.CONTENEDOR,
        contenedor.id,
        TipoEvento.CREADO,
        _limpiar({
            "id": contenedor.id,
            "codigo_iso": contenedor.codigo_iso,
            "tipo": contenedor.tipo,
            "estado": contenedor.estado.value,
        }),
        momento,
    )
