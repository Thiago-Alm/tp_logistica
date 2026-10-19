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

if __name__ == "__main__":
    contenedores = generar_contenedores(5)

    carpeta = Path(__file__).resolve().parent / "datos_generados"
    carpeta.mkdir(exist_ok=True)

    archivo = carpeta / "contenedores.json"

    with archivo.open("x", encoding="utf-8") as salida:
        json.dump(contenedores, salida, ensure_ascii=False, indent=2)

    print(f"Se guardaron {len(contenedores)} contenedores en {archivo}")