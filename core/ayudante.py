"""El ayudante: la única parte del programa que puede ejecutarse con privilegios.

La aplicación corre siempre como usuario normal. Cuando hace falta leer un
disco que el sistema solo deja leer a un administrador, y solo si el usuario
lo pide, se lanza este ayudante con permisos elevados:

    main.py --helper <acción> [argumentos]

Como va a ejecutarse con privilegios, está hecho para poder hacer lo mínimo:

- Solo acepta cuatro acciones (ACCIONES). Cualquier otra se rechaza.
- No recibe comandos ni rutas: solo nombres de disco, que se validan con una
  expresión estricta Y deben aparecer en lo que detecta "smartctl --scan".
- Llama a smartctl por su ruta absoluta, con una lista de argumentos, nunca
  a través de un intérprete de comandos.
- Todo es lectura. Las autopruebas las hace el propio disco y no escriben datos.
- Solo imprime JSON. No abre ventanas ni carga la interfaz.
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Callable
from pathlib import Path

from core.modelos import a_dict
from core.salud import (
    TIPOS_DE_PRUEBA, ErrorSalud, SmartctlNoInstalado, interpretar, leer_crudo, listar_discos,
    mandar_autoprueba,
)
from utils.sistema import WINDOWS, sistema_actual

LISTAR = "listar-discos"
LEER = "leer-smart"
INICIAR = "iniciar-autoprueba"
RESULTADO = "resultado-autoprueba"
ACCIONES = (LISTAR, LEER, INICIAR, RESULTADO)

# Nombres de disco admitidos. Nada de espacios, comodines, rutas ni opciones.
# Se comprueban con fullmatch(): con match(), el símbolo $ daría por bueno un
# nombre terminado en salto de línea.
PATRON_LINUX = re.compile(r"^/dev/(sd[a-z]+|nvme[0-9]+(n[0-9]+)?|hd[a-z]+)$")
PATRON_WINDOWS = re.compile(r"^\\\\\.\\PhysicalDrive[0-9]+$")
# En Windows smartctl llama a los discos /dev/sda, /dev/sdb... (sda es
# \\.\PhysicalDrive0, sdb el 1, etc.), y así los devuelve "smartctl --scan".
# Se aceptan las dos formas, que nombran exactamente lo mismo.
PATRON_WINDOWS_SMARTCTL = re.compile(r"^/dev/sd[a-z]+$")

# Nombre que debe tener el archivo de resultado en Windows (lo crea la aplicación).
PATRON_ARCHIVO = re.compile(r"^analizador-disco-[0-9a-f]{32}\.json$")


class AccionNoPermitida(ErrorSalud):
    """Se pidió al ayudante algo que no está en su lista."""


def _letras(numero: int) -> str:
    """0 -> a, 1 -> b, ..., 25 -> z, 26 -> aa (como nombra Linux y smartctl los discos)."""
    texto = ""
    numero += 1
    while numero > 0:
        numero, resto = divmod(numero - 1, 26)
        texto = chr(ord("a") + resto) + texto
    return texto


def validar_disco(nombre: object, sistema: str | None = None) -> str:
    """Devuelve el nombre del disco tal como lo entiende smartctl, o lanza ErrorSalud.

    Esta comprobación es solo de forma; después hay que confirmar que el
    disco existe con comprobar_que_existe().
    """
    sistema = sistema or sistema_actual()
    if not isinstance(nombre, str) or not nombre or len(nombre) > 64:
        raise ErrorSalud("El nombre del disco no es válido.")
    if sistema == WINDOWS:
        if PATRON_WINDOWS.fullmatch(nombre):
            return "/dev/sd" + _letras(int(nombre.rsplit("PhysicalDrive", 1)[1]))
        if PATRON_WINDOWS_SMARTCTL.fullmatch(nombre):
            return nombre
    elif PATRON_LINUX.fullmatch(nombre):
        return nombre
    raise ErrorSalud("El nombre del disco no es válido.")


def comprobar_que_existe(disco: str, ejecutar=None) -> str:
    """Confirma que smartctl detecta ese disco y devuelve el tipo (-d) que le corresponde."""
    for detectado in listar_discos(ejecutar):
        if detectado["name"] == disco:
            return detectado["type"]
    raise ErrorSalud("Ese disco no está entre los que detecta smartctl.")


def ejecutar_accion(accion: str, argumentos: list[str], ejecutar=None, sistema: str | None = None) -> object:
    """Hace una de las cuatro acciones permitidas y devuelve datos listos para JSON."""
    if accion not in ACCIONES:
        raise AccionNoPermitida(f"Acción no permitida: {accion!r}.")

    if accion == LISTAR:
        if argumentos:
            raise ErrorSalud("Esta acción no admite argumentos.")
        return listar_discos(ejecutar)

    if accion == LEER:
        # Varios discos en una sola llamada: así basta con pedir permiso una vez.
        if not 1 <= len(argumentos) <= 64:
            raise ErrorSalud("Indica entre 1 y 64 discos.")
        discos = [validar_disco(nombre, sistema) for nombre in argumentos]
        tipos = {d["name"]: d["type"] for d in listar_discos(ejecutar)}
        for disco in discos:
            if disco not in tipos:
                raise ErrorSalud("Ese disco no está entre los que detecta smartctl.")
        return {disco: leer_crudo(disco, tipos[disco], ejecutar) for disco in dict.fromkeys(discos)}

    if accion == INICIAR:
        if len(argumentos) != 2 or argumentos[1] not in TIPOS_DE_PRUEBA:
            raise ErrorSalud("Uso: iniciar-autoprueba <disco> <corta|larga>")
        disco = validar_disco(argumentos[0], sistema)
        return {"mensaje": mandar_autoprueba(disco, comprobar_que_existe(disco, ejecutar),
                                             argumentos[1], ejecutar)}

    # RESULTADO
    if len(argumentos) != 1:
        raise ErrorSalud("Uso: resultado-autoprueba <disco>")
    disco = validar_disco(argumentos[0], sistema)
    salud = interpretar(leer_crudo(disco, comprobar_que_existe(disco, ejecutar), ejecutar), disco)
    return {"disco": disco, "autoprueba": a_dict(salud.autoprueba) if salud.autoprueba else None}


def responder(accion: str, argumentos: list[str], ejecutar=None, sistema: str | None = None) -> dict:
    """Ejecuta la acción y envuelve el resultado: {"ok": true, "datos": ...} o {"ok": false, "error": ...}."""
    try:
        return {"ok": True, "datos": ejecutar_accion(accion, argumentos, ejecutar, sistema)}
    except SmartctlNoInstalado as problema:
        return {"ok": False, "motivo": "sin-smartctl", "error": str(problema)}
    except AccionNoPermitida as problema:
        return {"ok": False, "motivo": "accion-no-permitida", "error": str(problema)}
    except ErrorSalud as problema:
        return {"ok": False, "motivo": "error", "error": str(problema)}
    except Exception as problema:  # nunca debe salir una traza: solo JSON
        return {"ok": False, "motivo": "error", "error": f"Error inesperado: {type(problema).__name__}"}


def _escribir_en(archivo: str, texto: str) -> bool:
    """Escribe el resultado en el archivo que preparó la aplicación (solo Windows).

    El ayudante puede estar ejecutándose como administrador, así que NO acepta
    una ruta cualquiera: el archivo debe llamarse exactamente como los que
    crea la aplicación, existir ya, estar vacío y ser un archivo normal (ni
    enlace ni archivo con varios nombres). Así solo puede rellenar el archivo
    vacío que le dejaron, y nunca crear ni sobrescribir otra cosa.
    """
    ruta = Path(archivo)
    try:
        if not ruta.is_absolute() or not PATRON_ARCHIVO.fullmatch(ruta.name):
            return False
        info = os.lstat(ruta)
        import stat
        if not stat.S_ISREG(info.st_mode) or info.st_size != 0 or info.st_nlink != 1:
            return False
        if getattr(info, "st_file_attributes", 0) & 0x400:   # punto de reanálisis (enlace)
            return False
        with open(ruta, "r+", encoding="utf-8") as salida:   # "r+" nunca crea el archivo
            salida.write(texto)
        return True
    except OSError:
        return False


def main_ayudante(argumentos: list[str], escribir: Callable[[str], object] | None = None) -> int:
    """Punto de entrada de "main.py --helper ...". Devuelve el código de salida.

    Uso:  --helper [--salida ARCHIVO] <acción> [argumentos]
    Códigos: 0 correcto, 1 la acción falló, 2 petición no válida.
    """
    escribir = escribir or (lambda texto: (sys.stdout.write(texto + "\n"), sys.stdout.flush()))
    archivo = None
    if len(argumentos) >= 2 and argumentos[0] == "--salida":
        archivo, argumentos = argumentos[1], argumentos[2:]

    if not argumentos:
        respuesta = {"ok": False, "motivo": "accion-no-permitida", "error": "Falta la acción."}
    else:
        respuesta = responder(argumentos[0], argumentos[1:])
    # Solo ASCII (los acentos van como \uXXXX): así la salida se lee bien sea cual sea
    # la codificación de la consola o del proceso que lanzó al ayudante.
    texto = json.dumps(respuesta, ensure_ascii=True)

    if archivo is not None:
        if not _escribir_en(archivo, texto):
            return 2
    else:
        escribir(texto)
    if respuesta["ok"]:
        return 0
    return 2 if respuesta.get("motivo") == "accion-no-permitida" else 1
