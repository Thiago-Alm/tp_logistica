from datetime import datetime
from uuid import uuid4

from logistica.domain.lectura import Lectura


def nueva_lectura(**cambios) -> Lectura:
    datos = dict(
        sensor_id=uuid4(),
        contenedor_id=uuid4(),
        momento=datetime(2026, 2, 3, 14, 30, 5),
        temperatura=4.2,
        humedad=60.0,
        vibracion=0.1,
        latitud=-34.60,
        longitud=-58.38,
        bateria=95,
    )
    datos.update(cambios)
    return Lectura(**datos)


def test_una_lectura_puede_no_pertenecer_a_un_envio():
    """Un contenedor en deposito reporta igual, sin envio asignado."""
    assert nueva_lectura().envio_id is None


def test_una_lectura_puede_pertenecer_a_un_envio():
    envio_id = uuid4()
    assert nueva_lectura(envio_id=envio_id).envio_id == envio_id


def test_el_dia_se_deriva_del_momento():
    assert nueva_lectura().dia == "2026-02-03"
