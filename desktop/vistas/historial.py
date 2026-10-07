"""Historial: uso a lo largo del tiempo y comparación entre dos escaneos guardados."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLabel, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from core.historial import comparar, listar_escaneos
from desktop.componentes import CeldaTamano, Tarjeta, etiqueta
from desktop.graficas import GraficaLinea
from utils.formato import diferencia_en_mb, tamano_legible

MB = 1024 * 1024
MAXIMO_CAMBIOS = 200


class CeldaCambio(QTableWidgetItem):
    """Muestra '+12.0 MB' y se ordena por la cantidad real."""

    def __init__(self, diferencia: int) -> None:
        flecha = "▲ " if diferencia > 0 else "▼ " if diferencia < 0 else ""
        super().__init__(flecha + diferencia_en_mb(diferencia))
        self.diferencia = diferencia
        self.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    def __lt__(self, otra) -> bool:
        return self.diferencia < getattr(otra, "diferencia", 0)


class VistaHistorial(QWidget):
    def __init__(self, ventana) -> None:
        super().__init__()
        self.ventana = ventana
        self._escaneos = []

        caja = QVBoxLayout(self)
        caja.setContentsMargins(28, 24, 28, 16)
        caja.setSpacing(10)
        caja.addWidget(etiqueta("Historial", "titulo"))
        self._carpeta = etiqueta("", "suave", ajustar=True)
        caja.addWidget(self._carpeta)

        tarjeta = Tarjeta()
        tarjeta.caja.addWidget(etiqueta("Uso a lo largo del tiempo", "subtitulo"))
        self.grafica = GraficaLinea()
        tarjeta.caja.addWidget(self.grafica)
        caja.addWidget(tarjeta)

        caja.addWidget(etiqueta("Comparar dos fechas", "subtitulo"))
        fila = QHBoxLayout()
        self._antes, self._despues = QComboBox(), QComboBox()
        for texto, combo in (("Antes", self._antes), ("Después", self._despues)):
            fila.addWidget(QLabel(texto))
            combo.setMinimumWidth(230)
            combo.currentIndexChanged.connect(self._comparar)
            fila.addWidget(combo)
            fila.addSpacing(12)
        fila.addStretch(1)
        caja.addLayout(fila)
        self._resumen = etiqueta("", ajustar=True)
        caja.addWidget(self._resumen)

        self.tabla = QTableWidget(0, 4)
        self.tabla.setHorizontalHeaderLabels(["Carpeta", "Antes", "Después", "Cambio"])
        self.tabla.setAlternatingRowColors(True)
        self.tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabla.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tabla.setSortingEnabled(True)
        caja.addWidget(self.tabla, 1)

    def recargar(self) -> None:
        resultado = self.ventana.resultado
        if resultado is None:
            self._carpeta.setText("Escanea una carpeta para ver su historial. Cada escaneo que termina se guarda solo.")
            self._escaneos = []
        else:
            self._escaneos = listar_escaneos(resultado.raiz)
            self._carpeta.setText(f"Escaneos guardados de {resultado.raiz}: {len(self._escaneos)}.")
        self.grafica.establecer([(e.fecha, e.tamano_total) for e in self._escaneos])

        for combo in (self._antes, self._despues):
            combo.blockSignals(True)
            combo.clear()
            for escaneo in self._escaneos:
                combo.addItem(f"{escaneo.fecha:%d/%m/%Y %H:%M} — {tamano_legible(escaneo.tamano_total)}", escaneo.id)
            combo.blockSignals(False)
        if len(self._escaneos) >= 2:
            # Por defecto, los dos últimos.
            self._antes.setCurrentIndex(len(self._escaneos) - 2)
            self._despues.setCurrentIndex(len(self._escaneos) - 1)
        self._comparar()

    def _comparar(self) -> None:
        self.tabla.setSortingEnabled(False)
        self.tabla.setRowCount(0)
        if len(self._escaneos) < 2:
            self._resumen.setText("Hacen falta al menos dos escaneos guardados de esta carpeta para comparar.")
            return
        antes, despues = self._antes.currentData(), self._despues.currentData()
        if antes == despues:
            self._resumen.setText("Elige dos escaneos distintos.")
            return
        try:
            c = comparar(antes, despues, minimo=MB)
        except ValueError as problema:
            self._resumen.setText(str(problema))
            return

        verbo = "creció" if c.diferencia_total > 0 else "disminuyó" if c.diferencia_total < 0 else "no cambió"
        cuanto = f" {abs(c.diferencia_total) / MB:,.1f} MB" if c.diferencia_total else ""
        resto = "" if c.cambios else " Ninguna subcarpeta cambió 1 MB o más."
        self._resumen.setText(
            f"Entre el {c.antes.fecha:%d/%m/%Y %H:%M} y el {c.despues.fecha:%d/%m/%Y %H:%M} la carpeta "
            f"{verbo}{cuanto} (de {tamano_legible(c.antes.tamano_total)} a "
            f"{tamano_legible(c.despues.tamano_total)}).{resto}")

        cambios = c.cambios[:MAXIMO_CAMBIOS]
        self.tabla.setRowCount(len(cambios))
        for fila, cambio in enumerate(cambios):
            nota = "  (nueva)" if cambio.antes == 0 else "  (ya no existe)" if cambio.despues == 0 else ""
            celda = QTableWidgetItem(cambio.ruta + nota)
            celda.setToolTip(cambio.ruta)
            self.tabla.setItem(fila, 0, celda)
            self.tabla.setItem(fila, 1, CeldaTamano(cambio.antes))
            self.tabla.setItem(fila, 2, CeldaTamano(cambio.despues))
            self.tabla.setItem(fila, 3, CeldaCambio(cambio.diferencia))
        for columna in (1, 2, 3):
            self.tabla.resizeColumnToContents(columna)
        self.tabla.setSortingEnabled(True)

    def al_mostrar(self) -> None:
        self.recargar()

    def al_escanear(self) -> None:
        self.recargar()

    def al_cambiar_tema(self) -> None:
        self.grafica.update()
