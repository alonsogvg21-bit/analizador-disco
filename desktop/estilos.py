"""Colores y hoja de estilos de la aplicación, en modo claro y oscuro.

Todos los colores salen de aquí: los widgets normales los reciben por la hoja
de estilos (QSS) y los que se dibujan a mano (treemap, gráficas) los piden
con color() y color_tipo().
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import QApplication

MODOS = ("sistema", "claro", "oscuro")

_CLARO = {
    "fondo": "#f4f4f1", "superficie": "#fcfcfb", "borde": "#dddcd6", "texto": "#0b0b0b",
    "suave": "#52514e", "acento": "#2a78d6", "sobre_acento": "#ffffff", "pista": "#e8e7e2",
    "bueno": "#0ca30c", "aviso": "#fab219", "critico": "#d03b3b", "seleccion": "#cde2fb",
}
_OSCURO = {
    "fondo": "#0d0d0d", "superficie": "#1a1a19", "borde": "#383835", "texto": "#ffffff",
    "suave": "#c3c2b7", "acento": "#3987e5", "sobre_acento": "#ffffff", "pista": "#2e2e2c",
    "bueno": "#0ca30c", "aviso": "#fab219", "critico": "#d03b3b", "seleccion": "#184f95",
}
# Un color por tipo de archivo. "otros" es gris a propósito: no es una clase concreta.
_TIPOS_CLARO = {
    "videos": "#2a78d6", "imagenes": "#eb6834", "documentos": "#1baf7a", "comprimidos": "#eda100",
    "instaladores": "#e87ba4", "codigo": "#008300", "otros": "#a3a29b", "varios": "#e8e7e2",
}
_TIPOS_OSCURO = {
    "videos": "#3987e5", "imagenes": "#d95926", "documentos": "#199e70", "comprimidos": "#c98500",
    "instaladores": "#d55181", "codigo": "#008300", "otros": "#6b6a65", "varios": "#2e2e2c",
}

NOMBRES_TIPO = {
    "videos": "Videos", "imagenes": "Imágenes", "documentos": "Documentos",
    "comprimidos": "Comprimidos", "instaladores": "Instaladores", "codigo": "Código",
    "otros": "Otros", "varios": "Varios pequeños",
}

_actual = {"oscuro": False}

_QSS = """
* {{ font-family: "Segoe UI", "Noto Sans", "DejaVu Sans", sans-serif; font-size: 10.5pt; }}
QMainWindow, QDialog, QWidget#pagina {{ background: {fondo}; color: {texto}; }}
QWidget {{ color: {texto}; }}
QLabel {{ background: transparent; }}
QLabel#titulo {{ font-size: 17pt; font-weight: 700; }}
QLabel#subtitulo {{ font-size: 12pt; font-weight: 600; }}
QLabel#suave {{ color: {suave}; }}
QLabel#grande {{ font-size: 18pt; font-weight: 700; }}
QLabel#aviso {{ color: {critico}; font-weight: 600; }}
QLabel#nota {{ background: {pista}; border-left: 4px solid {aviso}; padding: 8px 10px; }}

QListWidget#lateral {{ background: {superficie}; border: none; border-right: 1px solid {borde}; outline: 0; padding: 8px 0; }}
QListWidget#lateral::item {{ padding: 11px 18px; border-left: 4px solid transparent; }}
QListWidget#lateral::item:hover {{ background: {pista}; }}
QListWidget#lateral::item:selected {{ background: {pista}; color: {texto}; border-left: 4px solid {acento}; font-weight: 600; }}

QFrame#tarjeta {{ background: {superficie}; border: 1px solid {borde}; border-radius: 10px; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}

QPushButton {{ background: {superficie}; border: 1px solid {borde}; border-radius: 7px; padding: 7px 14px; }}
QPushButton:hover {{ border-color: {acento}; }}
QPushButton:disabled {{ color: {suave}; background: {pista}; }}
QPushButton#principal {{ background: {acento}; border-color: {acento}; color: {sobre_acento}; font-weight: 600; }}
QPushButton#grande {{ background: {acento}; border-color: {acento}; color: {sobre_acento}; font-weight: 700; font-size: 13pt; padding: 12px 36px; }}
QPushButton#peligro {{ background: {critico}; border-color: {critico}; color: #ffffff; font-weight: 600; }}
QPushButton#miga {{ border: none; background: transparent; color: {acento}; padding: 4px 6px; }}
QPushButton#miga:hover {{ text-decoration: underline; }}

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTimeEdit {{ background: {fondo}; border: 1px solid {borde}; border-radius: 7px; padding: 6px 8px; selection-background-color: {acento}; }}
QComboBox QAbstractItemView {{ background: {superficie}; border: 1px solid {borde}; selection-background-color: {seleccion}; selection-color: {texto}; }}

