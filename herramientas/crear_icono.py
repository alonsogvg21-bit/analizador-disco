"""Dibuja el icono de la aplicación (un pequeño mapa de bloques) y lo guarda en PNG e ICO.

Solo hace falta ejecutarlo si se quiere cambiar el icono:
    python herramientas/crear_icono.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPainterPath

DESTINO = Path(__file__).resolve().parent.parent / "desktop" / "recursos"
LADO = 256
# (x, y, ancho, alto, color) en una cuadrícula de 100 x 100.
BLOQUES = (
    (0, 0, 56, 62, "#2a78d6"),     # azul: el bloque grande
    (60, 0, 40, 36, "#eb6834"),    # naranja
    (60, 40, 40, 22, "#eda100"),   # amarillo
    (0, 66, 34, 34, "#1baf7a"),    # verde agua
    (38, 66, 30, 34, "#e87ba4"),   # rosa
    (72, 66, 28, 34, "#a3a29b"),   # gris
)


def dibujar(lado: int = LADO) -> QImage:
    imagen = QImage(lado, lado, QImage.Format.Format_ARGB32)
    imagen.fill(Qt.GlobalColor.transparent)
    pintor = QPainter(imagen)
    pintor.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Fondo redondeado oscuro; los bloques se recortan con la misma forma.
    margen = lado * 0.04
    marco = QRectF(margen, margen, lado - 2 * margen, lado - 2 * margen)
    forma = QPainterPath()
    forma.addRoundedRect(marco, lado * 0.16, lado * 0.16)
    pintor.fillPath(forma, QColor("#1a1a19"))

    interior = marco.adjusted(lado * 0.07, lado * 0.07, -lado * 0.07, -lado * 0.07)
    escala_x, escala_y = interior.width() / 100, interior.height() / 100
    pintor.setPen(Qt.PenStyle.NoPen)
    for x, y, ancho, alto, color in BLOQUES:
        pintor.setBrush(QColor(color))
        pintor.drawRoundedRect(
            QRectF(interior.x() + x * escala_x, interior.y() + y * escala_y,
                   ancho * escala_x, alto * escala_y), lado * 0.025, lado * 0.025)
    pintor.end()
    return imagen


def main() -> int:
    app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    DESTINO.mkdir(parents=True, exist_ok=True)
    imagen = dibujar()
    correcto = imagen.save(str(DESTINO / "icono.png")) and imagen.save(str(DESTINO / "icono.ico"))
    print("Icono guardado en", DESTINO if correcto else "(no se pudo guardar)")
    del app
    return 0 if correcto else 1


if __name__ == "__main__":
    sys.exit(main())
