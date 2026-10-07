"""Archivos basura: categorías con casillas y contador del espacio a liberar."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QHeaderView, QPushButton, QTreeWidget, QVBoxLayout, QWidget,
)

from core.modelos import ElementoBasura
from desktop import estilos
from desktop.acciones import MOVER, PAPELERA
from desktop.componentes import FilaArbol, etiqueta
from utils.formato import tamano_legible

ELEMENTO = Qt.ItemDataRole.UserRole
# Una categoría puede tener miles de elementos diminutos: se listan los más grandes.
MAXIMO_POR_CATEGORIA = 200
MARCABLE = Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable


class VistaBasura(QWidget):
    def __init__(self, ventana) -> None:
        super().__init__()
        self.ventana = ventana

        caja = QVBoxLayout(self)
        caja.setContentsMargins(28, 24, 28, 16)
        caja.setSpacing(10)
        caja.addWidget(etiqueta("Archivos basura", "titulo"))
        caja.addWidget(etiqueta(
            "Marca lo que quieras quitar. No se borra nada hasta que lo confirmes, y todo va a la "
            "papelera, de donde se puede recuperar.", "suave", ajustar=True))

        self.arbol = QTreeWidget()
        self.arbol.setHeaderLabels(["Elemento", "Tamaño", "Detalle"])
        self.arbol.setAlternatingRowColors(True)
        self.arbol.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.arbol.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.arbol.header().resizeSection(2, 320)
        self.arbol.itemChanged.connect(lambda *_: self._contar())
        self.arbol.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.arbol.customContextMenuRequested.connect(self._menu)
        caja.addWidget(self.arbol, 1)

        pie = QHBoxLayout()
        self._contador = etiqueta("Nada seleccionado.", "subtitulo")
        pie.addWidget(self._contador, 1)
        mover = QPushButton("Mover a otra carpeta…")
        mover.clicked.connect(lambda: self.ventana.realizar(MOVER, self.seleccionados()))
        self._papelera = QPushButton("Enviar a la papelera…")
        self._papelera.setObjectName("principal")
        self._papelera.clicked.connect(lambda: self.ventana.realizar(PAPELERA, self.seleccionados()))
        self._botones = (mover, self._papelera)
        pie.addWidget(mover)
        pie.addWidget(self._papelera)
        caja.addLayout(pie)
        self._llenar()

    def _llenar(self) -> None:
        self.arbol.blockSignals(True)   # mientras se rellena no hace falta recontar
        self.arbol.clear()
        derecha = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        for categoria in self.ventana.categorias:
            if not categoria.elementos:
                continue
            mayores = sorted(categoria.elementos, key=lambda e: e.tamano, reverse=True)
            visibles, ocultos = mayores[:MAXIMO_POR_CATEGORIA], mayores[MAXIMO_POR_CATEGORIA:]
            grupo = FilaArbol([f"{categoria.nombre}  ({len(mayores):,})",
                               tamano_legible(categoria.tamano_total), categoria.descripcion])
            grupo.setData(1, ELEMENTO, categoria.tamano_total)
            grupo.setToolTip(2, categoria.descripcion)
            grupo.setTextAlignment(1, derecha)
            fuente = grupo.font(0)
            fuente.setBold(True)
            grupo.setFont(0, fuente)
            hay_limpiables = any(e.limpiable for e in visibles)
            if hay_limpiables:
                # Marcar la categoría marca todos sus elementos (y a la inversa).
                grupo.setFlags(MARCABLE | Qt.ItemFlag.ItemIsAutoTristate)
                grupo.setCheckState(0, Qt.CheckState.Unchecked)

            for elemento in visibles:
                fila = FilaArbol([str(elemento.ruta), tamano_legible(elemento.tamano),
                                  elemento.detalle if elemento.limpiable else f"Solo informativo. {elemento.detalle}"])
                fila.setData(0, ELEMENTO, elemento)
                fila.setData(1, ELEMENTO, elemento.tamano)
                fila.setToolTip(0, str(elemento.ruta))
                fila.setToolTip(2, elemento.detalle)
                fila.setTextAlignment(1, derecha)
                if elemento.limpiable:
                    fila.setFlags(MARCABLE)
                    fila.setCheckState(0, Qt.CheckState.Unchecked)
                else:
                    # Sin casilla: se ve, pero no se puede seleccionar para limpiar.
                    fila.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                    fila.setForeground(0, estilos.color("suave"))
                grupo.addChild(fila)
            if ocultos:
                resto = FilaArbol([f"… y {len(ocultos):,} más pequeños (están en el reporte CSV)",
                                   tamano_legible(sum(e.tamano for e in ocultos)), ""])
                resto.setFlags(Qt.ItemFlag.ItemIsEnabled)
                resto.setTextAlignment(1, derecha)
                resto.setForeground(0, estilos.color("suave"))
                grupo.addChild(resto)
            self.arbol.addTopLevelItem(grupo)
        self.arbol.blockSignals(False)
        self.arbol.resizeColumnToContents(1)
        if self.arbol.topLevelItemCount() == 0:
            vacio = FilaArbol(["Escanea una carpeta para buscar archivos basura."
                               if self.ventana.resultado is None else "No se encontró nada que limpiar."])
            vacio.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.arbol.addTopLevelItem(vacio)
        self._contar()

    def seleccionados(self) -> list[ElementoBasura]:
        elegidos = []
        for indice in range(self.arbol.topLevelItemCount()):
            grupo = self.arbol.topLevelItem(indice)
            for hijo in range(grupo.childCount()):
                fila = grupo.child(hijo)
                elemento = fila.data(0, ELEMENTO)
                if isinstance(elemento, ElementoBasura) and fila.checkState(0) == Qt.CheckState.Checked:
                    elegidos.append(elemento)
        return elegidos

    def _contar(self) -> None:
        elegidos = self.seleccionados()
        for boton in self._botones:
            boton.setEnabled(bool(elegidos))
        if not elegidos:
            self._contador.setText("Nada seleccionado.")
            return
        total = sum(e.tamano for e in elegidos)
        palabra = "elemento seleccionado" if len(elegidos) == 1 else "elementos seleccionados"
        self._contador.setText(f"{len(elegidos):,} {palabra} · se liberarían {tamano_legible(total)}")

    def _menu(self, punto) -> None:
        elementos = [fila.data(0, ELEMENTO) for fila in self.arbol.selectedItems()]
        self.ventana.menu_para([e for e in elementos if isinstance(e, ElementoBasura)],
                               self.arbol.viewport().mapToGlobal(punto))

    def al_escanear(self) -> None:
        self._llenar()

    def al_cambiar_datos(self, rutas) -> None:
        self._llenar()
