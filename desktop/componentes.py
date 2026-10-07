"""Piezas pequeñas que se repiten en varias vistas."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QLabel, QProgressBar, QScrollArea, QTableWidgetItem, QTreeWidgetItem, QVBoxLayout,
    QWidget,
)

from utils.formato import tamano_legible


def etiqueta(texto: str = "", nombre: str = "", ajustar: bool = False) -> QLabel:
    """Un texto. 'nombre' elige el estilo: titulo, subtitulo, suave, grande, aviso, nota."""
    widget = QLabel(texto)
    if nombre:
        widget.setObjectName(nombre)
    widget.setWordWrap(ajustar)
    widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return widget


class Tarjeta(QFrame):
    """Recuadro con borde redondeado donde se agrupan cosas relacionadas."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("tarjeta")
        self.caja = QVBoxLayout(self)
        self.caja.setContentsMargins(18, 16, 18, 16)
        self.caja.setSpacing(8)


def barra_de_nivel(porcentaje: float, nivel: str) -> QProgressBar:
    """Barra de uso. 'nivel' es bueno, aviso o critico y decide el color."""
    barra = QProgressBar()
    barra.setRange(0, 100)
    barra.setValue(int(max(0, min(porcentaje, 100))))
    barra.setTextVisible(False)
    barra.setFixedHeight(12)
    barra.setProperty("nivel", nivel)
    return barra


def nivel_de_uso(porcentaje: float) -> tuple[str, str]:
    """Color y texto de un disco según lo lleno que esté."""
    if porcentaje < 70:
        return "bueno", "Con espacio de sobra"
    if porcentaje < 90:
        return "aviso", "Se está llenando"
    return "critico", "Casi lleno"


def pagina_con_desplazamiento(contenido: QWidget) -> QScrollArea:
    area = QScrollArea()
    area.setWidgetResizable(True)
    # Las páginas se adaptan al ancho de la ventana; solo se desplazan en vertical.
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    area.setWidget(contenido)
    return area


def limpiar_caja(caja) -> None:
    """Quita todos los widgets de un layout."""
    while caja.count():
        elemento = caja.takeAt(0)
        if elemento.widget() is not None:
            elemento.widget().deleteLater()
        elif elemento.layout() is not None:
            limpiar_caja(elemento.layout())


class CeldaTamano(QTableWidgetItem):
    """Celda de tabla que muestra '1.5 GB' pero se ordena por los bytes."""

    def __init__(self, num_bytes: int) -> None:
        super().__init__(tamano_legible(num_bytes))
        self.num_bytes = num_bytes
        self.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    def __lt__(self, otra) -> bool:
        return self.num_bytes < getattr(otra, "num_bytes", 0)


class FilaArbol(QTreeWidgetItem):
    """Fila de árbol cuya columna de tamaño se ordena por bytes y no por texto."""

    COLUMNA_TAMANO = 1

    def __lt__(self, otra) -> bool:
        columna = self.treeWidget().sortColumn() if self.treeWidget() else 0
        if columna == self.COLUMNA_TAMANO:
            return (self.data(columna, Qt.ItemDataRole.UserRole) or 0) < \
                   (otra.data(columna, Qt.ItemDataRole.UserRole) or 0)
        return self.text(columna).lower() < otra.text(columna).lower()
