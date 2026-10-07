"""Mover archivos o carpetas a otra carpeta o disco.

Junto con core/limpieza.py, es lo único del programa que modifica el disco.
Sigue las mismas reglas: por defecto solo simula, comprueba cada elemento
justo antes de tocarlo y un fallo en uno no detiene los demás. Además:
- Nunca sobrescribe: si en el destino ya hay algo con ese nombre, se guarda
  como "nombre (1).ext".
- Antes de empezar comprueba que en el destino hay espacio suficiente.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from core import registro
from core.limpieza import motivo_de_rechazo
from core.modelos import ElementoBasura
from utils.formato import tamano_legible
from utils.seguridad import dentro_de_carpeta_critica


@dataclass
class ResultadoMovimiento:
    simulacion: bool
    destino: Path
    # (elemento, ruta nueva)
    movidos: list[tuple[ElementoBasura, Path]] = field(default_factory=list)
    # (elemento, motivo por el que no se movió)
    omitidos: list[tuple[ElementoBasura, str]] = field(default_factory=list)
    bytes_movidos: int = 0


def validar_destino(destino: str | os.PathLike) -> Path:
    """Devuelve el destino como ruta absoluta, o lanza ValueError si no sirve."""
    carpeta = Path(destino).expanduser()
    if not str(destino).strip() or not carpeta.is_dir():
        raise ValueError(f"La carpeta de destino no existe: {destino}")
    carpeta = carpeta.resolve()
    if dentro_de_carpeta_critica(carpeta):
        raise ValueError(f"No se puede mover nada a una carpeta del sistema: {carpeta}")
    return carpeta


def _ruta_libre(destino: Path, nombre: str, reservadas: set[str]) -> Path:
    """Primer nombre que no existe en el destino: foto.jpg, foto (1).jpg, foto (2).jpg..."""
    base, extension = os.path.splitext(nombre)
    candidata = destino / nombre
    numero = 0
    while os.path.lexists(candidata) or os.path.normcase(str(candidata)) in reservadas:
        numero += 1
        candidata = destino / f"{base} ({numero}){extension}"
    reservadas.add(os.path.normcase(str(candidata)))
    return candidata


def _mismo_disco(ruta: Path, destino: Path) -> bool:
    try:
        return os.stat(ruta).st_dev == os.stat(destino).st_dev
    except OSError:
        return False


def mover(
    elementos: Iterable[ElementoBasura],
    destino: str | os.PathLike,
    simulacion: bool = True,
) -> ResultadoMovimiento:
    """Mueve los elementos a 'destino' (o solo simula que lo hace).

    Lanza ValueError si el destino no es válido o no tiene espacio suficiente.
    En simulación, 'movidos' indica dónde quedaría cada elemento.
    """
    carpeta = validar_destino(destino)
    resultado = ResultadoMovimiento(simulacion=simulacion, destino=carpeta)
    reservadas: set[str] = set()
    plan: list[tuple[ElementoBasura, Path]] = []

    for elemento in elementos:
        motivo = motivo_de_rechazo(elemento, para_papelera=False)
        if motivo is None:
            origen = elemento.ruta.resolve()
            if origen.parent == carpeta:
                motivo = "ya está en la carpeta de destino"
            elif carpeta == origen or carpeta.is_relative_to(origen):
                motivo = "no se puede mover una carpeta dentro de sí misma"
        if motivo:
            resultado.omitidos.append((elemento, motivo))
        else:
            plan.append((elemento, _ruta_libre(carpeta, elemento.ruta.name, reservadas)))

    # Mover dentro del mismo disco no gasta espacio; a otro disco, sí.
    necesario = sum(e.tamano for e, _ in plan if not _mismo_disco(e.ruta, carpeta))
    libre = shutil.disk_usage(carpeta).free
    if necesario > libre:
        raise ValueError(
            f"No hay espacio suficiente en el destino: hacen falta "
            f"{tamano_legible(necesario)} y hay {tamano_legible(libre)} libres.")

    for elemento, nueva in plan:
        if simulacion:
            resultado.movidos.append((elemento, nueva))
            resultado.bytes_movidos += elemento.tamano
            continue

        try:
            shutil.move(str(elemento.ruta), str(nueva))
        except Exception:
            # En uso, sin permisos, disco desconectado... Se sigue con el resto.
            pass

        if not os.path.lexists(elemento.ruta):
            resultado.movidos.append((elemento, nueva))
            resultado.bytes_movidos += elemento.tamano
        elif not os.path.lexists(nueva):
            resultado.omitidos.append((elemento, "está en uso o no hay permisos"))
        elif nueva.is_file():
            # Copia de un archivo interrumpida: el original está intacto, así
            # que el trozo copiado (que creamos nosotros) se puede retirar.
            try:
                os.remove(nueva)
            except OSError:
                pass
            resultado.omitidos.append((elemento, "está en uso o no hay permisos"))
        else:
            # Carpeta movida a medias: parte está ya en el destino y parte sigue
            # en el origen. No se borra nada de ningún lado.
            resultado.omitidos.append(
                (elemento, f"se movió solo en parte (había archivos en uso); revisa {nueva}"))

    accion = "simulación de mover" if simulacion else "mover"
    registro.anotar_lote(
        [(accion, "hecho", e.tamano, e.ruta, f"a {nueva}") for e, nueva in resultado.movidos]
        + [(accion, "omitido", e.tamano, e.ruta, motivo) for e, motivo in resultado.omitidos])
    return resultado
