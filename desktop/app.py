"""Arranque de la aplicación de escritorio."""

from __future__ import annotations

import os
import sys


def iniciar(argumentos: list[str] | None = None) -> int:
    """Abre la ventana principal y devuelve el código de salida."""
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print("Para la aplicación de escritorio hace falta PySide6:\n"
              "    pip install PySide6-Essentials\n"
              "Mientras tanto puedes usar la terminal (python main.py cli --help) "
              "o la web (python main.py web).", file=sys.stderr)
        return 1

    from desktop.acerca import icono
    from desktop.asistente import mostrar_si_hace_falta
    from desktop.errores import instalar_gancho
    from desktop.ventana import VentanaPrincipal
    from utils.info import NOMBRE, NOMBRE_EJECUTABLE, VERSION

    if os.name == "nt":
        # Sin esto, Windows agrupa la ventana con "Python" en la barra de tareas
        # y muestra el icono de Python en lugar del nuestro.
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                f"analizador-disco.{NOMBRE_EJECUTABLE}")
        except (AttributeError, OSError):
            pass

    app = QApplication.instance() or QApplication(argumentos or sys.argv[:1])
    app.setApplicationName(NOMBRE)
    app.setApplicationDisplayName(NOMBRE)
    app.setApplicationVersion(VERSION)
    app.setWindowIcon(icono())
    ventana = VentanaPrincipal()
    instalar_gancho(ventana)
    ventana.show()
    # Primera ejecución: se explica qué hace el programa. Si no se acepta, se cierra.
    if not mostrar_si_hace_falta(ventana):
        return 0
    return app.exec()
