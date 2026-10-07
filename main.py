"""Punto de entrada único (también del ejecutable empaquetado).

    python main.py                     -> aplicación de escritorio (interfaz principal)
    python main.py cli <comando> ...   -> terminal
    python main.py web                 -> interfaz web local (opcional)
"""

from __future__ import annotations

import os
import sys

from utils.info import NOMBRE, VERSION

USO = f"""{NOMBRE} {VERSION}

Uso:
  python main.py                            Abrir la aplicación de escritorio
  python main.py cli <comando> [opciones]   Usar desde la terminal
  python main.py web                        Abrir la interfaz web local (opcional)
  python main.py --version                  Mostrar la versión

Para ver los comandos de terminal:  python main.py cli --help
(Con el programa empaquetado, sustituye "python main.py" por el ejecutable.)
"""


def preparar_salida(usar_terminal: bool) -> None:
    """Deja listas la salida y la entrada de texto en el ejecutable sin consola.

    El ejecutable se construye "sin ventana de consola" para que al abrir la
    aplicación de escritorio no aparezca una ventana negra. La contrapartida
    es que arranca sin salida de texto. Aquí se arregla:
    - en modo terminal o web, se conecta a la terminal desde la que se lanzó;
    - si no hay terminal (doble clic, tarea programada), la salida se descarta
      para que un simple print() no provoque un error.
    Con "python main.py" normal no hace nada.
    """
    if sys.stdout is not None and sys.stderr is not None and sys.stdin is not None:
        return

    conectado = False
    if usar_terminal and os.name == "nt":
        import ctypes
        nucleo = ctypes.windll.kernel32
        if nucleo.AttachConsole(-1):   # -1 = la consola del proceso que nos lanzó
            conectado = True
            codificacion = f"cp{nucleo.GetConsoleOutputCP()}"
            try:
                if sys.stdout is None:
                    sys.stdout = open("CONOUT$", "w", encoding=codificacion, errors="replace", buffering=1)
                if sys.stderr is None:
                    sys.stderr = sys.stdout
                if sys.stdin is None:
                    sys.stdin = open("CONIN$", "r", encoding=f"cp{nucleo.GetConsoleCP()}")
            except OSError:
                conectado = False

    if not conectado:
        nada = open(os.devnull, "w", encoding="utf-8")
        sys.stdout = sys.stdout or nada
        sys.stderr = sys.stderr or nada
        sys.stdin = sys.stdin or open(os.devnull, "r", encoding="utf-8")


def main(argumentos: list[str] | None = None) -> int:
    argumentos = sys.argv[1:] if argumentos is None else argumentos
    preparar_salida(usar_terminal=bool(argumentos))

    if not argumentos:
        # Import tardío: la terminal y la web no necesitan cargar Qt.
        from desktop.app import iniciar
        return iniciar()
    if argumentos[0] in ("-h", "--help"):
        print(USO)
        return 0
    if argumentos[0] in ("-V", "--version"):
        print(f"{NOMBRE} {VERSION}")
        return 0

    modo, resto = argumentos[0], argumentos[1:]
    if modo == "cli":
        from cli.comandos import ejecutar
        return ejecutar(resto)
    if modo in ("web", "gui"):   # "gui" es el nombre antiguo de la interfaz web
        import argparse

        parser = argparse.ArgumentParser(
            prog="python main.py web", description="Abre la interfaz web local (solo en 127.0.0.1).")
        parser.add_argument("--puerto", type=int, default=5000,
                            help="puerto preferido (por defecto 5000)")
        parser.add_argument("--no-abrir", action="store_true",
                            help="no abrir el navegador automáticamente")
        opciones = parser.parse_args(resto)

        from web.app import iniciar
        try:
            return iniciar(opciones.puerto, abrir_navegador=not opciones.no_abrir)
        except KeyboardInterrupt:
            return 0

    print(f"Modo desconocido: {modo}\n\n{USO}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
