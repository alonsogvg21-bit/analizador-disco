"""Acciones sobre archivos: confirmar, abrir ubicación, copiar ruta y menú contextual.

Aquí no se borra ni se mueve nada: eso lo hacen core.limpieza y core.mover,
que vuelven a comprobar cada elemento. Esta parte solo pregunta al usuario.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFileDialog, QHBoxLayout, QLineEdit, QListWidget, QMenu, QPushButton,
    QVBoxLayout, QWidget,
)

from core.consulta import buscar_archivo
from core.modelos import ElementoBasura, ResultadoEscaneo
from core.mover import validar_destino
from desktop.componentes import etiqueta
from utils.formato import tamano_legible
from utils.seguridad import es_ruta_protegida
from utils.sistema import WINDOWS, sistema_actual

PAPELERA = "papelera"
MOVER = "mover"


def elemento_de(resultado: ResultadoEscaneo | None, ruta: str) -> ElementoBasura | None:
    """Convierte una ruta en un elemento sobre el que actuar, solo si pertenece al escaneo."""
    if resultado is None:
        return None
    archivo = buscar_archivo(resultado, ruta)
    if archivo is not None:
        return ElementoBasura(archivo.path, archivo.tamano, "archivos",
                              limpiable=not es_ruta_protegida(ruta))
    if ruta in resultado.tamano_carpetas:
        return ElementoBasura(Path(ruta), resultado.tamano_carpetas[ruta], "carpetas",
                              es_carpeta=True, limpiable=not es_ruta_protegida(ruta))
    return None


def abrir_ubicacion(ruta: str | Path) -> None:
    """Abre la carpeta que contiene el archivo en el explorador del sistema."""
    ruta = Path(ruta)
    if sistema_actual() == WINDOWS and ruta.exists():
        # En Windows, además, deja el archivo seleccionado.
        subprocess.Popen(["explorer", "/select,", str(ruta)])
        return
    carpeta = ruta if ruta.is_dir() else ruta.parent
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(carpeta)))


def copiar_ruta(ruta: str | Path) -> None:
    QGuiApplication.clipboard().setText(str(ruta))


class DialogoConfirmacion(QDialog):
    """Lista exacta de lo que se va a tocar, el espacio y la opción de simular."""

    def __init__(self, parent: QWidget, elementos: list[ElementoBasura], accion: str) -> None:
        super().__init__(parent)
        self._mover = accion == MOVER
        self.destino = ""
        total = sum(e.tamano for e in elementos)
        cantidad = f"{len(elementos)} {'elemento' if len(elementos) == 1 else 'elementos'}"
        self.setWindowTitle("Mover a otra carpeta" if self._mover else "Enviar a la papelera")
        self.setMinimumSize(620, 460)

        caja = QVBoxLayout(self)
        caja.setSpacing(10)
        caja.addWidget(etiqueta(
            "¿Mover a otra carpeta?" if self._mover else "¿Enviar a la papelera?", "subtitulo"))
        caja.addWidget(etiqueta(
            f"Vas a mover {cantidad} ({tamano_legible(total)})." if self._mover else
            f"Vas a enviar {cantidad} a la papelera. Se liberarían {tamano_legible(total)}.",
            ajustar=True))

        lista = QListWidget()
        lista.setObjectName("lista")
        for elemento in sorted(elementos, key=lambda e: e.tamano, reverse=True):
            lista.addItem(f"{tamano_legible(elemento.tamano):>10}   {elemento.ruta}")
        caja.addWidget(lista, 1)

        self._campo_destino = QLineEdit()
        if self._mover:
            fila = QHBoxLayout()
            self._campo_destino.setPlaceholderText("Carpeta de destino")
            elegir = QPushButton("Elegir carpeta…")
            elegir.clicked.connect(self._elegir_destino)
            fila.addWidget(self._campo_destino, 1)
            fila.addWidget(elegir)
            caja.addLayout(fila)
            caja.addWidget(etiqueta(
                "Si en el destino ya hay algo con el mismo nombre no se sobrescribe: "
                "se guarda como «nombre (1)».", "suave", ajustar=True))
        else:
            caja.addWidget(etiqueta(
                "Los archivos van a la papelera y se pueden recuperar desde ahí. "
                "El espacio no vuelve al disco hasta que la vacíes.", "suave", ajustar=True))

        self._aviso = etiqueta("", "aviso", ajustar=True)
        self._aviso.hide()
        caja.addWidget(self._aviso)

        self._simular = QCheckBox("Solo simular (muestra qué pasaría sin tocar nada)")
        self._simular.toggled.connect(self._pintar_boton)
        caja.addWidget(self._simular)

        botones = QHBoxLayout()
        botones.addStretch(1)
        cancelar = QPushButton("Cancelar")
        cancelar.clicked.connect(self.reject)
        self._confirmar = QPushButton()
        self._confirmar.clicked.connect(self._aceptar)
        botones.addWidget(cancelar)
        botones.addWidget(self._confirmar)
        caja.addLayout(botones)
        self._pintar_boton()
        # Pulsar Intro nada más abrir cancela: la acción peligrosa nunca es la predeterminada.
        self._confirmar.setAutoDefault(False)
        cancelar.setDefault(True)
        cancelar.setFocus()

    @property
    def simulacion(self) -> bool:
        return self._simular.isChecked()

    def _pintar_boton(self) -> None:
        if self._simular.isChecked():
            self._confirmar.setText("Simular")
            self._confirmar.setObjectName("principal")
        else:
            self._confirmar.setText("Sí, mover" if self._mover else "Sí, enviar a la papelera")
            self._confirmar.setObjectName("principal" if self._mover else "peligro")
        # Al cambiar el nombre hay que pedir a Qt que vuelva a aplicar el estilo.
        self._confirmar.style().unpolish(self._confirmar)
        self._confirmar.style().polish(self._confirmar)

    def _elegir_destino(self) -> None:
        carpeta = QFileDialog.getExistingDirectory(self, "Carpeta de destino", self._campo_destino.text())
        if carpeta:
            self._campo_destino.setText(str(Path(carpeta)))

    def _aceptar(self) -> None:
        if self._mover:
            try:
                self.destino = str(validar_destino(self._campo_destino.text().strip()))
            except ValueError as problema:
                self._aviso.setText(str(problema))
                self._aviso.show()
                return
        self.accept()


def menu_contextual(ventana, elementos: list[ElementoBasura], posicion) -> None:
    """Menú del clic derecho: abrir ubicación, copiar ruta, mover y enviar a la papelera."""
    if not elementos:
        return
    menu = QMenu(ventana)
    primero = elementos[0]
    varios = len(elementos) > 1
    abrir = menu.addAction("Abrir ubicación")
    abrir.setEnabled(not varios)
    abrir.triggered.connect(lambda: abrir_ubicacion(primero.ruta))
    copiar = menu.addAction("Copiar rutas" if varios else "Copiar ruta")
    copiar.triggered.connect(lambda: copiar_ruta("\n".join(str(e.ruta) for e in elementos)))
    menu.addSeparator()

    tocables = [e for e in elementos if e.limpiable]
    mover = menu.addAction("Mover a otra carpeta…")
    papelera = menu.addAction("Enviar a la papelera…")
    for accion in (mover, papelera):
        accion.setEnabled(bool(tocables))
    if not tocables:
        aviso = menu.addAction("Protegido: no se puede mover ni borrar")
        aviso.setEnabled(False)
    mover.triggered.connect(lambda: ventana.realizar(MOVER, tocables))
    papelera.triggered.connect(lambda: ventana.realizar(PAPELERA, tocables))
    menu.exec(posicion)
