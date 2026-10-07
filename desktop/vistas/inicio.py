"""Inicio: una tarjeta por disco y el botón grande para escanear."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog, QGridLayout, QHBoxLayout, QLineEdit, QPushButton, QVBoxLayout, QWidget,
)

from core.discos import resumen_discos
from desktop.componentes import (
    Tarjeta, barra_de_nivel, etiqueta, limpiar_caja, nivel_de_uso, pagina_con_desplazamiento,
)
from utils.formato import tamano_legible
from utils.sistema import carpeta_descargas, carpeta_usuario


class VistaInicio(QWidget):
    def __init__(self, ventana) -> None:
        super().__init__()
        self.ventana = ventana

        contenido = QWidget()
        caja = QVBoxLayout(contenido)
        caja.setContentsMargins(28, 24, 28, 24)
        caja.setSpacing(14)
        caja.addWidget(etiqueta("Analizador de disco", "titulo"))
        caja.addWidget(etiqueta("Mira qué ocupa espacio y encuentra archivos que ya no necesitas.",
                                "suave", ajustar=True))

        caja.addWidget(etiqueta("Tus discos", "subtitulo"))
        self._rejilla = QGridLayout()
        self._rejilla.setSpacing(14)
        caja.addLayout(self._rejilla)

        # --- tarjeta de escaneo ---
        tarjeta = Tarjeta()
        tarjeta.caja.addWidget(etiqueta("Analizar una carpeta", "subtitulo"))
        tarjeta.caja.addWidget(etiqueta(
            "Elige qué quieres revisar. El análisis solo lee: no borra ni cambia nada.",
            "suave", ajustar=True))

        atajos = QHBoxLayout()
        home = carpeta_usuario()
        for nombre, ruta in (("Carpeta personal", home), ("Descargas", carpeta_descargas(home)),
                             ("Documentos", home / "Documents"), ("Escritorio", home / "Desktop")):
            if ruta.is_dir():
                boton = QPushButton(nombre)
                boton.setToolTip(str(ruta))
                boton.clicked.connect(lambda _=False, r=ruta: self._campo.setText(str(r)))
                atajos.addWidget(boton)
        atajos.addStretch(1)
        tarjeta.caja.addLayout(atajos)

        fila = QHBoxLayout()
        self._campo = QLineEdit(str(home))
        self._campo.setPlaceholderText("Carpeta que quieres analizar")
        self._campo.returnPressed.connect(self._escanear)
        elegir = QPushButton("Elegir carpeta…")
        elegir.clicked.connect(self._elegir)
        fila.addWidget(self._campo, 1)
        fila.addWidget(elegir)
        tarjeta.caja.addLayout(fila)

        self._boton = QPushButton("Escanear")
        self._boton.setObjectName("grande")
        self._boton.setCursor(Qt.CursorShape.PointingHandCursor)
        self._boton.clicked.connect(self._escanear)
        pie = QHBoxLayout()
        pie.addWidget(self._boton)
        pie.addStretch(1)
        tarjeta.caja.addLayout(pie)

        self._aviso = etiqueta("", "nota", ajustar=True)
        self._aviso.hide()
        tarjeta.caja.addWidget(self._aviso)
        caja.addWidget(tarjeta)
        caja.addStretch(1)

        exterior = QVBoxLayout(self)
        exterior.setContentsMargins(0, 0, 0, 0)
        exterior.addWidget(pagina_con_desplazamiento(contenido))
        self.cargar_discos()

    def cargar_discos(self) -> None:
        limpiar_caja(self._rejilla)
        for indice, disco in enumerate(resumen_discos()):
            nivel, texto = nivel_de_uso(disco.porcentaje)
            tarjeta = Tarjeta()
            cabecera = QHBoxLayout()
            cabecera.addWidget(etiqueta(disco.punto_montaje, "subtitulo"))
            cabecera.addStretch(1)
            cabecera.addWidget(etiqueta(f"{disco.porcentaje:.0f}%", "grande"))
            tarjeta.caja.addLayout(cabecera)
            tarjeta.caja.addWidget(barra_de_nivel(disco.porcentaje, nivel))
            # El estado va escrito, no solo en el color de la barra.
            tarjeta.caja.addWidget(etiqueta(texto))
            tarjeta.caja.addWidget(etiqueta(
                f"{tamano_legible(disco.usado)} usados de {tamano_legible(disco.total)} · "
                f"{tamano_legible(disco.libre)} libres", "suave", ajustar=True))
            boton = QPushButton("Analizar este disco")
            boton.clicked.connect(lambda _=False, r=disco.punto_montaje: self._campo.setText(r))
            tarjeta.caja.addWidget(boton, alignment=Qt.AlignmentFlag.AlignLeft)
            tarjeta.setMinimumWidth(270)
            tarjeta.setMaximumWidth(380)
            self._rejilla.addWidget(tarjeta, indice // 3, indice % 3)
        self._rejilla.setColumnStretch(3, 1)

    def _elegir(self) -> None:
        carpeta = QFileDialog.getExistingDirectory(self, "Carpeta que quieres analizar", self._campo.text())
        if carpeta:
            self._campo.setText(str(Path(carpeta)))

    def _escanear(self) -> None:
        self.ventana.escanear(self._campo.text())

    # ------------------------------------------------------------ avisos de la ventana

    def al_empezar_escaneo(self, aviso: str) -> None:
        self._boton.setEnabled(False)
        self._boton.setText("Escaneando…")
        self._aviso.setText(aviso)
        self._aviso.setVisible(bool(aviso))

    def al_terminar_escaneo(self) -> None:
        self._boton.setEnabled(True)
        self._boton.setText("Escanear")
        self._aviso.hide()

    def al_cambiar_datos(self, rutas) -> None:
        self.cargar_discos()
