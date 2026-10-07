"""Clasificación de archivos por tipo según su extensión."""

from __future__ import annotations

import os
from collections.abc import Iterable

from core.modelos import InfoArchivo, ResumenTipo

OTROS = "otros"

EXTENSIONES: dict[str, frozenset[str]] = {
    "videos": frozenset({
        ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v", ".mpg", ".mpeg", ".ts",
    }),
    "imagenes": frozenset({
        ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tif", ".tiff", ".svg", ".heic",
        ".raw", ".cr2", ".nef", ".psd", ".ico",
    }),
    "documentos": frozenset({
        ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt", ".ods", ".odp",
        ".txt", ".rtf", ".md", ".csv", ".epub",
    }),
    "comprimidos": frozenset({
        ".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".tgz", ".zst",
    }),
    "instaladores": frozenset({
        ".exe", ".msi", ".msix", ".deb", ".rpm", ".appimage", ".dmg", ".pkg", ".iso", ".apk",
    }),
    "codigo": frozenset({
        ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".c", ".cpp", ".h", ".hpp", ".cs", ".go",
        ".rs", ".rb", ".php", ".html", ".css", ".scss", ".json", ".xml", ".yml", ".yaml",
        ".sh", ".bat", ".ps1", ".sql", ".kt", ".swift", ".ipynb",
    }),
}

# Orden en que se muestran las categorías.
TIPOS = (*EXTENSIONES, OTROS)

# Índice inverso extensión -> tipo. ".ts" aparece en videos y en código;
# gana código, que es el uso más habitual hoy.
_POR_EXTENSION: dict[str, str] = {
    extension: tipo for tipo, extensiones in EXTENSIONES.items() for extension in extensiones
}


def clasificar(ruta: str | os.PathLike) -> str:
    """Devuelve el tipo de un archivo según su extensión (sin abrirlo)."""
    extension = os.path.splitext(os.fspath(ruta))[1].lower()
    return _POR_EXTENSION.get(extension, OTROS)


def resumen_por_tipo(archivos: Iterable[InfoArchivo]) -> list[ResumenTipo]:
    """Tamaño y cantidad de archivos de cada tipo, de mayor a menor tamaño."""
    totales = {tipo: [0, 0] for tipo in TIPOS}
    for archivo in archivos:
        acumulado = totales[clasificar(archivo.ruta)]
        acumulado[0] += archivo.tamano
        acumulado[1] += 1
    resumen = [ResumenTipo(tipo, tamano, cantidad) for tipo, (tamano, cantidad) in totales.items()]
    resumen.sort(key=lambda r: r.tamano, reverse=True)
    return resumen
