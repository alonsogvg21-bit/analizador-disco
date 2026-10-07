"""Reporte en PDF con resumen, gráficas de barras y los archivos más pesados.

Usa la biblioteca fpdf2 (Python puro, sin programas externos). Las gráficas
se dibujan directamente con rectángulos, así que no hace falta matplotlib.
"""

from __future__ import annotations

import os
from pathlib import Path

from core.reporte import DatosReporte
from utils.formato import fecha_legible, porcentaje, tamano_legible

# Colores (rojo, verde, azul)
_AZUL = (42, 120, 214)
_PISTA = (232, 231, 226)
_TEXTO = (11, 11, 11)
_SUAVE = (82, 81, 78)
_VERDE, _AMARILLO, _ROJO = (12, 163, 12), (250, 178, 25), (208, 59, 59)

MAX_CARPETAS = 12
MAX_ARCHIVOS = 25

_NOMBRES_TIPO = {
    "videos": "Videos", "imagenes": "Imágenes", "documentos": "Documentos",
    "comprimidos": "Comprimidos", "instaladores": "Instaladores", "codigo": "Código",
    "otros": "Otros",
}


def _texto(valor: object) -> str:
    """Las fuentes integradas del PDF solo admiten Latin-1; lo demás se sustituye por '?'."""
    return str(valor).encode("latin-1", "replace").decode("latin-1")


def _recortar(texto: str, maximo: int) -> str:
    """Acorta una ruta larga por el medio, conservando el principio y el nombre del archivo."""
    if len(texto) <= maximo:
        return texto
    mitad = (maximo - 5) // 2
    return f"{texto[:mitad]} ... {texto[-mitad:]}"


