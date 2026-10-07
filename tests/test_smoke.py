import pytest

from logistica.repositories.contenedor_repository import ContenedorRepository
from logistica.repositories.lectura_repository import LecturaRepository


def test_las_interfaces_no_se_pueden_instanciar():
    with pytest.raises(TypeError):
        ContenedorRepository()
    with pytest.raises(TypeError):
        LecturaRepository()
