"""Escaneos programados con el programador de tareas del propio sistema.

- Windows: Programador de tareas, mediante el comando schtasks.
- Linux: cron, mediante el comando crontab (una línea marcada con un comentario).

Este módulo no deja ningún proceso propio en marcha: solo crea, lista o quita
la tarea. Lo que la tarea ejecuta es "python main.py cli guardar RUTA", que
escanea y guarda el resultado en el historial.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import shlex
import subprocess
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from core.historial import carpeta_de_datos
from utils.sistema import LINUX, WINDOWS, sistema_actual

CARPETA_TAREAS = "AnalizadorDisco"       # carpeta dentro del Programador de tareas
MARCA_CRON = "# analizador-disco:"        # comentario que identifica nuestras líneas
FRECUENCIAS = ("diaria", "semanal")       # semanal = cada lunes
LIMITE_COMANDO_WINDOWS = 261              # máximo que admite schtasks en /TR

_HORA = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_NOMBRE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

# ejecutar(comando, entrada) -> (código de salida, salida, error)
Ejecutor = Callable[[list[str], "str | None"], "tuple[int, str, str]"]


class ErrorProgramador(Exception):
    """No se pudo crear, listar o quitar la tarea."""


@dataclass(slots=True)
class TareaProgramada:
    nombre: str
    ruta: str
    frecuencia: str
    hora: str


# ---------------------------------------------------------------- utilidades

def _ejecutar(comando: list[str], entrada: str | None = None) -> tuple[int, str, str]:
    try:
        proceso = subprocess.run(
            comando, input=entrada, capture_output=True, text=True,
            # schtasks escribe con la página de códigos de la consola.
            encoding="oem" if os.name == "nt" else None, errors="replace",
        )
    except FileNotFoundError:
        raise ErrorProgramador(
            f"No se encontró el comando '{comando[0]}' en este sistema.") from None
    return proceso.returncode, proceso.stdout, proceso.stderr


def nombre_de_tarea(ruta: str | os.PathLike) -> str:
    """Nombre estable para la tarea de una carpeta: 'Downloads-3f2a9c1b'."""
    texto = os.path.normcase(os.path.abspath(ruta))
    legible = re.sub(r"[^A-Za-z0-9]+", "-", os.path.basename(texto.rstrip("\\/"))).strip("-")
    return f"{legible[:30] or 'raiz'}-{hashlib.sha1(texto.encode('utf-8')).hexdigest()[:8]}"


def comando_de_escaneo(ruta: str | os.PathLike) -> list[str]:
    """El comando que ejecutará la tarea."""
    principal = Path(__file__).resolve().parent.parent / "main.py"
    return [sys.executable, str(principal), "cli", "--silencioso", "guardar", str(ruta)]


def _archivo_de_datos() -> Path:
    return carpeta_de_datos() / "programados.json"


def _leer_datos() -> dict[str, dict]:
    """Detalles de las tareas creadas (carpeta, frecuencia y hora) para mostrarlos al listar."""
    try:
        return json.loads(_archivo_de_datos().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _escribir_datos(datos: dict[str, dict]) -> None:
    archivo = _archivo_de_datos()
    archivo.parent.mkdir(parents=True, exist_ok=True)
    archivo.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")


def _comprobar_sistema(sistema: str | None) -> str:
    sistema = sistema or sistema_actual()
    if sistema not in (WINDOWS, LINUX):
        raise ErrorProgramador("Los escaneos programados solo están disponibles en Windows y Linux.")
    return sistema


# ---------------------------------------------------------------- Windows (schtasks)

def linea_de_comando_windows(comando: list[str]) -> str:
    """Une el comando en un texto, entre comillas, como lo espera schtasks en /TR."""
    partes = []
    for parte in comando:
        if " " in parte or "\\" in parte or "/" in parte:
            # Una barra final escaparía la comilla de cierre: se duplica.
            partes.append('"' + (parte + "\\" if parte.endswith("\\") else parte) + '"')
        else:
            partes.append(parte)
    return " ".join(partes)


def _lanzador_windows(nombre: str) -> Path:
    return carpeta_de_datos() / "tareas" / f"{nombre}.cmd"


def _crear_windows(tarea: TareaProgramada, ejecutar: Ejecutor,
                   comando_tarea: list[str] | None = None, elevada: bool = False) -> None:
    # schtasks solo admite 261 caracteres en el comando, y la ruta de Python
    # más la de la carpeta los superan con facilidad. Por eso el comando real
    # se guarda en un pequeño archivo .cmd y la tarea solo ejecuta ese archivo.
    lanzador = _lanzador_windows(tarea.nombre)
    lanzador.parent.mkdir(parents=True, exist_ok=True)
    # En un .cmd el símbolo % introduce variables: se duplica para que sea literal.
    linea = linea_de_comando_windows(
        comando_tarea or comando_de_escaneo(tarea.ruta)).replace("%", "%%")
    # chcp 65001 = UTF-8, para que las rutas con acentos se lean bien.
    lanzador.write_text(f"@echo off\r\nchcp 65001 >nul\r\n{linea}\r\n",
                        encoding="utf-8", newline="")
    orden = f'"{lanzador}"'
    if len(orden) > LIMITE_COMANDO_WINDOWS:
        raise ErrorProgramador(
            "La carpeta de datos del programa tiene una ruta demasiado larga para el "
            f"Programador de tareas de Windows ({len(orden)} caracteres; máximo "
            f"{LIMITE_COMANDO_WINDOWS}).")
    comando = ["schtasks", "/Create", "/TN", f"{CARPETA_TAREAS}\\{tarea.nombre}",
               "/TR", orden, "/ST", tarea.hora, "/F"]
    comando += ["/SC", "WEEKLY", "/D", "MON"] if tarea.frecuencia == "semanal" else ["/SC", "DAILY"]
    if elevada:
        # Leer SMART exige permisos de administrador también cuando lo hace la tarea.
        comando += ["/RL", "HIGHEST"]
    codigo, _, fallo = ejecutar(comando, None)
    if codigo != 0 and elevada:
        raise ErrorProgramador(
            "Windows no pudo crear la tarea. Para programar la revisión de salud hay que "
            f"ejecutar este comando desde una terminal de administrador. ({fallo.strip()})")
    if codigo != 0:
        raise ErrorProgramador(f"Windows no pudo crear la tarea: {fallo.strip()}")


def _nombres_windows(ejecutar: Ejecutor) -> list[str]:
    codigo, salida, fallo = ejecutar(["schtasks", "/Query", "/FO", "CSV", "/NH"], None)
    if codigo != 0:
        raise ErrorProgramador(f"Windows no pudo listar las tareas: {fallo.strip()}")
    prefijo = f"\\{CARPETA_TAREAS}\\"
    nombres = []
    for fila in csv.reader(io.StringIO(salida)):
        if fila and fila[0].startswith(prefijo):
            nombres.append(fila[0][len(prefijo):])
    return sorted(set(nombres))


def _quitar_windows(nombre: str, ejecutar: Ejecutor) -> bool:
    codigo, _, _ = ejecutar(
        ["schtasks", "/Delete", "/TN", f"{CARPETA_TAREAS}\\{nombre}", "/F"], None)
    try:
        _lanzador_windows(nombre).unlink()
    except OSError:
        pass
    return codigo == 0


# ---------------------------------------------------------------- Linux (cron)

def linea_cron(tarea: TareaProgramada, comando_tarea: list[str] | None = None) -> str:
    """Línea de crontab: minuto hora día-del-mes mes día-de-la-semana comando."""
    hora, minuto = tarea.hora.split(":")
    dia_semana = "1" if tarea.frecuencia == "semanal" else "*"
    # En crontab el símbolo % significa salto de línea: hay que escaparlo.
    comando = shlex.join(comando_tarea or comando_de_escaneo(tarea.ruta)).replace("%", "\\%")
    return f"{int(minuto)} {int(hora)} * * {dia_semana} {comando} {MARCA_CRON}{tarea.nombre}"


def _leer_crontab(ejecutar: Ejecutor) -> list[str]:
    codigo, salida, _ = ejecutar(["crontab", "-l"], None)
    # Sin crontab todavía, 'crontab -l' termina con error: equivale a estar vacío.
    return salida.splitlines() if codigo == 0 else []


def _escribir_crontab(lineas: list[str], ejecutar: Ejecutor) -> None:
    codigo, _, fallo = ejecutar(["crontab", "-"], "\n".join(lineas) + "\n" if lineas else "")
    if codigo != 0:
        raise ErrorProgramador(f"No se pudo actualizar el crontab: {fallo.strip()}")


def _crear_linux(tarea: TareaProgramada, ejecutar: Ejecutor,
                 comando_tarea: list[str] | None = None, elevada: bool = False) -> None:
    # 'elevada' no cambia nada aquí: en Linux la tarea tiene los permisos del
    # usuario que la crea, así que para leer SMART hay que crearla con sudo.
    marca = MARCA_CRON + tarea.nombre
    lineas = [linea for linea in _leer_crontab(ejecutar) if not linea.rstrip().endswith(marca)]
    _escribir_crontab(lineas + [linea_cron(tarea, comando_tarea)], ejecutar)


def _nombres_linux(ejecutar: Ejecutor) -> list[str]:
    return sorted({
        linea.rsplit(MARCA_CRON, 1)[1].strip()
        for linea in _leer_crontab(ejecutar) if MARCA_CRON in linea
    })


def _quitar_linux(nombre: str, ejecutar: Ejecutor) -> bool:
    marca = MARCA_CRON + nombre
    lineas = _leer_crontab(ejecutar)
    restantes = [linea for linea in lineas if not linea.rstrip().endswith(marca)]
    if len(restantes) == len(lineas):
        return False
    _escribir_crontab(restantes, ejecutar)
    return True


# ---------------------------------------------------------------- funciones públicas

def crear_tarea(
    ruta: str | os.PathLike,
    frecuencia: str = "diaria",
    hora: str = "09:00",
    sistema: str | None = None,
    ejecutar: Ejecutor | None = None,
) -> TareaProgramada:
    """Programa un escaneo periódico de 'ruta'. Si ya existía uno para esa carpeta, lo reemplaza."""
    sistema = _comprobar_sistema(sistema)
    if frecuencia not in FRECUENCIAS:
        raise ErrorProgramador(f"Frecuencia no válida: {frecuencia}. Opciones: {', '.join(FRECUENCIAS)}")
    if not _HORA.match(hora):
        raise ErrorProgramador(f"Hora no válida: {hora}. Usa el formato HH:MM, por ejemplo 09:30.")
    carpeta = Path(ruta).expanduser()
    if not carpeta.is_dir():
        raise ErrorProgramador(f"La carpeta no existe: {ruta}")
    carpeta = carpeta.resolve()

    tarea = TareaProgramada(nombre_de_tarea(carpeta), str(carpeta), frecuencia, hora)
    (_crear_windows if sistema == WINDOWS else _crear_linux)(tarea, ejecutar or _ejecutar)

    datos = _leer_datos()
    datos[tarea.nombre] = asdict(tarea)
    _escribir_datos(datos)
    return tarea


NOMBRE_TAREA_SALUD = "salud-discos"
RUTA_TAREA_SALUD = "(salud de todos los discos)"


def comando_de_salud() -> list[str]:
    principal = Path(__file__).resolve().parent.parent / "main.py"
    return [sys.executable, str(principal), "cli", "salud", "revisar"]


def crear_tarea_salud(
    frecuencia: str = "diaria",
    hora: str = "09:00",
    sistema: str | None = None,
    ejecutar: Ejecutor | None = None,
) -> TareaProgramada:
    """Programa la revisión periódica de la salud de los discos (con sus alertas).

    Leer SMART exige administrador: en Windows hay que crear la tarea desde una
    terminal de administrador; en Linux, con sudo (queda en el crontab de root).
    """
    sistema = _comprobar_sistema(sistema)
    if frecuencia not in FRECUENCIAS:
        raise ErrorProgramador(f"Frecuencia no válida: {frecuencia}. Opciones: {', '.join(FRECUENCIAS)}")
    if not _HORA.match(hora):
        raise ErrorProgramador(f"Hora no válida: {hora}. Usa el formato HH:MM, por ejemplo 09:30.")

    tarea = TareaProgramada(NOMBRE_TAREA_SALUD, RUTA_TAREA_SALUD, frecuencia, hora)
    (_crear_windows if sistema == WINDOWS else _crear_linux)(
        tarea, ejecutar or _ejecutar, comando_tarea=comando_de_salud(), elevada=True)

    datos = _leer_datos()
    datos[tarea.nombre] = asdict(tarea)
    _escribir_datos(datos)
    return tarea


def listar_tareas(sistema: str | None = None, ejecutar: Ejecutor | None = None) -> list[TareaProgramada]:
    """Tareas de este programa que existen de verdad en el programador del sistema."""
    sistema = _comprobar_sistema(sistema)
    nombres = (_nombres_windows if sistema == WINDOWS else _nombres_linux)(ejecutar or _ejecutar)
    datos = _leer_datos()
    tareas = []
    for nombre in nombres:
        detalle = datos.get(nombre, {})
        tareas.append(TareaProgramada(
            nombre, detalle.get("ruta", "(desconocida)"),
            detalle.get("frecuencia", "(desconocida)"), detalle.get("hora", "")))
    return tareas


def quitar_tarea(nombre: str, sistema: str | None = None, ejecutar: Ejecutor | None = None) -> bool:
    """Quita una tarea por su nombre. Devuelve False si no existía."""
    sistema = _comprobar_sistema(sistema)
    # El nombre se valida para que este comando solo pueda tocar tareas propias.
    if not _NOMBRE.match(nombre):
        raise ErrorProgramador(f"Nombre de tarea no válido: {nombre}")
    quitada = (_quitar_windows if sistema == WINDOWS else _quitar_linux)(nombre, ejecutar or _ejecutar)

    datos = _leer_datos()
    if datos.pop(nombre, None) is not None:
        _escribir_datos(datos)
    return quitada
