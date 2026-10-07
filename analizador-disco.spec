# -*- mode: python ; coding: utf-8 -*-
"""Receta de PyInstaller para Analizador de disco.

No se ejecuta directamente: la usa build.py (python build.py).
Genera una carpeta (modo "onedir") con el ejecutable, sin ventana de consola
(modo "windowed"), y dentro "_internal" con Python, Qt y los recursos.
"""

import sys
from pathlib import Path

RAIZ = Path(SPECPATH)            # SPECPATH lo define PyInstaller: carpeta de este archivo
sys.path.insert(0, str(RAIZ))
from utils.info import NOMBRE_EJECUTABLE  # noqa: E402

RECURSOS = RAIZ / "desktop" / "recursos"

# Archivos que no son código. Dentro del paquete quedan en sys._MEIPASS con la
# misma ruta relativa; el programa los busca con utils.rutas.ruta_recurso().
DATOS = [
    (str(RECURSOS), "desktop/recursos"),              # icono
    (str(RAIZ / "web" / "templates"), "web/templates"),
    (str(RAIZ / "web" / "static"), "web/static"),
    (str(RAIZ / "LICENSE"), "."),                      # se muestran en "Acerca de"
    (str(RAIZ / "NOTICE"), "."),
]

# Módulos que PyInstaller arrastraría y que el programa no usa.
# (unittest no se excluye: fpdf2 lo importa al cargarse.)
EXCLUIDOS = [
    "tkinter", "pytest", "_pytest", "tests", "pydoc_data",
    "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtOpenGL",
    "numpy", "lxml",   # opcionales de fpdf2; el reporte en PDF no los necesita
]

analisis = Analysis(
    [str(RAIZ / "main.py")],
    pathex=[str(RAIZ)],
    datas=DATOS,
    # Los plugins de Qt (plataforma, estilos, formatos de imagen) los añade el
    # "hook" de PySide6 que trae PyInstaller. Estos módulos se cargan según el
    # sistema y conviene nombrarlos para que nunca falten.
    hiddenimports=["core.reglas.windows", "core.reglas.linux"],
    excludes=EXCLUIDOS,
    noarchive=False,
)

# Windows 10 y 11 ya traen el "Universal C Runtime" (ucrtbase.dll y las
# api-ms-win-*.dll). PyInstaller las copia del equipo donde se compila, pero no
# hacen falta, y un instalador que suelta bibliotecas con nombre de sistema
# hace desconfiar a los antivirus (alguno llega a bloquear la instalación).
if sys.platform == "win32":
    def _es_del_sistema(nombre: str) -> bool:
        nombre = Path(nombre).name.lower()
        return nombre == "ucrtbase.dll" or nombre.startswith("api-ms-win-")

    analisis.binaries = [b for b in analisis.binaries if not _es_del_sistema(b[0])]

paquete = PYZ(analisis.pure)

# build.py genera este archivo con la versión; solo existe y se usa en Windows.
version_windows = RAIZ / "build" / "version_windows.txt"

ejecutable = EXE(
    paquete,
    analisis.scripts,
    [],
    exclude_binaries=True,          # onedir: las bibliotecas van aparte, en _internal
    name=NOMBRE_EJECUTABLE,
    console=False,                  # windowed: sin ventana negra al abrir la aplicación
    icon=str(RECURSOS / "icono.ico") if sys.platform == "win32" else None,
    version=str(version_windows) if sys.platform == "win32" and version_windows.exists() else None,
    upx=False,                      # comprimir con UPX dispara falsos positivos de antivirus
)

COLLECT(
    ejecutable,
    analisis.binaries,
    analisis.datas,
    upx=False,
    name=NOMBRE_EJECUTABLE,
)
