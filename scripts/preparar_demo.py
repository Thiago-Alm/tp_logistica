"""Deja el sistema listo para usar, y explica que hacer si algo falla.

    python scripts/preparar_demo.py            # levanta y verifica
    python scripts/preparar_demo.py --recargar # ademas recarga los datos semilla

Existe por un motivo concreto: la primera condicion de la defensa es que la
aplicacion funcione. Los dos problemas que nos rompieron el arranque -un
contenedor ajeno ocupando un puerto, y Cassandra tardando en aceptar conexiones-
no dan un error claro, asi que este script los detecta y los nombra.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

# Puerto -> (servicio del compose, nombre legible)
PUERTOS = {
    5432: "PostgreSQL",
    27017: "MongoDB",
    7687: "Neo4j",
    6379: "Redis",
    9042: "Cassandra",
}

# Cassandra es la mas lenta en aceptar CQL: el healthcheck le da 60 s de gracia.
ESPERA_MAXIMA = 180
ESPERA_ENTRE_INTENTOS = 5


def ejecutar(comando: list[str], texto: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(comando, capture_output=True, text=texto, cwd=RAIZ)


def paso(numero: int, titulo: str) -> None:
    print(f"\n[{numero}] {titulo}")


def docker_responde() -> bool:
    return ejecutar(["docker", "info", "--format", "{{.ServerVersion}}"]).returncode == 0


def contenedores_ajenos() -> dict[int, str]:
    """Contenedores que NO son del TP y ocupan alguno de nuestros puertos.

    Es el problema que mas cuesta diagnosticar: Docker falla con "port is
    already allocated" y no dice quien lo tiene.
    """
    salida = ejecutar(
        ["docker", "ps", "--format", "{{.Names}}\t{{.Ports}}"]
    ).stdout
    ocupados: dict[int, str] = {}
    for linea in salida.splitlines():
        if "\t" not in linea:
            continue
        nombre, puertos = linea.split("\t", 1)
        if nombre.startswith("tp_logistica"):
            continue
        for puerto in PUERTOS:
            if re.search(rf"0\.0\.0\.0:{puerto}->", puertos):
                ocupados[puerto] = nombre
    return ocupados


def sin_puerto_publicado() -> list[str]:
    """Contenedores del TP que estan Up pero SIN el puerto mapeado.

    Pasa cuando arrancan mientras otro proceso tenia el puerto tomado: Docker
    los deja corriendo igual, sin publicar nada. Es el caso mas enganoso de
    todos, porque `docker ps` dice "Up" y la aplicacion no conecta.
    """
    salida = ejecutar(
        ["docker", "ps", "--filter", "name=tp_logistica",
         "--format", "{{.Names}}	{{.Ports}}"]
    ).stdout
    rotos = []
    for linea in salida.splitlines():
        if "	" not in linea:
            continue
        nombre, puertos = linea.split("	", 1)
        if "->" not in puertos:
            rotos.append(nombre)
    return rotos


def levantar() -> bool:
    resultado = ejecutar(["docker", "compose", "up", "-d"])
    if resultado.returncode != 0:
        print("    No se pudieron levantar los contenedores:")
        for linea in (resultado.stderr or "").strip().splitlines()[-3:]:
            print(f"    {linea}")
        return False
    return True


def estado_de_los_contenedores() -> list[tuple[str, str]]:
    salida = ejecutar(
        ["docker", "ps", "-a", "--filter", "name=tp_logistica",
         "--format", "{{.Names}}\t{{.Status}}"]
    ).stdout
    return [tuple(x.split("\t", 1)) for x in salida.splitlines() if "\t" in x]


def bases_que_responden() -> tuple[int, str]:
    """Corre el chequeo de conexiones y devuelve (cuantas, salida)."""
    resultado = ejecutar([sys.executable, "scripts/chequear_conexiones.py"])
    salida = resultado.stdout or ""
    encontrado = re.search(r"(\d)/5 bases responden", salida)
    return (int(encontrado.group(1)) if encontrado else 0), salida


def esperar_a_las_cinco() -> bool:
    limite = time.time() + ESPERA_MAXIMA
    ultima = ""
    while time.time() < limite:
        cuantas, salida = bases_que_responden()
        ultima = salida
        if cuantas == 5:
            print(_solo_las_lineas_ok(salida))
            return True
        faltan = ESPERA_MAXIMA - int(limite - time.time())
        print(f"    {cuantas}/5 responden; esperando... ({faltan}s)")
        time.sleep(ESPERA_ENTRE_INTENTOS)
    print(_solo_las_lineas_ok(ultima))
    return False


def _solo_las_lineas_ok(salida: str) -> str:
    return "\n".join(
        f"    {x.strip()}" for x in salida.splitlines() if x.strip().startswith(("[OK]", "[ERROR]"))
    )


def recargar_datos() -> bool:
    print("    Aplicando esquema y datos semilla...")
    resultado = ejecutar([sys.executable, "scripts/aplicar_esquema.py"])
    if resultado.returncode != 0:
        for linea in (resultado.stderr or resultado.stdout or "").strip().splitlines()[-5:]:
            print(f"    {linea}")
        return False
    print("    Listo. Las fechas de la semilla son relativas a hoy (D56).")
    return True


def main() -> int:
    analizador = argparse.ArgumentParser(description="Prepara el sistema para usarlo")
    analizador.add_argument(
        "--recargar",
        action="store_true",
        help="vuelve a aplicar el esquema y los datos semilla de PostgreSQL",
    )
    opciones = analizador.parse_args()

    print("=" * 70)
    print("  Preparando la plataforma de logistica")
    print("=" * 70)

    paso(1, "Docker")
    if not docker_responde():
        print("    Docker no responde.")
        print("    Abri Docker Desktop, espera a que diga 'Engine running' y volve a correr esto.")
        return 1
    print("    OK, el motor responde.")

    paso(2, "Puertos")
    ajenos = contenedores_ajenos()
    if ajenos:
        print("    Hay contenedores que NO son del TP ocupando puertos nuestros:\n")
        for puerto, nombre in sorted(ajenos.items()):
            print(f"      {PUERTOS[puerto]:11} (puerto {puerto})  lo tiene: {nombre}")
        print("\n    Esto hace fallar el arranque con 'port is already allocated'.")
        print("    Para liberarlos:\n")
        for nombre in sorted(set(ajenos.values())):
            print(f"      docker stop {nombre}")
        print("\n    (despues se vuelven a prender con 'docker start <nombre>')")
        return 1
    print("    Libres.")

    paso(3, "Contenedores")
    if not levantar():
        return 1
    for nombre, estado in estado_de_los_contenedores():
        print(f"    {nombre:28} {estado}")

    rotos = sin_puerto_publicado()
    if rotos:
        print("\n    Estos estan corriendo pero SIN publicar su puerto:")
        for nombre in rotos:
            print(f"      {nombre}")
        print("\n    Pasa cuando arrancan con el puerto tomado por otro proceso.")
        print("    Docker los deja Up igual, y la aplicacion no conecta.")
        print("    Se arregla recreandolos:\n")
        print("      docker compose up -d --force-recreate\n")
        return 1

    paso(4, "Conexiones")
    print("    Cassandra tarda cerca de un minuto en aceptar consultas.")
    if not esperar_a_las_cinco():
        print("\n    No responden las cinco. Mira el detalle de arriba:")
        print("    - si falta una sola, dale mas tiempo y volve a correr esto;")
        print("    - si el error habla de autenticacion, revisa el archivo .env.")
        return 1

    if opciones.recargar:
        paso(5, "Datos de prueba")
        if not recargar_datos():
            return 1

    print("\n" + "=" * 70)
    print("  Todo listo. Para entrar:")
    print()
    print("      python -m logistica")
    print()
    print("  Usuario: admin@logistica.com     Contrasena: demo1234")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
