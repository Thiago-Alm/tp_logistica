from uuid import uuid4

import pytest

from logistica.domain.reportes import (
    MovimientoDeContenedor,
    RelacionClienteEnvioOperador,
    TramoDeRuta,
)
from logistica.exceptions import NoEncontrado
from logistica.services.consulta_grafo_service import ConsultaGrafoService


class _Repo:
    def __init__(self, existentes):
        self._existentes = existentes

    def obtener(self, id):
        return object() if id in self._existentes else None


class _Uow:
    def __init__(self, existentes):
        self.envios = _Repo(existentes)
        self.clientes = _Repo(existentes)
        self.contenedores = _Repo(existentes)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Consultas:
    def __init__(self):
        self.llamadas = []
        self.tramo = TramoDeRuta("t1", 1, "MARITIMO", "Buenos Aires", "Santos", "Buque")
        self.relacion = RelacionClienteEnvioOperador(
            "c", "Cliente", "e", "EN_TRANSITO", "o", "Operador"
        )
        self.movimiento = MovimientoDeContenedor("k", "e", "t1", 1, "Buenos Aires", "Santos")

    def ruta_de_envio(self, envio_id):
        self.llamadas.append(envio_id)
        return [self.tramo]

    def red_de_cliente(self, cliente_id):
        self.llamadas.append(cliente_id)
        return [self.relacion]

    def movimientos_de_contenedor(self, contenedor_id):
        self.llamadas.append(contenedor_id)
        return [self.movimiento]


def _servicio(*existentes):
    consultas = _Consultas()
    return ConsultaGrafoService(consultas, _Uow(set(existentes))), consultas


def test_ruta_de_un_envio_existente():
    envio_id = uuid4()
    servicio, consultas = _servicio(envio_id)
    assert servicio.ruta_de_envio(envio_id) == [consultas.tramo]


def test_red_de_un_cliente_existente():
    cliente_id = uuid4()
    servicio, consultas = _servicio(cliente_id)
    assert servicio.red_de_cliente(cliente_id) == [consultas.relacion]


def test_movimientos_de_un_contenedor_existente():
    contenedor_id = uuid4()
    servicio, consultas = _servicio(contenedor_id)
    assert servicio.movimientos_de_contenedor(contenedor_id) == [consultas.movimiento]


@pytest.mark.parametrize(
    "metodo", ["ruta_de_envio", "red_de_cliente", "movimientos_de_contenedor"]
)
def test_si_no_existe_en_postgres_no_consulta_el_grafo(metodo):
    servicio, consultas = _servicio()
    with pytest.raises(NoEncontrado):
        getattr(servicio, metodo)(uuid4())
    assert consultas.llamadas == []
