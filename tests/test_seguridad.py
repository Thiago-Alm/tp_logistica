from logistica.seguridad import ALGORITMO, hashear_password, verificar_password


def test_la_contrasena_correcta_verifica():
    assert verificar_password("demo1234", hashear_password("demo1234"))


def test_la_contrasena_incorrecta_no_verifica():
    assert not verificar_password("otracosa", hashear_password("demo1234"))


def test_la_misma_contrasena_da_hashes_distintos():
    """Cada hash lleva su propio salt aleatorio, asi que dos usuarios con la
    misma contrasena no comparten el hash y una tabla precalculada no sirve."""
    uno = hashear_password("demo1234")
    otro = hashear_password("demo1234")
    assert uno != otro
    assert verificar_password("demo1234", uno)
    assert verificar_password("demo1234", otro)


def test_el_hash_no_contiene_la_contrasena():
    assert "demo1234" not in hashear_password("demo1234")


def test_el_formato_declara_el_algoritmo():
    partes = hashear_password("demo1234").split("$")
    assert len(partes) == 4
    assert partes[0] == ALGORITMO
    assert int(partes[1]) >= 100_000


def test_un_hash_con_basura_no_rompe():
    """verificar_password nunca lanza: devuelve False ante cualquier formato."""
    for basura in ["", "nada", "a$b$c", "a$b$c$d$e", "otro$200000$aa$bb", "x$y$zz$ww"]:
        assert verificar_password("demo1234", basura) is False


def test_contrasena_vacia():
    assert verificar_password("", hashear_password(""))
    assert not verificar_password("algo", hashear_password(""))
