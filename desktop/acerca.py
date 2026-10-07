"""Icono de la aplicación y ventana «Acerca de»."""

from __future__ import annotations

import platform

from PySide6 import __version__ as VERSION_QT
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

from desktop.componentes import etiqueta
from utils.info import DESCRIPCION, LICENCIA, NOMBRE, VERSION, WEB
from utils.rutas import ruta_recurso

# ruta_recurso() encuentra los archivos igual desde el código que dentro del
# ejecutable empaquetado.
RECURSOS = ruta_recurso("desktop", "recursos")


def texto_de(archivo: str) -> str:
    """Contenido de LICENSE o NOTICE, que se distribuyen con el programa."""
    try:
        return ruta_recurso(archivo).read_text(encoding="utf-8")
    except OSError:
        return f"No se encontró el archivo {archivo}. Puedes consultarlo en {WEB}"


class DialogoTexto(QDialog):
    """Ventana sencilla para leer un texto largo (licencias)."""

    def __init__(self, parent: QWidget | None, titulo: str, texto: str) -> None:
        super().__init__(parent)
        self.setWindowTitle(titulo)
        self.resize(680, 520)
        caja = QVBoxLayout(self)
        self.texto = QPlainTextEdit(texto)
        self.texto.setReadOnly(True)
        caja.addWidget(self.texto, 1)
        pie = QHBoxLayout()
        pie.addStretch(1)
        cerrar = QPushButton("Cerrar")
        cerrar.clicked.connect(self.accept)
        pie.addWidget(cerrar)
        caja.addLayout(pie)


def icono() -> QIcon:
    """Icono de la aplicación (vacío si faltara el archivo; nunca falla)."""
    return QIcon(str(RECURSOS / "icono.png"))


class DialogoAcercaDe(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Acerca de {NOMBRE}")
        self.setMinimumWidth(460)

        caja = QVBoxLayout(self)
        caja.setContentsMargins(24, 22, 24, 18)
        caja.setSpacing(10)

        cabecera = QHBoxLayout()
        cabecera.setSpacing(16)
        imagen = QLabel()
        dibujo = QPixmap(str(RECURSOS / "icono.png"))
        if not dibujo.isNull():
            imagen.setPixmap(dibujo.scaled(72, 72, Qt.AspectRatioMode.KeepAspectRatio,
                                           Qt.TransformationMode.SmoothTransformation))
        cabecera.addWidget(imagen, alignment=Qt.AlignmentFlag.AlignTop)
        titulos = QVBoxLayout()
        titulos.setSpacing(2)
        titulos.addWidget(etiqueta(NOMBRE, "titulo"))
        self.version = etiqueta(f"Versión {VERSION}", "subtitulo")
        titulos.addWidget(self.version)
        cabecera.addLayout(titulos, 1)
        caja.addLayout(cabecera)

        caja.addWidget(etiqueta(DESCRIPCION, ajustar=True))
        caja.addWidget(etiqueta(
            "Por defecto solo lee. Mover o borrar exige una lista exacta y tu confirmación, "
            "y borrar siempre envía a la papelera.", "suave", ajustar=True))

        caja.addWidget(etiqueta(
            "Privacidad: este programa no envía datos a ningún servidor. Todo se analiza en tu "
            "equipo. La única conexión saliente posible es el correo de alertas, si lo configuras.",
            ajustar=True))

        enlace = QLabel(f'<a href="{WEB}">{WEB}</a>')
        enlace.setOpenExternalLinks(True)
        enlace.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        caja.addWidget(enlace)
        caja.addWidget(etiqueta(
            f"{LICENCIA} · Python {platform.python_version()} · Qt {VERSION_QT} · "
            f"{platform.system()} {platform.release()}", "suave", ajustar=True))

        pie = QHBoxLayout()
        licencia = QPushButton("Licencia")
        licencia.clicked.connect(lambda: DialogoTexto(self, "Licencia", texto_de("LICENSE")).exec())
        terceros = QPushButton("Licencias de terceros")
        terceros.clicked.connect(
            lambda: DialogoTexto(self, "Licencias de terceros", texto_de("NOTICE")).exec())
        pie.addWidget(licencia)
        pie.addWidget(terceros)
        pie.addStretch(1)
        cerrar = QPushButton("Cerrar")
        cerrar.setObjectName("principal")
        cerrar.clicked.connect(self.accept)
        pie.addWidget(cerrar)
        caja.addLayout(pie)
