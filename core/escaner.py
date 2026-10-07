"""Recorrido del disco. Es la única parte lenta del análisis.

Se recorre el árbol UNA sola vez y de ese recorrido salen los tamaños por
carpeta, el top de archivos, los tipos y los candidatos a duplicados.
Este módulo solo lee: no abre el contenido de los archivos ni modifica nada.
"""

from __future__ import annotations

import heapq
import os
import threading
from collections.abc import Callable
from pathlib import Path

from core.modelos import InfoArchivo, ResultadoEscaneo

# Carpetas que se pueden volver a generar con un comando (npm install, etc.).
CARPETAS_REGENERABLES = frozenset({"node_modules", "__pycache__", ".gradle", ".venv"})

# Carpetas virtuales de Linux: no son archivos reales y pueden dar tamaños absurdos.
_VIRTUALES_LINUX = frozenset(
    str(Path(os.sep) / nombre) for nombre in ("proc", "sys", "dev", "run")
)

# Windows: enlaces de carpeta (junction / symlink). Seguirlos provoca bucles
# y hace que el mismo contenido se cuente dos veces.
_ETIQUETAS_ENLACE = frozenset({0xA0000003, 0xA000000C})
# Windows: archivos "solo en la nube" (OneDrive). No ocupan disco, y abrirlos
# los descargaría, así que se dejan fuera.
_ATRIBUTOS_NUBE = 0x1000 | 0x40000 | 0x400000

# progreso(archivos_contados, carpeta_actual)
Progreso = Callable[[int, str], None]


def escanear(
    raiz: str | os.PathLike,
    progreso: Progreso | None = None,
    cancelar: threading.Event | None = None,
    avisar_cada: int = 1000,
) -> ResultadoEscaneo:
    """Recorre 'raiz' completa y devuelve un ResultadoEscaneo.

    Los errores de permisos y los archivos en uso se cuentan en
    'resultado.errores' y se ignoran: nunca detienen el recorrido.
    """
    raiz = Path(raiz).expanduser().resolve()
    if not raiz.is_dir():
        raise NotADirectoryError(f"No es una carpeta: {raiz}")

    resultado = ResultadoEscaneo(raiz=raiz)
    orden: list[tuple[str, str | None]] = []  # (carpeta, carpeta padre)
    # Pila en lugar de recursión: evita el límite de profundidad de Python.
    pila: list[tuple[str, str | None, bool]] = [(str(raiz), None, False)]

    while pila:
        if cancelar is not None and cancelar.is_set():
            resultado.cancelado = True
            break

        carpeta, padre, dentro_regenerable = pila.pop()
        orden.append((carpeta, padre))
        resultado.tamano_carpetas[carpeta] = 0
        resultado.archivos_por_carpeta[carpeta] = 0
        resultado.tamano_directo[carpeta] = 0
        if padre is not None:
            resultado.hijos[padre].append(carpeta)

        try:
            iterador = os.scandir(carpeta)
        except OSError:
            resultado.errores += 1
            continue

        with iterador:
            while True:
                try:
                    entrada = next(iterador)
                except StopIteration:
                    break
                except OSError:
                    resultado.errores += 1
                    break

                try:
                    if entrada.is_symlink():
                        continue
                    info = entrada.stat(follow_symlinks=False)

                    if entrada.is_dir(follow_symlinks=False):
                        if getattr(info, "st_reparse_tag", 0) in _ETIQUETAS_ENLACE:
                            continue
                        if entrada.path in _VIRTUALES_LINUX:
                            continue
                        es_regenerable = (
                            not dentro_regenerable
                            and entrada.name in CARPETAS_REGENERABLES
                        )
                        if es_regenerable:
                            resultado.rutas_regenerables.append(entrada.path)
                        pila.append(
                            (entrada.path, carpeta, dentro_regenerable or es_regenerable)
                        )

                    elif entrada.is_file(follow_symlinks=False):
                        if getattr(info, "st_file_attributes", 0) & _ATRIBUTOS_NUBE:
                            resultado.bytes_en_nube += info.st_size
                            continue
                        resultado.archivos.append(
                            InfoArchivo(
                                ruta=entrada.path,
                                tamano=info.st_size,
                                modificado=info.st_mtime,
                                accedido=info.st_atime,
                                en_regenerable=dentro_regenerable,
                            )
                        )
                        resultado.tamano_carpetas[carpeta] += info.st_size
                        resultado.tamano_directo[carpeta] += info.st_size
                        resultado.archivos_por_carpeta[carpeta] += 1

                        if progreso and len(resultado.archivos) % avisar_cada == 0:
                            progreso(len(resultado.archivos), carpeta)
                except OSError:
                    resultado.errores += 1

    # Cada carpeta aparece en 'orden' después de su padre; recorriéndolo al
    # revés, el tamaño de cada hija ya está completo cuando se suma al padre.
    for carpeta, padre in reversed(orden):
        if padre is not None:
            resultado.tamano_carpetas[padre] += resultado.tamano_carpetas[carpeta]
            resultado.archivos_por_carpeta[padre] += resultado.archivos_por_carpeta[carpeta]

    if progreso:
        progreso(len(resultado.archivos), str(raiz))
    return resultado


def archivos_mas_pesados(resultado: ResultadoEscaneo, cantidad: int = 50) -> list[InfoArchivo]:
    """Los 'cantidad' archivos más grandes, de mayor a menor."""
    return heapq.nlargest(cantidad, resultado.archivos, key=lambda a: a.tamano)
