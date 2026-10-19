"""Casos de uso de Cliente. Requisito: alta, baja y modificacion de clientes."""
import logging
from datetime import datetime, timezone
from uuid import UUID, uuid4

from logistica.domain.cliente import Cliente, EstadoCliente
from logistica.exceptions import ConflictoDeDatos, NoEncontrado
from logistica.repositories.unidad_de_trabajo import UnidadDeTrabajo

log = logging.getLogger(__name__)


class ClienteService:
    """El servicio es el unico que decide que hora es y que id se genera.

    Las entidades no lo hacen: asi los tests son deterministas y el dominio no
    depende del reloj. Tambien es el unico que valida lo que necesita consultar
    la base, segun el criterio de D3.
    """

    def __init__(self, unidad_de_trabajo: UnidadDeTrabajo) -> None:
        self._uow = unidad_de_trabajo

    def alta(
        self,
        cuit: str,
        razon_social: str,
        email: str,
        pais: str,
        telefono: str | None = None,
        direccion: str | None = None,
    ) -> Cliente:
        cliente = Cliente(
            id=uuid4(),
            cuit=cuit,
            razon_social=razon_social,
            email=email,
            pais=pais,
            telefono=telefono,
            direccion=direccion,
            fecha_creacion=datetime.now(timezone.utc),
        )
        with self._uow as uow:
            if uow.clientes.obtener_por_cuit(cuit) is not None:
                raise ConflictoDeDatos(f"Ya existe un cliente con CUIT {cuit}")
            uow.clientes.guardar(cliente)
            uow.commit()
        log.info("Cliente dado de alta: %s (%s)", cliente.razon_social, cliente.id)
        return cliente

    def modificar(
        self,
        id: UUID,
        razon_social: str | None = None,
        email: str | None = None,
        telefono: str | None = None,
        direccion: str | None = None,
        pais: str | None = None,
    ) -> Cliente:
        """Modifica solo los campos recibidos y revalida los invariantes."""
        with self._uow as uow:
            cliente = uow.clientes.obtener(id)
            if cliente is None:
                raise NoEncontrado(f"No existe el cliente {id}")
            if razon_social is not None:
                cliente.razon_social = razon_social
            if email is not None:
                cliente.email = email
            if telefono is not None:
                cliente.telefono = telefono
            if direccion is not None:
                cliente.direccion = direccion
            if pais is not None:
                cliente.pais = pais
            cliente.validar()
            uow.clientes.actualizar(cliente)
            uow.commit()
        log.info("Cliente modificado: %s", id)
        return cliente

    def baja(self, id: UUID) -> Cliente:
        """Baja LOGICA (D26): el cliente queda INACTIVO. No se borra la fila,
        porque hay envios y facturas que la referencian."""
        with self._uow as uow:
            cliente = uow.clientes.obtener(id)
            if cliente is None:
                raise NoEncontrado(f"No existe el cliente {id}")
            cliente.dar_de_baja()
            uow.clientes.actualizar(cliente)
            uow.commit()
        log.info("Cliente dado de baja: %s", id)
        return cliente

    def reactivar(self, id: UUID) -> Cliente:
        with self._uow as uow:
            cliente = uow.clientes.obtener(id)
            if cliente is None:
                raise NoEncontrado(f"No existe el cliente {id}")
            cliente.reactivar()
            uow.clientes.actualizar(cliente)
            uow.commit()
        log.info("Cliente reactivado: %s", id)
        return cliente

    def obtener(self, id: UUID) -> Cliente:
        with self._uow as uow:
            cliente = uow.clientes.obtener(id)
        if cliente is None:
            raise NoEncontrado(f"No existe el cliente {id}")
        return cliente

    def buscar_por_cuit(self, cuit: str) -> Cliente:
        with self._uow as uow:
            cliente = uow.clientes.obtener_por_cuit(cuit)
        if cliente is None:
            raise NoEncontrado(f"No existe un cliente con CUIT {cuit}")
        return cliente

    def listar(self, solo_activos: bool = False) -> list[Cliente]:
        with self._uow as uow:
            return uow.clientes.listar(EstadoCliente.ACTIVO if solo_activos else None)
