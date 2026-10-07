"""Forma común de las reglas de cada sistema operativo."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Claves de categoría usadas por las reglas de ubicación.
TEMPORALES = "temporales"
CACHE = "cache"
PAPELERA = "papelera"
DESCARGAS = "descargas"
LOGS = "logs"


@dataclass(frozen=True, slots=True)
class ReglaUbicacion:
    """Una carpeta conocida donde se acumula basura.

    'limpiable=False' significa solo informativo: se mide y se muestra, pero
    el programa no la limpia (carpeta del sistema, requiere administrador,
    o contiene archivos personales que debe revisar el usuario).
    """
    categoria: str
    nombre: str
    ruta: Path
    limpiable: bool = True
    nota: str = ""
