"""Generador de datos de prueba para el proyecto de logística."""
from uuid import uuid4
import json
from pathlib import Path

def generar_codigo_iso(numero: int) -> str:
    """Genera un código de prueba de 4 letras y 7 dígitos."""
    if not 0 <= numero <= 9_999_999:
        raise ValueError("El número debe estar entre 0 y 9.999.999.")

    return f"TSTU{numero:07d}"

def generar_contenedores(cantidad: int) -> list[dict]:
    """Genera contenedores ficticios con códigos únicos en este lote."""
    if not 1 <= cantidad <= 9_999_999:
        raise ValueError("La cantidad debe estar entre 1 y 9.999.999.")

    return [
        {
            "id": str(uuid4()),
            "codigo_iso": generar_codigo_iso(numero),
            "tipo": "DRY_20",
            "capacidad": 33.0,
            "estado": "DISPONIBLE",
        }
        for numero in range(1, cantidad + 1)
    ]
def generar_sensores(contenedores: list[dict]) -> list[dict]:
    """Genera un sensor por contenedor del lote."""
    return [
        {
            "id": str(uuid4()),
            "contenedor_id": contenedor["id"],
            "numero_serie": f"TST-SENSOR-{contenedor['codigo_iso']}",
            "modelo": "MULTI-PRUEBA",
            "tipo": "MULTISENSOR",
            "intervalo_reporte_segundos": 60,
            "estado": "ACTIVO",
        }
        for contenedor in contenedores
    ]

if __name__ == "__main__":
    carpeta = Path(__file__).resolve().parent / "datos_generados"
    carpeta.mkdir(exist_ok=True)

    archivo_contenedores = carpeta / "contenedores.json"

    if archivo_contenedores.exists():
        with archivo_contenedores.open(encoding="utf-8") as entrada:
            contenedores = json.load(entrada)
    else:
        contenedores = generar_contenedores(5)
        with archivo_contenedores.open("x", encoding="utf-8") as salida:
            json.dump(contenedores, salida, ensure_ascii=False, indent=2)

    archivo_sensores = carpeta / "sensores.json"

    if archivo_sensores.exists():
        print("El lote de sensores ya existe; se conserva.")
    else:
        sensores = generar_sensores(contenedores)
        with archivo_sensores.open("x", encoding="utf-8") as salida:
            json.dump(sensores, salida, ensure_ascii=False, indent=2)

        print(f"Se guardaron {len(sensores)} sensores en {archivo_sensores}")