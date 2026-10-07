"""Permisos de administrador, solo para leer la salud de los discos.

El programa funciona siempre con los permisos normales del usuario. La única
excepción es la lectura SMART: el sistema exige administrador para hablar
directamente con algunos discos. Cuando hace falta, y solo si el usuario lo
acepta, se lanza UNA lectura con permisos elevados:

    <este programa> cli salud volcar <archivo>

Ese proceso elevado ejecuta smartctl en modo lectura, escribe el resultado en
un archivo y termina. La aplicación sigue sin privilegios y lee ese archivo.
En Windows aparece el aviso habitual de Control de cuentas de usuario; en
Linux, el de contraseña de pkexec.
"""

from __future__ import annotations

import json
import os
import secrets
import subprocess
from collections.abc import Callable
from pathlib import Path

from core.historial import carpeta_de_datos
from core.programador import comando_del_programa
from core.salud import ErrorSalud, SaludDisco, Umbrales, interpretar, listar_discos, leer_crudo
from utils.sistema import WINDOWS, sistema_actual

EXPLICACION = (
    "Para leer la salud de este disco el sistema exige permisos de administrador.\n\n"
    "Qué va a pasar si continúas:\n"
    "  • El sistema te pedirá permiso (o tu contraseña).\n"
    "  • Se hará una única lectura de los datos SMART de tus discos.\n"
    "  • No se escribe ni se modifica nada en ellos.\n"
    "  • La aplicación seguirá funcionando sin permisos de administrador.\n\n"
    "Si no quieres concederlos, cancela: el resto del programa funciona igual."
)

# lanzar(comando) -> código de salida del proceso elevado
Lanzador = Callable[[list[str]], int]


def volcar_salud(destino: str | os.PathLike, ejecutar=None) -> int:
    """Lo ejecuta el proceso elevado: guarda en 'destino' la respuesta de smartctl de cada disco.

    El archivo se crea en modo exclusivo: si ya existe, no se toca. Así un
    proceso con privilegios nunca sobrescribe un archivo que no creó él.
    """
    datos = [{"nombre": disco["name"], "datos": leer_crudo(disco["name"], disco["type"], ejecutar)}
             for disco in listar_discos(ejecutar)]
    with open(destino, "x", encoding="utf-8") as archivo:
        json.dump(datos, archivo)
    return len(datos)


def _lanzar_windows(comando: list[str]) -> int:
    import ctypes
    from ctypes import wintypes

    class InfoEjecucion(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD), ("fMask", wintypes.ULONG), ("hwnd", wintypes.HWND),
            ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR),
            ("lpParameters", wintypes.LPCWSTR), ("lpDirectory", wintypes.LPCWSTR),
            ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE), ("lpIDList", wintypes.LPVOID),
            ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY), ("dwHotKey", wintypes.DWORD),
            ("hIcon", wintypes.HANDLE), ("hProcess", wintypes.HANDLE),
        ]

    info = InfoEjecucion()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x00000040          # SEE_MASK_NOCLOSEPROCESS: para poder esperar a que termine
    info.lpVerb = "runas"            # "ejecutar como administrador": muestra el aviso de Windows
    info.lpFile = comando[0]
    info.lpParameters = subprocess.list2cmdline(comando[1:])
    info.nShow = 0                   # sin ventana
    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info)):
        raise ErrorSalud("No se concedieron los permisos de administrador.")
    nucleo = ctypes.windll.kernel32
    nucleo.WaitForSingleObject(info.hProcess, 120_000)
    codigo = wintypes.DWORD()
    nucleo.GetExitCodeProcess(info.hProcess, ctypes.byref(codigo))
    nucleo.CloseHandle(info.hProcess)
    return codigo.value


def _lanzar_linux(comando: list[str]) -> int:
    try:
        return subprocess.run(["pkexec", *comando], timeout=180).returncode
    except FileNotFoundError:
        raise ErrorSalud(
            "No se encontró 'pkexec' para pedir permisos. Abre una terminal y ejecuta el "
            "programa con sudo, por ejemplo:  sudo analizador-disco cli salud") from None
    except subprocess.TimeoutExpired:
        raise ErrorSalud("Se agotó el tiempo esperando los permisos.") from None


def leer_salud_con_permisos(
    umbrales: Umbrales | None = None, lanzar: Lanzador | None = None
) -> list[SaludDisco]:
    """Lee la salud de todos los discos mediante un proceso con permisos de administrador."""
    carpeta = carpeta_de_datos()
    carpeta.mkdir(parents=True, exist_ok=True)
    # Nombre imposible de adivinar: nadie puede preparar ese archivo de antemano.
    destino = carpeta / f"salud-{secrets.token_hex(12)}.json"
    comando = [*comando_del_programa(), "cli", "salud", "volcar", str(destino)]
    try:
        lanzador = lanzar or (_lanzar_windows if sistema_actual() == WINDOWS else _lanzar_linux)
        lanzador(comando)
        if not destino.exists():
            raise ErrorSalud("No se concedieron los permisos, o la lectura no pudo completarse.")
        datos = json.loads(destino.read_text(encoding="utf-8"))
    except (OSError, ValueError) as problema:
        raise ErrorSalud(f"No se pudo leer el resultado: {problema}") from None
    finally:
        try:
            Path(destino).unlink()
        except OSError:
            pass
    return [interpretar(disco["datos"], disco["nombre"], umbrales) for disco in datos]
