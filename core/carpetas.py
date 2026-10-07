"""Tamaño por carpeta, un nivel a la vez.

Para "profundizar" basta con volver a llamar a contenido_de() con la ruta de
una de las subcarpetas devueltas: no hace falta escanear de nuevo.
"""

from __future__ import annotations

import os
from pathlib import Path

from core.modelos import ContenidoCarpeta, InfoCarpeta, ResultadoEscaneo


def buscar_clave(resultado: ResultadoEscaneo, ruta: str | os.PathLike) -> str | None:
    """Encuentra la carpeta dentro del resultado, sin distinguir mayúsculas en Windows."""
    clave = str(Path(ruta))
    if clave in resultado.tamano_carpetas:
        return clave
    buscada = os.path.normcase(os.path.abspath(clave))
    for candidata in resultado.tamano_carpetas:
        if os.path.normcase(candidata) == buscada:
            return candidata
    return None


def info_carpeta(resultado: ResultadoEscaneo, clave: str) -> InfoCarpeta:
    return InfoCarpeta(
        ruta=Path(clave),
        tamano=resultado.tamano_carpetas.get(clave, 0),
        num_archivos=resultado.archivos_por_carpeta.get(clave, 0),
    )


def contenido_de(
    resultado: ResultadoEscaneo, ruta: str | os.PathLike | None = None
) -> ContenidoCarpeta:
    """Subcarpetas directas de 'ruta' (por defecto la raíz), de mayor a menor."""
    clave = buscar_clave(resultado, ruta if ruta is not None else resultado.raiz)
    if clave is None:
        raise KeyError(f"La carpeta no forma parte del escaneo: {ruta}")

    subcarpetas = [info_carpeta(resultado, hija) for hija in resultado.hijos.get(clave, [])]
    subcarpetas.sort(key=lambda c: c.tamano, reverse=True)

    return ContenidoCarpeta(
        ruta=Path(clave),
        tamano=resultado.tamano_carpetas[clave],
        num_archivos=resultado.archivos_por_carpeta[clave],
        tamano_archivos_directos=resultado.tamano_directo[clave],
        subcarpetas=subcarpetas,
    )
