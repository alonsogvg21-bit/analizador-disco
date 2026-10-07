"""Permisos de administrador: solo para el ayudante de salud, y solo si el usuario lo pide.

La aplicación (escritorio, web y terminal) corre siempre como usuario normal.
Este módulo es el único punto por el que se piden privilegios, y lo único que
lanza con ellos es el ayudante (core/ayudante.py), que solo sabe leer SMART.

- Windows: se lanza el ayudante con el verbo "runas" (aparece el aviso de
  Control de cuentas de usuario) y el resultado se lee de un archivo temporal.
- Linux: se lanza con pkexec (aparece la ventana de contraseña de polkit) y
  el resultado se lee de la salida del ayudante.
- Si el proceso ya es administrador, no se eleva nada: se ejecuta directamente.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

from core import ayudante
from core.programador import comando_del_programa
from core.salud import (
    ErrorSalud, FaltaPermiso, SaludDisco, Umbrales, completar_datos_basicos, iniciar_autoprueba,
    interpretar, listar_discos,
)
from utils.sistema import LINUX, WINDOWS, sistema_actual

# Donde el paquete .deb instala el lanzador del ayudante. Es una carpeta
# propiedad de root: un usuario normal no puede modificar lo que hay dentro.
AYUDANTE_INSTALADO = Path("/usr/lib/analizador-disco/ayudante")

_CANCELADO_WINDOWS = 1223    # ERROR_CANCELLED: el usuario dijo "No" en el aviso de UAC
_CANCELADO_PKEXEC = 126      # el usuario cerró la ventana de contraseña
_NO_AUTORIZADO_PKEXEC = 127  # no hay agente de polkit, o la contraseña no valió


class PermisoCancelado(ErrorSalud):
    """El usuario decidió no dar permisos. No es un fallo: se le informa con calma."""


class SinAgenteDePermisos(ErrorSalud):
    """No hay forma gráfica de pedir permisos (Linux sin agente de polkit)."""


# lanzar(comando) -> (código de salida, salida estándar)
Lanzador = Callable[[list[str]], "tuple[int, str]"]


def es_administrador() -> bool:
    """True si este proceso ya tiene privilegios (administrador elevado en Windows, root en Linux)."""
    try:
        if os.name == "nt":
            import ctypes
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        return os.geteuid() == 0
    except (AttributeError, OSError):
        return False


def explicacion(sistema: str | None = None) -> str:
    """Texto corto para la tarjeta: qué se lee, que no se escribe nada y por qué se piden permisos."""
    comun = ("Se leerán los datos de salud (SMART) de tus discos. No se escribe ni se cambia "
             "nada en ellos. ")
    if (sistema or sistema_actual()) == WINDOWS:
        return comun + ("Windows solo permite esa lectura a un administrador: al pulsar verás el "
                        "aviso de Control de cuentas de usuario.")
    return comun + ("El sistema solo permite esa lectura a un administrador: al pulsar se te "
                    "pedirá la contraseña.")


def mensaje_cancelado(sistema: str | None = None) -> str:
    if (sistema or sistema_actual()) == WINDOWS:
        return ("No se concedieron los permisos, así que no se ha hecho nada. "
                "No pasa nada: puedes volver a pulsar el botón cuando quieras.")
    return ("No se introdujo la contraseña, así que no se ha hecho nada. "
            "No pasa nada: puedes volver a pulsar el botón cuando quieras.")


def comando_del_ayudante() -> list[str]:
    """Cómo se invoca el ayudante en este equipo."""
    if sistema_actual() == LINUX and AYUDANTE_INSTALADO.is_file():
        return [str(AYUDANTE_INSTALADO)]
    return [*comando_del_programa(), "--helper"]


# ---------------------------------------------------------------- Windows: UAC

def _lanzar_windows(comando: list[str]) -> tuple[int, str]:
    """Lanza el ayudante con el aviso de UAC, espera a que termine y devuelve lo que escribió."""
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

    # La aplicación crea el archivo, vacío y con un nombre imposible de adivinar,
    # en la carpeta temporal del usuario. El ayudante solo puede rellenar ese archivo.
    archivo = Path(tempfile.gettempdir()) / f"analizador-disco-{secrets.token_hex(16)}.json"
    descriptor = os.open(archivo, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.close(descriptor)
    try:
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        nucleo = ctypes.WinDLL("kernel32", use_last_error=True)
        info = InfoEjecucion()
        info.cbSize = ctypes.sizeof(info)
        info.fMask = 0x00000040        # SEE_MASK_NOCLOSEPROCESS: para poder esperar al proceso
        info.lpVerb = "runas"          # "ejecutar como administrador": muestra el aviso de UAC
        info.lpFile = comando[0]
        # "--salida ARCHIVO" va justo detrás de "--helper", antes de la acción.
        corte = comando.index("--helper") + 1
        info.lpParameters = subprocess.list2cmdline(
            [*comando[1:corte], "--salida", str(archivo), *comando[corte:]])
        info.nShow = 0                 # sin ventana
        if not shell32.ShellExecuteExW(ctypes.byref(info)):
            if ctypes.get_last_error() == _CANCELADO_WINDOWS:
                raise PermisoCancelado(mensaje_cancelado(WINDOWS))
            raise ErrorSalud(f"Windows no pudo pedir los permisos (error {ctypes.get_last_error()}).")
        nucleo.WaitForSingleObject(info.hProcess, 180_000)
        codigo = wintypes.DWORD()
        nucleo.GetExitCodeProcess(info.hProcess, ctypes.byref(codigo))
        nucleo.CloseHandle(info.hProcess)
        return codigo.value, archivo.read_text(encoding="utf-8")
    finally:
        try:
            archivo.unlink()           # el archivo temporal se borra siempre
        except OSError:
            pass


# ---------------------------------------------------------------- Linux: polkit

def instrucciones_sudo() -> str:
    programa = "analizador-disco" if AYUDANTE_INSTALADO.is_file() else " ".join(comando_del_programa())
    return ("No se pudo abrir la ventana para pedir la contraseña (hace falta un agente de "
            "polkit, que traen los escritorios habituales). Como alternativa, abre una terminal "
            f"y ejecuta:\n    sudo {programa} cli salud")


def _lanzar_linux(comando: list[str]) -> tuple[int, str]:
    if shutil.which("pkexec") is None:
        raise SinAgenteDePermisos(instrucciones_sudo())
    try:
        proceso = subprocess.run(["pkexec", *comando], capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        raise PermisoCancelado(mensaje_cancelado(LINUX)) from None
    if proceso.returncode == _CANCELADO_PKEXEC:
        raise PermisoCancelado(mensaje_cancelado(LINUX))
    if proceso.returncode == _NO_AUTORIZADO_PKEXEC and not proceso.stdout.strip():
        raise SinAgenteDePermisos(instrucciones_sudo())
    return proceso.returncode, proceso.stdout


# ---------------------------------------------------------------- funciones públicas

def resultado_a_diccionario(texto: str) -> dict:
    """Convierte lo que devolvió el ayudante en un diccionario, comprobando su forma."""
    try:
        respuesta = json.loads(texto)
    except ValueError:
        raise ErrorSalud("El ayudante no devolvió una respuesta válida.") from None
    if not isinstance(respuesta, dict) or "ok" not in respuesta:
        raise ErrorSalud("El ayudante no devolvió una respuesta válida.")
    return respuesta


def ejecutar_ayudante(
    accion: str,
    *argumentos: str,
    elevar: bool = True,
    lanzar: Lanzador | None = None,
    administrador: bool | None = None,
) -> object:
    """Ejecuta una acción del ayudante y devuelve sus datos.

    - Si este proceso ya es administrador, o elevar=False, se ejecuta aquí
      mismo, sin lanzar nada.
    - Si no, se piden permisos al sistema y se lanza el ayudante con ellos.
    Lanza PermisoCancelado si el usuario no los concede, y ErrorSalud si la
    acción falla. 'lanzar' y 'administrador' existen para las pruebas.
    """
    if accion not in ayudante.ACCIONES:
        raise ayudante.AccionNoPermitida(f"Acción no permitida: {accion!r}.")
    administrador = es_administrador() if administrador is None else administrador

    if administrador or not elevar:
        respuesta = ayudante.responder(accion, list(argumentos))
    else:
        if lanzar is None:
            sistema = sistema_actual()
            if sistema not in (WINDOWS, LINUX):
                raise ErrorSalud("Pedir permisos solo está disponible en Windows y Linux.")
            lanzar = _lanzar_windows if sistema == WINDOWS else _lanzar_linux
        _, salida = lanzar([*comando_del_ayudante(), accion, *argumentos])
        if not salida.strip():
            raise ErrorSalud("El ayudante terminó sin devolver ningún resultado.")
        respuesta = resultado_a_diccionario(salida)

    if not respuesta.get("ok"):
        raise ErrorSalud(str(respuesta.get("error") or "El ayudante no pudo completar la acción."))
    return respuesta.get("datos")


def leer_salud_con_permiso(umbrales: Umbrales | None = None, **opciones) -> list[SaludDisco]:
    """Lee la salud de TODOS los discos pidiendo permisos una sola vez."""
    nombres = [disco["name"] for disco in listar_discos()]   # detectar no necesita permisos
    if not nombres:
        return []
    datos = ejecutar_ayudante(ayudante.LEER, *nombres, **opciones)
    discos = [interpretar(datos[nombre], nombre, umbrales) for nombre in nombres if nombre in datos]
    completar_datos_basicos(discos)
    return discos


def iniciar_autoprueba_con_permiso(disco: str, tipo: str = "corta", **opciones) -> str:
    """Lanza una autoprueba pidiendo permisos al sistema."""
    return ejecutar_ayudante(ayudante.INICIAR, disco, tipo, **opciones)["mensaje"]


def iniciar_autoprueba_pidiendo_permiso(disco: str, tipo: str = "corta", elevar_ya: bool = False,
                                        **opciones) -> str:
    """Lanza una autoprueba; si el sistema exige permisos para ello, los pide.

    Es lo que usan los botones "Prueba corta" y "Prueba larga": primero se
    intenta sin permisos y, solo si el disco lo exige, se piden (el usuario
    acaba de pulsar el botón, así que es él quien lo solicita). Muchos discos
    dejan leer su salud sin permisos pero no lanzar una autoprueba.
    Con elevar_ya=True se piden directamente, sin el primer intento.
    """
    if not elevar_ya:
        try:
            return iniciar_autoprueba(disco, tipo)
        except FaltaPermiso:
            pass
    return iniciar_autoprueba_con_permiso(disco, tipo, **opciones)
