"""Listados de archivos con orden y filtros.

Trabaja sobre un escaneo ya hecho: ordenar o filtrar de otra forma no
obliga a recorrer el disco de nuevo.
"""

from __future__ import annotations

import heapq
import os
from collections.abc import Iterable

from core.arbol import preparar_indice
from core.modelos import InfoArchivo, ResultadoEscaneo
from core.tipos import TIPOS, clasificar

# Campos por los que se puede ordenar.
ORDENES = {
    "tamano": lambda archivo: archivo.tamano,
    "modificado": lambda archivo: archivo.modificado,
    "accedido": lambda archivo: archivo.accedido,
}


def listar_archivos(
    resultado: ResultadoEscaneo,
    orden: str = "tamano",
    descendente: bool = True,
    tipos: Iterable[str] | None = None,
    tamano_minimo: int = 0,
    limite: int | None = 50,
) -> list[InfoArchivo]:
    """Archivos del escaneo, filtrados y ordenados.

    - orden: 'tamano', 'modificado' (fecha de modificación) o 'accedido'
      (fecha de último acceso).
    - descendente: True = primero los más grandes / más recientes.
    - tipos: si se indica, solo esos tipos ('videos', 'imagenes'...).
    - tamano_minimo: en bytes.
    - limite: cuántos devolver; None = todos.
    Lanza ValueError si el orden o algún tipo no existe.
    """
    if orden not in ORDENES:
        raise ValueError(f"Orden no válido: {orden}. Opciones: {', '.join(ORDENES)}")
    tipos = set(tipos or ())
    desconocidos = tipos - set(TIPOS)
    if desconocidos:
        raise ValueError(
            f"Tipo no válido: {', '.join(sorted(desconocidos))}. Opciones: {', '.join(TIPOS)}")

    candidatos = (
        archivo for archivo in resultado.archivos
        if archivo.tamano >= tamano_minimo and (not tipos or clasificar(archivo.ruta) in tipos)
    )
    clave = ORDENES[orden]
    if limite is None:
        return sorted(candidatos, key=clave, reverse=descendente)
    # nlargest / nsmallest evitan ordenar millones de archivos para mostrar 50.
    elegir = heapq.nlargest if descendente else heapq.nsmallest
    return elegir(max(limite, 0), candidatos, key=clave)


def buscar_archivo(resultado: ResultadoEscaneo, ruta: str) -> InfoArchivo | None:
    """Devuelve el archivo del escaneo con esa ruta exacta, o None si no pertenece a él.

    Las interfaces lo usan para aceptar solo archivos que el escaneo encontró,
    nunca una ruta cualquiera.
    """
    indice = preparar_indice(resultado)
    for archivo in indice.archivos.get(os.path.dirname(ruta), ()):
        if archivo.ruta == ruta:
            return archivo
    return None


def quitar_del_escaneo(resultado: ResultadoEscaneo, rutas: Iterable[str]) -> None:
    """Olvida archivos que ya se movieron o se enviaron a la papelera.

    Así dejan de aparecer en tablas y mapas sin tener que escanear de nuevo.
    Los tamaños acumulados de las carpetas no se recalculan: siguen siendo los
    del último escaneo.
    """
    rutas = set(rutas)
    if not rutas:
        return
    resultado.archivos = [a for a in resultado.archivos if a.ruta not in rutas]
    indice = resultado.indice_arbol
    if indice is not None:
        for ruta in rutas:
            carpeta = os.path.dirname(ruta)
            if carpeta in indice.archivos:
                indice.archivos[carpeta] = [a for a in indice.archivos[carpeta] if a.ruta != ruta]
