"""Configuración: apariencia, escaneo y alertas de salud."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QHBoxLayout, QLabel, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

from core.alertas import guardar_config, leer_config
from core.registro import anotar, ruta_registro
from desktop.asistente import AsistenteInicial
from core.historial import carpeta_de_datos
from desktop.componentes import Tarjeta, etiqueta, pagina_con_desplazamiento
from utils.info import NOMBRE, VERSION

TEMAS = (("Igual que el sistema", "sistema"), ("Claro", "claro"), ("Oscuro", "oscuro"))


class VistaConfiguracion(QWidget):
    def __init__(self, ventana) -> None:
        super().__init__()
        self.ventana = ventana

        contenido = QWidget()
        caja = QVBoxLayout(contenido)
        caja.setContentsMargins(28, 24, 28, 24)
        caja.setSpacing(14)
        caja.addWidget(etiqueta("Configuración", "titulo"))

        # --- apariencia ---
        tarjeta = Tarjeta()
        tarjeta.caja.addWidget(etiqueta("Apariencia", "subtitulo"))
        fila = QHBoxLayout()
        fila.addWidget(QLabel("Tema"))
        self._tema = QComboBox()
        for nombre, modo in TEMAS:
            self._tema.addItem(nombre, modo)
        self._tema.setCurrentIndex([m for _, m in TEMAS].index(ventana.tema()))
        self._tema.currentIndexChanged.connect(lambda: ventana.cambiar_tema(self._tema.currentData()))
        fila.addWidget(self._tema)
        fila.addStretch(1)
        tarjeta.caja.addLayout(fila)
        caja.addWidget(tarjeta)

        # --- escaneo ---
        tarjeta = Tarjeta()
        tarjeta.caja.addWidget(etiqueta("Escaneo", "subtitulo"))
        self._duplicados = QCheckBox("Buscar archivos duplicados al escanear")
        self._duplicados.setChecked(ventana.buscar_duplicados_al_escanear())
        self._duplicados.toggled.connect(
            lambda marcado: ventana.ajustes.setValue("duplicados", "true" if marcado else "false"))
        tarjeta.caja.addWidget(self._duplicados)
        tarjeta.caja.addWidget(etiqueta(
            "Más completo, pero tarda bastante más en carpetas grandes. Si lo desactivas, puedes "
            "buscarlos cuando quieras desde la sección Duplicados.", "suave", ajustar=True))
        caja.addWidget(tarjeta)

        # --- seguridad ---
        tarjeta = Tarjeta()
        tarjeta.caja.addWidget(etiqueta("Seguridad", "subtitulo"))
        self._simular = QCheckBox("Empezar siempre en modo simulación al mover o borrar")
        self._simular.setChecked(ventana.simular_por_defecto())
        self._simular.toggled.connect(
            lambda marcado: ventana.ajustes.setValue("simular_por_defecto", "true" if marcado else "false"))
        tarjeta.caja.addWidget(self._simular)
        tarjeta.caja.addWidget(etiqueta(
            "Con esta opción, la ventana de confirmación aparece con «Solo simular» marcado: para "
            "tocar algo de verdad hay que desmarcarlo. Recomendado.", "suave", ajustar=True))
        fila = QHBoxLayout()
        registro_boton = QPushButton("Abrir el registro de acciones")
        registro_boton.setToolTip(str(ruta_registro()))
        registro_boton.clicked.connect(self._abrir_registro)
        asistente = QPushButton("Ver de nuevo la introducción")
        asistente.clicked.connect(lambda: AsistenteInicial(ventana).exec())
        fila.addWidget(registro_boton)
        fila.addWidget(asistente)
        fila.addStretch(1)
        tarjeta.caja.addLayout(fila)
        tarjeta.caja.addWidget(etiqueta(
            "El registro anota cada elemento que se mueve o se envía a la papelera. Se guarda solo "
            "en tu equipo.", "suave", ajustar=True))
        caja.addWidget(tarjeta)

        # --- alertas de salud ---
        config = leer_config()
        tarjeta = Tarjeta()
        tarjeta.caja.addWidget(etiqueta("Alertas de salud del disco", "subtitulo"))
        self._escritorio = QCheckBox("Mostrar una notificación de escritorio cuando un disco empeore")
        self._escritorio.setChecked(config.escritorio)
        tarjeta.caja.addWidget(self._escritorio)
        fila = QHBoxLayout()
        self._automatico = QCheckBox("Límite de temperatura automático (55 °C en SATA, 70 °C en NVMe)")
        self._automatico.setChecked(config.temperatura_limite is None)
        self._grados = QSpinBox()
        self._grados.setRange(20, 100)
        self._grados.setSuffix(" °C")
        self._grados.setValue(config.temperatura_limite or 55)
        self._grados.setEnabled(config.temperatura_limite is not None)
        fila.addWidget(self._automatico)
        fila.addWidget(self._grados)
        fila.addStretch(1)
        tarjeta.caja.addLayout(fila)
        tarjeta.caja.addWidget(etiqueta(
            "El aviso por correo se configura desde la terminal: python main.py cli salud alertas --help",
            "suave", ajustar=True))
        self._escritorio.toggled.connect(self._guardar_alertas)
        self._automatico.toggled.connect(self._guardar_alertas)
        self._grados.valueChanged.connect(self._guardar_alertas)
        caja.addWidget(tarjeta)

        # --- información ---
        tarjeta = Tarjeta()
        tarjeta.caja.addWidget(etiqueta(f"{NOMBRE} {VERSION}", "subtitulo"))
        acerca = QPushButton("Acerca de…")
        acerca.clicked.connect(ventana.acerca_de)
        fila = QHBoxLayout()
        fila.addWidget(acerca)
        fila.addStretch(1)
        tarjeta.caja.addLayout(fila)
        tarjeta.caja.addWidget(etiqueta(f"Historial y preferencias: {carpeta_de_datos()}", ajustar=True))
        tarjeta.caja.addWidget(etiqueta(
            "Otras formas de usar el programa: añade  cli --help  (terminal) o  web  "
            "(interfaz web local) al comando con el que lo abres.", "suave", ajustar=True))
        caja.addWidget(tarjeta)
        caja.addStretch(1)

        exterior = QVBoxLayout(self)
        exterior.setContentsMargins(0, 0, 0, 0)
        exterior.addWidget(pagina_con_desplazamiento(contenido))

    def _abrir_registro(self) -> None:
        archivo = ruta_registro()
        if not archivo.exists():
            # Todavía no se ha movido ni borrado nada: se crea vacío para poder abrirlo.
            anotar("registro", "creado")
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(archivo)))

    def _guardar_alertas(self) -> None:
        self._grados.setEnabled(not self._automatico.isChecked())
        # Se parte de lo guardado para no perder la configuración del correo.
        config = leer_config()
        config.escritorio = self._escritorio.isChecked()
        config.temperatura_limite = None if self._automatico.isChecked() else self._grados.value()
        guardar_config(config)
