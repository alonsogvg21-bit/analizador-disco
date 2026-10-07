"""Errores explicados con claridad, con el detalle técnico a un clic para poder copiarlo."""

from __future__ import annotations

import errno
import platform
import sys
import traceback

from PySide6 import __version__ as VERSION_QT
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

from core import registro
from desktop.componentes import etiqueta
from utils.info import NOMBRE, VERSION


def mensaje_amigable(problema: BaseException) -> str:
    """Explica un error en lenguaje normal, sin jerga."""
    if isinstance(problema, PermissionError):
        return ("No hay permisos para acceder a ese archivo o carpeta. Puede que esté protegido "
                "por el sistema o abierto en otro programa.")
    if isinstance(problema, FileNotFoundError):
        return "El archivo o la carpeta ya no existe. Puede que se haya movido o borrado mientras tanto."
    if isinstance(problema, OSError) and problema.errno == errno.ENOSPC:
        return "No queda espacio suficiente en el disco para completar la operación."
    if isinstance(problema, MemoryError):
        return "El equipo se ha quedado sin memoria. Prueba a escanear una carpeta más pequeña."
    if isinstance(problema, (ValueError, RuntimeError)) and str(problema):
        return str(problema)   # estos mensajes ya los escribe el programa pensando en el usuario
    return "Ha ocurrido un error inesperado. No se ha perdido ningún archivo por ello."


def detalle_tecnico(problema: BaseException) -> str:
    """Todo lo que alguien necesitaría para investigar el fallo."""
    traza = "".join(traceback.format_exception(type(problema), problema, problema.__traceback__))
    return (f"{NOMBRE} {VERSION}\n"
            f"Python {platform.python_version()} · Qt {VERSION_QT}\n"
            f"{platform.system()} {platform.release()} ({platform.machine()})\n\n{traza}")


class DialogoError(QDialog):
    def __init__(self, parent: QWidget | None, mensaje: str, detalle: str = "",
                 titulo: str = "Algo no ha ido bien") -> None:
        super().__init__(parent)
        self.setWindowTitle(titulo)
        self.setMinimumWidth(520)
        self._detalle = detalle

        caja = QVBoxLayout(self)
        caja.setContentsMargins(22, 20, 22, 16)
        caja.setSpacing(10)
        caja.addWidget(etiqueta(titulo, "subtitulo"))
        self.mensaje = etiqueta(mensaje, ajustar=True)
        caja.addWidget(self.mensaje)

        self.texto = QPlainTextEdit(detalle)
        self.texto.setReadOnly(True)
        self.texto.setMinimumHeight(180)
        self.texto.hide()
        caja.addWidget(self.texto, 1)

        pie = QHBoxLayout()
        self.ver = QPushButton("Ver detalle técnico")
        self.ver.clicked.connect(self._alternar)
        self.copiar = QPushButton("Copiar detalle técnico")
        self.copiar.clicked.connect(self._copiar)
        for boton in (self.ver, self.copiar):
            boton.setVisible(bool(detalle))
            pie.addWidget(boton)
        pie.addStretch(1)
        cerrar = QPushButton("Cerrar")
        cerrar.setObjectName("principal")
        cerrar.clicked.connect(self.accept)
        pie.addWidget(cerrar)
        caja.addLayout(pie)

    def _alternar(self) -> None:
        self.texto.setVisible(not self.texto.isVisible())
        self.ver.setText("Ocultar detalle técnico" if self.texto.isVisible() else "Ver detalle técnico")
        self.adjustSize()

    def _copiar(self) -> None:
        QGuiApplication.clipboard().setText(self._detalle)
        self.copiar.setText("Copiado")


def mostrar_error(parent: QWidget | None, problema: BaseException | str, titulo: str = "Algo no ha ido bien") -> None:
    """Muestra un error de forma amigable y lo anota en el registro."""
    if isinstance(problema, BaseException):
        mensaje, detalle = mensaje_amigable(problema), detalle_tecnico(problema)
        registro.anotar("error", type(problema).__name__, detalle=str(problema))
    else:
        mensaje, detalle = str(problema), ""
        registro.anotar("error", "aviso", detalle=mensaje)
    DialogoError(parent, mensaje, detalle, titulo).exec()


def instalar_gancho(ventana: QWidget) -> None:
    """Cualquier error no previsto se muestra en una ventana en lugar de cerrar el programa."""
    estado = {"mostrando": False}

    def gancho(tipo, problema, traza) -> None:
        if issubclass(tipo, KeyboardInterrupt):
            sys.__excepthook__(tipo, problema, traza)
            return
        if estado["mostrando"]:
            return   # un error mientras se muestra otro: no abrir ventanas en cadena
        estado["mostrando"] = True
        try:
            mostrar_error(ventana, problema.with_traceback(traza))
        finally:
            estado["mostrando"] = False

    sys.excepthook = gancho
