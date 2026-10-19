"""Inyeccion de dependencias: aca se decide que implementacion usa cada interfaz.

Es el UNICO lugar del proyecto donde se nombra una tecnologia concreta junto a
una interfaz. Los servicios reciben una `UnidadDeTrabajo` y no saben si detras
hay PostgreSQL, otro motor o un doble de prueba. Por eso los tests pueden
construir un `Contenedor` con una unidad de trabajo falsa sin tocar este
archivo.

Uso:

    contenedor = Contenedor()
    contenedor.clientes.alta(cuit="30-71122334-9", ...)
"""
import logging
from functools import cached_property

from logistica.config import Settings
from logistica.config import settings as settings_por_defecto
from logistica.infrastructure.postgres.unidad_de_trabajo import UnidadDeTrabajoPostgres
from logistica.logging_config import setup_logging
from logistica.repositories.unidad_de_trabajo import UnidadDeTrabajo
from logistica.services.cliente_service import ClienteService
from logistica.services.usuario_service import UsuarioService

log = logging.getLogger(__name__)


class Contenedor:
    def __init__(
        self,
        settings: Settings | None = None,
        unidad_de_trabajo: UnidadDeTrabajo | None = None,
        configurar_logging: bool = True,
    ) -> None:
        self.settings = settings or settings_por_defecto
        if configurar_logging:
            setup_logging(self.settings.log_level)
        # Se puede inyectar otra unidad de trabajo (por ejemplo, una falsa en los
        # tests) sin tocar nada mas.
        self._uow = unidad_de_trabajo

    @cached_property
    def unidad_de_trabajo(self) -> UnidadDeTrabajo:
        if self._uow is None:
            self._uow = UnidadDeTrabajoPostgres(self.settings)
        return self._uow

    @cached_property
    def clientes(self) -> ClienteService:
        return ClienteService(self.unidad_de_trabajo)

    @cached_property
    def usuarios(self) -> UsuarioService:
        return UsuarioService(self.unidad_de_trabajo)
