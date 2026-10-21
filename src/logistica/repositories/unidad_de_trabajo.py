"""Unit of Work: agrupa varios repositorios en UNA transaccion.

Es el patron que hace real lo que el grupo justifico para elegir PostgreSQL:
"o se hace todo o nada". Sin el, cada repositorio confirmaria por su cuenta y
una facturacion a medias dejaria la factura escrita y la cuenta corriente sin
actualizar.

Uso:

    with uow:
        uow.clientes.guardar(cliente)
        uow.usuarios.guardar(usuario)
        uow.commit()

Si el bloque termina sin commit (por una excepcion o porque alguien se olvido),
se deshace todo.
"""
from abc import ABC, abstractmethod

from logistica.repositories.cliente_repository import ClienteRepository
from logistica.repositories.contenedor_repository import ContenedorRepository
from logistica.repositories.envio_repository import EnvioRepository
from logistica.repositories.reporte_envio_repository import ReporteEnvioRepository
from logistica.repositories.rol_repository import RolRepository
from logistica.repositories.tramo_repository import TramoRepository
from logistica.repositories.usuario_repository import UsuarioRepository


class UnidadDeTrabajo(ABC):
    clientes: ClienteRepository
    roles: RolRepository
    usuarios: UsuarioRepository
    envios: EnvioRepository
    tramos: TramoRepository
    contenedores: ContenedorRepository
    reportes_envio: ReporteEnvioRepository

    def __enter__(self) -> "UnidadDeTrabajo":
        return self

    def __exit__(self, tipo, valor, traza) -> None:
        # Deshacer siempre al salir: si hubo commit, no queda nada que deshacer.
        self.rollback()
        self.cerrar()

    @abstractmethod
    def commit(self) -> None: ...

    @abstractmethod
    def rollback(self) -> None: ...

    @abstractmethod
    def cerrar(self) -> None: ...
