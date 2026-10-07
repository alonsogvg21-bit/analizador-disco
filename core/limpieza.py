"""Limpieza segura. Es el ÚNICO módulo del programa que modifica el disco.

Reglas que se cumplen aquí, pase lo que pase en las interfaces:
- Por defecto solo simula (simulacion=True).
- Nunca borra definitivamente: envía a la papelera con send2trash.
- Vuelve a comprobar cada elemento justo antes de tocarlo (protegido,
  informativo, inexistente, enlace) aunque ya se comprobara al detectarlo.
- Un archivo en uso o sin permisos se omite y se sigue con el siguiente.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass, field

from send2trash import send2trash

from core import registro
from core.basura import medir_ruta
from core.modelos import ElementoBasura
from utils.red import es_ruta_de_red
from utils.seguridad import es_ruta_protegida


# Por encima de este tamaño total, las interfaces piden confirmar dos veces.
UMBRAL_DOBLE_CONFIRMACION = 1024 ** 3   # 1 GB


def requiere_doble_confirmacion(elementos: Iterable[ElementoBasura]) -> bool:
    """True si la acción afecta a más de 1 GB en total."""
    return sum(e.tamano for e in elementos) > UMBRAL_DOBLE_CONFIRMACION


@dataclass
class ResultadoLimpieza:
    simulacion: bool
    enviados: list[ElementoBasura] = field(default_factory=list)
    # (elemento, motivo por el que no se tocó)
    omitidos: list[tuple[ElementoBasura, str]] = field(default_factory=list)
    bytes_liberados: int = 0


def motivo_de_rechazo(elemento: ElementoBasura, para_papelera: bool = True) -> str | None:
    """Devuelve por qué NO se puede tocar un elemento, o None si se puede.

    Vale tanto para enviar a la papelera como para mover (para_papelera=False).
    """
    ruta = elemento.ruta
    if not elemento.limpiable:
        return "es solo informativo"
    if not ruta.is_absolute():
        return "la ruta no es absoluta"
    if es_ruta_protegida(ruta):
        return "está en una carpeta protegida del sistema"
    if not os.path.lexists(ruta):
        return "ya no existe"
    if ruta.is_symlink():
        return "es un enlace, no un archivo real"
    if para_papelera and es_ruta_de_red(ruta):
        # En un disco de red no hay papelera: el sistema lo borraría para siempre.
        return "está en un disco de red, donde no hay papelera (puedes moverlo)"
    return None


def limpiar(elementos: Iterable[ElementoBasura], simulacion: bool = True) -> ResultadoLimpieza:
    """Envía los elementos a la papelera (o solo simula que lo hace).

    En simulación no se toca nada: 'enviados' contiene lo que se habría
    enviado y 'bytes_liberados' lo que se habría liberado.
    """
    resultado = ResultadoLimpieza(simulacion=simulacion)

    for elemento in elementos:
        motivo = motivo_de_rechazo(elemento)
        if motivo:
            resultado.omitidos.append((elemento, motivo))
            continue

        if simulacion:
            resultado.enviados.append(elemento)
            resultado.bytes_liberados += elemento.tamano
            continue

        try:
            send2trash(str(elemento.ruta))
        except Exception:
            # send2trash lanza distintos errores según el sistema (archivo en
            # uso, sin permisos, papelera no disponible en ese disco...).
            # Ninguno debe detener la limpieza del resto.
            pass

        if os.path.lexists(elemento.ruta):
            # Sigue ahí: no se pudo mover, o solo en parte (una carpeta con
            # algún archivo en uso). Se cuenta únicamente lo que sí salió.
            restante, _ = medir_ruta(elemento.ruta)
            resultado.bytes_liberados += max(elemento.tamano - restante, 0)
            resultado.omitidos.append((elemento, "está en uso o no hay permisos"))
        else:
            resultado.enviados.append(elemento)
            resultado.bytes_liberados += elemento.tamano

    # Todo queda anotado en el registro de acciones, también lo que no se tocó.
    accion = "simulación de papelera" if simulacion else "papelera"
    registro.anotar_lote(
        [(accion, "hecho", e.tamano, e.ruta, "") for e in resultado.enviados]
        + [(accion, "omitido", e.tamano, e.ruta, motivo) for e, motivo in resultado.omitidos])
    return resultado
