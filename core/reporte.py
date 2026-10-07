"""Exportación del análisis a HTML y CSV."""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass, field
from datetime import datetime
from html import escape
from pathlib import Path

from core.carpetas import contenido_de
from core.discos import resumen_discos
from core.escaner import archivos_mas_pesados
from core.modelos import (
    CategoriaBasura, InfoArchivo, InfoCarpeta, InfoDisco, ResultadoEscaneo, ResumenTipo,
)
from core.tipos import resumen_por_tipo
from utils.formato import fecha_legible, porcentaje, tamano_legible


@dataclass
class DatosReporte:
    """Todo lo que aparece en un reporte, ya calculado."""
    raiz: Path
    tamano_total: int
    num_archivos: int
    errores: int
    discos: list[InfoDisco]
    carpetas: list[InfoCarpeta]
    top: list[InfoArchivo]
    tipos: list[ResumenTipo]
    basura: list[CategoriaBasura] = field(default_factory=list)
    generado: datetime = field(default_factory=datetime.now)


def reunir_datos(
    resultado: ResultadoEscaneo,
    basura: list[CategoriaBasura] | None = None,
    cantidad_top: int = 50,
) -> DatosReporte:
    """Junta las distintas funciones del motor en un solo objeto para exportar."""
    return DatosReporte(
        raiz=resultado.raiz,
        tamano_total=resultado.tamano_total,
        num_archivos=resultado.num_archivos,
        errores=resultado.errores,
        discos=resumen_discos(),
        carpetas=contenido_de(resultado).subcarpetas,
        top=archivos_mas_pesados(resultado, cantidad_top),
        tipos=resumen_por_tipo(resultado.archivos),
        basura=basura or [],
    )


# ---------------------------------------------------------------- CSV

_COLUMNAS = ("seccion", "nombre", "ruta", "tamano_bytes", "tamano", "fecha_modificacion", "detalle")


def exportar_csv(datos: DatosReporte, destino: str | os.PathLike) -> Path:
    """Escribe una sola tabla; la columna 'seccion' indica a qué parte pertenece cada fila."""
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig: Excel en Windows reconoce así los acentos.
    with destino.open("w", newline="", encoding="utf-8-sig") as archivo:
        salida = csv.writer(archivo)
        salida.writerow(_COLUMNAS)

        for d in datos.discos:
            salida.writerow(("disco", d.dispositivo, d.punto_montaje, d.usado,
                             tamano_legible(d.usado), "",
                             f"{d.porcentaje}% usado de {tamano_legible(d.total)}"))
        for c in datos.carpetas:
            salida.writerow(("carpeta", c.ruta.name, c.ruta, c.tamano,
                             tamano_legible(c.tamano), "", f"{c.num_archivos} archivos"))
        for a in datos.top:
            salida.writerow(("archivo_pesado", a.nombre, a.ruta, a.tamano,
                             tamano_legible(a.tamano), fecha_legible(a.modificado), ""))
        for t in datos.tipos:
            salida.writerow(("tipo", t.tipo, "", t.tamano,
                             tamano_legible(t.tamano), "", f"{t.cantidad} archivos"))
        for categoria in datos.basura:
            for e in categoria.elementos:
                salida.writerow(("basura", categoria.nombre, e.ruta, e.tamano,
                                 tamano_legible(e.tamano), "",
                                 e.detalle if e.limpiable else f"[solo informativo] {e.detalle}"))
    return destino


# ---------------------------------------------------------------- HTML

_ESTILO = """
body{font-family:system-ui,Segoe UI,sans-serif;margin:2rem auto;max-width:1000px;padding:0 1rem;
color:#1f2933;background:#f7f9fb}
h1{margin-bottom:.2rem} h2{margin-top:2.2rem;border-bottom:2px solid #d9e2ec;padding-bottom:.3rem}
.nota{color:#627d98;font-size:.9rem}
table{border-collapse:collapse;width:100%;background:#fff;font-size:.9rem}
th,td{padding:.45rem .6rem;border-bottom:1px solid #e4e9ef;text-align:left;vertical-align:top}
th{background:#eef2f6} td.num{text-align:right;white-space:nowrap}
td.ruta{word-break:break-all}
.barra{background:#e4e9ef;border-radius:4px;height:10px;min-width:120px}
.barra span{display:block;height:10px;border-radius:4px}
.verde{background:#2f9e44}.amarillo{background:#f0b429}.rojo{background:#d64545}
"""


