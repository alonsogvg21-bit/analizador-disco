"""Gráficas dibujadas con QPainter: barras por tipo de archivo y línea de uso en el tiempo."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from desktop import estilos
from utils.formato import diferencia_en_mb, tamano_legible


class GraficaBarras(QWidget):
    """Barras horizontales: una por categoría, de un solo color, con el valor escrito al lado."""

    ALTO_FILA = 34

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # (etiqueta, porcentaje 0-100, texto del valor, texto del recuadro flotante)
        self._filas: list[tuple[str, float, str, str]] = []
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def establecer(self, filas: list[tuple[str, float, str, str]]) -> None:
        self._filas = filas
        self.setFixedHeight(max(len(filas) * self.ALTO_FILA + 8, 60))
        self.update()

    def paintEvent(self, evento) -> None:
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        ancho_etiqueta, ancho_valor = 120, 250
        ancho_barra = max(self.width() - ancho_etiqueta - ancho_valor - 16, 40)
        for indice, (nombre, porcentaje, valor, _) in enumerate(self._filas):
            y = indice * self.ALTO_FILA + 4
            pintor.setPen(estilos.color("texto"))
            pintor.drawText(QRectF(0, y, ancho_etiqueta, 26), Qt.AlignmentFlag.AlignVCenter, nombre)
            pista = QRectF(ancho_etiqueta, y + 6, ancho_barra, 14)
            pintor.setPen(Qt.PenStyle.NoPen)
            pintor.setBrush(estilos.color("pista"))
            pintor.drawRoundedRect(pista, 4, 4)
            if porcentaje > 0:
                pintor.setBrush(estilos.color("acento"))
                pintor.drawRoundedRect(
                    QRectF(pista.x(), pista.y(), max(pista.width() * min(porcentaje, 100) / 100, 2), 14), 4, 4)
            pintor.setPen(estilos.color("suave"))
            pintor.drawText(QRectF(ancho_etiqueta + ancho_barra + 12, y, ancho_valor, 26),
                            Qt.AlignmentFlag.AlignVCenter, valor)

    def mouseMoveEvent(self, evento) -> None:
        indice = int((evento.position().y() - 4) // self.ALTO_FILA)
        if 0 <= indice < len(self._filas):
            QToolTip.showText(evento.globalPosition().toPoint(), self._filas[indice][3], self)
        else:
            QToolTip.hideText()


class GraficaLinea(QWidget):
    """Espacio ocupado en cada escaneo guardado. Una sola serie: no necesita leyenda."""

    MARGEN = (74, 18, 20, 34)   # izquierda, arriba, derecha, abajo

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._puntos: list[tuple[datetime, int]] = []
        self._posiciones: list[QPointF] = []
        self.setMouseTracking(True)
        self.setMinimumHeight(250)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def establecer(self, puntos: list[tuple[datetime, int]]) -> None:
        self._puntos = puntos
        self.update()

    def paintEvent(self, evento) -> None:
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._posiciones = []
        if not self._puntos:
            pintor.setPen(estilos.color("suave"))
            pintor.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                            "Todavía no hay escaneos guardados de esta carpeta.")
            return

        izq, arr, der, aba = self.MARGEN
        ancho, alto = self.width() - izq - der, self.height() - arr - aba
        tiempos = [p[0].timestamp() for p in self._puntos]
        valores = [p[1] for p in self._puntos]
        t0, t1 = min(tiempos), max(tiempos)
        v0, v1 = min(valores), max(valores)
        # El eje se ajusta a los datos, con holgura, para que los cambios se aprecien.
        holgura = (v1 - v0) * 0.15 or max(v1 * 0.05, 1)
        v0, v1 = max(0, v0 - holgura), v1 + holgura

        def x(t: float) -> float:
            return izq + ancho / 2 if t1 == t0 else izq + (t - t0) / (t1 - t0) * ancho

        def y(v: float) -> float:
            return arr + alto - (v - v0) / (v1 - v0) * alto

        pequena = QFont(self.font())
        pequena.setPointSizeF(8.5)
        pintor.setFont(pequena)
        for paso in range(4):
            valor = v0 + (v1 - v0) * paso / 3
            pintor.setPen(QPen(estilos.color("borde"), 1))
            pintor.drawLine(QPointF(izq, y(valor)), QPointF(izq + ancho, y(valor)))
            pintor.setPen(estilos.color("suave"))
            pintor.drawText(QRectF(0, y(valor) - 9, izq - 8, 18),
                            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, tamano_legible(valor))

        extremos = [0, len(self._puntos) - 1] if len(self._puntos) > 1 else [0]
        for posicion, indice in enumerate(extremos):
            texto = f"{self._puntos[indice][0]:%d/%m/%Y}"
            alineacion = (Qt.AlignmentFlag.AlignHCenter if len(extremos) == 1
                          else Qt.AlignmentFlag.AlignLeft if posicion == 0 else Qt.AlignmentFlag.AlignRight)
            caja = QRectF(x(tiempos[indice]) - 60, arr + alto + 8, 120, 18)
            if len(extremos) > 1:
                caja = QRectF(x(tiempos[indice]) - (0 if posicion == 0 else 120), arr + alto + 8, 120, 18)
            pintor.drawText(caja, alineacion | Qt.AlignmentFlag.AlignVCenter, texto)

        self._posiciones = [QPointF(x(t), y(v)) for t, v in zip(tiempos, valores)]
        if len(self._posiciones) > 1:
            camino = QPainterPath(self._posiciones[0])
            for punto in self._posiciones[1:]:
                camino.lineTo(punto)
            pintor.setPen(QPen(estilos.color("acento"), 2, Qt.PenStyle.SolidLine,
                               Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            pintor.setBrush(Qt.BrushStyle.NoBrush)
            pintor.drawPath(camino)
        pintor.setPen(QPen(estilos.color("superficie"), 2))
        pintor.setBrush(estilos.color("acento"))
        for punto in self._posiciones:
            pintor.drawEllipse(punto, 4.5, 4.5)

    def mouseMoveEvent(self, evento) -> None:
        cursor = evento.position()
        for indice, punto in enumerate(self._posiciones):
            # La zona sensible es mayor que el punto dibujado.
            if abs(punto.x() - cursor.x()) <= 14 and abs(punto.y() - cursor.y()) <= 14:
                fecha, valor = self._puntos[indice]
                cambio = ("Primer escaneo guardado" if indice == 0 else
                          f"{diferencia_en_mb(valor - self._puntos[indice - 1][1])} desde el anterior")
                QToolTip.showText(evento.globalPosition().toPoint(),
                                  f"{fecha:%d/%m/%Y %H:%M}\n{tamano_legible(valor)}\n{cambio}", self)
                return
        QToolTip.hideText()
