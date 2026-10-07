"""Pruebas del listado de archivos con orden y filtros."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from cli.comandos import ejecutar
from core.consulta import listar_archivos
from core.escaner import escanear

DIA = 86400
BASE = 1_700_000_000  # una fecha fija cualquiera


@pytest.fixture
def carpeta(tmp_path: Path) -> Path:
    """Cuatro archivos con tamaños y fechas distintos entre sí.

    nombre       tamaño  modificado  último acceso
    peli.mp4       4000    día 1        día 9
    foto.jpg       3000    día 4        día 2
    informe.pdf    2000    día 3        día 7
    clip.mkv       1000    día 2        día 5
    """
    datos = (("peli.mp4", 4000, 1, 9), ("foto.jpg", 3000, 4, 2),
             ("informe.pdf", 2000, 3, 7), ("clip.mkv", 1000, 2, 5))
    for nombre, tamano, modificado, accedido in datos:
        archivo = tmp_path / nombre
        archivo.write_bytes(b"x" * tamano)
        os.utime(archivo, (BASE + accedido * DIA, BASE + modificado * DIA))
    return tmp_path


def nombres(archivos) -> list[str]:
    return [a.nombre for a in archivos]


def test_por_defecto_los_mas_pesados(carpeta):
    assert nombres(listar_archivos(escanear(carpeta))) == [
        "peli.mp4", "foto.jpg", "informe.pdf", "clip.mkv"]


@pytest.mark.parametrize("orden, descendente, esperado", [
    ("tamano", False, ["clip.mkv", "informe.pdf", "foto.jpg", "peli.mp4"]),
    ("modificado", True, ["foto.jpg", "informe.pdf", "clip.mkv", "peli.mp4"]),
    ("modificado", False, ["peli.mp4", "clip.mkv", "informe.pdf", "foto.jpg"]),
    ("accedido", True, ["peli.mp4", "informe.pdf", "clip.mkv", "foto.jpg"]),
    ("accedido", False, ["foto.jpg", "clip.mkv", "informe.pdf", "peli.mp4"]),
])
def test_ordenes(carpeta, orden, descendente, esperado):
    resultado = escanear(carpeta)
    assert nombres(listar_archivos(resultado, orden=orden, descendente=descendente)) == esperado


def test_filtro_por_tipo(carpeta):
    resultado = escanear(carpeta)
    assert nombres(listar_archivos(resultado, tipos=["videos"])) == ["peli.mp4", "clip.mkv"]
    assert nombres(listar_archivos(resultado, tipos=["imagenes", "documentos"])) == [
        "foto.jpg", "informe.pdf"]
    assert listar_archivos(resultado, tipos=["comprimidos"]) == []


def test_filtro_por_tamano_minimo(carpeta):
    assert nombres(listar_archivos(escanear(carpeta), tamano_minimo=2000)) == [
        "peli.mp4", "foto.jpg", "informe.pdf"]


def test_filtros_combinados_y_limite(carpeta):
    resultado = escanear(carpeta)
    assert nombres(listar_archivos(
        resultado, orden="modificado", tipos=["videos"], tamano_minimo=500, limite=1,
    )) == ["clip.mkv"]
    assert len(listar_archivos(resultado, limite=2)) == 2
    assert len(listar_archivos(resultado, limite=None)) == 4


def test_valores_no_validos(carpeta):
    resultado = escanear(carpeta)
    with pytest.raises(ValueError, match="Orden"):
        listar_archivos(resultado, orden="nombre")
    with pytest.raises(ValueError, match="Tipo"):
        listar_archivos(resultado, tipos=["musica"])


# ------------------------------------------------------------ terminal

def test_cli_top_con_orden_y_filtros(carpeta, capsys):
    assert ejecutar(["top", str(carpeta), "--orden", "accedido", "--ascendente",
                     "--tipo", "videos,documentos", "--min-mb", "0.0015"]) == 0
    salida = capsys.readouterr().out
    # Quedan informe.pdf (acceso día 7) y peli.mp4 (día 9); clip.mkv es demasiado pequeño.
    assert salida.index("informe.pdf") < salida.index("peli.mp4")
    assert "clip.mkv" not in salida and "foto.jpg" not in salida
    assert "Último acceso" in salida


def test_cli_top_tipo_invalido(carpeta, capsys):
    with pytest.raises(SystemExit):
        ejecutar(["top", str(carpeta), "--tipo", "musica"])
    assert "tipo no válido" in capsys.readouterr().err


def test_cli_top_sin_coincidencias(carpeta, capsys):
    assert ejecutar(["top", str(carpeta), "--tipo", "comprimidos"]) == 0
    assert "Ningún archivo cumple" in capsys.readouterr().out
