"""Compila el programa y prepara los archivos para repartirlo.

    pip install -r requirements-empaquetado.txt
    python build.py                 -> carpeta con el ejecutable + paquete portable + SHA-256
    python build.py --instalador    -> además, el instalador del sistema en el que se ejecuta

Se compila para el sistema en el que se lanza: Windows en Windows, Linux en Linux.

Resultado, en dist/entregables/:
    Windows   AnalizadorDisco-X.Y.Z-windows-x64-portable.zip
              AnalizadorDisco-X.Y.Z-windows-x64-setup.exe     (con --instalador; requiere Inno Setup)
    Linux     AnalizadorDisco-X.Y.Z-linux-x86_64.tar.gz
              AnalizadorDisco-X.Y.Z-x86_64.AppImage           (con --instalador; requiere appimagetool)
              analizador-disco_X.Y.Z_amd64.deb                (con --instalador; requiere dpkg-deb)
    Ambos     SHA256SUMS-<sistema>.txt

Firma de código (opcional): si están definidas las variables de entorno
FIRMA_PFX (ruta del certificado) y FIRMA_CLAVE, en Windows se firman el
ejecutable y el instalador con signtool. Ver docs/DISTRIBUCION.md.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

from utils.info import DESCRIPCION, NOMBRE, NOMBRE_EJECUTABLE, VERSION, WEB

RAIZ = Path(__file__).resolve().parent
DIST = RAIZ / "dist"
APP = DIST / NOMBRE_EJECUTABLE                 # carpeta que genera PyInstaller
ENTREGABLES = DIST / "entregables"
INSTALADOR = RAIZ / "instalador"
ICONO = RAIZ / "desktop" / "recursos" / "icono.png"
PAQUETE_LINUX = "analizador-disco"             # nombre del paquete y del comando en Linux
WINDOWS = sys.platform == "win32"
LINUX = sys.platform.startswith("linux")


def paso(texto: str) -> None:
    print(f"\n=== {texto} ===", flush=True)


def ejecutar(comando: list[str], **opciones) -> None:
    print("  $", " ".join(str(parte) for parte in comando), flush=True)
    subprocess.run([str(parte) for parte in comando], check=True, **opciones)


# ---------------------------------------------------------------- 1. ejecutable

def archivo_de_version() -> None:
    """Metadatos que Windows muestra en Propiedades > Detalles del .exe."""
    numeros = tuple(int(parte) for parte in (VERSION.split(".") + ["0", "0", "0"])[:4])
    destino = RAIZ / "build" / "version_windows.txt"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(f"""# Generado por build.py
