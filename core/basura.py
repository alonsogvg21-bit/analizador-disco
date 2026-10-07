"""Detección de archivos basura por categorías.

Este módulo solo DETECTA y mide. No borra nada: devuelve una lista de
candidatos para que el usuario decida.
"""

from __future__ import annotations

import heapq
import os
import threading
import time
from collections.abc import Callable, Iterable
from pathlib import Path

from core.carpetas import info_carpeta
from core.duplicados import buscar_duplicados
from core.modelos import CategoriaBasura, ElementoBasura, ResultadoEscaneo
from core.reglas import reglas_del_sistema
from core.reglas.base import CACHE, DESCARGAS, LOGS, PAPELERA, TEMPORALES, ReglaUbicacion
from utils.seguridad import carpetas_personales, en_carpeta_personal, es_ruta_protegida

REGENERABLES = "regenerables"
DUPLICADOS = "duplicados"
ANTIGUOS = "antiguos"

MB = 1024 * 1024
# Un temporal modificado hace poco probablemente lo está usando un programa abierto.
HORAS_TEMPORAL_RECIENTE = 24
MAX_ANTIGUOS = 500

# clave -> (nombre visible, explicación breve). El orden es el de presentación.
CATEGORIAS: dict[str, tuple[str, str]] = {
    TEMPORALES: ("Archivos temporales",
                 "Archivos que los programas crean mientras trabajan y que ya no necesitan."),
    CACHE: ("Caché",
            "Copias que guardan navegadores y aplicaciones para ir más rápido. "
            "Se vuelven a crear solas."),
    PAPELERA: ("Papelera",
               "Archivos que ya borraste pero que siguen ocupando espacio hasta vaciarla."),
    REGENERABLES: ("Carpetas regenerables",
                   "Carpetas de proyectos (node_modules, __pycache__, .gradle, .venv) que se "
                   "pueden volver a crear con un comando."),
    DUPLICADOS: ("Duplicados",
                 "Copias idénticas de un mismo archivo. Se conserva la más antigua."),
    ANTIGUOS: ("Sin abrir hace más de un año",
               "Archivos grandes que no se usan desde hace mucho. La fecha es aproximada: "
               "revísalos antes de borrar."),
    DESCARGAS: ("Descargas",
                "Tu carpeta de descargas. Solo se muestra cuánto ocupa."),
    LOGS: ("Registros del sistema",
           "Historial que guarda el sistema. Solo se muestra cuánto ocupa."),
}


def medir_ruta(ruta: str | os.PathLike) -> tuple[int, int]:
    """Tamaño total y número de archivos de un archivo o carpeta.

    No sigue enlaces e ignora lo que no se puede leer.
    """
    tamano, cantidad, _ = _medir(ruta)
    return tamano, cantidad


def _medir(ruta: str | os.PathLike) -> tuple[int, int, float]:
    """Como medir_ruta, pero además devuelve la fecha de modificación más reciente."""
    try:
        info = os.stat(ruta, follow_symlinks=False)
    except OSError:
        return 0, 0, 0.0
    if not os.path.isdir(ruta) or os.path.islink(ruta):
        return info.st_size, 1, info.st_mtime

    tamano = cantidad = 0
    reciente = info.st_mtime
    pila = [os.fspath(ruta)]
    while pila:
        try:
            with os.scandir(pila.pop()) as entradas:
                for entrada in entradas:
                    try:
                        if entrada.is_symlink():
                            continue
                        if entrada.is_dir(follow_symlinks=False):
                            pila.append(entrada.path)
                        else:
                            datos = entrada.stat(follow_symlinks=False)
                            tamano += datos.st_size
                            cantidad += 1
                            reciente = max(reciente, datos.st_mtime)
                    except OSError:
                        continue
        except OSError:
            continue
    return tamano, cantidad, reciente


def elementos_de_regla(regla: ReglaUbicacion) -> list[ElementoBasura]:
    """Convierte una ubicación conocida en elementos de basura.

    - Limpiable: un elemento por cada archivo o carpeta de primer nivel,
      para poder seleccionarlos uno a uno.
    - Solo informativa: un único elemento con el tamaño total.
    """
    if not regla.ruta.is_dir():
        return []

    detalle = f"{regla.nombre}. {regla.nota}".strip() if regla.nota else regla.nombre

    if not regla.limpiable:
        tamano, _ = medir_ruta(regla.ruta)
        if tamano == 0:
            return []
        return [ElementoBasura(regla.ruta, tamano, regla.categoria,
                               es_carpeta=True, limpiable=False, detalle=detalle)]

    elementos: list[ElementoBasura] = []
    try:
        entradas = list(os.scandir(regla.ruta))
    except OSError:
        return []
    limite_reciente = time.time() - HORAS_TEMPORAL_RECIENTE * 3600
    for entrada in entradas:
        tamano, _, modificado = _medir(entrada.path)
        if tamano == 0:
            continue
        try:
            es_carpeta = entrada.is_dir(follow_symlinks=False)
        except OSError:
            continue
        limpiable = not es_ruta_protegida(entrada.path)
        detalle_elemento = detalle
        if regla.categoria == TEMPORALES and modificado > limite_reciente:
            limpiable = False
            detalle_elemento = (f"{regla.nombre}. Modificado en las últimas "
                                f"{HORAS_TEMPORAL_RECIENTE} horas: puede estar en uso.")
        elementos.append(ElementoBasura(
            Path(entrada.path), tamano, regla.categoria, es_carpeta=es_carpeta,
            limpiable=limpiable, detalle=detalle_elemento,
        ))
    elementos.sort(key=lambda e: e.tamano, reverse=True)
    return elementos