QTreeWidget, QTableWidget, QListWidget#lista {{ background: {superficie}; alternate-background-color: {fondo}; border: 1px solid {borde}; border-radius: 8px; gridline-color: {borde}; outline: 0; }}
QTreeWidget::item, QTableWidget::item {{ padding: 4px 6px; }}
QTreeWidget::item:selected, QTableWidget::item:selected, QListWidget#lista::item:selected {{ background: {seleccion}; color: {texto}; }}
QHeaderView::section {{ background: {pista}; color: {suave}; border: none; border-bottom: 1px solid {borde}; padding: 6px 8px; font-weight: 600; }}
QTableCornerButton::section {{ background: {pista}; border: none; }}

QTabWidget::pane {{ border: none; }}
QTabBar::tab {{ background: transparent; color: {suave}; padding: 9px 16px; border-bottom: 3px solid transparent; font-weight: 600; }}
QTabBar::tab:selected {{ color: {texto}; border-bottom: 3px solid {acento}; }}

QProgressBar {{ background: {pista}; border: none; border-radius: 6px; height: 12px; text-align: center; }}
QProgressBar::chunk {{ background: {acento}; border-radius: 6px; }}
QProgressBar[nivel="bueno"]::chunk {{ background: {bueno}; }}
QProgressBar[nivel="aviso"]::chunk {{ background: {aviso}; }}
QProgressBar[nivel="critico"]::chunk {{ background: {critico}; }}

QStatusBar {{ background: {superficie}; border-top: 1px solid {borde}; }}
QStatusBar::item {{ border: none; }}
QStatusBar QLabel {{ padding: 4px 10px; }}
QToolTip {{ background: {superficie}; color: {texto}; border: 1px solid {borde}; padding: 6px; }}
QMenu {{ background: {superficie}; border: 1px solid {borde}; padding: 4px; }}
QMenu::item {{ padding: 6px 22px; }}
QMenu::item:selected {{ background: {seleccion}; color: {texto}; }}
QMenu::item:disabled {{ color: {suave}; }}
QCheckBox, QRadioButton {{ spacing: 8px; }}
QScrollBar:vertical {{ background: transparent; width: 12px; }}
QScrollBar::handle:vertical {{ background: {borde}; border-radius: 5px; min-height: 30px; margin: 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 12px; }}
QScrollBar::handle:horizontal {{ background: {borde}; border-radius: 5px; min-width: 30px; margin: 2px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
"""


def _sistema_en_oscuro() -> bool:
    try:
        return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except AttributeError:  # versiones de Qt anteriores a la 6.5
        return False


def aplicar(app: QApplication, modo: str = "sistema") -> None:
    """Aplica el modo claro u oscuro a toda la aplicación."""
    _actual["oscuro"] = _sistema_en_oscuro() if modo == "sistema" else modo == "oscuro"
    app.setStyleSheet(_QSS.format(**(_OSCURO if _actual["oscuro"] else _CLARO)))


def es_oscuro() -> bool:
    return _actual["oscuro"]


def color(nombre: str) -> QColor:
    return QColor((_OSCURO if _actual["oscuro"] else _CLARO)[nombre])


def color_tipo(tipo: str) -> QColor:
    paleta = _TIPOS_OSCURO if _actual["oscuro"] else _TIPOS_CLARO
    return QColor(paleta.get(tipo, paleta["otros"]))


def tinta_sobre(fondo: QColor) -> QColor:
    """Negro o blanco, lo que mejor se lea encima de ese color."""
    luminosidad = 0.299 * fondo.red() + 0.587 * fondo.green() + 0.114 * fondo.blue()
    return QColor("#0b0b0b") if luminosidad > 110 else QColor("#ffffff")
