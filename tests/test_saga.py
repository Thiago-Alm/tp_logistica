"""La saga: atomicidad entre motores, sin transaccion.

Lo que se verifica no es que los pasos corran -eso es trivial- sino que **al
fallar uno se deshagan los anteriores**, y que cuando la vuelta atras tampoco
se puede, el error lo diga en vez de callarlo.
"""
import pytest

from logistica.sync import saga


def _paso(nombre, hechos, falla=False, compensacion_falla=False, sin_deshacer=False):
    def hacer():
        if falla:
            raise RuntimeError(f"{nombre} exploto")
        hechos.append(f"hacer:{nombre}")
        return nombre

    def deshacer(resultado):
        if compensacion_falla:
            raise RuntimeError(f"no se pudo deshacer {nombre}")
        hechos.append(f"deshacer:{resultado}")

    return saga.Paso(nombre, "motor", hacer, None if sin_deshacer else deshacer)


def test_si_todos_los_pasos_salen_bien_no_se_deshace_nada():
    hechos = []
    resultados = saga.ejecutar(
        [_paso("uno", hechos), _paso("dos", hechos), _paso("tres", hechos)]
    )
    assert resultados == ["uno", "dos", "tres"]
    assert hechos == ["hacer:uno", "hacer:dos", "hacer:tres"]


def test_al_fallar_un_paso_se_deshacen_los_anteriores_en_orden_inverso():
    """Inverso porque el ultimo puede depender de los anteriores: deshacer el
    primero antes que el segundo dejaria al segundo apoyado en la nada."""
    hechos = []
    with pytest.raises(saga.SagaFallida) as capturado:
        saga.ejecutar(
            [
                _paso("uno", hechos),
                _paso("dos", hechos),
                _paso("tres", hechos, falla=True),
            ]
        )

    assert hechos == ["hacer:uno", "hacer:dos", "deshacer:dos", "deshacer:uno"]
    error = capturado.value
    assert error.paso == "tres"
    assert isinstance(error.causa, RuntimeError)
    assert error.quedo_consistente
    assert "no quedo nada a medias" in str(error)


def test_el_paso_que_falla_no_se_deshace_a_si_mismo():
    """No llego a hacer nada: deshacerlo seria revertir algo que no paso."""
    hechos = []
    with pytest.raises(saga.SagaFallida):
        saga.ejecutar([_paso("uno", hechos), _paso("dos", hechos, falla=True)])
    assert "deshacer:dos" not in hechos


def test_si_la_compensacion_tambien_falla_el_error_lo_dice():
    """El caso feo y el motivo de que SagaFallida tenga dos campos: el sistema
    quedo inconsistente y callarlo seria mentir sobre su estado."""
    hechos = []
    with pytest.raises(saga.SagaFallida) as capturado:
        saga.ejecutar(
            [
                _paso("uno", hechos, compensacion_falla=True),
                _paso("dos", hechos, falla=True),
            ]
        )

    error = capturado.value
    assert not error.quedo_consistente
    assert "uno" in error.sin_compensar[0]
    assert "inconsistente" in str(error)


def test_una_compensacion_que_falla_no_frena_a_las_demas():
    """Deshacer dos de tres deja el sistema mas cerca de donde estaba que
    deshacer cero."""
    hechos = []
    with pytest.raises(saga.SagaFallida) as capturado:
        saga.ejecutar(
            [
                _paso("uno", hechos),
                _paso("dos", hechos, compensacion_falla=True),
                _paso("tres", hechos),
                _paso("cuatro", hechos, falla=True),
            ]
        )

    assert "deshacer:tres" in hechos
    assert "deshacer:uno" in hechos     # se siguio despues del fallo de "dos"
    assert len(capturado.value.sin_compensar) == 1


def test_un_paso_sin_compensacion_se_reporta_como_tal():
    hechos = []
    with pytest.raises(saga.SagaFallida) as capturado:
        saga.ejecutar(
            [
                _paso("uno", hechos, sin_deshacer=True),
                _paso("dos", hechos, falla=True),
            ]
        )
    error = capturado.value
    assert not error.quedo_consistente
    assert "no tiene compensacion" in error.sin_compensar[0]


def test_la_causa_original_queda_encadenada():
    """`raise ... from error`: el traceback muestra que fallo de verdad, no
    solo que la saga fallo."""
    hechos = []
    with pytest.raises(saga.SagaFallida) as capturado:
        saga.ejecutar([_paso("uno", hechos, falla=True)])
    assert capturado.value.__cause__ is capturado.value.causa
