"""Carpetas críticas del sistema que el programa nunca debe tocar.

Leer dentro de ellas está permitido (para medir tamaños), pero cualquier
elemento que caiga aquí se marca como "no limpiable" y la limpieza lo rechaza.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from pathlib import Path

from utils.sistema import LINUX, WINDOWS, sistema_actual

_NOMBRES_LINUX = (
    "bin", "boot", "dev", "etc", "lib", "lib32", "lib64",
    "proc", "sbin", "sys", "usr",
)


def carpetas_criticas(
    sistema: str | None = None,
    entorno: Mapping[str, str] | None = None,
    raiz_linux: Path | None = None,
) -> list[Path]:
    """Lista de carpetas bloqueadas para el sistema indicado (o el actual)."""
    sistema = sistema or sistema_actual()
    entorno = os.environ if entorno is None else entorno

    if sistema == WINDOWS:
        unidad = Path(entorno.get("SystemDrive", "C:") + os.sep)
        criticas = [
            Path(entorno.get("SystemRoot") or unidad / "Windows"),
            Path(entorno.get("ProgramFiles") or unidad / "Program Files"),
            Path(entorno.get("ProgramFiles(x86)") or unidad / "Program Files (x86)"),
        ]
        return criticas

    if sistema == LINUX:
        raiz = raiz_linux or Path(os.sep)
        return [raiz / nombre for nombre in _NOMBRES_LINUX]

    return []


def _normalizar(ruta: Path) -> Path:
    # normcase iguala mayúsculas y separadores en Windows; en Linux no cambia nada.
    return Path(os.path.normcase(str(ruta)))


def _dentro_de(ruta: Path, carpeta: Path) -> bool:
    """True si 'ruta' es 'carpeta' o está en su interior."""
    return _normalizar(ruta).is_relative_to(_normalizar(carpeta))


def es_ruta_protegida(
    ruta: str | os.PathLike,
    criticas: Iterable[Path] | None = None,
    home: Path | None = None,
) -> bool:
    """Indica si una ruta está bloqueada para la limpieza.

    Está protegida si:
    - está dentro de una carpeta crítica (C:\\Windows, /etc, ...);
    - contiene a una carpeta crítica (por ejemplo la raíz del disco);
    - es la carpeta personal del usuario o una carpeta que la contiene.
    """
    criticas = list(carpetas_criticas() if criticas is None else criticas)
    home = home or Path.home()

    absoluta = Path(os.path.abspath(ruta))
    candidatas = {absoluta}
    try:
        # También se comprueba la ruta real, por si se llega mediante un enlace.
        candidatas.add(absoluta.resolve())
    except OSError:
        pass

    for candidata in candidatas:
        if candidata == Path(candidata.anchor):
            return True  # raíz de un disco
        if _dentro_de(home, candidata):
            return True  # la carpeta personal o alguna de sus carpetas padre
        for critica in criticas:
            if _dentro_de(candidata, critica) or _dentro_de(critica, candidata):
                return True
    return False


def dentro_de_carpeta_critica(
    ruta: str | os.PathLike, criticas: Iterable[Path] | None = None
) -> bool:
    """True si la ruta es una carpeta crítica del sistema o está dentro de una.

    Se usa para validar el DESTINO al mover archivos. Es menos estricta que
    es_ruta_protegida(): sí permite, por ejemplo, la carpeta personal o la
    raíz de un disco de datos como destino.
    """
    criticas = list(carpetas_criticas() if criticas is None else criticas)
    absoluta = Path(os.path.abspath(ruta))
    candidatas = {absoluta}
    try:
        candidatas.add(absoluta.resolve())
    except OSError:
        pass
    return any(_dentro_de(c, critica) for c in candidatas for critica in criticas)
