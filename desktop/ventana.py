"""Ventana principal: barra lateral, páginas, barra de estado y coordinación.

La ventana guarda el último escaneo y avisa a las vistas cuando cambia. Las
vistas no se conocen entre sí: todo pasa por aquí.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QListWidget, QMainWindow, QMessageBox, QProgressBar,
    QPushButton, QStackedWidget, QWidget,
)

from core.consulta import quitar_del_escaneo
from core.historial import carpeta_de_datos
from core.limpieza import limpiar
from core.modelos import CategoriaBasura, ElementoBasura, ResultadoEscaneo
from core.mover import mover
from desktop import estilos
from desktop.acciones import MOVER, DialogoConfirmacion, menu_contextual
from desktop.hilos import HiloEscaneo, HiloFuncion
from desktop.vistas.basura import VistaBasura
from desktop.vistas.configuracion import VistaConfiguracion
from desktop.vistas.duplicados import VistaDuplicados
from desktop.vistas.explorar import VistaExplorar
from desktop.vistas.historial import VistaHistorial
from desktop.vistas.inicio import VistaInicio
from desktop.vistas.salud import VistaSalud
from utils.formato import tamano_legible
from utils.red import AVISO_RED, es_ruta_de_red

SECCIONES = (
    ("Inicio", VistaInicio),
    ("Explorar espacio", VistaExplorar),
    ("Archivos basura", VistaBasura),
    ("Duplicados", VistaDuplicados),
    ("Historial", VistaHistorial),
    ("Salud del disco", VistaSalud),
    ("Configuración", VistaConfiguracion),
)


class VentanaPrincipal(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Analizador de disco")
        self.resize(1180, 760)
        self.setMinimumSize(880, 560)

        # Preferencias de la interfaz, junto al resto de datos del programa.
        self.ajustes = QSettings(str(carpeta_de_datos() / "escritorio.ini"), QSettings.Format.IniFormat)
        self.resultado: ResultadoEscaneo | None = None
        self.categorias: list[CategoriaBasura] = []
        self._hilo_escaneo: HiloEscaneo | None = None
        self._hilos: list[HiloFuncion] = []   # se guardan para que no se destruyan a medias

        estilos.aplicar(QApplication.instance(), self.tema())

        # --- barra lateral y páginas ---
        self.lateral = QListWidget()
        self.lateral.setObjectName("lateral")
        self.lateral.setFixedWidth(210)
        self.lateral.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.paginas = QStackedWidget()
        self.vistas: dict[str, QWidget] = {}
        for nombre, clase in SECCIONES:
            vista = clase(self)
            vista.setObjectName("pagina")
            self.vistas[nombre] = vista
            self.paginas.addWidget(vista)
            self.lateral.addItem(nombre)
        self.lateral.currentRowChanged.connect(self._cambiar_pagina)

        centro = QWidget()
        caja = QHBoxLayout(centro)
        caja.setContentsMargins(0, 0, 0, 0)
        caja.setSpacing(0)
        caja.addWidget(self.lateral)
        caja.addWidget(self.paginas, 1)
        self.setCentralWidget(centro)

        # --- barra de estado: mensaje, progreso y cancelar ---
        self._mensaje = QLabel("Listo.")
        self._progreso = QProgressBar()
        self._progreso.setFixedWidth(220)
        self._progreso.setTextVisible(False)
        self._progreso.hide()
        self._cancelar = QPushButton("Cancelar")
        self._cancelar.clicked.connect(self.cancelar_escaneo)
        self._cancelar.hide()
        barra = self.statusBar()
        barra.setSizeGripEnabled(False)
        barra.addWidget(self._mensaje, 1)
        barra.addPermanentWidget(self._progreso)
        barra.addPermanentWidget(self._cancelar)

        self.lateral.setCurrentRow(0)

    # ------------------------------------------------------------ navegación y preferencias

    def _cambiar_pagina(self, fila: int) -> None:
        self.paginas.setCurrentIndex(fila)
        vista = self.paginas.currentWidget()
        if hasattr(vista, "al_mostrar"):
            vista.al_mostrar()

    def ir_a(self, nombre: str) -> None:
        self.lateral.setCurrentRow([n for n, _ in SECCIONES].index(nombre))

    def tema(self) -> str:
        modo = str(self.ajustes.value("tema", "sistema"))
        return modo if modo in estilos.MODOS else "sistema"

    def cambiar_tema(self, modo: str) -> None:
        self.ajustes.setValue("tema", modo)
        estilos.aplicar(QApplication.instance(), modo)
        for vista in self.vistas.values():
            if hasattr(vista, "al_cambiar_tema"):
                vista.al_cambiar_tema()
            vista.update()

    def buscar_duplicados_al_escanear(self) -> bool:
        return str(self.ajustes.value("duplicados", "true")).lower() == "true"

    def estado(self, texto: str) -> None:
        self._mensaje.setText(texto)

    # ------------------------------------------------------------ escaneo en segundo plano

    def escaneando(self) -> bool:
        return self._hilo_escaneo is not None and self._hilo_escaneo.isRunning()

    def escanear(self, ruta: str) -> None:
        if self.escaneando():
            return
        carpeta = Path(ruta.strip()).expanduser() if ruta.strip() else None
        if carpeta is None or not carpeta.is_dir():
            QMessageBox.warning(self, "Carpeta no válida",
                                f"La carpeta no existe:\n{ruta}" if ruta.strip() else "Elige una carpeta para escanear.")
            return

        hilo = HiloEscaneo(carpeta, self.buscar_duplicados_al_escanear(), self)
        hilo.fase.connect(self._en_fase)
        hilo.avance.connect(lambda n, actual: self.estado(f"Contando archivos… {n:,} encontrados   {actual}"))
        hilo.avance_duplicados.connect(self._en_duplicados)
        hilo.terminado.connect(self._escaneo_terminado)
        hilo.cancelado.connect(lambda: self._fin_escaneo("Escaneo cancelado."))
        hilo.fallo.connect(lambda texto: self._fin_escaneo(f"No se pudo completar el escaneo: {texto}"))
        self._hilo_escaneo = hilo

        self._progreso.setRange(0, 0)   # sin porcentaje: no se sabe cuántos archivos faltan
        self._progreso.show()
        self._cancelar.show()
        self._cancelar.setEnabled(True)
        self.vistas["Inicio"].al_empezar_escaneo(AVISO_RED if es_ruta_de_red(carpeta) else "")
        hilo.start()

    def _en_fase(self, texto: str) -> None:
        self.estado(texto)
        self._progreso.setRange(0, 0)

    def _en_duplicados(self, hechos: int, total: int) -> None:
        # Aquí sí se conoce el total: la barra muestra el avance real.
        self._progreso.setRange(0, max(total, 1))
        self._progreso.setValue(hechos)
        self.estado(f"Comparando posibles duplicados… {hechos:,} de {total:,}")

    def cancelar_escaneo(self) -> None:
        if self.escaneando():
            self._cancelar.setEnabled(False)
            self.estado("Cancelando…")
            self._hilo_escaneo.cancelar()

    def _fin_escaneo(self, mensaje: str) -> None:
        self._progreso.hide()
        self._cancelar.hide()
        self.estado(mensaje)
        self.vistas["Inicio"].al_terminar_escaneo()

    def _escaneo_terminado(self, resultado: ResultadoEscaneo, categorias: list) -> None:
        self.resultado, self.categorias = resultado, categorias
        notas = ""
        if resultado.errores:
            notas = f" {resultado.errores:,} elementos sin acceso se ignoraron."
        self._fin_escaneo(f"{resultado.raiz} ocupa {tamano_legible(resultado.tamano_total)} "
                          f"en {resultado.num_archivos:,} archivos.{notas}")
        for vista in self.vistas.values():
            if hasattr(vista, "al_escanear"):
                vista.al_escanear()
        self.ir_a("Explorar espacio")

    # ------------------------------------------------------------ tareas cortas en segundo plano

    def lanzar(self, funcion, *argumentos, al_terminar, al_fallar=None, **opciones) -> None:
        """Ejecuta una función sin bloquear la ventana y entrega su resultado."""
        hilo = HiloFuncion(funcion, *argumentos, parent=self, **opciones)
        hilo.resultado.connect(al_terminar)
        hilo.fallo.connect(al_fallar or (lambda problema: QMessageBox.warning(self, "Error", str(problema))))
        hilo.finished.connect(lambda: self._hilos.remove(hilo) if hilo in self._hilos else None)
        self._hilos.append(hilo)
        hilo.start()

    # ------------------------------------------------------------ mover y enviar a la papelera

    def menu_para(self, elementos: list[ElementoBasura], posicion) -> None:
        menu_contextual(self, elementos, posicion)

    def realizar(self, accion: str, elementos: list[ElementoBasura]) -> None:
        """Pide confirmación con la lista exacta y, solo entonces, mueve o envía a la papelera."""
        elementos = [e for e in elementos if e.limpiable]
        if not elementos:
            QMessageBox.information(self, "Nada seleccionado",
                                    "No hay ningún elemento seleccionado que se pueda mover o borrar.")
            return
        dialogo = DialogoConfirmacion(self, elementos, accion)
        if dialogo.exec() != DialogoConfirmacion.DialogCode.Accepted:
            return
        simulacion = dialogo.simulacion
        self.estado("Simulando…" if simulacion else "Trabajando…")
        if accion == MOVER:
            self.lanzar(mover, elementos, dialogo.destino, simulacion=simulacion,
                        al_terminar=self._accion_terminada, al_fallar=self._accion_fallida)
        else:
            self.lanzar(limpiar, elementos, simulacion=simulacion,
                        al_terminar=self._accion_terminada, al_fallar=self._accion_fallida)

    def _accion_fallida(self, problema: Exception) -> None:
        self.estado("No se hizo ningún cambio.")
        QMessageBox.warning(self, "No se pudo completar", str(problema))

    def _accion_terminada(self, hecho) -> None:
        movimiento = hasattr(hecho, "movidos")
        hechos = [e for e, _ in hecho.movidos] if movimiento else hecho.enviados
        cantidad = f"{len(hechos)} {'elemento' if len(hechos) == 1 else 'elementos'}"
        if movimiento:
            tamano = tamano_legible(hecho.bytes_movidos)
            titulo = (f"Simulación: se habrían movido {cantidad} ({tamano}) a {hecho.destino}. No se ha tocado nada."
                      if hecho.simulacion else f"Movidos {cantidad} ({tamano}) a {hecho.destino}.")
        else:
            tamano = tamano_legible(hecho.bytes_liberados)
            titulo = (f"Simulación: se habrían enviado {cantidad} a la papelera ({tamano}). No se ha tocado nada."
                      if hecho.simulacion else
                      f"{cantidad} en la papelera. Espacio liberado: {tamano} (vuelve al disco al vaciar la papelera).")
        self.estado(titulo)

        aviso = QMessageBox(self)
        aviso.setWindowTitle("Simulación" if hecho.simulacion else "Hecho")
        aviso.setIcon(QMessageBox.Icon.Information)
        aviso.setText(titulo)
        if hecho.omitidos:
            aviso.setInformativeText(f"{len(hecho.omitidos)} no se tocaron. Pulsa «Mostrar detalles» para verlos.")
            aviso.setDetailedText("\n".join(f"{e.ruta} — {motivo}" for e, motivo in hecho.omitidos))
        aviso.exec()

        if not hecho.simulacion and hechos:
            self._olvidar(hechos)

    def _olvidar(self, elementos: list[ElementoBasura]) -> None:
        """Lo que ya se movió o se envió a la papelera deja de mostrarse."""
        quitados = {id(e) for e in elementos}
        rutas = {str(e.ruta) for e in elementos}
        if self.resultado is not None:
            quitar_del_escaneo(self.resultado, rutas)
        for categoria in self.categorias:
            categoria.elementos = [
                e for e in categoria.elementos if id(e) not in quitados and str(e.ruta) not in rutas]
        for vista in self.vistas.values():
            if hasattr(vista, "al_cambiar_datos"):
                vista.al_cambiar_datos(rutas)

    def closeEvent(self, evento) -> None:
        # Se espera a que el escaneo se detenga para no cerrar con un hilo a medias.
        if self.escaneando():
            self._hilo_escaneo.cancelar()
            self._hilo_escaneo.wait(5000)
        for hilo in list(self._hilos):
            hilo.wait(3000)
        evento.accept()

    def keyPressEvent(self, evento) -> None:
        if evento.key() == Qt.Key.Key_Escape and self.escaneando():
            self.cancelar_escaneo()
        else:
            super().keyPressEvent(evento)
