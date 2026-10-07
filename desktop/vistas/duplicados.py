"""Duplicados: grupos de archivos idénticos, con el original protegido."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QDoubleSpinBox, QHBoxLayout, QHeaderView, QLabel, QPushButton, QTreeWidget,
    QVBoxLayout, QWidget,
)

from core.duplicados import buscar_duplicados
from core.modelos import ElementoBasura, GrupoDuplicados
from desktop import estilos
from desktop.acciones import MOVER, PAPELERA
from desktop.componentes import FilaArbol, etiqueta
from utils.formato import tamano_legible
from utils.seguridad import es_ruta_protegida

ELEMENTO = Qt.ItemDataRole.UserRole
MB = 1024 * 1024
MAXIMO_GRUPOS = 300


class VistaDuplicados(QWidget):
    def __init__(self, ventana) -> None:
        super().__init__()
        self.ventana = ventana
        self._grupos: list[GrupoDuplicados] = []

        caja = QVBoxLayout(self)
        caja.setContentsMargins(28, 24, 28, 16)
        caja.setSpacing(10)
        caja.addWidget(etiqueta("Duplicados", "titulo"))
        caja.addWidget(etiqueta(
            "Copias idénticas de un mismo archivo. En cada grupo se conserva la más antigua "
            "(el original), que no se puede marcar.", "suave", ajustar=True))

        fila = QHBoxLayout()
        fila.addWidget(QLabel("Tamaño mínimo"))
        self._minimo = QDoubleSpinBox()
        self._minimo.setRange(0, 1_000_000)
        self._minimo.setDecimals(0)
        self._minimo.setValue(1)
        self._minimo.setSuffix(" MB")
        fila.addWidget(self._minimo)
        self._buscar = QPushButton("Buscar duplicados")
        self._buscar.setObjectName("principal")
        self._buscar.clicked.connect(self.buscar)
        fila.addWidget(self._buscar)
        self._marcar = QPushButton("Marcar todas las copias")
        self._marcar.clicked.connect(lambda: self._marcar_todas(True))
        self._desmarcar = QPushButton("Desmarcar todo")
        self._desmarcar.clicked.connect(lambda: self._marcar_todas(False))
        fila.addWidget(self._marcar)
        fila.addWidget(self._desmarcar)
        fila.addStretch(1)
        caja.addLayout(fila)

        self._resumen = etiqueta("", "suave", ajustar=True)
        caja.addWidget(self._resumen)

        self.arbol = QTreeWidget()
        self.arbol.setHeaderLabels(["Archivo", "Tamaño", ""])
        self.arbol.setAlternatingRowColors(True)
        self.arbol.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.arbol.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.arbol.itemChanged.connect(lambda *_: self._contar())
        self.arbol.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.arbol.customContextMenuRequested.connect(self._menu)
        caja.addWidget(self.arbol, 1)

        pie = QHBoxLayout()
        self._contador = etiqueta("Nada seleccionado.", "subtitulo")
        pie.addWidget(self._contador, 1)
        mover = QPushButton("Mover a otra carpeta…")
        mover.clicked.connect(lambda: self.ventana.realizar(MOVER, self.seleccionados()))
        papelera = QPushButton("Enviar a la papelera…")
        papelera.setObjectName("principal")
        papelera.clicked.connect(lambda: self.ventana.realizar(PAPELERA, self.seleccionados()))
        self._botones = (mover, papelera)
        pie.addWidget(mover)
        pie.addWidget(papelera)
        caja.addLayout(pie)
        self._pintar()

    # ------------------------------------------------------------ búsqueda en segundo plano

    def buscar(self) -> None:
        if self.ventana.resultado is None:
            self._resumen.setText("Primero escanea una carpeta desde Inicio.")
            return
        self._buscar.setEnabled(False)
        self._buscar.setText("Comparando…")
        self.ventana.estado("Comparando archivos para encontrar duplicados…")
        self.ventana.lanzar(buscar_duplicados, self.ventana.resultado.archivos,
                            int(self._minimo.value() * MB),
                            al_terminar=self._encontrados, al_fallar=self._fallo)

    def _fallo(self, problema: Exception) -> None:
        self._buscar.setEnabled(True)
        self._buscar.setText("Buscar duplicados")
        self._resumen.setText(f"No se pudo completar la búsqueda: {problema}")

    def _encontrados(self, grupos: list[GrupoDuplicados]) -> None:
        self._buscar.setEnabled(True)
        self._buscar.setText("Buscar duplicados")
        self._grupos = grupos
        self.ventana.estado(f"Búsqueda de duplicados terminada: {len(grupos):,} grupos.")
        self._pintar(buscado=True)

    # ------------------------------------------------------------ lista

    def _pintar(self, buscado: bool = False) -> None:
        self.arbol.blockSignals(True)
        self.arbol.clear()
        derecha = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        recuperable = sum(g.espacio_recuperable for g in self._grupos)
        for grupo in self._grupos[:MAXIMO_GRUPOS]:
            cabeza = FilaArbol([f"{len(grupo.archivos)} copias de {grupo.archivos[0].name}",
                                tamano_legible(grupo.tamano),
                                f"sobran {tamano_legible(grupo.espacio_recuperable)}"])
            cabeza.setData(1, ELEMENTO, grupo.espacio_recuperable)
            cabeza.setTextAlignment(1, derecha)
            fuente = cabeza.font(0)
            fuente.setBold(True)
            cabeza.setFont(0, fuente)
            for posicion, ruta in enumerate(grupo.archivos):
                fila = FilaArbol([str(ruta), tamano_legible(grupo.tamano),
                                  "original (se conserva)" if posicion == 0 else "copia"])
                fila.setTextAlignment(1, derecha)
                fila.setToolTip(0, str(ruta))
                protegido = es_ruta_protegida(ruta)
                elemento = ElementoBasura(ruta, grupo.tamano, "duplicados", limpiable=not protegido,
                                          detalle=f"Copia de {grupo.archivos[0]}")
                fila.setData(0, ELEMENTO, elemento)
                if posicion == 0 or protegido:
                    fila.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                    fila.setForeground(0, estilos.color("suave"))
                    # El original nunca entra en la selección, ni por el menú contextual.
                    elemento.limpiable = False if posicion == 0 else elemento.limpiable
                else:
                    fila.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled
                                  | Qt.ItemFlag.ItemIsSelectable)
                    fila.setCheckState(0, Qt.CheckState.Unchecked)
                cabeza.addChild(fila)
            self.arbol.addTopLevelItem(cabeza)
            cabeza.setExpanded(True)
        self.arbol.blockSignals(False)
        self.arbol.resizeColumnToContents(1)
        self.arbol.resizeColumnToContents(2)

        if self._grupos:
            extra = (f" Se muestran los {MAXIMO_GRUPOS} grupos que más espacio recuperan."
                     if len(self._grupos) > MAXIMO_GRUPOS else "")
            self._resumen.setText(f"{len(self._grupos):,} grupos de duplicados. Quitando las copias "
                                  f"se recuperarían {tamano_legible(recuperable)}.{extra}")
        elif buscado:
            self._resumen.setText("No se encontraron duplicados con ese tamaño mínimo.")
        else:
            self._resumen.setText("Pulsa «Buscar duplicados» después de escanear una carpeta. "
                                  "Comparar archivos grandes puede tardar.")
        for boton in (self._marcar, self._desmarcar):
            boton.setEnabled(bool(self._grupos))
        self._contar()

    def _copias(self):
        for indice in range(self.arbol.topLevelItemCount()):
            cabeza = self.arbol.topLevelItem(indice)
            for hijo in range(cabeza.childCount()):
                fila = cabeza.child(hijo)
                if fila.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                    yield fila

    def _marcar_todas(self, marcar: bool) -> None:
        self.arbol.blockSignals(True)
        for fila in self._copias():
            fila.setCheckState(0, Qt.CheckState.Checked if marcar else Qt.CheckState.Unchecked)
        self.arbol.blockSignals(False)
        self._contar()

    def seleccionados(self) -> list[ElementoBasura]:
        return [fila.data(0, ELEMENTO) for fila in self._copias()
                if fila.checkState(0) == Qt.CheckState.Checked]

    def _contar(self) -> None:
        elegidos = self.seleccionados()
        for boton in self._botones:
            boton.setEnabled(bool(elegidos))
        if not elegidos:
            self._contador.setText("Nada seleccionado.")
            return
        palabra = "copia seleccionada" if len(elegidos) == 1 else "copias seleccionadas"
        self._contador.setText(f"{len(elegidos):,} {palabra} · se liberarían "
                               f"{tamano_legible(sum(e.tamano for e in elegidos))}")

    def _menu(self, punto) -> None:
        elementos = [fila.data(0, ELEMENTO) for fila in self.arbol.selectedItems()]
        self.ventana.menu_para([e for e in elementos if isinstance(e, ElementoBasura)],
                               self.arbol.viewport().mapToGlobal(punto))

    def al_escanear(self) -> None:
        # Los duplicados de un escaneo anterior ya no valen.
        self._grupos = []
        self._pintar()

    def al_cambiar_datos(self, rutas) -> None:
        """Quita de los grupos lo que se movió o borró; un grupo con una sola copia deja de serlo."""
        restantes = []
        for grupo in self._grupos:
            archivos = [ruta for ruta in grupo.archivos if str(ruta) not in rutas]
            if len(archivos) > 1:
                restantes.append(GrupoDuplicados(grupo.hash, grupo.tamano, archivos))
        self._grupos = restantes
        self._pintar(buscado=True)