VSVersionInfo(
  ffi=FixedFileInfo(filevers={numeros}, prodvers={numeros}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('0c0a04b0', [
      StringStruct('CompanyName', 'alonsogvg21-bit'),
      StringStruct('FileDescription', {NOMBRE!r}),
      StringStruct('FileVersion', {VERSION!r}),
      StringStruct('InternalName', {NOMBRE_EJECUTABLE!r}),
      StringStruct('OriginalFilename', {NOMBRE_EJECUTABLE + '.exe'!r}),
      StringStruct('ProductName', {NOMBRE!r}),
      StringStruct('ProductVersion', {VERSION!r}),
      StringStruct('Comments', {DESCRIPCION!r}),
      StringStruct('LegalCopyright', 'Licencia MIT'),
    ])]),
    VarFileInfo([VarStruct('Translation', [0x0c0a, 1200])])
  ]
)
""", encoding="utf-8")


def compilar() -> Path:
    paso(f"Compilando {NOMBRE} {VERSION} con PyInstaller")
    if WINDOWS:
        archivo_de_version()
    ejecutar([sys.executable, "-m", "PyInstaller", RAIZ / "analizador-disco.spec",
              "--noconfirm", "--clean", "--distpath", DIST, "--workpath", RAIZ / "build" / "pyinstaller"])
    ejecutable = APP / (NOMBRE_EJECUTABLE + (".exe" if WINDOWS else ""))

    # Comprobaciones: mejor fallar aquí que entregar un paquete que no arranca.
    interno = APP / "_internal"
    plugin = "qwindows.dll" if WINDOWS else "libqxcb.so"
    imprescindibles = [
        ejecutable,
        interno / "desktop" / "recursos" / "icono.png", interno / "web" / "templates" / "index.html",
        interno / "LICENSE", interno / "NOTICE",
    ]
    faltan = [str(ruta) for ruta in imprescindibles if not ruta.exists()]
    # El plugin de plataforma de Qt es el que abre la ventana. Su carpeta cambia
    # según el sistema (PySide6/plugins en Windows, PySide6/Qt/plugins en Linux).
    if not any((interno / "PySide6").rglob(f"platforms/{plugin}")):
        faltan.append(f"el plugin de Qt platforms/{plugin}")
    if faltan:
        raise SystemExit("El paquete está incompleto. Faltan:\n  " + "\n  ".join(faltan))
    print(f"  Ejecutable: {ejecutable}")
    return ejecutable


# ---------------------------------------------------------------- firma (opcional)

def firmar_windows(archivo: Path) -> None:
    """Firma un .exe si hay certificado configurado. Sin certificado no hace nada."""
    certificado, clave = os.environ.get("FIRMA_PFX"), os.environ.get("FIRMA_CLAVE")
    if not (WINDOWS and certificado and clave):
        return
    herramienta = shutil.which("signtool")
    if herramienta is None:
        raise SystemExit("Hay certificado pero no se encuentra signtool (viene con el SDK de Windows).")
    print(f"  Firmando {archivo.name}")
    # La clave no se imprime: por eso no se usa ejecutar().
    subprocess.run([herramienta, "sign", "/f", certificado, "/p", clave, "/fd", "SHA256",
                    "/tr", "http://timestamp.digicert.com", "/td", "SHA256", str(archivo)], check=True)


# ---------------------------------------------------------------- 2. paquete portable

def paquete_portable() -> Path:
    paso("Paquete portable (no necesita instalación)")
    if WINDOWS:
        destino = ENTREGABLES / f"{NOMBRE_EJECUTABLE}-{VERSION}-windows-x64-portable.zip"
        with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archivo:
            for ruta in sorted(APP.rglob("*")):
                if ruta.is_file():
                    archivo.write(ruta, Path(NOMBRE_EJECUTABLE) / ruta.relative_to(APP))
    else:
        destino = ENTREGABLES / f"{NOMBRE_EJECUTABLE}-{VERSION}-linux-{platform.machine()}.tar.gz"
        with tarfile.open(destino, "w:gz") as archivo:
            archivo.add(APP, arcname=NOMBRE_EJECUTABLE)
    print(f"  {destino.name}")
    return destino


# ---------------------------------------------------------------- 3. instaladores

def buscar_inno_setup() -> str | None:
    encontrado = shutil.which("iscc") or shutil.which("ISCC")
    if encontrado:
        return encontrado
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"),
                 os.environ.get("LOCALAPPDATA", "") + "\\Programs"):
        candidato = Path(base or "") / "Inno Setup 6" / "ISCC.exe"
        if candidato.is_file():
            return str(candidato)
    return None


def instalador_windows() -> Path:
    paso("Instalador de Windows (Inno Setup)")
    compilador = buscar_inno_setup()
    if compilador is None:
        raise SystemExit("No se encuentra Inno Setup 6. Instálalo desde https://jrsoftware.org/isdl.php "
                         "(o con: winget install JRSoftware.InnoSetup) y vuelve a ejecutar.")
    nombre = f"{NOMBRE_EJECUTABLE}-{VERSION}-windows-x64-setup"
    ejecutar([compilador, f"/DVersion={VERSION}", f"/DNombre={NOMBRE}", f"/DEjecutable={NOMBRE_EJECUTABLE}",
              f"/DWeb={WEB}", f"/DOrigen={APP}", f"/DRaiz={RAIZ}", f"/DSalida={ENTREGABLES}",
              f"/DArchivo={nombre}", INSTALADOR / "windows" / "analizador-disco.iss"])
    destino = ENTREGABLES / f"{nombre}.exe"
    firmar_windows(destino)
    return destino


def _escribir_ejecutable(ruta: Path, texto: str) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(texto, encoding="utf-8", newline="\n")
    ruta.chmod(ruta.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _entrada_de_escritorio(comando: str) -> str:
    plantilla = (INSTALADOR / "linux" / "analizador-disco.desktop").read_text(encoding="utf-8")
    return plantilla.replace("@NOMBRE@", NOMBRE).replace("@DESCRIPCION@", DESCRIPCION).replace("@COMANDO@", comando)


def appimage() -> Path:
    paso("AppImage para Linux")
    herramienta = os.environ.get("APPIMAGETOOL") or shutil.which("appimagetool")
    if herramienta is None:
        raise SystemExit("No se encuentra appimagetool. Descárgalo de "
                         "https://github.com/AppImage/appimagetool/releases y ponlo en el PATH "
                         "(o indica su ruta en la variable APPIMAGETOOL).")
    carpeta = RAIZ / "build" / "AppDir"
    shutil.rmtree(carpeta, ignore_errors=True)
    shutil.copytree(APP, carpeta / "usr" / "lib" / PAQUETE_LINUX, symlinks=True)
    shutil.copy(ICONO, carpeta / f"{PAQUETE_LINUX}.png")
    (carpeta / f"{PAQUETE_LINUX}.desktop").write_text(_entrada_de_escritorio(PAQUETE_LINUX), encoding="utf-8")
    # AppRun es lo que se ejecuta al abrir la AppImage; pasa los argumentos tal cual
    # (así "archivo.AppImage cli resumen" también funciona).
    _escribir_ejecutable(carpeta / "AppRun", '#!/bin/sh\n'
                         'AQUI="$(dirname "$(readlink -f "$0")")"\n'
                         f'exec "$AQUI/usr/lib/{PAQUETE_LINUX}/{NOMBRE_EJECUTABLE}" "$@"\n')
    destino = ENTREGABLES / f"{NOMBRE_EJECUTABLE}-{VERSION}-{platform.machine()}.AppImage"
    # Dentro de contenedores (como en GitHub Actions) no hay FUSE: se extrae y se ejecuta.
    entorno = {**os.environ, "ARCH": platform.machine(), "APPIMAGE_EXTRACT_AND_RUN": "1"}
    ejecutar([herramienta, carpeta, destino], env=entorno)
    return destino


def paquete_deb() -> Path:
    paso("Paquete .deb (Debian, Ubuntu, Mint)")
    if shutil.which("dpkg-deb") is None:
        raise SystemExit("No se encuentra dpkg-deb (solo existe en sistemas tipo Debian).")
    arquitectura = subprocess.run(["dpkg", "--print-architecture"], capture_output=True,
                                  text=True, check=True).stdout.strip()
    carpeta = RAIZ / "build" / "deb"
    shutil.rmtree(carpeta, ignore_errors=True)
    # Todo el programa va en /usr/lib/analizador-disco, que pertenece a root.
    # Es imprescindible para el ayudante de salud: polkit lo ejecuta como
    # administrador, así que un usuario normal no debe poder modificarlo. Si
    # estuviera en una carpeta del usuario, cualquiera podría cambiarlo y
    # conseguir que su propio código se ejecutara con privilegios.
    programa = carpeta / "usr" / "lib" / PAQUETE_LINUX / "programa"
    shutil.copytree(APP, programa, symlinks=True)
    en_disco = f"/usr/lib/{PAQUETE_LINUX}/programa/{NOMBRE_EJECUTABLE}"
    _escribir_ejecutable(carpeta / "usr" / "bin" / PAQUETE_LINUX, f'#!/bin/sh\nexec {en_disco} "$@"\n')
    # El ayudante es un lanzador fijo: siempre añade "--helper", de modo que con
    # permisos de administrador solo se puede entrar en el modo ayudante.
    _escribir_ejecutable(carpeta / "usr" / "lib" / PAQUETE_LINUX / "ayudante",
                         f'#!/bin/sh\nexec {en_disco} --helper "$@"\n')
    politica = carpeta / "usr" / "share" / "polkit-1" / "actions"
    politica.mkdir(parents=True)
    shutil.copy(INSTALADOR / "linux" / "io.github.alonsogvg21bit.analizador-disco.policy", politica)
    aplicaciones = carpeta / "usr" / "share" / "applications"
    aplicaciones.mkdir(parents=True)
    (aplicaciones / f"{PAQUETE_LINUX}.desktop").write_text(_entrada_de_escritorio(PAQUETE_LINUX), encoding="utf-8")
    iconos = carpeta / "usr" / "share" / "icons" / "hicolor" / "256x256" / "apps"
    iconos.mkdir(parents=True)
    shutil.copy(ICONO, iconos / f"{PAQUETE_LINUX}.png")
    documentos = carpeta / "usr" / "share" / "doc" / PAQUETE_LINUX
    documentos.mkdir(parents=True)
    shutil.copy(RAIZ / "LICENSE", documentos / "copyright")
    shutil.copy(RAIZ / "NOTICE", documentos / "NOTICE")

    tamano_kb = sum(r.stat().st_size for r in carpeta.rglob("*") if r.is_file()) // 1024
    control = carpeta / "DEBIAN" / "control"
    control.parent.mkdir()
    control.write_text(
        f"Package: {PAQUETE_LINUX}\nVersion: {VERSION}\nSection: utils\nPriority: optional\n"
        f"Architecture: {arquitectura}\nInstalled-Size: {tamano_kb}\n"
        "Maintainer: alonsogvg21-bit <291668446+alonsogvg21-bit@users.noreply.github.com>\n"
        f"Homepage: {WEB}\n"
        # Bibliotecas del sistema que Qt necesita para abrir la ventana.
        "Depends: libc6, libegl1, libgl1, libxkbcommon-x11-0, libxcb-cursor0, libxcb-icccm4, "
        "libxcb-keysyms1, libxcb-shape0, libfontconfig1, libdbus-1-3\n"
        # Opcionales: la salud del disco y pedir permisos de administrador.
        "Recommends: smartmontools, policykit-1 | polkitd\n"
        f"Description: {NOMBRE}\n {DESCRIPCION}\n Por defecto solo lee; nada se borra sin confirmación.\n",
        encoding="utf-8", newline="\n")
    # Permisos fijos, sin depender de cómo estuvieran los archivos de origen.
    # Nada puede ser modificable por usuarios normales: el ayudante y la
    # política de polkit se ejecutan o se leen con privilegios.
    for ruta in carpeta.rglob("*"):
        if ruta.is_symlink():
            continue
        if ruta.is_dir():
            ruta.chmod(0o755)
        elif (carpeta / "usr" / "share") in ruta.parents or ruta.parent.name == "DEBIAN":
            ruta.chmod(0o644)           # datos: política, icono, entrada de menú, licencias
        else:
            ejecutable = ruta.stat().st_mode & stat.S_IXUSR
            ruta.chmod(0o755 if ejecutable else 0o644)

    destino = ENTREGABLES / f"{PAQUETE_LINUX}_{VERSION}_{arquitectura}.deb"
    ejecutar(["dpkg-deb", "--build", "--root-owner-group", carpeta, destino])
    return destino


# ---------------------------------------------------------------- 4. sumas SHA-256

def sha256(archivo: Path) -> str:
    resumen = hashlib.sha256()
    with archivo.open("rb") as contenido:
        for bloque in iter(lambda: contenido.read(1024 * 1024), b""):
            resumen.update(bloque)
    return resumen.hexdigest()


def escribir_sumas(archivos: list[Path]) -> Path:
    """Archivo con el formato de 'sha256sum': se comprueba con  sha256sum -c ARCHIVO."""
    paso("Sumas SHA-256")
    sistema = "windows" if WINDOWS else "linux"
    destino = ENTREGABLES / f"SHA256SUMS-{sistema}.txt"
    lineas = [f"{sha256(archivo)}  {archivo.name}" for archivo in sorted(archivos)]
    destino.write_text("\n".join(lineas) + "\n", encoding="utf-8", newline="\n")
    print("  " + "\n  ".join(lineas))
    return destino


# ---------------------------------------------------------------- principal

def main() -> int:
    parser = argparse.ArgumentParser(description=f"Compila {NOMBRE} y prepara los entregables.")
    parser.add_argument("--instalador", action="store_true",
                        help="crear también el instalador (Inno Setup en Windows; AppImage y .deb en Linux)")
    parser.add_argument("--sin-compilar", action="store_true",
                        help="reutilizar la carpeta dist/ ya compilada")
    argumentos = parser.parse_args()
    if not (WINDOWS or LINUX):
        raise SystemExit("Solo se puede compilar en Windows o en Linux.")

    if argumentos.sin_compilar:
        if not APP.is_dir():
            raise SystemExit(f"No existe {APP}; ejecuta primero sin --sin-compilar.")
    else:
        firmar_windows(compilar())

    shutil.rmtree(ENTREGABLES, ignore_errors=True)
    ENTREGABLES.mkdir(parents=True)
    archivos = [paquete_portable()]
    if argumentos.instalador:
        archivos += [instalador_windows()] if WINDOWS else [appimage(), paquete_deb()]
    escribir_sumas(archivos)

    paso("Listo")
    for archivo in sorted(ENTREGABLES.iterdir()):
        print(f"  {archivo.stat().st_size / 1024 / 1024:8.1f} MB  {archivo}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
