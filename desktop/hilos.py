"""Trabajo en segundo plano.

Escanear un disco puede tardar minutos. Si se hiciera en el hilo de la
ventana, esta se quedaría congelada; por eso el trabajo corre en un QThread y
avisa a la ventana mediante señales, que Qt entrega de forma segura.
"""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from core.arbol import preparar_indice
from core.basura import detectar_basura
from core.escaner import escanear
from core.historial import guardar_escaneo


class HiloEscaneo(QThread):
    """Escanea una carpeta, busca basura y guarda el resultado en el historial."""

    avance = Signal(int, str)        # archivos contados, carpeta actual
    fase = Signal(str)               # texto para la barra de estado
    avance_duplicados = Signal(int, int)  # comparados, total
    terminado = Signal(object, object)    # ResultadoEscaneo, lista de CategoriaBasura
    cancelado = Signal()
    fallo = Signal(str)

    def __init__(self, ruta: Path, con_duplicados: bool, parent=None) -> None:
        super().__init__(parent)
        self._ruta = ruta
        self._con_duplicados = con_duplicados
        self._cancelar = threading.Event()

    def cancelar(self) -> None:
        self._cancelar.set()

    def run(self) -> None:
        try:
            self.fase.emit("Contando archivos…")
            resultado = escanear(self._ruta, progreso=self.avance.emit, cancelar=self._cancelar)
            if resultado.cancelado:
                self.cancelado.emit()
                return

            self.fase.emit("Buscando archivos basura…")
            categorias = detectar_basura(
                resultado, incluir_duplicados=self._con_duplicados,
                progreso=self.avance_duplicados.emit, cancelar=self._cancelar)
            if self._cancelar.is_set():
                self.cancelado.emit()
                return

            preparar_indice(resultado)
            try:
                guardar_escaneo(resultado)
            except Exception:
                pass  # no poder guardar el historial no invalida el escaneo
            self.terminado.emit(resultado, categorias)
        except Exception as problema:  # un fallo aquí no debe cerrar el programa
            self.fallo.emit(str(problema))


class HiloFuncion(QThread):
    """Ejecuta cualquier función en segundo plano y entrega lo que devuelve."""

    resultado = Signal(object)
    fallo = Signal(object)   # la excepción, para que cada vista decida qué mostrar

    def __init__(self, funcion, *argumentos, parent=None, **opciones) -> None:
        super().__init__(parent)
        self._funcion, self._argumentos, self._opciones = funcion, argumentos, opciones

    def run(self) -> None:
        try:
            self.resultado.emit(self._funcion(*self._argumentos, **self._opciones))
        except Exception as problema:
            self.fallo.emit(problema)
