"""Escaneo en segundo plano.

El escaneo puede tardar minutos. Si se hiciera dentro de la petición web, la
página quedaría congelada; por eso corre en un hilo aparte y la página
pregunta cada medio segundo cómo va.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from core.arbol import preparar_indice
from core.basura import detectar_basura
from core.consulta import quitar_del_escaneo
from core.escaner import archivos_mas_pesados, escanear
from core.historial import guardar_escaneo
from utils.red import AVISO_RED, es_ruta_de_red
from core.modelos import CategoriaBasura, ElementoBasura, InfoArchivo, ResultadoEscaneo, ResumenTipo
from core.tipos import resumen_por_tipo

INACTIVO = "inactivo"
ESCANEANDO = "escaneando"
BUSCANDO_BASURA = "basura"
LISTO = "listo"
CANCELADO = "cancelado"
ERROR = "error"

_EN_CURSO = (ESCANEANDO, BUSCANDO_BASURA)


class GestorEscaneo:
    """Guarda el estado del único escaneo que puede haber a la vez."""

    def __init__(self) -> None:
        self._candado = threading.Lock()
        self._cancelar = threading.Event()
        self._hilo: threading.Thread | None = None
        self._inicio = 0.0
        self._estado: dict = {"fase": INACTIVO}

        # Resultados del último escaneo terminado.
        self.resultado: ResultadoEscaneo | None = None
        self.categorias: list[CategoriaBasura] = []
        self.tipos: list[ResumenTipo] = []
        self.top: list[InfoArchivo] = []
        # Cada elemento de basura recibe un identificador. La página solo
        # maneja identificadores, nunca rutas escritas por ella misma.
        self.elementos: dict[str, ElementoBasura] = {}

    # ------------------------------------------------------------ control

    def iniciar(self, ruta: Path, con_duplicados: bool = True) -> bool:
        """Lanza el escaneo. Devuelve False si ya hay uno en marcha."""
        with self._candado:
            if self._estado["fase"] in _EN_CURSO:
                return False
            self._cancelar.clear()
            self._inicio = time.monotonic()
            self._estado = {
                "fase": ESCANEANDO, "ruta": str(ruta), "archivos": 0,
                "carpeta_actual": "", "hechos": 0, "total": 0, "error": "",
                "aviso": AVISO_RED if es_ruta_de_red(ruta) else "",
            }
        self._hilo = threading.Thread(
            target=self._trabajar, args=(ruta, con_duplicados), daemon=True)
        self._hilo.start()
        return True

    def cancelar(self) -> None:
        self._cancelar.set()

    def esperar(self, segundos: float | None = None) -> None:
        """Bloquea hasta que termine el escaneo (lo usan las pruebas)."""
        if self._hilo is not None:
            self._hilo.join(segundos)

    def estado(self) -> dict:
        with self._candado:
            copia = dict(self._estado)
        if copia["fase"] in _EN_CURSO:
            copia["segundos"] = round(time.monotonic() - self._inicio, 1)
        return copia

    def en_curso(self) -> bool:
        return self.estado()["fase"] in _EN_CURSO

    def quitar(self, elementos: list[ElementoBasura]) -> None:
        """Olvida elementos ya movidos o enviados a la papelera, para no volver a ofrecerlos."""
        quitados = {id(e) for e in elementos}
        rutas = {str(e.ruta) for e in elementos}
        with self._candado:
            # También salen de la tabla de archivos y del mapa.
            if self.resultado is not None:
                quitar_del_escaneo(self.resultado, rutas)
            self.elementos = {
                clave: e for clave, e in self.elementos.items() if id(e) not in quitados}
            for categoria in self.categorias:
                categoria.elementos = [e for e in categoria.elementos if id(e) not in quitados]

    def _actualizar(self, **cambios) -> None:
        with self._candado:
            self._estado.update(cambios)

    # ------------------------------------------------------------ trabajo del hilo

    def _trabajar(self, ruta: Path, con_duplicados: bool) -> None:
        try:
            resultado = escanear(
                ruta,
                progreso=lambda n, carpeta: self._actualizar(archivos=n, carpeta_actual=carpeta),
                cancelar=self._cancelar,
            )
            if resultado.cancelado:
                self._actualizar(fase=CANCELADO)
                return

            self._actualizar(fase=BUSCANDO_BASURA, archivos=resultado.num_archivos)
            categorias = detectar_basura(
                resultado,
                incluir_duplicados=con_duplicados,
                progreso=lambda hechos, total: self._actualizar(hechos=hechos, total=total),
                cancelar=self._cancelar,
            )
            if self._cancelar.is_set():
                self._actualizar(fase=CANCELADO)
                return

            elementos = {
                f"{categoria.clave}-{indice}": elemento
                for categoria in categorias
                for indice, elemento in enumerate(categoria.elementos)
            }
            tipos = resumen_por_tipo(resultado.archivos)
            top = archivos_mas_pesados(resultado, 50)
            # Se deja listo ahora para que el mapa de bloques abra al instante.
            preparar_indice(resultado)
            # Cada escaneo terminado queda en el historial para poder comparar.
            # Si falla (disco lleno, sin permisos) el escaneo sigue siendo válido.
            try:
                guardar_escaneo(resultado)
            except Exception:
                pass

            # Se publica todo junto, para que la página nunca vea datos a medias.
            with self._candado:
                self.resultado, self.categorias = resultado, categorias
                self.tipos, self.top, self.elementos = tipos, top, elementos
                self._estado.update(
                    fase=LISTO, segundos=round(time.monotonic() - self._inicio, 1))
        except Exception as error:  # un fallo del hilo no debe tumbar el servidor
            self._actualizar(fase=ERROR, error=str(error))
