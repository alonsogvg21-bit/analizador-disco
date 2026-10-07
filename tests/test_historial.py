"""Pruebas del historial de escaneos y de la comparación entre fechas."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from cli.comandos import ejecutar
from core.escaner import escanear
from core.historial import (
    borrar_escaneo, comparar, escaneo_cercano, guardar_escaneo, listar_escaneos, ruta_bd,
)

ENERO = datetime(2026, 1, 10, 9, 0)
MARZO = datetime(2026, 3, 10, 9, 0)
JUNIO = datetime(2026, 6, 10, 9, 0)


def escribir(raiz: Path, contenido: dict[str, int]) -> None:
    for relativa, tamano in contenido.items():
        archivo = raiz.joinpath(*relativa.split("/"))
        archivo.parent.mkdir(parents=True, exist_ok=True)
        archivo.write_bytes(b"x" * tamano)


@pytest.fixture
def raiz(tmp_path: Path) -> Path:
    carpeta = tmp_path / "raiz"
    escribir(carpeta, {"fotos/a.jpg": 1000, "videos/v.mp4": 5000, "docs/viejos/x.pdf": 300})
    return carpeta


@pytest.fixture
def dos_escaneos(raiz: Path):
    """Enero: estado inicial. Marzo: fotos crece, videos encoge, docs desaparece, música aparece."""
    antes = guardar_escaneo(escanear(raiz), fecha=ENERO)
    escribir(raiz, {"fotos/b.jpg": 2500, "videos/v.mp4": 1000, "musica/c.mp3": 700})
    (raiz / "docs" / "viejos" / "x.pdf").unlink()
    (raiz / "docs" / "viejos").rmdir()
    (raiz / "docs").rmdir()
    despues = guardar_escaneo(escanear(raiz), fecha=MARZO)
    return antes, despues


def test_guardar_y_listar(raiz, tmp_path):
    guardado = guardar_escaneo(escanear(raiz), fecha=ENERO)
    assert (guardado.tamano_total, guardado.num_archivos, guardado.fecha) == (6300, 3, ENERO)
    assert ruta_bd().is_file()

    otra = tmp_path / "otra"
    escribir(otra, {"z.bin": 5})
    guardar_escaneo(escanear(otra), fecha=MARZO)
    guardar_escaneo(escanear(raiz), fecha=JUNIO)

    assert [e.fecha for e in listar_escaneos(raiz)] == [ENERO, JUNIO]
    assert len(listar_escaneos()) == 3
    assert listar_escaneos(tmp_path / "nunca-escaneada") == []


def test_la_raiz_no_distingue_mayusculas_en_windows(raiz):
    import os
    if os.path.normcase("A") == "A":
        pytest.skip("solo aplica a sistemas que no distinguen mayúsculas")
    guardar_escaneo(escanear(raiz), fecha=ENERO)
    assert len(listar_escaneos(str(raiz).upper())) == 1


def test_comparar(dos_escaneos, raiz):
    antes, despues = dos_escaneos
    comparacion = comparar(antes.id, despues.id)

    assert comparacion.antes.fecha == ENERO and comparacion.despues.fecha == MARZO
    assert comparacion.diferencia_total == 5200 - 6300
    por_nombre = {Path(c.ruta).name: c for c in comparacion.cambios}
    assert (por_nombre["fotos"].antes, por_nombre["fotos"].despues, por_nombre["fotos"].diferencia) == (1000, 3500, 2500)
    assert por_nombre["videos"].diferencia == -4000
    assert (por_nombre["musica"].antes, por_nombre["musica"].diferencia) == (0, 700)      # nueva
    assert (por_nombre["docs"].despues, por_nombre["docs"].diferencia) == (0, -300)        # borrada
    assert por_nombre["viejos"].diferencia == -300                                         # segundo nivel
    # De mayor a menor cambio, sin importar si creció o disminuyó.
    assert [Path(c.ruta).name for c in comparacion.cambios[:2]] == ["videos", "fotos"]


def test_comparar_no_depende_del_orden_de_los_ids(dos_escaneos):
    antes, despues = dos_escaneos
    assert comparar(despues.id, antes.id).diferencia_total == comparar(antes.id, despues.id).diferencia_total


def test_comparar_con_minimo(dos_escaneos):
    antes, despues = dos_escaneos
    nombres = {Path(c.ruta).name for c in comparar(antes.id, despues.id, minimo=1000).cambios}
    assert nombres == {"fotos", "videos"}


def test_comparar_errores(dos_escaneos, tmp_path):
    antes, _ = dos_escaneos
    with pytest.raises(ValueError, match="No existe"):
        comparar(antes.id, 9999)
    otra = tmp_path / "otra"
    escribir(otra, {"z.bin": 5})
    ajeno = guardar_escaneo(escanear(otra))
    with pytest.raises(ValueError, match="misma carpeta"):
        comparar(antes.id, ajeno.id)


def test_solo_se_guardan_los_primeros_niveles(tmp_path):
    escribir(tmp_path, {"a/b/c/d/e/profundo.bin": 100})
    antes = guardar_escaneo(escanear(tmp_path), fecha=ENERO, profundidad=2)
    escribir(tmp_path, {"a/b/c/d/e/otro.bin": 50})
    despues = guardar_escaneo(escanear(tmp_path), fecha=MARZO, profundidad=2)
    assert {Path(c.ruta).name for c in comparar(antes.id, despues.id).cambios} == {"a", "b"}


def test_escaneo_cercano_y_borrar(dos_escaneos, raiz):
    antes, despues = dos_escaneos
    assert escaneo_cercano(raiz, datetime(2026, 1, 20)).id == antes.id
    assert escaneo_cercano(raiz, datetime(2026, 12, 1)).id == despues.id
    assert escaneo_cercano(raiz.parent, ENERO) is None

    assert borrar_escaneo(antes.id) and not borrar_escaneo(antes.id)
    assert [e.id for e in listar_escaneos(raiz)] == [despues.id]


# ------------------------------------------------------------ terminal

def test_cli_guardar_e_historial(raiz, capsys):
    assert ejecutar(["guardar", str(raiz)]) == 0
    assert "Escaneo guardado" in capsys.readouterr().out
    escribir(raiz, {"fotos/nueva.jpg": 3 * 1024 * 1024})
    assert ejecutar(["guardar", str(raiz)]) == 0
    assert "+3.0 MB" in capsys.readouterr().out      # cambio respecto al escaneo anterior

    assert ejecutar(["historial", str(raiz)]) == 0
    assert capsys.readouterr().out.count(str(raiz)) >= 2
    assert ejecutar(["historial"]) == 0


def test_cli_comparar_los_dos_ultimos(dos_escaneos, raiz, capsys):
    assert ejecutar(["comparar", str(raiz), "--min-mb", "0"]) == 0
    salida = capsys.readouterr().out
    assert "2026-01-10" in salida and "2026-03-10" in salida
    assert "fotos" in salida and "videos" in salida and "nueva" in salida and "ya no existe" in salida


def test_cli_comparar_por_fechas(dos_escaneos, raiz, capsys):
    guardar_escaneo(escanear(raiz), fecha=JUNIO)
    assert ejecutar(["comparar", str(raiz), "--desde", "2026-01-01", "--hasta", "2026-03-15"]) == 0
    salida = capsys.readouterr().out
    assert "2026-01-10" in salida and "2026-03-10" in salida and "2026-06-10" not in salida


def test_cli_comparar_sin_datos_suficientes(raiz, capsys):
    assert ejecutar(["comparar", str(raiz)]) == 1
    guardar_escaneo(escanear(raiz), fecha=ENERO)
    assert ejecutar(["comparar", str(raiz)]) == 1
    assert "al menos dos" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        ejecutar(["comparar", str(raiz), "--desde", "ayer"])
