"""Historial de escaneos, para comparar el uso del disco entre dos fechas.

Cada escaneo se guarda en una base de datos SQLite (viene con Python, no hay
que instalar nada). Se guarda el total y el tamaño de las carpetas de los
primeros niveles; guardar todas las carpetas de un disco entero haría crecer
la base de datos sin aportar mucho a la comparación.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from core.modelos import ResultadoEscaneo
from utils.sistema import WINDOWS, sistema_actual

PROFUNDIDAD_GUARDADA = 3
VARIABLE_DATOS = "ANALIZADOR_DISCO_DATOS"

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS escaneos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    raiz TEXT NOT NULL,
    raiz_clave TEXT NOT NULL,      -- la raíz normalizada, para buscar sin distinguir mayúsculas
    fecha TEXT NOT NULL,           -- AAAA-MM-DDTHH:MM:SS
    tamano_total INTEGER NOT NULL,
    num_archivos INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS carpetas (
    escaneo_id INTEGER NOT NULL REFERENCES escaneos(id) ON DELETE CASCADE,
    ruta TEXT NOT NULL,
    tamano INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS carpetas_por_escaneo ON carpetas(escaneo_id);
"""


@dataclass(slots=True)
class EscaneoGuardado:
    id: int
    raiz: str
    fecha: datetime
    tamano_total: int
    num_archivos: int


@dataclass(slots=True)
class CambioCarpeta:
    ruta: str
    antes: int      # 0 si la carpeta no existía
    despues: int    # 0 si la carpeta ya no existe
    diferencia: int  # positivo = creció, negativo = disminuyó


@dataclass(slots=True)
class Comparacion:
    antes: EscaneoGuardado
    despues: EscaneoGuardado
    cambios: list[CambioCarpeta]  # de mayor a menor cambio, sin importar el signo

    @property
    def diferencia_total(self) -> int:
        return self.despues.tamano_total - self.antes.tamano_total


# ---------------------------------------------------------------- ubicación

def carpeta_de_datos() -> Path:
    """Carpeta donde el programa guarda sus datos (se puede cambiar con una variable de entorno)."""
    personalizada = os.environ.get(VARIABLE_DATOS)
    if personalizada:
        return Path(personalizada)
    if sistema_actual() == WINDOWS:
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "analizador-disco"


def ruta_bd() -> Path:
    return carpeta_de_datos() / "historial.db"


def _conectar(bd: str | os.PathLike | None) -> sqlite3.Connection:
    archivo = Path(bd) if bd is not None else ruta_bd()
    archivo.parent.mkdir(parents=True, exist_ok=True)
    conexion = sqlite3.connect(archivo)
    conexion.execute("PRAGMA foreign_keys = ON")
    conexion.executescript(_ESQUEMA)
    return conexion


def _clave(raiz: str | os.PathLike) -> str:
    return os.path.normcase(os.path.abspath(raiz))


def _fila_a_escaneo(fila: tuple) -> EscaneoGuardado:
    identificador, raiz, fecha, tamano, archivos = fila
    return EscaneoGuardado(identificador, raiz, datetime.fromisoformat(fecha), tamano, archivos)


_COLUMNAS = "id, raiz, fecha, tamano_total, num_archivos"


# ---------------------------------------------------------------- guardar y consultar

def guardar_escaneo(
    resultado: ResultadoEscaneo,
    fecha: datetime | None = None,
    bd: str | os.PathLike | None = None,
    profundidad: int = PROFUNDIDAD_GUARDADA,
) -> EscaneoGuardado:
    """Guarda el total y las carpetas de los primeros niveles de un escaneo."""
    fecha = (fecha or datetime.now()).replace(microsecond=0)
    raiz = str(resultado.raiz)

    # Carpetas hasta 'profundidad' niveles por debajo de la raíz.
    carpetas: list[tuple[str, int]] = []
    nivel = [raiz]
    for _ in range(profundidad):
        nivel = [hija for carpeta in nivel for hija in resultado.hijos.get(carpeta, ())]
        carpetas.extend((carpeta, resultado.tamano_carpetas[carpeta]) for carpeta in nivel)

    with closing(_conectar(bd)) as conexion, conexion:
        cursor = conexion.execute(
            "INSERT INTO escaneos (raiz, raiz_clave, fecha, tamano_total, num_archivos) "
            "VALUES (?, ?, ?, ?, ?)",
            (raiz, _clave(raiz), fecha.isoformat(), resultado.tamano_total, resultado.num_archivos),
        )
        identificador = cursor.lastrowid
        conexion.executemany(
            "INSERT INTO carpetas (escaneo_id, ruta, tamano) VALUES (?, ?, ?)",
            ((identificador, ruta, tamano) for ruta, tamano in carpetas),
        )
    return EscaneoGuardado(identificador, raiz, fecha, resultado.tamano_total, resultado.num_archivos)


