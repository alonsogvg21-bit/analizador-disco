"""Búsqueda de archivos duplicados.

Calcular el hash de todos los archivos sería lentísimo, así que se descarta
en tres pasos, del más barato al más caro:
  1. Tamaño: dos archivos de distinto tamaño no pueden ser iguales.
  2. Hash de los primeros 64 KB: descarta casi todos los falsos candidatos.
  3. Hash completo: solo para los que siguen coincidiendo.
"""

from __future__ import annotations

import hashlib
import os
import threading
from collections import defaultdict
from collections.abc import Callable, Iterable
from pathlib import Path

from core.modelos import GrupoDuplicados, InfoArchivo

BYTES_PARCIAL = 64 * 1024
_BLOQUE = 1024 * 1024

# progreso(archivos_revisados, total_candidatos)
Progreso = Callable[[int, int], None]


def hash_archivo(ruta: str | os.PathLike, limite: int | None = None) -> str | None:
    """Hash del archivo (o de sus primeros 'limite' bytes).

    Devuelve None si no se puede leer (en uso, sin permisos, borrado...).
    """
    resumen = hashlib.blake2b(digest_size=20)
    restante = limite
    try:
        with open(ruta, "rb") as archivo:
            while restante is None or restante > 0:
                bloque = archivo.read(_BLOQUE if restante is None else min(_BLOQUE, restante))
                if not bloque:
                    break
                resumen.update(bloque)
                if restante is not None:
                    restante -= len(bloque)
    except OSError:
        return None
    return resumen.hexdigest()


def _quitar_enlaces_duros(archivos: list[InfoArchivo]) -> list[InfoArchivo]:
    """Dos nombres del mismo archivo físico no son duplicados: no gastan espacio extra."""
    unicos: dict[object, InfoArchivo] = {}
    for archivo in archivos:
        try:
            info = os.stat(archivo.ruta)
        except OSError:
            continue
        clave = (info.st_dev, info.st_ino) if info.st_ino else archivo.ruta
        unicos.setdefault(clave, archivo)
    return list(unicos.values())


def buscar_duplicados(
    archivos: Iterable[InfoArchivo],
    tamano_minimo: int = 1,
    progreso: Progreso | None = None,
    cancelar: threading.Event | None = None,
) -> list[GrupoDuplicados]:
    """Grupos de archivos idénticos, ordenados por espacio recuperable.

    Se ignoran los archivos vacíos y los que están dentro de carpetas
    regenerables (node_modules está lleno de copias legítimas).
    """
    tamano_minimo = max(tamano_minimo, 1)

    # Paso 1: agrupar por tamaño.
    por_tamano: dict[int, list[InfoArchivo]] = defaultdict(list)
    for archivo in archivos:
        if archivo.tamano >= tamano_minimo and not archivo.en_regenerable:
            por_tamano[archivo.tamano].append(archivo)
    candidatos = [grupo for grupo in por_tamano.values() if len(grupo) > 1]

    total = sum(len(grupo) for grupo in candidatos)
    revisados = 0
    grupos: list[GrupoDuplicados] = []

    for grupo in candidatos:
        tamano = grupo[0].tamano

        # Paso 2: hash parcial.
        por_parcial: dict[str, list[InfoArchivo]] = defaultdict(list)
        for archivo in grupo:
            if cancelar is not None and cancelar.is_set():
                return _ordenar(grupos)
            parcial = hash_archivo(archivo.ruta, limite=BYTES_PARCIAL)
            revisados += 1
            if progreso:
                progreso(revisados, total)
            if parcial:
                por_parcial[parcial].append(archivo)

        for parcial, coincidentes in por_parcial.items():
            if len(coincidentes) < 2:
                continue

            # Paso 3: hash completo (si el archivo es pequeño, el parcial ya lo es).
            if tamano <= BYTES_PARCIAL:
                por_hash = {parcial: coincidentes}
            else:
                por_hash = defaultdict(list)
                for archivo in coincidentes:
                    if cancelar is not None and cancelar.is_set():
                        return _ordenar(grupos)
                    completo = hash_archivo(archivo.ruta)
                    if completo:
                        por_hash[completo].append(archivo)

            for valor, iguales in por_hash.items():
                iguales = _quitar_enlaces_duros(iguales)
                if len(iguales) > 1:
                    # El más antiguo va primero: se trata como el original.
                    iguales.sort(key=lambda a: (a.modificado, a.ruta))
                    grupos.append(
                        GrupoDuplicados(valor, tamano, [Path(a.ruta) for a in iguales])
                    )

    return _ordenar(grupos)


def _ordenar(grupos: list[GrupoDuplicados]) -> list[GrupoDuplicados]:
    grupos.sort(key=lambda g: g.espacio_recuperable, reverse=True)
    return grupos
