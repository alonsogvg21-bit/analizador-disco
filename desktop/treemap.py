"""Mapa de bloques (treemap) dibujado con QPainter.

La posición de cada bloque la calcula desktop/squarify.py y los datos vienen
de core.arbol.arbol_json(). Aquí solo se pinta y se atiende al ratón.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QToolTip, QWidget

from desktop import estilos
from desktop.squarify import Bloque, bloque_en, disponer_arbol
from utils.formato import tamano_legible

ALTO_CABECERA = 18
ANCHO_MINIMO_TEXTO = 54
ALTO_MINIMO_TEXTO = 18


def descripcion(bloque: Bloque) -> str:
    """Texto del recuadro flotante: nombre, clase, tamaño y porcentaje respecto a la carpeta padre."""
    nodo, padre = bloque.nodo, bloque.padre
    tipo = estilos.NOMBRES_TIPO.get(nodo.get("tipo", "otros"), "Otros")
    if nodo.get("agrupado"):
        clase = "Elementos pequeños agrupados"
    elif nodo.get("es_carpeta"):
        clase = f"Carpeta · sobre todo {tipo.lower()}"
    else:
        clase = f"Archivo · {tipo}"
    porcentaje = nodo["tamano"] * 100 / padre["tamano"] if padre.get("tamano") else 0
    texto = "menos del 0.1" if 0 < porcentaje < 0.1 else f"{porcentaje:.1f}"
    lineas = [nodo["nombre"], clase, f"{tamano_legible(nodo['tamano'])} · {texto} % de {padre['nombre']}"]
    if nodo.get("es_carpeta"):
        lineas.append("Clic para entrar")
    return "\n".join(lineas)


class Treemap(QWidget):
    carpeta_elegida = Signal(str)          # ruta de la carpeta en la que se hizo clic
    menu_pedido = Signal(object, QPoint)   # nodo bajo el cursor y posición en pantalla

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._arbol: dict | None = None
        self._bloques: list[Bloque] = []
        self.setMouseTracking(True)
        self.setMinimumSize(320, 240)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def establecer(self, arbol: dict | None) -> None:
        self._arbol = arbol
        self._recalcular()

    def bloques(self) -> list[Bloque]:
        return self._bloques

    def _recalcular(self) -> None:
        self._bloques = (disponer_arbol(self._arbol, self.width(), self.height(), ALTO_CABECERA)
                         if self._arbol else [])
        self.update()

    def resizeEvent(self, evento) -> None:
        self._recalcular()

    # ------------------------------------------------------------ dibujo

    def paintEvent(self, evento) -> None:
        pintor = QPainter(self)
        pintor.fillRect(self.rect(), estilos.color("fondo"))
        if not self._bloques:
            pintor.setPen(estilos.color("suave"))
            texto = "Esta carpeta está vacía." if self._arbol else "Escanea una carpeta para ver el mapa."
            pintor.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, texto)
            return

        fuente = QFont(self.font())
        fuente.setPointSizeF(8.5)
        negrita = QFont(fuente)
        negrita.setBold(True)
        metrica = QFontMetrics(negrita)
        superficie = estilos.color("superficie")

        for bloque in self._bloques:
            r, nodo = bloque.rect, bloque.nodo
            if r.ancho < 1.5 or r.alto < 1.5:
                continue
            # Medio píxel de separación por cada lado, para que se distingan los bloques.
            marco = QRectF(r.x + 0.5, r.y + 0.5, r.ancho - 1, r.alto - 1)

            if bloque.es_grupo:
                pintor.fillRect(marco, estilos.color("pista"))
                pintor.setPen(estilos.color("texto"))
                pintor.setFont(negrita)
                titulo = f"{nodo['nombre']} · {tamano_legible(nodo['tamano'])}"
                pintor.drawText(
                    QRectF(r.x + 5, r.y, r.ancho - 8, ALTO_CABECERA),
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                    metrica.elidedText(titulo, Qt.TextElideMode.ElideRight, int(r.ancho - 10)))
                continue

            relleno = estilos.color_tipo(nodo.get("tipo", "otros"))
            pintor.fillRect(marco, relleno)
            if nodo.get("agrupado"):
                pintor.setPen(QPen(estilos.color("suave"), 1, Qt.PenStyle.DashLine))
                pintor.drawRect(marco.adjusted(0.5, 0.5, -0.5, -0.5))
            elif nodo.get("es_carpeta") and r.ancho > 14 and r.alto > 14:
                # Esquina doblada: distingue una carpeta de un archivo del mismo color.
                pintor.setPen(Qt.PenStyle.NoPen)
                pintor.setBrush(QColor(superficie.red(), superficie.green(), superficie.blue(), 190))
                esquina = marco.topRight()
                pintor.drawPolygon(QPolygonF([
                    esquina, esquina + QPointF(-11, 0), esquina + QPointF(0, 11)]))

            if r.ancho >= ANCHO_MINIMO_TEXTO and r.alto >= ALTO_MINIMO_TEXTO:
                pintor.setPen(estilos.tinta_sobre(relleno) if not nodo.get("agrupado") else estilos.color("texto"))
                pintor.setFont(negrita)
                ancho_texto = int(r.ancho - 10)
                pintor.drawText(QRectF(r.x + 5, r.y + 2, ancho_texto, 15),
                                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                                metrica.elidedText(nodo["nombre"], Qt.TextElideMode.ElideRight, ancho_texto))
                if r.alto >= 36:
                    pintor.setFont(fuente)
                    pintor.drawText(QRectF(r.x + 5, r.y + 17, ancho_texto, 15),
                                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                                    tamano_legible(nodo["tamano"]))

    # ------------------------------------------------------------ ratón

    def _bloque_bajo(self, punto) -> Bloque | None:
        return bloque_en(self._bloques, punto.x(), punto.y())

    def mouseMoveEvent(self, evento) -> None:
        bloque = self._bloque_bajo(evento.position())
        if bloque is None:
            QToolTip.hideText()
            self.unsetCursor()
            return
        QToolTip.showText(evento.globalPosition().toPoint(), descripcion(bloque), self)
        if bloque.nodo.get("es_carpeta"):
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.unsetCursor()

    def mousePressEvent(self, evento) -> None:
        if evento.button() != Qt.MouseButton.LeftButton:
            return
        bloque = self._bloque_bajo(evento.position())
        if bloque and bloque.nodo.get("es_carpeta") and bloque.nodo.get("ruta"):
            self.carpeta_elegida.emit(bloque.nodo["ruta"])

    def contextMenuEvent(self, evento) -> None:
        bloque = self._bloque_bajo(evento.pos())
        if bloque and bloque.nodo.get("ruta"):
            self.menu_pedido.emit(bloque.nodo, evento.globalPos())


class Leyenda(QWidget):
    """Fila con el color de cada tipo de archivo y su nombre."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._caja = QHBoxLayout(self)
        self._caja.setContentsMargins(0, 4, 0, 0)
        self._caja.setSpacing(14)
        self.repintar()

    def repintar(self) -> None:
        """Se llama al cambiar de tema, porque los colores cambian."""
        while self._caja.count():
            elemento = self._caja.takeAt(0)
            if elemento.widget():
                elemento.widget().setParent(None)   # desaparece ya, sin esperar al siguiente ciclo
        for tipo, nombre in estilos.NOMBRES_TIPO.items():
            borde = f"1px dashed {estilos.color('suave').name()}" if tipo == "varios" else "none"
            muestra = QLabel()
            muestra.setFixedSize(14, 14)
            muestra.setStyleSheet(
                f"background: {estilos.color_tipo(tipo).name()}; border: {borde}; border-radius: 3px;")
            self._caja.addWidget(muestra)
            self._caja.addWidget(QLabel(nombre))
        self._caja.addStretch(1)
