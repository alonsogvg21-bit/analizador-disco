"""Funciones pequeñas para mostrar tamaños y fechas de forma legible."""

from __future__ import annotations

from datetime import datetime

_UNIDADES = ("B", "KB", "MB", "GB", "TB", "PB")


def tamano_legible(num_bytes: int | float) -> str:
    """Convierte bytes a un texto corto: 1536 -> '1.5 KB'."""
    valor = float(max(num_bytes, 0))
    for unidad in _UNIDADES:
        if valor < 1024 or unidad == _UNIDADES[-1]:
            # Los bytes sueltos no llevan decimales.
            return f"{int(valor)} B" if unidad == "B" else f"{valor:.1f} {unidad}"
        valor /= 1024
    return f"{valor:.1f} {_UNIDADES[-1]}"


def fecha_legible(marca_tiempo: float) -> str:
    """Convierte una marca de tiempo (segundos) a 'AAAA-MM-DD HH:MM'."""
    try:
        return datetime.fromtimestamp(marca_tiempo).strftime("%Y-%m-%d %H:%M")
    except (OSError, OverflowError, ValueError):
        # Algunos archivos traen fechas corruptas o fuera de rango.
        return "desconocida"


def porcentaje(parte: int | float, total: int | float) -> float:
    """Porcentaje con un decimal; devuelve 0 si el total es 0."""
    return round(parte * 100 / total, 1) if total else 0.0


def diferencia_en_mb(num_bytes: int | float) -> str:
    """Un cambio de tamaño en MB y con signo: 3145728 -> '+3.0 MB'."""
    return f"{num_bytes / (1024 * 1024):+,.1f} MB"
