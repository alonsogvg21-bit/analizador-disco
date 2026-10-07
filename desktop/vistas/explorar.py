"""Explorar espacio: mapa de bloques, árbol de carpetas, tipos y tabla de archivos.

Todos los datos salen del motor: core.arbol (mapa), core.carpetas (árbol),
core.tipos (gráfica) y core.consulta (tabla con orden y filtros).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDoubleSpinBox, QHBoxLayout, QHeaderView, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QTabWidget, QTreeWidget, QVBoxLayout, QWidget,
)

from core.arbol import arbol_json
from core.carpetas import contenido_de
from core.consulta import listar_archivos
from core.tipos import TIPOS, clasificar, resumen_por_tipo
from desktop import estilos
from desktop.acciones import MOVER, PAPELERA, elemento_de
from desktop.componentes import CeldaTamano, FilaArbol, etiqueta
from desktop.graficas import GraficaBarras
from desktop.treemap import Leyenda, Treemap
from utils.formato import fecha_legible, porcentaje, tamano_legible

RUTA = Qt.ItemDataRole.UserRole
CARGADO = Qt.ItemDataRole.UserRole + 1
# Columnas de la tabla que se pueden ordenar y el campo del motor que les corresponde.
ORDEN_POR_COLUMNA = {2: "tamano", 3: "modificado", 4: "accedido"}
MB = 1024 * 1024


class VistaExplorar(QWidget):
    def __init__(self, ventana) -> None:
        super().__init__()
        self.ventana = ventana
        self._orden, self._descendente = "tamano", True

        caja = QVBoxLayout(self)
        caja.setContentsMargins(28, 24, 28, 16)
        caja.setSpacing(10)
        caja.addWidget(etiqueta("Explorar espacio", "titulo"))
        self._resumen = etiqueta("Todavía no hay ningún escaneo. Ve a Inicio y pulsa «Escanear».", "suave", ajustar=True)
        caja.addWidget(self._resumen)

        self._pestanas = QTabWidget()
        self._pestanas.addTab(self._crear_mapa(), "Mapa de bloques")
        self._pestanas.addTab(self._crear_arbol(), "Árbol de carpetas")
        self._pestanas.addTab(self._crear_tipos(), "Tipos de archivo")
        self._pestanas.addTab(self._crear_tabla(), "Archivos")
        caja.addWidget(self._pestanas, 1)

    # ------------------------------------------------------------ 1. mapa de bloques

    def _crear_mapa(self) -> QWidget:
        pagina = QWidget()
        caja = QVBoxLayout(pagina)
        caja.setContentsMargins(0, 10, 0, 0)
        self._migas = QHBoxLayout()
        self._migas.setSpacing(0)
        caja.addLayout(self._migas)
        self.mapa = Treemap()
        self.mapa.carpeta_elegida.connect(self.abrir)
        self.mapa.menu_pedido.connect(lambda nodo, pos: self._menu([nodo["ruta"]], pos))
        caja.addWidget(self.mapa, 1)
        self._leyenda = Leyenda()
        caja.addWidget(self._leyenda)
        caja.addWidget(etiqueta(
            "Cuanto más grande el bloque, más espacio ocupa. Pulsa una carpeta para entrar; "
            "una carpeta toma el color del tipo de archivo que más pesa dentro de ella.", "suave", ajustar=True))
        return pagina

    def abrir(self, ruta: str | None = None) -> None:
        """Muestra en el mapa el contenido de una carpeta (dos niveles por consulta)."""
        resultado = self.ventana.resultado
        if resultado is None:
            return
        try:
            arbol = arbol_json(resultado, ruta, niveles=2, max_hijos=30)
        except KeyError:
            return
        self.mapa.establecer(arbol)

        # Ruta de navegación: cada parte es un botón para volver a esa carpeta.
        while self._migas.count():
            elemento = self._migas.takeAt(0)
            if elemento.widget():
                elemento.widget().setParent(None)
        ultimo = len(arbol["migas"]) - 1
        for indice, miga in enumerate(arbol["migas"]):
            if indice:
                self._migas.addWidget(QLabel("›"))
            if indice == ultimo:
                # La carpeta actual no es un enlace: va como texto en negrita.
                boton = QLabel(miga["nombre"])
                fuente = boton.font()
                fuente.setBold(True)
                boton.setFont(fuente)
                boton.setContentsMargins(6, 4, 6, 4)
            else:
                boton = QPushButton(miga["nombre"])
                boton.setCursor(Qt.CursorShape.PointingHandCursor)
                boton.clicked.connect(lambda _=False, r=miga["ruta"]: self.abrir(r))
            boton.setObjectName("miga")
            boton.setToolTip(miga["ruta"])
            self._migas.addWidget(boton)
        self._migas.addStretch(1)

    # ------------------------------------------------------------ 2. árbol de carpetas

    def _crear_arbol(self) -> QWidget:
        self.arbol = QTreeWidget()
        self.arbol.setHeaderLabels(["Carpeta", "Tamaño", "% de su carpeta", "Archivos"])
        self.arbol.setAlternatingRowColors(True)
        self.arbol.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.arbol.header().setStretchLastSection(False)
        self.arbol.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.arbol.itemExpanded.connect(self._cargar_hijos)
        self.arbol.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.arbol.customContextMenuRequested.connect(lambda punto: self._menu(
            [i.data(0, RUTA) for i in self.arbol.selectedItems() if i.data(0, RUTA)],
            self.arbol.viewport().mapToGlobal(punto)))
        return self.arbol

    def _filas_de(self, ruta: str | None) -> list[FilaArbol]:
        nivel = contenido_de(self.ventana.resultado, ruta)
        filas = []
        for carpeta in nivel.subcarpetas:
            fila = FilaArbol([carpeta.ruta.name, tamano_legible(carpeta.tamano),
                              f"{porcentaje(carpeta.tamano, nivel.tamano):.1f} %",
                              f"{carpeta.num_archivos:,}"])
            fila.setData(0, RUTA, str(carpeta.ruta))
            fila.setData(1, RUTA, carpeta.tamano)
            fila.setToolTip(0, str(carpeta.ruta))
            for columna in (1, 2, 3):
                fila.setTextAlignment(columna, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if self.ventana.resultado.hijos.get(str(carpeta.ruta)):
                # Marcador para que aparezca la flecha; los hijos reales se cargan al desplegar.
                fila.addChild(FilaArbol(["…"]))
            filas.append(fila)
        if nivel.tamano_archivos_directos:
            sueltos = FilaArbol(["(archivos sueltos en esta carpeta)",
                                 tamano_legible(nivel.tamano_archivos_directos),
                                 f"{porcentaje(nivel.tamano_archivos_directos, nivel.tamano):.1f} %", ""])
            sueltos.setData(1, RUTA, nivel.tamano_archivos_directos)
            sueltos.setForeground(0, estilos.color("suave"))
            for columna in (1, 2):
                sueltos.setTextAlignment(columna, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            filas.append(sueltos)
        return filas

    def _cargar_hijos(self, fila) -> None:
        if fila.data(0, CARGADO) or not fila.data(0, RUTA):
            return
        fila.setData(0, CARGADO, True)
        fila.takeChildren()
        fila.addChildren(self._filas_de(fila.data(0, RUTA)))

    def _llenar_arbol(self) -> None:
        self.arbol.clear()
        if self.ventana.resultado is not None:
            self.arbol.addTopLevelItems(self._filas_de(None))
            for columna in (1, 2, 3):
                self.arbol.resizeColumnToContents(columna)

    # ------------------------------------------------------------ 3. tipos de archivo

    def _crear_tipos(self) -> QWidget:
        pagina = QWidget()
        caja = QVBoxLayout(pagina)
        caja.setContentsMargins(0, 14, 0, 0)
        caja.addWidget(etiqueta("Cuánto espacio usa cada clase de archivo.", "suave"))
        self.grafica_tipos = GraficaBarras()
        caja.addWidget(self.grafica_tipos)
        caja.addStretch(1)
        return pagina

    def _llenar_tipos(self) -> None:
        resultado = self.ventana.resultado
        filas = []
        for tipo in resumen_por_tipo(resultado.archivos):
            porc = porcentaje(tipo.tamano, resultado.tamano_total)
            nombre = estilos.NOMBRES_TIPO.get(tipo.tipo, tipo.tipo)
            valor = f"{tamano_legible(tipo.tamano)} · {porc:.1f} % · {tipo.cantidad:,} archivos"
            filas.append((nombre, porc, valor, f"{nombre}\n{valor}"))
        self.grafica_tipos.establecer(filas)

    # ------------------------------------------------------------ 4. tabla de archivos

    def _crear_tabla(self) -> QWidget:
        pagina = QWidget()
        caja = QVBoxLayout(pagina)
        caja.setContentsMargins(0, 10, 0, 0)

        filtros = QHBoxLayout()
        self._tipo = QComboBox()
        self._tipo.addItem("Todos los tipos", "")
        for tipo in TIPOS:
            self._tipo.addItem(estilos.NOMBRES_TIPO[tipo], tipo)
        self._minimo = QDoubleSpinBox()
        self._minimo.setRange(0, 1_000_000)
        self._minimo.setDecimals(0)
        self._minimo.setSuffix(" MB")
        self._limite = QComboBox()
        for cantidad in (50, 100, 200, 500):
            self._limite.addItem(f"{cantidad} archivos", cantidad)
        for texto, control in (("Tipo", self._tipo), ("Tamaño mínimo", self._minimo), ("Mostrar", self._limite)):
            filtros.addWidget(QLabel(texto))
            filtros.addWidget(control)
            filtros.addSpacing(10)
        filtros.addStretch(1)
        mover = QPushButton("Mover…")
        mover.clicked.connect(lambda: self.ventana.realizar(MOVER, self._seleccion_tabla()))
        papelera = QPushButton("Enviar a la papelera…")
        papelera.clicked.connect(lambda: self.ventana.realizar(PAPELERA, self._seleccion_tabla()))
        filtros.addWidget(mover)
        filtros.addWidget(papelera)
        caja.addLayout(filtros)
        self._tipo.currentIndexChanged.connect(self._llenar_tabla)
        self._limite.currentIndexChanged.connect(self._llenar_tabla)
        self._minimo.editingFinished.connect(self._llenar_tabla)

        self.tabla = QTableWidget(0, 5)
        self.tabla.setHorizontalHeaderLabels(["Archivo", "Tipo", "Tamaño", "Modificado", "Último acceso"])
        self.tabla.setAlternatingRowColors(True)
        self.tabla.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabla.verticalHeader().setVisible(False)
        cabecera = self.tabla.horizontalHeader()
        cabecera.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        cabecera.setSortIndicatorShown(True)
        cabecera.setSortIndicator(2, Qt.SortOrder.DescendingOrder)
        cabecera.sectionClicked.connect(self._ordenar_por)
        self.tabla.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tabla.customContextMenuRequested.connect(
            lambda punto: self._menu(self._rutas_tabla(), self.tabla.viewport().mapToGlobal(punto)))
        caja.addWidget(self.tabla, 1)
        caja.addWidget(etiqueta(
            "Pulsa «Tamaño», «Modificado» o «Último acceso» para ordenar; otra vez para invertir. "
            "Clic derecho sobre un archivo para más opciones.", "suave", ajustar=True))
        return pagina

    def _ordenar_por(self, columna: int) -> None:
        cabecera = self.tabla.horizontalHeader()
        if columna not in ORDEN_POR_COLUMNA:
            # Las otras columnas no se ordenan: se deja el indicador donde estaba.
            actual = next(c for c, campo in ORDEN_POR_COLUMNA.items() if campo == self._orden)
            cabecera.setSortIndicator(
                actual, Qt.SortOrder.DescendingOrder if self._descendente else Qt.SortOrder.AscendingOrder)
            return
        campo = ORDEN_POR_COLUMNA[columna]
        self._descendente = not self._descendente if campo == self._orden else True
        self._orden = campo
        cabecera.setSortIndicator(
            columna, Qt.SortOrder.DescendingOrder if self._descendente else Qt.SortOrder.AscendingOrder)
        self._llenar_tabla()

    def _llenar_tabla(self) -> None:
        resultado = self.ventana.resultado
        self.tabla.setRowCount(0)
        if resultado is None:
            return
        tipo = self._tipo.currentData()
        # El orden y los filtros los aplica el motor; aquí solo se muestran.
        archivos = listar_archivos(
            resultado, orden=self._orden, descendente=self._descendente,
            tipos=[tipo] if tipo else None, tamano_minimo=int(self._minimo.value() * MB),
            limite=self._limite.currentData())
        self.tabla.setRowCount(len(archivos))
        derecha = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        for fila, archivo in enumerate(archivos):
            celda = QTableWidgetItem(archivo.ruta)
            celda.setData(RUTA, archivo.ruta)
            celda.setToolTip(archivo.ruta)
            self.tabla.setItem(fila, 0, celda)
            self.tabla.setItem(fila, 1, QTableWidgetItem(estilos.NOMBRES_TIPO[clasificar(archivo.ruta)]))
            self.tabla.setItem(fila, 2, CeldaTamano(archivo.tamano))
            for columna, marca in ((3, archivo.modificado), (4, archivo.accedido)):
                fecha = QTableWidgetItem(fecha_legible(marca))
                fecha.setTextAlignment(derecha)
                self.tabla.setItem(fila, columna, fecha)
        for columna in (1, 2, 3, 4):
            self.tabla.resizeColumnToContents(columna)

    def _rutas_tabla(self) -> list[str]:
        filas = sorted({indice.row() for indice in self.tabla.selectedIndexes()})
        return [self.tabla.item(fila, 0).data(RUTA) for fila in filas]

    def _seleccion_tabla(self) -> list:
        elementos = [elemento_de(self.ventana.resultado, ruta) for ruta in self._rutas_tabla()]
        return [e for e in elementos if e is not None]

    # ------------------------------------------------------------ común

    def _menu(self, rutas: list[str], posicion) -> None:
        elementos = [elemento_de(self.ventana.resultado, ruta) for ruta in rutas]
        self.ventana.menu_para([e for e in elementos if e is not None], posicion)

    def al_escanear(self) -> None:
        resultado = self.ventana.resultado
        notas = []
        if resultado.errores:
            notas.append(f"{resultado.errores:,} elementos sin acceso se ignoraron.")
        if resultado.bytes_en_nube:
            notas.append(f"{tamano_legible(resultado.bytes_en_nube)} están solo en la nube y no ocupan disco.")
        self._resumen.setText(
            f"{resultado.raiz} ocupa {tamano_legible(resultado.tamano_total)} en "
            f"{resultado.num_archivos:,} archivos. " + " ".join(notas))
        self.abrir(None)
        self._llenar_arbol()
        self._llenar_tipos()
        self._llenar_tabla()

    def al_cambiar_datos(self, rutas) -> None:
        if self.ventana.resultado is None:
            return
        arbol = self.mapa._arbol
        self.abrir(arbol["ruta"] if arbol else None)
        self._llenar_tabla()

    def al_cambiar_tema(self) -> None:
        self._leyenda.repintar()
        self.mapa.update()
        self.grafica_tipos.update()
