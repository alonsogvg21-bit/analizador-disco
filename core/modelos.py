"""Estructuras de datos que devuelve el motor.

Las interfaces (terminal y web) solo reciben estos objetos; nunca imprimen
ni leen el disco por su cuenta. Así el motor se puede probar de forma aislada.
"""

from __future__ import annotations

import dataclasses
import os
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class InfoDisco:
    dispositivo: str
    punto_montaje: str
    sistema_archivos: str
    total: int
    usado: int
    libre: int
    porcentaje: float


@dataclass(slots=True)
class InfoArchivo:
    # La ruta se guarda como texto y no como Path: un disco puede tener
    # millones de archivos y un Path ocupa varias veces más memoria.
    ruta: str
    tamano: int
    modificado: float
    accedido: float
    en_regenerable: bool = False

    @property
    def path(self) -> Path:
        return Path(self.ruta)

    @property
    def nombre(self) -> str:
        return os.path.basename(self.ruta)

    @property
    def ultimo_uso(self) -> float:
        """La fecha más reciente entre último acceso y última modificación."""
        return max(self.modificado, self.accedido)


@dataclass(slots=True)
class InfoCarpeta:
    ruta: Path
    tamano: int
    num_archivos: int


@dataclass(slots=True)
class ContenidoCarpeta:
    """Un nivel del árbol: las subcarpetas directas de una ruta."""
    ruta: Path
    tamano: int
    num_archivos: int
    tamano_archivos_directos: int
    subcarpetas: list[InfoCarpeta]


@dataclass(slots=True)
class ResumenTipo:
    tipo: str
    tamano: int
    cantidad: int


@dataclass(slots=True)
class GrupoDuplicados:
    hash: str
    tamano: int
    # El primero es el más antiguo y se considera el "original".
    archivos: list[Path]

    @property
    def espacio_recuperable(self) -> int:
        return self.tamano * (len(self.archivos) - 1)


@dataclass(slots=True)
class ElementoBasura:
    ruta: Path
    tamano: int
    categoria: str
    es_carpeta: bool = False
    # False = solo informativo: se muestra, pero la limpieza lo rechaza.
    limpiable: bool = True
    detalle: str = ""


@dataclass(slots=True)
class CategoriaBasura:
    clave: str
    nombre: str
    descripcion: str
    elementos: list[ElementoBasura] = field(default_factory=list)

    @property
    def tamano_total(self) -> int:
        return sum(e.tamano for e in self.elementos)

    @property
    def tamano_limpiable(self) -> int:
        return sum(e.tamano for e in self.elementos if e.limpiable)


@dataclass
class ResultadoEscaneo:
    """Todo lo que se obtiene de recorrer una carpeta una sola vez."""
    raiz: Path
    archivos: list[InfoArchivo] = field(default_factory=list)
    # Las claves son rutas de carpeta en texto.
    tamano_carpetas: dict[str, int] = field(default_factory=dict)       # acumulado
    archivos_por_carpeta: dict[str, int] = field(default_factory=dict)  # acumulado
    tamano_directo: dict[str, int] = field(default_factory=dict)        # solo archivos sueltos
    hijos: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    rutas_regenerables: list[str] = field(default_factory=list)
    errores: int = 0            # carpetas o archivos que no se pudieron leer
    bytes_en_nube: int = 0      # archivos de OneDrive que no ocupan disco
    cancelado: bool = False
    # Índice auxiliar del mapa de bloques; lo rellena core.arbol la primera vez.
    indice_arbol: Any = field(default=None, repr=False)

    @property
    def tamano_total(self) -> int:
        return self.tamano_carpetas.get(str(self.raiz), 0)

    @property
    def num_archivos(self) -> int:
        return len(self.archivos)


def a_dict(objeto: Any) -> Any:
    """Convierte modelos (y listas de modelos) a tipos simples para JSON."""
    if dataclasses.is_dataclass(objeto) and not isinstance(objeto, type):
        return {c.name: a_dict(getattr(objeto, c.name)) for c in dataclasses.fields(objeto)}
    if isinstance(objeto, Path):
        return str(objeto)
    if isinstance(objeto, dict):
        return {str(k): a_dict(v) for k, v in objeto.items()}
    if isinstance(objeto, (list, tuple)):
        return [a_dict(v) for v in objeto]
    return objeto
