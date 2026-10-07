"""Asistente de la primera ejecución: qué hace el programa y qué no hará nunca."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox, QDialog, QHBoxLayout, QLabel, QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from desktop.componentes import etiqueta
from utils.info import NOMBRE

# Si algún día cambia el contenido de forma importante, se sube este número y
# el asistente vuelve a mostrarse una vez a quien ya lo había visto.
VERSION_ASISTENTE = 1

PAGINAS = (
    ("Bienvenido", (
        f"{NOMBRE} te enseña qué ocupa espacio en tus discos y te ayuda a encontrar "
        "archivos que probablemente ya no necesitas.",
        "•  Mira qué carpetas y archivos pesan más, con un mapa de bloques.",
        "•  Encuentra temporales, caché, duplicados y archivos que no usas desde hace mucho.",
        "•  Consulta la salud de tus discos.",
    )),
    ("Tú decides: nada se borra sin tu permiso", (
        "Por defecto el programa solo lee. Escanear, explorar y buscar basura no cambia nada en tu equipo.",
        "•  Antes de mover o borrar verás siempre la lista exacta y el espacio afectado.",
        "•  El modo simulación empieza activado: te enseña qué pasaría sin tocar nada.",
        "•  Borrar significa enviar a la papelera; nunca se borra de forma definitiva.",
        "•  Las acciones de más de 1 GB piden confirmar dos veces.",
        "•  Las carpetas del sistema y tus carpetas de Documentos, Escritorio e Imágenes están protegidas.",
        "•  Todo lo que se mueve o se borra queda anotado en un registro, en tu equipo.",
    )),
    ("Privacidad y responsabilidad", (
        "Este programa no envía datos a ningún servidor. Todo el análisis se hace en tu equipo y "
        "no hay cuentas, anuncios ni estadísticas de uso.",
        "Solo pide permisos de administrador si quieres ver la salud de un disco que lo exige, "
        "y antes te explica por qué.",
        "Aviso: el programa se ofrece tal cual, sin garantía. Aunque está pensado para ser prudente, "
        "revisa lo que marcas antes de confirmar y ten copia de seguridad de lo que te importa. "
        "Las decisiones sobre qué borrar o mover son tuyas.",
    )),
)


class AsistenteInicial(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Te damos la bienvenida a {NOMBRE}")
        self.setMinimumSize(600, 440)
        self.setModal(True)

        caja = QVBoxLayout(self)
        caja.setContentsMargins(26, 22, 26, 18)
        caja.setSpacing(12)
        self.paginas = QStackedWidget()
        for titulo, parrafos in PAGINAS:
            pagina = QWidget()
            contenido = QVBoxLayout(pagina)
            contenido.setContentsMargins(0, 0, 0, 0)
            contenido.setSpacing(10)
            contenido.addWidget(etiqueta(titulo, "titulo", ajustar=True))
            for parrafo in parrafos:
                contenido.addWidget(etiqueta(parrafo, ajustar=True))
            contenido.addStretch(1)
            self.paginas.addWidget(pagina)
        caja.addWidget(self.paginas, 1)

        self.entendido = QCheckBox("He leído lo anterior y entiendo que yo decido qué se mueve o se borra.")
        self.entendido.toggled.connect(self._actualizar)
        caja.addWidget(self.entendido)

        pie = QHBoxLayout()
        self._paso = QLabel()
        self._paso.setObjectName("suave")
        pie.addWidget(self._paso)
        pie.addStretch(1)
        self.atras = QPushButton("Atrás")
        self.atras.clicked.connect(lambda: self._ir(-1))
        self.siguiente = QPushButton()
        self.siguiente.setObjectName("principal")
        self.siguiente.clicked.connect(self._avanzar)
        pie.addWidget(self.atras)
        pie.addWidget(self.siguiente)
        caja.addLayout(pie)
        self._actualizar()

    def _ultima(self) -> bool:
        return self.paginas.currentIndex() == self.paginas.count() - 1

    def _ir(self, pasos: int) -> None:
        self.paginas.setCurrentIndex(self.paginas.currentIndex() + pasos)
        self._actualizar()

    def _avanzar(self) -> None:
        if self._ultima():
            self.accept()
        else:
            self._ir(1)

    def _actualizar(self) -> None:
        ultima = self._ultima()
        self._paso.setText(f"Paso {self.paginas.currentIndex() + 1} de {self.paginas.count()}")
        self.atras.setEnabled(self.paginas.currentIndex() > 0)
        self.entendido.setVisible(ultima)
        self.siguiente.setText("Empezar" if ultima else "Siguiente")
        # No se puede empezar sin marcar la casilla de la última página.
        self.siguiente.setEnabled(not ultima or self.entendido.isChecked())


def mostrar_si_hace_falta(ventana) -> bool:
    """Muestra el asistente la primera vez. Devuelve False si el usuario lo cierra sin aceptar."""
    visto = int(ventana.ajustes.value("asistente_visto", 0) or 0)
    if visto >= VERSION_ASISTENTE:
        return True
    if AsistenteInicial(ventana).exec() != QDialog.DialogCode.Accepted:
        return False
    ventana.ajustes.setValue("asistente_visto", VERSION_ASISTENTE)
    return True
