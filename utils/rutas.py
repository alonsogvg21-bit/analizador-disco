"""Dónde están los archivos del programa, tanto en desarrollo como empaquetado.

Con PyInstaller el código y los recursos se desempaquetan en una carpeta cuya
ruta queda en sys._MEIPASS. Todo lo que necesite un archivo del programa
(icono, licencias, plantillas web) debe pedirlo con ruta_recurso().
"""

from __future__ import annotations

import sys
from pathlib import Path


def empaquetado() -> bool:
    """True si se está ejecutando el programa empaquetado y no 'python main.py'."""
    return bool(getattr(sys, "frozen", False))


def carpeta_base() -> Path:
    """Carpeta raíz de los archivos del programa."""
    en_paquete = getattr(sys, "_MEIPASS", None)
    return Path(en_paquete) if en_paquete else Path(__file__).resolve().parent.parent


def ruta_recurso(*partes: str) -> Path:
    """Ruta de un archivo incluido con el programa, p. ej. ruta_recurso('desktop', 'recursos', 'icono.png')."""
    return carpeta_base().joinpath(*partes)
