"""Detección del sistema operativo y de carpetas especiales del usuario."""

from __future__ import annotations

import platform
from pathlib import Path

WINDOWS = "windows"
LINUX = "linux"
OTRO = "otro"


def sistema_actual() -> str:
    """Devuelve 'windows', 'linux' u 'otro' según platform.system()."""
    nombre = platform.system().lower()
    if nombre == "windows":
        return WINDOWS
    if nombre == "linux":
        return LINUX
    return OTRO


def carpeta_usuario() -> Path:
    """Carpeta personal: C:\\Users\\nombre en Windows, /home/nombre en Linux."""
    return Path.home()


def carpeta_descargas(home: Path | None = None) -> Path:
    """Carpeta de descargas (en Linux puede llamarse 'Descargas')."""
    home = home or carpeta_usuario()
    for nombre in ("Downloads", "Descargas"):
        if (home / nombre).is_dir():
            return home / nombre
    return home / "Downloads"
