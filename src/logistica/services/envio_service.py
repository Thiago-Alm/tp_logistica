"""Casos de uso de Envio y sus tramos.

Requisitos que cubre: registro de envios, seguimiento de trayectos, seguimiento
temporal de cada envio y los reportes operativos y analiticos de envios.
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from logistica.domain.contenedor import Contenedor, EstadoContenedor
from logistica.domain.envio import Envio, EstadoEnvio, PrioridadEnvio
from logistica.domain.tramo import MedioTransporte, Tramo
from logistica.exceptions import ConflictoDeDatos, NoEncontrado, ValidacionError
from logistica.repositories.unidad_de_trabajo import UnidadDeTrabajo
from logistica.sync import eventos

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class EnvioConTramos:
    """Un envio junto a su recorrido.

    `Envio` no carga sus tramos (D6): cuando una consulta necesita las dos
    cosas, es el servicio el que las compone. Este objeto es el resultado de esa
    composicion, no una entidad.
    """

    envio: Envio
    tramos: list[Tramo]

    @property
    def llegada_estimada(self) -> datetime | None:
        """La del ultimo tramo. Es la que define si un envio esta demorado (D7)."""
        if not self.tramos:
            return None
        return max(t.fecha_llegada_estimada for t in self.tramos)

    @property
    def costo_total(self) -> Decimal:
        return sum((t.costo for t in self.tramos), Decimal("0"))

    def esta_demorado(self, momento: datetime) -> bool:
        estimada = self.llegada_estimada
        if estimada is None or self.envio.estado in (
            EstadoEnvio.ENTREGADO,
            EstadoEnvio.CANCELADO,
        ):
            return False
        return estimada < momento


class EnvioService:
    def __init__(self, unidad_de_trabajo: UnidadDeTrabajo) -> None:
        self._uow = unidad_de_trabajo

    # --- Alta y ciclo de vida --------------------------------------------

    def registrar(
        self,
        cliente_id: UUID,
        origen_id: UUID,
        destino_id: UUID,
        prioridad: PrioridadEnvio = PrioridadEnvio.MEDIA,
    ) -> Envio:
        """Requisito: "Registro de envios". Nace en estado CREADO."""
        envio = Envio(
            id=uuid4(),
            cliente_id=cliente_id,
            origen_id=origen_id,
            destino_id=destino_id,
            estado=EstadoEnvio.CREADO,
            prioridad=prioridad,
            fecha_creacion=datetime.now(timezone.utc),
        )
        with self._uow as uow:
            cliente = uow.clientes.obtener(cliente_id)
            if cliente is None:
                raise ValidacionError(f"No existe el cliente {cliente_id}")
            if not cliente.esta_activo():
                raise ValidacionError(
                    f"El cliente {cliente.razon_social} esta dado de baja"
                )
            uow.envios.guardar(envio)
            # Mismo criterio que en ClienteService: el evento entra en la
            # transaccion del dato, no despues (D34).
            uow.outbox.guardar(eventos.envio_creado(envio, envio.fecha_creacion))
            uow.commit()
        log.info("Envio registrado: %s para el cliente %s", envio.id, cliente_id)
        return envio

    def cambiar_estado(
        self, envio_id: UUID, nuevo: EstadoEnvio, momento: datetime | None = None
    ) -> Envio:
        """El cambio lo valida el dominio con `Envio.pasar_a()` (D4, D18): el
        servicio solo obtiene, pide el cambio y guarda."""
        with self._uow as uow:
            envio = uow.envios.obtener(envio_id)
            if envio is None:
                raise NoEncontrado(f"No existe el envio {envio_id}")
            envio.pasar_a(nuevo, momento)
            uow.envios.actualizar(envio)
            uow.outbox.guardar(
                eventos.envio_cambio_de_estado(envio, datetime.now(timezone.utc))
            )
            uow.commit()
        log.info("Envio %s paso a %s", envio_id, nuevo.value)
        return envio

    def entregar(self, envio_id: UUID, momento: datetime | None = None) -> Envio:
        return self.cambiar_estado(
            envio_id, EstadoEnvio.ENTREGADO, momento or datetime.now(timezone.utc)
        )

    # --- Tramos ----------------------------------------------------------

    def agregar_tramo(
        self,
        envio_id: UUID,
        vehiculo_id: UUID,
        medio_transporte: MedioTransporte,
        origen_id: UUID,
        destino_id: UUID,
        fecha_salida: datetime,
        fecha_llegada_estimada: datetime,
        costo: Decimal,
    ) -> Tramo:
        """El `orden` no se recibe: se calcula como el siguiente del envio.

        Dejarlo a cargo de quien llama invitaba a saltearse numeros o a repetir
        uno, que la restriccion UNIQUE (envio_id, orden) rechazaria (D10).
        """
        with self._uow as uow:
            if uow.envios.obtener(envio_id) is None:
                raise NoEncontrado(f"No existe el envio {envio_id}")
            existentes = uow.tramos.listar_por_envio(envio_id)
            tramo = Tramo(
                id=uuid4(),
                envio_id=envio_id,
                vehiculo_id=vehiculo_id,
                medio_transporte=medio_transporte,
                origen_id=origen_id,
                destino_id=destino_id,
                orden=len(existentes) + 1,
                fecha_salida=fecha_salida,
                fecha_llegada_estimada=fecha_llegada_estimada,
                costo=costo,
            )
            uow.tramos.guardar(tramo)
            uow.outbox.guardar(eventos.tramo_creado(tramo, datetime.now(timezone.utc)))
            uow.commit()
        log.info("Tramo %s agregado al envio %s (orden %s)", tramo.id, envio_id, tramo.orden)
        return tramo

    def completar_tramo(self, tramo_id: UUID, fecha_llegada_real: datetime) -> Tramo:
        with self._uow as uow:
            tramo = uow.tramos.obtener(tramo_id)
            if tramo is None:
                raise NoEncontrado(f"No existe el tramo {tramo_id}")
            tramo.completar(fecha_llegada_real)
            uow.tramos.actualizar(tramo)
            uow.commit()
        return tramo

    # --- Contenedores ----------------------------------------------------

    def asignar_contenedor(self, envio_id: UUID, contenedor_id: UUID) -> Contenedor:
        """Un contenedor no puede estar en dos envios activos a la vez.

        La relacion envio_contenedor es N:M historica a proposito, asi que esa
        regla no se puede declarar en la base: se valida aca, segun D3.
        """
        with self._uow as uow:
            if uow.envios.obtener(envio_id) is None:
                raise NoEncontrado(f"No existe el envio {envio_id}")
            contenedor = uow.contenedores.obtener(contenedor_id)
            if contenedor is None:
                raise NoEncontrado(f"No existe el contenedor {contenedor_id}")
            if not contenedor.estado.puede_asignarse():
                raise ConflictoDeDatos(
                    f"El contenedor {contenedor.codigo_iso} no esta disponible "
                    f"(estado: {contenedor.estado.value})"
                )
            # La asociacion y el cambio de estado del contenedor van en la
            # MISMA transaccion: si una fallara, el contenedor quedaria
            # marcado como asignado a un envio que no lo tiene (D28).
            uow.envios.asociar_contenedor(envio_id, contenedor_id)
            contenedor.estado = EstadoContenedor.ASIGNADO
            uow.contenedores.actualizar(contenedor)
            uow.outbox.guardar(
                eventos.contenedor_asignado(
                    envio_id, contenedor_id, datetime.now(timezone.utc)
                )
            )
            uow.commit()
        log.info("Contenedor %s asignado al envio %s", contenedor_id, envio_id)
        return contenedor

    # --- Consultas -------------------------------------------------------

    def obtener(self, envio_id: UUID) -> Envio:
        with self._uow as uow:
            envio = uow.envios.obtener(envio_id)
        if envio is None:
            raise NoEncontrado(f"No existe el envio {envio_id}")
        return envio

    def obtener_con_tramos(self, envio_id: UUID) -> EnvioConTramos:
        """Requisito: "Seguimiento de trayectos". Compone los dos repositorios."""
        with self._uow as uow:
            envio = uow.envios.obtener(envio_id)
            if envio is None:
                raise NoEncontrado(f"No existe el envio {envio_id}")
            tramos = uow.tramos.listar_por_envio(envio_id)
        return EnvioConTramos(envio=envio, tramos=tramos)

    def listar_por_cliente(self, cliente_id: UUID) -> list[Envio]:
        with self._uow as uow:
            return uow.envios.listar_por_cliente(cliente_id)

    def listar_por_estado(self, estado: EstadoEnvio) -> list[Envio]:
        with self._uow as uow:
            return uow.envios.listar_por_estado(estado)

    def listar_por_pais_destino(self, pais: str) -> list[Envio]:
        with self._uow as uow:
            return uow.envios.listar_por_pais_destino(pais)

    def listar_demorados(self, momento: datetime | None = None) -> list[Envio]:
        with self._uow as uow:
            return uow.envios.listar_demorados(momento or datetime.now(timezone.utc))
