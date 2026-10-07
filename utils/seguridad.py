"""Carpetas críticas del sistema que el programa nunca debe tocar.

Leer dentro de ellas está permitido (para medir tamaños), pero cualquier
elemento que caiga aquí se marca como "no limpiable" y la limpieza lo rechaza.
"""

from __future__ import annotations

import functools
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


# Carpetas personales: nombres habituales en inglés y en español.
NOMBRES_PERSONALES = ("Documents", "Documentos", "Desktop", "Escritorio",
                      "Pictures", "Imágenes", "Imagenes")


def _subcarpetas(carpeta: Path) -> list[Path]:
    try:
        return [p for p in carpeta.iterdir() if p.is_dir()]
    except OSError:
        return []


def _carpetas_xdg(home: Path) -> list[Path]:
    """En Linux las carpetas personales pueden llamarse de otra forma; lo dice user-dirs.dirs."""
    try:
        texto = (home / ".config" / "user-dirs.dirs").read_text(encoding="utf-8")
    except OSError:
        return []
    carpetas = []
    for linea in texto.splitlines():
        clave, _, valor = linea.partition("=")
        if clave.strip() in ("XDG_DOCUMENTS_DIR", "XDG_DESKTOP_DIR", "XDG_PICTURES_DIR"):
            ruta = valor.strip().strip('"').replace("$HOME", str(home))
            if ruta and Path(ruta) != home:
                carpetas.append(Path(ruta))
    return carpetas


def carpetas_personales(home: Path | None = None) -> list[Path]:
    """Documentos, Escritorio e Imágenes del usuario (también dentro de OneDrive).

    Es donde la gente guarda lo que le importa. El programa nunca sugiere como
    basura nada que esté dentro, y nunca permite mover o borrar estas carpetas
    en sí (su contenido sí, si el usuario lo elige a mano y lo confirma).
    """
    home = home or Path.home()
    bases = [home] + [p for p in _subcarpetas(home) if p.name.lower().startswith("onedrive")]
    candidatas = [base / nombre for base in bases for nombre in NOMBRES_PERSONALES]
    candidatas += _carpetas_xdg(home)
    vistas: set[str] = set()
    resultado = []
    for carpeta in candidatas:
        clave = os.path.normcase(str(carpeta))
        if clave not in vistas and carpeta.is_dir():
            vistas.add(clave)
            resultado.append(carpeta)
    return resultado


@functools.lru_cache(maxsize=1)
def _personales_del_usuario() -> tuple[Path, ...]:
    return tuple(carpetas_personales())


def en_carpeta_personal(ruta: str | os.PathLike, personales: Iterable[Path] | None = None) -> bool:
    """True si la ruta es una carpeta personal o está dentro de una."""
    personales = carpetas_personales() if personales is None else personales
    absoluta = Path(os.path.abspath(ruta))
    return any(_dentro_de(absoluta, carpeta) for carpeta in personales)


def es_ruta_protegida(
    ruta: str | os.PathLike,
    criticas: Iterable[Path] | None = None,
    home: Path | None = None,
    personales: Iterable[Path] | None = None,
) -> bool:
    """Indica si una ruta está bloqueada: no se puede mover ni enviar a la papelera.

    Está protegida si:
    - está dentro de una carpeta crítica (C:\\Windows, /etc, ...);
    - contiene a una carpeta crítica (por ejemplo la raíz del disco);
    - es la carpeta personal del usuario o una carpeta que la contiene;
    - es una carpeta personal en sí (Documentos, Escritorio, Imágenes);
    - es el perfil de otro usuario del equipo o está dentro de él.
    """
    criticas = list(carpetas_criticas() if criticas is None else criticas)
    home = home or Path.home()
    if personales is None:
        # Con la carpeta personal real se reutiliza la lista: esta función se
        # llama miles de veces y no hace falta volver a mirar el disco cada vez.
        personales = _personales_del_usuario() if home == Path.home() else carpetas_personales(home)
    personales = list(personales)
    # Carpeta donde viven los perfiles (C:\Users, /home). Si la carpeta personal
    # cuelga directamente de la raíz (p. ej. /root), no hay carpeta de perfiles.
    perfiles = home.parent if home.parent != Path(home.anchor) else None

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
        if any(_normalizar(candidata) == _normalizar(personal) for personal in personales):
            return True  # Documentos, Escritorio o Imágenes (la carpeta, no su contenido)
        if perfiles is not None and _dentro_de(candidata, perfiles) and not _dentro_de(candidata, home):
            return True  # el perfil de otro usuario
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
