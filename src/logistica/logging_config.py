"""Logging a consola y a archivo rotativo (logs/logistica.log)."""
import logging
import os
from logging.handlers import RotatingFileHandler


def setup_logging(level: str = "INFO", carpeta: str = "logs") -> None:
    os.makedirs(carpeta, exist_ok=True)
    formato = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    archivo = RotatingFileHandler(
        os.path.join(carpeta, "logistica.log"), maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    archivo.setFormatter(formato)
    consola = logging.StreamHandler()
    consola.setFormatter(formato)

    raiz = logging.getLogger()
    raiz.setLevel(level)
    if not raiz.handlers:
        raiz.addHandler(archivo)
        raiz.addHandler(consola)