def exportar_pdf(datos: DatosReporte, destino: str | os.PathLike) -> Path:
    """Genera el reporte en PDF y devuelve la ruta del archivo."""
    try:
        from fpdf import FPDF
    except ImportError:
        raise RuntimeError(
            "Para exportar a PDF hace falta la biblioteca fpdf2: pip install fpdf2") from None

    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)

    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_title("Reporte de uso de disco")
    pdf.add_page()
    ancho = pdf.w - pdf.l_margin - pdf.r_margin

    def linea(texto: str, tamano: int = 10, estilo: str = "", color=_TEXTO, alto: float = 5.5) -> None:
        pdf.set_font("Helvetica", estilo, tamano)
        pdf.set_text_color(*color)
        pdf.multi_cell(ancho, alto, _texto(texto), new_x="LMARGIN", new_y="NEXT")

    def seccion(titulo: str, espacio_minimo: float = 30) -> None:
        # Un título nunca se queda solo al final de la página.
        if pdf.get_y() + espacio_minimo > pdf.h - pdf.b_margin:
            pdf.add_page()
        pdf.ln(4)
        linea(titulo, 13, "B", alto=7)
        pdf.set_draw_color(*_PISTA)
        pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + ancho, pdf.get_y())
        pdf.ln(2)

    def barras(filas: list[tuple[str, float, str, tuple]]) -> None:
        """Gráfica de barras horizontales. Cada fila: (etiqueta, porcentaje, valor escrito, color)."""
        ancho_etiqueta, ancho_valor, alto = 48, 52, 6
        ancho_barra = ancho - ancho_etiqueta - ancho_valor - 4
        pdf.set_font("Helvetica", "", 9)
        for etiqueta, porc, valor, color in filas:
            if pdf.get_y() + alto + 1 > pdf.h - pdf.b_margin:
                pdf.add_page()
            y = pdf.get_y()
            pdf.set_text_color(*_TEXTO)
            pdf.set_xy(pdf.l_margin, y)
            pdf.cell(ancho_etiqueta, alto, _texto(_recortar(etiqueta, 28)))
            x = pdf.l_margin + ancho_etiqueta + 2
            pdf.set_fill_color(*_PISTA)
            pdf.rect(x, y + 1.2, ancho_barra, alto - 2.4, style="F")
            relleno = ancho_barra * max(0.0, min(porc, 100.0)) / 100
            if relleno > 0:
                pdf.set_fill_color(*color)
                pdf.rect(x, y + 1.2, max(relleno, 0.4), alto - 2.4, style="F")
            pdf.set_text_color(*_SUAVE)
            pdf.set_xy(x + ancho_barra + 2, y)
            pdf.cell(ancho_valor, alto, _texto(valor))
            pdf.set_xy(pdf.l_margin, y + alto + 1)

    def tabla(encabezados: list[str], anchos: list[float], filas: list[list[str]],
              derecha: tuple[int, ...] = ()) -> None:
        def fila_de_tabla(celdas: list[str], estilo: str, color) -> None:
            pdf.set_font("Helvetica", estilo, 8)
            pdf.set_text_color(*color)
            for indice, (celda, w) in enumerate(zip(celdas, anchos)):
                pdf.cell(w, 5.5, _texto(celda), border="B",
                         align="R" if indice in derecha else "L")
            pdf.ln(5.5)

        fila_de_tabla(encabezados, "B", _SUAVE)
        for fila in filas:
            if pdf.get_y() + 6 > pdf.h - pdf.b_margin:
                pdf.add_page()
                fila_de_tabla(encabezados, "B", _SUAVE)
            fila_de_tabla(fila, "", _TEXTO)

    # ------------------------------------------------------------ portada y resumen
    linea("Reporte de uso de disco", 20, "B", alto=10)
    linea(f"Carpeta analizada: {datos.raiz}", 10, color=_SUAVE)
    linea(f"Generado el {datos.generado:%Y-%m-%d %H:%M}", 10, color=_SUAVE)

    liberable = sum(c.tamano_limpiable for c in datos.basura)
    seccion("Resumen")
    resumen = [
        ("Espacio ocupado", tamano_legible(datos.tamano_total)),
        ("Archivos", f"{datos.num_archivos:,}".replace(",", " ")),
        ("Elementos sin acceso", str(datos.errores)),
        ("Basura que se podría liberar", tamano_legible(liberable)),
    ]
    if datos.top:
        mayor = datos.top[0]
        resumen.append(("Archivo más pesado", f"{mayor.nombre} ({tamano_legible(mayor.tamano)})"))
    if datos.carpetas:
        mayor = datos.carpetas[0]
        resumen.append(("Carpeta más pesada", f"{mayor.ruta.name} ({tamano_legible(mayor.tamano)})"))
    for etiqueta, valor in resumen:
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(*_SUAVE)
        pdf.cell(62, 6, _texto(etiqueta))
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(*_TEXTO)
        pdf.cell(ancho - 62, 6, _texto(_recortar(valor, 70)), new_x="LMARGIN", new_y="NEXT")

    # ------------------------------------------------------------ gráficas
    if datos.discos:
        seccion("Discos")
        barras([
            (d.punto_montaje, d.porcentaje,
             f"{d.porcentaje:.0f}% - {tamano_legible(d.libre)} libres",
             _VERDE if d.porcentaje < 70 else _AMARILLO if d.porcentaje < 90 else _ROJO)
            for d in datos.discos
        ])

    seccion("Tipos de archivo")
    barras([
        (_NOMBRES_TIPO.get(t.tipo, t.tipo), porcentaje(t.tamano, datos.tamano_total),
         f"{tamano_legible(t.tamano)} - {porcentaje(t.tamano, datos.tamano_total):.1f}%", _AZUL)
        for t in datos.tipos
    ])

    seccion("Carpetas que más ocupan")
    if datos.carpetas:
        barras([
            (c.ruta.name, porcentaje(c.tamano, datos.tamano_total),
             f"{tamano_legible(c.tamano)} - {porcentaje(c.tamano, datos.tamano_total):.1f}%", _AZUL)
            for c in datos.carpetas[:MAX_CARPETAS]
        ])
        if len(datos.carpetas) > MAX_CARPETAS:
            linea(f"... y {len(datos.carpetas) - MAX_CARPETAS} carpetas más.", 8, color=_SUAVE)
    else:
        linea("Esta carpeta no tiene subcarpetas.", 9, color=_SUAVE)

    # ------------------------------------------------------------ tablas
    seccion(f"Los {min(len(datos.top), MAX_ARCHIVOS)} archivos más pesados")
    tabla(["#", "Archivo", "Tamaño", "Modificado"], [8, ancho - 8 - 24 - 30, 24, 30],
          [[str(i), _recortar(a.ruta, 88), tamano_legible(a.tamano), fecha_legible(a.modificado)]
           for i, a in enumerate(datos.top[:MAX_ARCHIVOS], 1)],
          derecha=(0, 2, 3))

    con_elementos = [c for c in datos.basura if c.elementos]
    if con_elementos:
        seccion("Posible basura")
        tabla(["Categoría", "Elementos", "Tamaño", "Se podría liberar"],
              [ancho - 28 - 30 - 36, 28, 30, 36],
              [[c.nombre, str(len(c.elementos)), tamano_legible(c.tamano_total),
                tamano_legible(c.tamano_limpiable)] for c in con_elementos],
              derecha=(1, 2, 3))
        pdf.ln(2)
        linea("Este reporte es solo informativo: no se ha borrado nada. "
              "La lista completa de elementos está en el reporte CSV.", 8, color=_SUAVE, alto=4.5)

    pdf.output(str(destino))
    return destino