def _color(porc: float) -> str:
    return "verde" if porc < 70 else "amarillo" if porc < 90 else "rojo"


def _tabla(encabezados: list[str], filas: list[list[str]]) -> str:
    """Arma una tabla. Las celdas ya deben venir escapadas."""
    if not filas:
        return '<p class="nota">Sin datos.</p>'
    cabecera = "".join(f"<th>{e}</th>" for e in encabezados)
    cuerpo = "".join("<tr>" + "".join(fila) + "</tr>" for fila in filas)
    return f"<table><thead><tr>{cabecera}</tr></thead><tbody>{cuerpo}</tbody></table>"


def _td(texto: object, clase: str = "") -> str:
    atributo = f' class="{clase}"' if clase else ""
    return f"<td{atributo}>{escape(str(texto))}</td>"


def _barra(porc: float, clase: str = "verde") -> str:
    ancho = max(0.0, min(porc, 100.0))
    return f'<td><div class="barra"><span class="{clase}" style="width:{ancho}%"></span></div></td>'


def exportar_html(datos: DatosReporte, destino: str | os.PathLike, max_basura: int = 100) -> Path:
    """Genera un reporte HTML en un solo archivo, sin dependencias externas."""
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)

    discos = _tabla(
        ["Disco", "Usado", "Libre", "Total", "%", ""],
        [[_td(d.punto_montaje), _td(tamano_legible(d.usado), "num"),
          _td(tamano_legible(d.libre), "num"), _td(tamano_legible(d.total), "num"),
          _td(f"{d.porcentaje}%", "num"), _barra(d.porcentaje, _color(d.porcentaje))]
         for d in datos.discos],
    )
    carpetas = _tabla(
        ["Carpeta", "Tamaño", "Archivos", ""],
        [[_td(c.ruta, "ruta"), _td(tamano_legible(c.tamano), "num"), _td(c.num_archivos, "num"),
          _barra(porcentaje(c.tamano, datos.tamano_total))]
         for c in datos.carpetas],
    )
    tipos = _tabla(
        ["Tipo", "Tamaño", "Archivos", ""],
        [[_td(t.tipo), _td(tamano_legible(t.tamano), "num"), _td(t.cantidad, "num"),
          _barra(porcentaje(t.tamano, datos.tamano_total))]
         for t in datos.tipos],
    )
    top = _tabla(
        ["#", "Archivo", "Tamaño", "Modificado"],
        [[_td(i, "num"), _td(a.ruta, "ruta"), _td(tamano_legible(a.tamano), "num"),
          _td(fecha_legible(a.modificado), "num")]
         for i, a in enumerate(datos.top, 1)],
    )

    partes_basura = []
    for categoria in datos.basura:
        if not categoria.elementos:
            continue
        mostrados = sorted(categoria.elementos, key=lambda e: e.tamano, reverse=True)[:max_basura]
        resto = len(categoria.elementos) - len(mostrados)
        partes_basura.append(
            f"<h3>{escape(categoria.nombre)} — {tamano_legible(categoria.tamano_total)}</h3>"
            f'<p class="nota">{escape(categoria.descripcion)}</p>'
            + _tabla(
                ["Ruta", "Tamaño", "Detalle"],
                [[_td(e.ruta, "ruta"), _td(tamano_legible(e.tamano), "num"),
                  _td(e.detalle if e.limpiable else f"[solo informativo] {e.detalle}")]
                 for e in mostrados],
            )
            + (f'<p class="nota">… y {resto} elementos más (ver CSV).</p>' if resto > 0 else "")
        )
    basura = "".join(partes_basura) or '<p class="nota">No se analizó o no se encontró nada.</p>'

    html = f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Reporte de disco</title><style>{_ESTILO}</style></head><body>
<h1>Reporte de uso de disco</h1>
<p class="nota">Carpeta analizada: <strong>{escape(str(datos.raiz))}</strong> ·
{tamano_legible(datos.tamano_total)} en {datos.num_archivos} archivos ·
{datos.errores} elementos sin acceso · generado el {datos.generado:%Y-%m-%d %H:%M}</p>
<h2>Discos</h2>{discos}
<h2>Carpetas que más ocupan</h2>{carpetas}
<h2>Tipos de archivo</h2>{tipos}
<h2>Archivos más pesados</h2>{top}
<h2>Posible basura</h2>
<p class="nota">Este reporte es solo informativo: no se ha borrado nada.</p>{basura}
</body></html>"""
    destino.write_text(html, encoding="utf-8")
    return destino
