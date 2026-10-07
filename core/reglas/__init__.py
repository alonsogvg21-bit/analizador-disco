"""Carga las reglas que corresponden al sistema operativo actual."""

from __future__ import annotations

from core.reglas.base import ReglaUbicacion
from utils.sistema import LINUX, WINDOWS, sistema_actual


def reglas_del_sistema(sistema: str | None = None) -> list[ReglaUbicacion]:
    sistema = sistema or sistema_actual()
    if sistema == WINDOWS:
        from core.reglas import windows
        return windows.obtener_reglas()
    if sistema == LINUX:
        from core.reglas import linux
        return linux.obtener_reglas()
    return []  # sistema no soportado: solo funcionan las detecciones genéricas
