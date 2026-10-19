"""Hash de contrasenas con PBKDF2-HMAC-SHA256.

Por que PBKDF2 y no un SHA256 pelado: un hash comun esta pensado para ser
RAPIDO, que es exactamente lo que no se quiere aca. PBKDF2 repite el hash
cientos de miles de veces, asi que probar un diccionario entero cuesta tiempo
de verdad. Ademas cada contrasena lleva su propio salt aleatorio, con lo cual
dos usuarios con la misma contrasena guardan hashes distintos y una tabla
precalculada no sirve.

Se usa hashlib, de la biblioteca estandar, para no sumar una dependencia mas al
proyecto. En un sistema real convendria argon2 o bcrypt.

Formato guardado: pbkdf2_sha256$<iteraciones>$<salt_hex>$<hash_hex>
"""
import hashlib
import hmac
import secrets

ALGORITMO = "pbkdf2_sha256"
ITERACIONES = 200_000
BYTES_DE_SALT = 16
SEPARADOR = "$"
PARTES = 4


def hashear_password(password: str) -> str:
    salt = secrets.token_bytes(BYTES_DE_SALT)
    derivado = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERACIONES)
    return SEPARADOR.join([ALGORITMO, str(ITERACIONES), salt.hex(), derivado.hex()])


def verificar_password(password: str, almacenado: str) -> bool:
    """Compara con hmac.compare_digest y no con ==.

    Un == corta en el primer byte distinto, y medir cuanto tarda permite
    adivinar el hash byte por byte. compare_digest tarda lo mismo siempre.
    """
    partes = almacenado.split(SEPARADOR)
    if len(partes) != PARTES:
        return False
    algoritmo, iteraciones, salt_hex, hash_hex = partes
    if algoritmo != ALGORITMO:
        return False
    try:
        salt = bytes.fromhex(salt_hex)
        vueltas = int(iteraciones)
    except ValueError:
        return False
    derivado = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, vueltas)
    return hmac.compare_digest(derivado.hex(), hash_hex)
