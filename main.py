"""Punto de entrada único.

    python main.py                     -> aplicación de escritorio (interfaz principal)
    python main.py cli <comando> ...   -> terminal
    python main.py web                 -> interfaz web local (opcional)
"""

from __future__ import annotations

import sys

USO = """Analizador de disco

Uso:
  python main.py                            Abrir la aplicación de escritorio
  python main.py cli <comando> [opciones]   Usar desde la terminal
  python main.py web                        Abrir la interfaz web local (opcional)

Para ver los comandos de terminal:  python main.py cli --help
"""


def main(argumentos: list[str] | None = None) -> int:
    argumentos = sys.argv[1:] if argumentos is None else argumentos

    if not argumentos:
        # Import tardío: la terminal y la web no necesitan cargar Qt.
        from desktop.app import iniciar
        return iniciar()
    if argumentos[0] in ("-h", "--help"):
        print(USO)
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