def listar_escaneos(
    raiz: str | os.PathLike | None = None, bd: str | os.PathLike | None = None
) -> list[EscaneoGuardado]:
    """Escaneos guardados, del más antiguo al más reciente. Con 'raiz', solo los de esa carpeta."""
    consulta = f"SELECT {_COLUMNAS} FROM escaneos"
    parametros: tuple = ()
    if raiz is not None:
        consulta += " WHERE raiz_clave = ?"
        parametros = (_clave(raiz),)
    with closing(_conectar(bd)) as conexion:
        filas = conexion.execute(consulta + " ORDER BY fecha, id", parametros).fetchall()
    return [_fila_a_escaneo(fila) for fila in filas]


def obtener_escaneo(identificador: int, bd: str | os.PathLike | None = None) -> EscaneoGuardado | None:
    with closing(_conectar(bd)) as conexion:
        fila = conexion.execute(
            f"SELECT {_COLUMNAS} FROM escaneos WHERE id = ?", (identificador,)).fetchone()
    return _fila_a_escaneo(fila) if fila else None


def escaneo_cercano(
    raiz: str | os.PathLike, fecha: datetime, bd: str | os.PathLike | None = None
) -> EscaneoGuardado | None:
    """El escaneo de esa carpeta más próximo a la fecha indicada."""
    escaneos = listar_escaneos(raiz, bd)
    if not escaneos:
        return None
    return min(escaneos, key=lambda e: abs((e.fecha - fecha).total_seconds()))


def borrar_escaneo(identificador: int, bd: str | os.PathLike | None = None) -> bool:
    """Quita un escaneo del historial. Devuelve False si no existía."""
    with closing(_conectar(bd)) as conexion, conexion:
        return conexion.execute(
            "DELETE FROM escaneos WHERE id = ?", (identificador,)).rowcount > 0


# ---------------------------------------------------------------- comparar

def comparar(
    id_a: int, id_b: int, bd: str | os.PathLike | None = None, minimo: int = 1
) -> Comparacion:
    """Compara dos escaneos de la misma carpeta.

    No importa el orden de los identificadores: siempre se toma el más antiguo
    como "antes". 'minimo' descarta los cambios menores de esos bytes.
    Lanza ValueError si falta alguno o si son de carpetas distintas.
    """
    uno, otro = obtener_escaneo(id_a, bd), obtener_escaneo(id_b, bd)
    if uno is None or otro is None:
        raise ValueError("No existe alguno de los escaneos indicados.")
    if _clave(uno.raiz) != _clave(otro.raiz):
        raise ValueError("Los dos escaneos deben ser de la misma carpeta.")
    antes, despues = sorted((uno, otro), key=lambda e: (e.fecha, e.id))

    with closing(_conectar(bd)) as conexion:
        def carpetas(identificador: int) -> dict[str, int]:
            return dict(conexion.execute(
                "SELECT ruta, tamano FROM carpetas WHERE escaneo_id = ?", (identificador,)))
        tamanos_antes, tamanos_despues = carpetas(antes.id), carpetas(despues.id)

    cambios = []
    for ruta in tamanos_antes.keys() | tamanos_despues.keys():
        previo, actual = tamanos_antes.get(ruta, 0), tamanos_despues.get(ruta, 0)
        if abs(actual - previo) >= max(minimo, 1):
            cambios.append(CambioCarpeta(ruta, previo, actual, actual - previo))
    cambios.sort(key=lambda c: (-abs(c.diferencia), c.ruta))
    return Comparacion(antes, despues, cambios)
