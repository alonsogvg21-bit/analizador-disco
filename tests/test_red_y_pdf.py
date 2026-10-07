"""Pruebas de la detección de discos de red y del reporte en PDF."""

from __future__ import annotations

from collections import namedtuple
from pathlib import Path

import pytest

from cli.comandos import ejecutar
from core import limpieza
from core.basura import detectar_basura
from core.escaner import escanear
from core.limpieza import limpiar
from core.modelos import ElementoBasura
from core.mover import mover
from core.reporte import reunir_datos
from core.reporte_pdf import exportar_pdf
from utils.red import es_ruta_de_red
from utils.sistema import LINUX, WINDOWS, sistema_actual

Particion = namedtuple("Particion", "mountpoint fstype")


# ------------------------------------------------------------ discos de red

@pytest.mark.parametrize("ruta, esperado", [
    (r"\\servidor\compartido\fotos", True),
    (r"\\192.168.1.10\datos", True),
    ("//servidor/compartido", True),
    (r"\\?\UNC\servidor\compartido", True),
    (r"\\?\C:\Users\ana", False),          # ruta larga de un disco local, no es de red
    (r"C:\Users\ana", False),
])
def test_rutas_unc_en_windows(ruta, esperado):
    assert es_ruta_de_red(ruta, sistema=WINDOWS, tipo_de_unidad=lambda raiz: 3) is esperado


def test_letra_de_unidad_conectada_a_la_red():
    tipos = {"Z:\\": 4, "C:\\": 3}  # 4 = unidad de red, 3 = disco fijo
    if sistema_actual() != WINDOWS:
        pytest.skip("las letras de unidad solo existen en Windows")
    assert es_ruta_de_red(r"Z:\peliculas", sistema=WINDOWS, tipo_de_unidad=tipos.get) is True
    assert es_ruta_de_red(r"C:\Users", sistema=WINDOWS, tipo_de_unidad=tipos.get) is False


def test_carpetas_montadas_en_linux():
    if sistema_actual() == WINDOWS:
        pytest.skip("usa rutas con formato de Linux")
    particiones = [Particion("/", "ext4"), Particion("/mnt/nas", "nfs4"),
                   Particion("/mnt/nas/local", "ext4"), Particion("/media/smb", "cifs"),
                   Particion("/home/ana/servidor", "fuse.sshfs")]

    def de_red(ruta):
        return es_ruta_de_red(ruta, sistema=LINUX, particiones=particiones)

    assert de_red("/mnt/nas") and de_red("/mnt/nas/fotos/2024")
    assert de_red("/media/smb/x") and de_red("/home/ana/servidor/www")
    assert not de_red("/home/ana") and not de_red("/mnt/nasa")
    assert not de_red("/mnt/nas/local/datos")   # disco local montado dentro del de red


def test_carpeta_local_real_no_es_de_red(tmp_path):
    assert es_ruta_de_red(tmp_path) is False
    assert es_ruta_de_red(tmp_path, sistema="otro") is False


def test_la_papelera_no_se_usa_en_discos_de_red(tmp_path, monkeypatch):
    """En la red no hay papelera y el borrado sería definitivo: se rechaza. Mover sí se permite."""
    def prohibido(ruta):
        raise AssertionError("no se debe llamar a la papelera en un disco de red")
    monkeypatch.setattr(limpieza, "send2trash", prohibido)
    monkeypatch.setattr(limpieza, "es_ruta_de_red", lambda ruta: True)

    archivo = tmp_path / "origen" / "a.bin"
    archivo.parent.mkdir()
    archivo.write_bytes(b"x" * 10)
    elemento = ElementoBasura(archivo, 10, "archivos")

    resultado = limpiar([elemento], simulacion=False)
    assert resultado.enviados == [] and "disco de red" in resultado.omitidos[0][1]
    assert archivo.exists()

    destino = tmp_path / "destino"
    destino.mkdir()
    assert len(mover([elemento], destino, simulacion=False).movidos) == 1


def test_cli_avisa_si_la_carpeta_es_de_red(tmp_path, capsys, monkeypatch):
    (tmp_path / "a.txt").write_text("hola")
    monkeypatch.setattr("cli.comandos.es_ruta_de_red", lambda ruta: True)
    assert ejecutar(["tipos", str(tmp_path)]) == 0
    assert "disco de red" in capsys.readouterr().err

    monkeypatch.setattr("cli.comandos.es_ruta_de_red", lambda ruta: False)
    ejecutar(["tipos", str(tmp_path)])
    assert "disco de red" not in capsys.readouterr().err


# ------------------------------------------------------------ PDF

@pytest.fixture
def carpeta(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setattr("core.basura.reglas_del_sistema", lambda: [])
    raiz = tmp_path / "raiz"
    for relativa, tamano in (("fotos/año nuevo – 日本.jpg", 300), ("videos/peli.mp4", 2000),
                             ("proyecto/node_modules/x.js", 1000), ("suelto.txt", 10)):
        archivo = raiz.joinpath(*relativa.split("/"))
        archivo.parent.mkdir(parents=True, exist_ok=True)
        archivo.write_bytes(b"x" * tamano)
    return raiz


def test_exportar_pdf(carpeta, tmp_path):
    resultado = escanear(carpeta)
    datos = reunir_datos(resultado, detectar_basura(resultado, reglas=[]))
    destino = exportar_pdf(datos, tmp_path / "salida" / "reporte.pdf")

    contenido = destino.read_bytes()
    assert contenido.startswith(b"%PDF-") and contenido.rstrip().endswith(b"%%EOF")
    assert len(contenido) > 1500


def test_pdf_con_muchos_archivos_ocupa_varias_paginas(tmp_path):
    for indice in range(60):
        carpeta = tmp_path / "datos" / f"carpeta-{indice:02}"
        carpeta.mkdir(parents=True)
        (carpeta / f"archivo-{indice:02}.bin").write_bytes(b"x" * (indice + 1))
    resultado = escanear(tmp_path / "datos")
    destino = exportar_pdf(reunir_datos(resultado, []), tmp_path / "grande.pdf")
    assert destino.read_bytes().count(b"/Type /Page\n") >= 2 or destino.stat().st_size > 3000


def test_pdf_de_carpeta_vacia(tmp_path):
    vacia = tmp_path / "vacia"
    vacia.mkdir()
    destino = exportar_pdf(reunir_datos(escanear(vacia), []), tmp_path / "vacio.pdf")
    assert destino.read_bytes().startswith(b"%PDF-")


@pytest.mark.parametrize("formato, extensiones", [
    ("pdf", [".pdf"]), ("todos", [".csv", ".html", ".pdf"]), ("ambos", [".csv", ".html"]),
])
def test_cli_reporte_formatos(carpeta, tmp_path, capsys, formato, extensiones):
    salida = tmp_path / "reportes"
    assert ejecutar(["reporte", str(carpeta), "-s", str(salida), "-f", formato, "--sin-duplicados"]) == 0
    assert sorted(p.suffix for p in salida.iterdir()) == extensiones
    if ".pdf" in extensiones:
        assert "Reporte PDF" in capsys.readouterr().out
