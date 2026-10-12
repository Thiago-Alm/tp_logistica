import pytest

from logistica.repositories.contenedor_repository import ContenedorRepository
from logistica.repositories.envio_repository import EnvioRepository
from logistica.repositories.lectura_repository import LecturaRepository
from logistica.repositories.reporte_envio_repository import ReporteEnvioRepository

INTERFACES = [
    ContenedorRepository,
    EnvioRepository,
    LecturaRepository,
    ReporteEnvioRepository,
]


@pytest.mark.parametrize("interfaz", INTERFACES, ids=lambda i: i.__name__)
def test_las_interfaces_no_se_pueden_instanciar(interfaz):
    with pytest.raises(TypeError):
        interfaz()