def carpetas_regenerables(resultado: ResultadoEscaneo) -> list[ElementoBasura]:
    """node_modules, __pycache__, .gradle y .venv encontradas en el escaneo."""
    elementos = []
    for clave in resultado.rutas_regenerables:
        carpeta = info_carpeta(resultado, clave)
        if carpeta.tamano == 0:
            continue
        elementos.append(ElementoBasura(
            carpeta.ruta, carpeta.tamano, REGENERABLES, es_carpeta=True,
            limpiable=not es_ruta_protegida(carpeta.ruta),
            detalle=f"{carpeta.num_archivos} archivos",
        ))
    elementos.sort(key=lambda e: e.tamano, reverse=True)
    return elementos


def archivos_antiguos(
    resultado: ResultadoEscaneo,
    dias: int = 365,
    tamano_minimo: int = MB,
    maximo: int = MAX_ANTIGUOS,
    ahora: float | None = None,
) -> list[ElementoBasura]:
    """Archivos sin usar desde hace más de 'dias' días, los más grandes primero.

    Windows a menudo no actualiza la fecha de último acceso, así que se usa la
    más reciente entre acceso y modificación. Es una aproximación.
    """
    limite = (ahora if ahora is not None else time.time()) - dias * 86400
    candidatos = (
        a for a in resultado.archivos
        if a.tamano >= tamano_minimo and not a.en_regenerable and a.ultimo_uso < limite
    )
    from utils.formato import fecha_legible

    return [
        ElementoBasura(
            a.path, a.tamano, ANTIGUOS, limpiable=not es_ruta_protegida(a.ruta),
            detalle=f"Último uso: {fecha_legible(a.ultimo_uso)}",
        )
        for a in heapq.nlargest(maximo, candidatos, key=lambda a: a.tamano)
    ]


def elementos_duplicados(
    resultado: ResultadoEscaneo,
    tamano_minimo: int = MB,
    progreso: Callable[[int, int], None] | None = None,
    cancelar: threading.Event | None = None,
) -> list[ElementoBasura]:
    """Las copias sobrantes de cada grupo de duplicados (nunca el original)."""
    elementos = []
    for grupo in buscar_duplicados(resultado.archivos, tamano_minimo, progreso, cancelar):
        original, *copias = grupo.archivos
        for copia in copias:
            elementos.append(ElementoBasura(
                copia, grupo.tamano, DUPLICADOS, limpiable=not es_ruta_protegida(copia),
                detalle=f"Copia de {original}",
            ))
    return elementos


def _dentro_de_alguna(ruta: Path, carpetas: list[str]) -> bool:
    texto = os.path.normcase(str(ruta))
    return any(texto == c or texto.startswith(c + os.sep) for c in carpetas)


def detectar_basura(
    resultado: ResultadoEscaneo | None = None,
    reglas: Iterable[ReglaUbicacion] | None = None,
    dias_antiguedad: int = 365,
    tamano_minimo_antiguos: int = MB,
    tamano_minimo_duplicados: int = MB,
    incluir_duplicados: bool = True,
    progreso: Callable[[int, int], None] | None = None,
    cancelar: threading.Event | None = None,
    personales: Iterable[Path] | None = None,
) -> list[CategoriaBasura]:
    """Reúne todas las categorías de basura.

    - Las ubicaciones conocidas (temporales, caché, papelera...) se miden
      siempre, estén o no dentro de la carpeta escaneada.
    - Regenerables, duplicados y antiguos salen de 'resultado'; si no se pasa
      un escaneo, esas categorías quedan vacías.
    Un mismo archivo nunca aparece en dos categorías, para no contar dos veces
    el espacio que se liberaría.
    Nada que esté dentro de Documentos, Escritorio o Imágenes se sugiere como
    basura ('personales' permite indicar otras carpetas en las pruebas).
    """
    reglas = list(reglas_del_sistema() if reglas is None else reglas)
    categorias = {
        clave: CategoriaBasura(clave, nombre, descripcion)
        for clave, (nombre, descripcion) in CATEGORIAS.items()
    }

    for regla in reglas:
        categorias[regla.categoria].elementos.extend(elementos_de_regla(regla))

    if resultado is not None:
        # Lo que ya está cubierto por una ubicación limpiable no se repite.
        # Las informativas (como Descargas) no cuentan: dentro de ellas sí
        # interesa encontrar duplicados y archivos antiguos.
        ubicaciones = [os.path.normcase(str(r.ruta)) for r in reglas if r.limpiable]
        vistos: set[str] = set()
        protegidas = list(carpetas_personales() if personales is None else personales)

        def agregar(clave: str, elementos: list[ElementoBasura]) -> None:
            for elemento in elementos:
                texto = os.path.normcase(str(elemento.ruta))
                if texto in vistos or _dentro_de_alguna(elemento.ruta, ubicaciones):
                    continue
                if protegidas and en_carpeta_personal(elemento.ruta, protegidas):
                    continue  # archivos personales: nunca se sugieren como basura
                vistos.add(texto)
                categorias[clave].elementos.append(elemento)

        agregar(REGENERABLES, carpetas_regenerables(resultado))
        if incluir_duplicados:
            agregar(DUPLICADOS, elementos_duplicados(
                resultado, tamano_minimo_duplicados, progreso, cancelar))
        agregar(ANTIGUOS, archivos_antiguos(resultado, dias_antiguedad, tamano_minimo_antiguos))

    return list(categorias.values())
