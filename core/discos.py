"""Resumen de discos y particiones usando psutil."""

from __future__ import annotations

import psutil

from core.modelos import InfoDisco

# Sistemas de archivos virtuales o de solo lectura que no interesan (Linux).
_IGNORADOS = {"squashfs", "tmpfs", "devtmpfs", "overlay", "iso9660", "udf", ""}


def resumen_discos() -> list[InfoDisco]:
    """Devuelve total, usado y libre de cada partición real."""
    discos: list[InfoDisco] = []
    vistos: set[str] = set()

    for particion in psutil.disk_partitions(all=False):
        if particion.fstype.lower() in _IGNORADOS or particion.device in vistos:
            continue
        try:
            uso = psutil.disk_usage(particion.mountpoint)
        except OSError:
            # Lector de CD vacío, unidad de red desconectada, sin permisos...
            continue
        if uso.total == 0:
            continue
        vistos.add(particion.device)
        discos.append(
            InfoDisco(
                dispositivo=particion.device,
                punto_montaje=particion.mountpoint,
                sistema_archivos=particion.fstype,
                total=uso.total,
                usado=uso.used,
                libre=uso.free,
                porcentaje=uso.percent,
            )
        )
    return discos
