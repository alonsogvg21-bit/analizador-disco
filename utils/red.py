"""Detección de discos de red (unidades ya montadas).

El programa no monta nada: solo reconoce que una ruta está en la red para
avisar de que el escaneo será lento y para no usar allí la papelera.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable

from utils.sistema import LINUX, WINDOWS, sistema_actual

AVISO_RED = ("Esta carpeta está en un disco de red: el escaneo puede ser bastante "
             "más lento que en un disco local.")

# Sistemas de archivos de red habituales en Linux.
SISTEMAS_DE_RED = frozenset({
    "nfs", "nfs4", "cifs", "smbfs", "smb3", "sshfs", "fuse.sshfs", "davfs", "fuse.davfs2",
    "9p", "ceph", "glusterfs", "fuse.glusterfs", "afs", "ncpfs", "fuse.rclone",
})

_UNIDAD_REMOTA = 4  # valor DRIVE_REMOTE de Windows


def _tipo_de_unidad_windows(raiz: str) -> int:
    import ctypes
    return ctypes.windll.kernel32.GetDriveTypeW(raiz)


def _es_unc(texto: str) -> bool:
    """\\\\servidor\\recurso (o su forma larga \\\\?\\UNC\\...), pero no \\\\?\\C:\\ ni \\\\.\\."""
    texto = texto.replace("/", "\\")
    if texto.upper().startswith("\\\\?\\UNC\\"):
        return True
    return texto.startswith("\\\\") and not texto.startswith(("\\\\?\\", "\\\\.\\"))


def es_ruta_de_red(
    ruta: str | os.PathLike,
    sistema: str | None = None,
    tipo_de_unidad: Callable[[str], int] | None = None,
    particiones: Iterable | None = None,
) -> bool:
    """True si la ruta está en un disco de red.

    - Windows: rutas UNC (\\\\servidor\\recurso) y letras de unidad conectadas a la red.
    - Linux: carpetas montadas con NFS, SMB/CIFS, SSHFS, etc.
    Los dos últimos parámetros solo sirven para las pruebas.
    """
    sistema = sistema or sistema_actual()
    texto = os.fspath(ruta)

    if sistema == WINDOWS:
        # Importante: aquí no se consulta la red (nada de resolve() ni exists()).
        # Preguntar por un servidor apagado dejaría el programa esperando.
        if _es_unc(texto):
            return True
        unidad = os.path.splitdrive(os.path.abspath(texto) if sistema_actual() == WINDOWS else texto)[0]
        if len(unidad) == 2 and unidad[1] == ":":
            try:
                return (tipo_de_unidad or _tipo_de_unidad_windows)(unidad + "\\") == _UNIDAD_REMOTA
            except (OSError, AttributeError):
                return False
        return False

    if sistema == LINUX:
        if particiones is None:
            import psutil
            particiones = psutil.disk_partitions(all=True)
        real = os.path.realpath(texto)
        # El punto de montaje más largo que contiene a la ruta es el suyo.
        mejor, tipo = "", ""
        for particion in particiones:
            montaje = particion.mountpoint.rstrip("/") or "/"
            if (real == montaje or real.startswith(montaje.rstrip("/") + "/")) and len(montaje) >= len(mejor):
                mejor, tipo = montaje, particion.fstype.lower()
        return tipo in SISTEMAS_DE_RED or tipo.startswith(("nfs", "cifs", "smb"))

    return False
