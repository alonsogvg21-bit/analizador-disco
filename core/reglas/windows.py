"""Ubicaciones de basura conocidas en Windows."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterable, Mapping
from pathlib import Path

from core.reglas.base import CACHE, DESCARGAS, PAPELERA, TEMPORALES, ReglaUbicacion
from utils.sistema import carpeta_descargas

# Subcarpetas de caché dentro de cada perfil de Chrome / Edge (misma base: Chromium).
_CACHES_CHROMIUM = (("Cache",), ("Code Cache",), ("GPUCache",))


def _perfiles_chromium(datos_usuario: Path) -> list[Path]:
    """Perfiles 'Default', 'Profile 1', 'Profile 2'... de un navegador Chromium."""
    if not datos_usuario.is_dir():
        return []
    try:
        return [
            p for p in datos_usuario.iterdir()
            if p.is_dir() and (p.name == "Default" or p.name.startswith("Profile "))
        ]
    except OSError:
        return []


def _unidades() -> list[Path]:
    import psutil  # import local: solo hace falta en Windows real

    return [Path(p.mountpoint) for p in psutil.disk_partitions(all=False)]


def obtener_reglas(
    entorno: Mapping[str, str] | None = None,
    home: Path | None = None,
    unidades: Iterable[Path] | None = None,
) -> list[ReglaUbicacion]:
    """Reglas de Windows. Los parámetros permiten simular otro equipo en las pruebas."""
    entorno = os.environ if entorno is None else entorno
    home = home or Path.home()
    reglas: list[ReglaUbicacion] = []

    # --- Temporales ---
    temp_usuario = Path(entorno.get("TEMP") or tempfile.gettempdir())
    reglas.append(ReglaUbicacion(TEMPORALES, "Temporales del usuario", temp_usuario))

    raiz_windows = Path(entorno.get("SystemRoot") or Path("C:" + os.sep) / "Windows")
    reglas.append(ReglaUbicacion(
        TEMPORALES, "Temporales de Windows", raiz_windows / "Temp", limpiable=False,
        nota="Carpeta del sistema. Usa el 'Liberador de espacio en disco' de Windows.",
    ))
    reglas.append(ReglaUbicacion(
        TEMPORALES, "Prefetch", raiz_windows / "Prefetch", limpiable=False,
        nota="Windows la usa para abrir programas más rápido; no conviene borrarla.",
    ))

    # --- Caché de navegadores ---
    local = Path(entorno.get("LOCALAPPDATA") or home / "AppData" / "Local")
    navegadores = (
        ("Chrome", local / "Google" / "Chrome" / "User Data"),
        ("Edge", local / "Microsoft" / "Edge" / "User Data"),
    )
    for navegador, datos_usuario in navegadores:
        for perfil in _perfiles_chromium(datos_usuario):
            for partes in _CACHES_CHROMIUM:
                reglas.append(ReglaUbicacion(
                    CACHE, f"Caché de {navegador} ({perfil.name})", perfil.joinpath(*partes),
                    nota="Cierra el navegador antes de limpiar.",
                ))

    perfiles_firefox = local / "Mozilla" / "Firefox" / "Profiles"
    if perfiles_firefox.is_dir():
        try:
            for perfil in perfiles_firefox.iterdir():
                reglas.append(ReglaUbicacion(
                    CACHE, f"Caché de Firefox ({perfil.name})", perfil / "cache2",
                    nota="Cierra el navegador antes de limpiar.",
                ))
        except OSError:
            pass

    # --- Papelera (una por disco) ---
    for unidad in (_unidades() if unidades is None else unidades):
        reglas.append(ReglaUbicacion(
            PAPELERA, f"Papelera de {unidad}", Path(unidad) / "$Recycle.Bin", limpiable=False,
            nota="Vacíala desde el icono de la Papelera de reciclaje.",
        ))

    # --- Descargas ---
    reglas.append(ReglaUbicacion(
        DESCARGAS, "Carpeta de descargas", carpeta_descargas(home), limpiable=False,
        nota="Son archivos tuyos: revísalos a mano antes de borrar nada.",
    ))

    return reglas
