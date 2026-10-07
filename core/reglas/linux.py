"""Ubicaciones de basura conocidas en Linux."""

from __future__ import annotations

import os
from pathlib import Path

from core.reglas.base import CACHE, DESCARGAS, LOGS, PAPELERA, TEMPORALES, ReglaUbicacion
from utils.sistema import carpeta_descargas


def obtener_reglas(home: Path | None = None, raiz: Path | None = None) -> list[ReglaUbicacion]:
    """Reglas de Linux. 'raiz' permite simular el sistema de archivos en las pruebas."""
    home = home or Path.home()
    raiz = raiz or Path(os.sep)
    var = raiz / "var"

    return [
        # --- Temporales ---
        ReglaUbicacion(TEMPORALES, "Temporales del sistema", raiz / "tmp",
                       nota="Solo se podrán limpiar los archivos que te pertenecen."),
        ReglaUbicacion(TEMPORALES, "Temporales persistentes", var / "tmp",
                       nota="Solo se podrán limpiar los archivos que te pertenecen."),

        # --- Caché ---
        # Aquí guardan su caché los navegadores (Chrome, Firefox) y casi todas las apps.
        ReglaUbicacion(CACHE, "Caché de aplicaciones", home / ".cache",
                       nota="Cierra las aplicaciones antes de limpiar."),
        ReglaUbicacion(CACHE, "Paquetes descargados por apt", var / "cache" / "apt" / "archives",
                       limpiable=False, nota="Requiere administrador: sudo apt clean"),

        # --- Papelera ---
        ReglaUbicacion(PAPELERA, "Papelera", home / ".local" / "share" / "Trash",
                       limpiable=False, nota="Vacíala desde el gestor de archivos."),

        # --- Registros (solo lectura) ---
        ReglaUbicacion(LOGS, "Registros del sistema", var / "log", limpiable=False,
                       nota="Solo lectura. Incluye el journal de systemd."),
        ReglaUbicacion(LOGS, "Journal de systemd", var / "log" / "journal", limpiable=False,
                       nota="Ya contado en la fila anterior. "
                            "Para reducirlo: sudo journalctl --vacuum-time=2weeks"),

        # --- Descargas ---
        ReglaUbicacion(DESCARGAS, "Carpeta de descargas", carpeta_descargas(home),
                       limpiable=False,
                       nota="Son archivos tuyos: revísalos a mano antes de borrar nada."),
    ]
