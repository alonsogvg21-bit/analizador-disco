"""Datos básicos de cada disco (modelo, capacidad y tipo) que NO necesitan permisos.

Sirven para que la tarjeta de salud muestre de qué disco se trata aunque
todavía no se hayan concedido permisos para leer su SMART.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from utils.sistema import LINUX, WINDOWS, sistema_actual

# Los nombres son los de smartctl: /dev/sda, /dev/nvme0...
# Cada valor: {"modelo": str, "capacidad": int, "es_ssd": bool | None, "interfaz": str}


def _letras(numero: int) -> str:
    texto = ""
    numero += 1
    while numero > 0:
        numero, resto = divmod(numero - 1, 26)
        texto = chr(ord("a") + resto) + texto
    return texto


def _windows(ejecutar=subprocess.run) -> dict[str, dict]:
    """Pregunta a Windows por sus discos físicos. No requiere administrador."""
    orden = ("Get-PhysicalDisk | Select-Object DeviceId,FriendlyName,Size,MediaType,BusType "
             "| ConvertTo-Json -Compress")
    try:
        proceso = ejecutar(["powershell", "-NoProfile", "-NonInteractive", "-Command", orden],
                           capture_output=True, text=True, timeout=20,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        datos = json.loads(proceso.stdout or "[]")
    except (OSError, ValueError, subprocess.SubprocessError):
        return {}
    if isinstance(datos, dict):   # con un solo disco, PowerShell no devuelve una lista
        datos = [datos]
    discos = {}
    for disco in datos:
        try:
            numero = int(disco["DeviceId"])
        except (KeyError, TypeError, ValueError):
            continue
        tipo = str(disco.get("MediaType") or "")
        discos["/dev/sd" + _letras(numero)] = {
            "modelo": str(disco.get("FriendlyName") or "").strip(),
            "capacidad": int(disco.get("Size") or 0),
            "es_ssd": True if tipo == "SSD" else False if tipo == "HDD" else None,
            "interfaz": str(disco.get("BusType") or ""),
        }
    return discos


def _leer(archivo: Path) -> str:
    try:
        return archivo.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def _linux(sys_block: Path = Path("/sys/block")) -> dict[str, dict]:
    """Lee /sys/block, que cualquier usuario puede consultar."""
    discos = {}
    try:
        entradas = sorted(sys_block.iterdir())
    except OSError:
        return discos
    for entrada in entradas:
        nombre = entrada.name
        if nombre.startswith("nvme"):
            # El bloque es nvme0n1, pero smartctl nombra el controlador: /dev/nvme0
            dispositivo, interfaz = "/dev/nvme" + nombre[4:].split("n")[0], "NVMe"
        elif nombre.startswith(("sd", "hd")):
            dispositivo, interfaz = "/dev/" + nombre, "SATA/USB"
        else:
            continue   # loop, ram, dm-, sr...
        sectores = _leer(entrada / "size")
        giratorio = _leer(entrada / "queue" / "rotational")
        discos.setdefault(dispositivo, {
            "modelo": _leer(entrada / "device" / "model"),
            "capacidad": int(sectores) * 512 if sectores.isdigit() else 0,
            "es_ssd": True if nombre.startswith("nvme") or giratorio == "0" else
                      False if giratorio == "1" else None,
            "interfaz": interfaz,
        })
    return discos


def info_basica(sistema: str | None = None) -> dict[str, dict]:
    """Modelo, capacidad y tipo de cada disco, sin pedir permisos. Nunca lanza errores."""
    sistema = sistema or sistema_actual()
    try:
        if sistema == WINDOWS:
            return _windows()
        if sistema == LINUX:
            return _linux()
    except Exception:
        pass
    return {}
