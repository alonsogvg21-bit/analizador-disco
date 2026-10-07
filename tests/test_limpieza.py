"""Pruebas de la limpieza.

Para no llenar la papelera real en cada ejecución, send2trash se sustituye
por una función que simplemente elimina dentro de la carpeta temporal.
La prueba con la papelera de verdad solo corre si se define la variable de
entorno PROBAR_PAPELERA=1.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from core import limpieza
from core.limpieza import limpiar, motivo_de_rechazo
from core.modelos import ElementoBasura


def papelera_falsa(ruta: str) -> None:
    if os.path.isdir(ruta):
        shutil.rmtree(ruta)
    else:
        os.remove(ruta)


@pytest.fixture
def falsa(monkeypatch):
    monkeypatch.setattr(limpieza, "send2trash", papelera_falsa)


def elemento(ruta: Path, tamano: int = 100, **extra) -> ElementoBasura:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_bytes(b"x" * tamano)
    return ElementoBasura(ruta, tamano, "temporales", **extra)


def test_por_defecto_solo_simula(tmp_path, monkeypatch):
    def prohibido(ruta):
        raise AssertionError("en simulación no se debe llamar a la papelera")
    monkeypatch.setattr(limpieza, "send2trash", prohibido)

    a, b = elemento(tmp_path / "a.tmp", 100), elemento(tmp_path / "b.tmp", 250)
    resultado = limpiar([a, b])  # sin indicar nada: simulación

    assert resultado.simulacion
    assert resultado.enviados == [a, b] and resultado.bytes_liberados == 350
    assert a.ruta.exists() and b.ruta.exists()


def test_limpieza_real(tmp_path, falsa):
    archivo = elemento(tmp_path / "a.tmp", 100)
    carpeta = ElementoBasura(tmp_path / "node_modules", 40, "regenerables", es_carpeta=True)
    elemento(carpeta.ruta / "x.js", 40)

    resultado = limpiar([archivo, carpeta], simulacion=False)

    assert not archivo.ruta.exists() and not carpeta.ruta.exists()
    assert len(resultado.enviados) == 2 and resultado.omitidos == []
    assert resultado.bytes_liberados == 140


def test_rechazos(tmp_path, falsa, monkeypatch):
    informativo = elemento(tmp_path / "papelera.bin", limpiable=False)
    inexistente = ElementoBasura(tmp_path / "ya-no-esta.tmp", 10, "temporales")
    relativo = ElementoBasura(Path("relativo.tmp"), 10, "temporales")
    protegido = elemento(tmp_path / "sistema" / "kernel.dll")
    normal = elemento(tmp_path / "normal.tmp")
    monkeypatch.setattr(limpieza, "es_ruta_protegida", lambda ruta: "sistema" in Path(ruta).parts)

    resultado = limpiar([informativo, inexistente, relativo, protegido, normal], simulacion=False)

    assert resultado.enviados == [normal]
    motivos = {e.ruta.name: motivo for e, motivo in resultado.omitidos}
    assert "informativo" in motivos["papelera.bin"]
    assert "no existe" in motivos["ya-no-esta.tmp"]
    assert "absoluta" in motivos["relativo.tmp"]
    assert "protegida" in motivos["kernel.dll"]
    assert informativo.ruta.exists() and protegido.ruta.exists()


def test_carpetas_del_sistema_reales_se_rechazan():
    """Sin sustituir nada: la comprobación real bloquea la carpeta personal y la raíz."""
    for ruta in (Path.home(), Path(Path.home().anchor)):
        assert motivo_de_rechazo(ElementoBasura(ruta, 1, "temporales")) is not None


def test_enlace_se_rechaza(tmp_path, falsa):
    destino = elemento(tmp_path / "real.bin").ruta
    enlace = tmp_path / "enlace.bin"
    try:
        os.symlink(destino, enlace)
    except (OSError, NotImplementedError):
        pytest.skip("este sistema no permite crear enlaces simbólicos")
    resultado = limpiar([ElementoBasura(enlace, 100, "temporales")], simulacion=False)
    assert resultado.enviados == [] and enlace.is_symlink() and destino.exists()


def test_archivo_en_uso_no_detiene_la_limpieza(tmp_path, monkeypatch):
    def papelera_con_bloqueo(ruta: str) -> None:
        if "bloqueado" in ruta:
            raise PermissionError("el archivo está en uso")
        papelera_falsa(ruta)
    monkeypatch.setattr(limpieza, "send2trash", papelera_con_bloqueo)

    bloqueado = elemento(tmp_path / "bloqueado.tmp", 500)
    libre = elemento(tmp_path / "libre.tmp", 100)
    resultado = limpiar([bloqueado, libre], simulacion=False)

    assert resultado.enviados == [libre] and resultado.bytes_liberados == 100
    assert resultado.omitidos[0][0] is bloqueado and "en uso" in resultado.omitidos[0][1]
    assert bloqueado.ruta.exists()


def test_carpeta_limpiada_a_medias(tmp_path, monkeypatch):
    """Si dentro de una carpeta queda un archivo en uso, solo se cuenta lo que salió."""
    carpeta = ElementoBasura(tmp_path / "cache", 400, "cache", es_carpeta=True)
    elemento(carpeta.ruta / "libre.bin", 300)
    elemento(carpeta.ruta / "en_uso.bin", 100)
    monkeypatch.setattr(limpieza, "send2trash",
                        lambda ruta: os.remove(os.path.join(ruta, "libre.bin")))

    resultado = limpiar([carpeta], simulacion=False)
    assert resultado.enviados == [] and resultado.bytes_liberados == 300


@pytest.mark.skipif(not os.environ.get("PROBAR_PAPELERA"),
                    reason="usa la papelera real; actívala con PROBAR_PAPELERA=1")
def test_papelera_real(tmp_path):
    archivo = elemento(tmp_path / "prueba-analizador-disco.tmp", 10)
    resultado = limpiar([archivo], simulacion=False)
    assert resultado.enviados == [archivo] and not archivo.ruta.exists()
