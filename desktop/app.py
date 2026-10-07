"""Arranque de la aplicación de escritorio."""

from __future__ import annotations

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

    from desktop.ventana import VentanaPrincipal

    app = QApplication.instance() or QApplication(argumentos or sys.argv[:1])
    app.setApplicationName("Analizador de disco")
    ventana = VentanaPrincipal()
    ventana.show()
    return app.exec()
