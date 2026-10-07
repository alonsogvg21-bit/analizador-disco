"""Registro de acciones: qué se movió o se envió a la papelera, y cuándo.

Se guarda en la carpeta de datos del usuario (AppData en Windows,
~/.local/share en Linux) como texto plano, una línea por elemento. Sirve para
saber después qué hizo el programa. Nunca sale del equipo.

Escribir el registro jamás debe impedir la acción ni romper el programa: si
el archivo no se puede escribir, simplemente no se anota.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from core.historial import carpeta_de_datos

TAMANO_MAXIMO = 2 * 1024 * 1024   # al superarlo, el archivo actual pasa a ser "registro.log.1"
NOMBRE = "registro.log"


def ruta_registro() -> Path:
    return carpeta_de_datos() / NOMBRE


def _linea(accion: str, resultado: str, tamano: int = 0, ruta: object = "", detalle: str = "") -> str:
    campos = (f"{datetime.now():%Y-%m-%d %H:%M:%S}", accion, resultado, str(tamano), str(ruta), detalle)
    # Tabuladores y saltos de línea dentro de un campo romperían el formato.
    return "\t".join(campo.replace("\t", " ").replace("\n", " ").replace("\r", " ") for campo in campos)


def anotar_lote(lineas: Iterable[tuple]) -> None:
    """Añade varias líneas de una vez. Cada una: (acción, resultado, tamaño, ruta, detalle)."""
    texto = "".join(_linea(*linea) + "\n" for linea in lineas)
    if not texto:
        return
    try:
        archivo = ruta_registro()
        archivo.parent.mkdir(parents=True, exist_ok=True)
        if archivo.exists() and archivo.stat().st_size > TAMANO_MAXIMO:
            archivo.replace(archivo.with_name(NOMBRE + ".1"))
        with archivo.open("a", encoding="utf-8") as salida:
            salida.write(texto)
    except OSError:
        pass


def anotar(accion: str, resultado: str, tamano: int = 0, ruta: object = "", detalle: str = "") -> None:
    anotar_lote([(accion, resultado, tamano, ruta, detalle)])


def ultimas_lineas(cantidad: int = 200) -> list[str]:
    try:
        return ruta_registro().read_text(encoding="utf-8").splitlines()[-cantidad:]
    except OSError:
        return []
