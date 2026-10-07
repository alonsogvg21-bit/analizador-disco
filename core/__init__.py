"""Motor de análisis de disco. No depende de ninguna interfaz."""

from core.basura import detectar_basura
from core.carpetas import contenido_de
from core.discos import resumen_discos
from core.duplicados import buscar_duplicados
from core.escaner import archivos_mas_pesados, escanear
from core.reporte import exportar_csv, exportar_html, reunir_datos
from core.tipos import clasificar, resumen_por_tipo

__all__ = [
    "archivos_mas_pesados", "buscar_duplicados", "clasificar", "contenido_de",
    "detectar_basura", "escanear", "exportar_csv", "exportar_html",
    "resumen_discos", "resumen_por_tipo", "reunir_datos",
]
