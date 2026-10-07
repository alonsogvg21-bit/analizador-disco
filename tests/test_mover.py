"""Pruebas de mover archivos. Todo ocurre dentro de carpetas temporales."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from cli.comandos import ejecutar
from core import mover as modulo_mover
from core.modelos import ElementoBasura
from core.mover import mover, validar_destino


def elemento(ruta: Path, tamano: int = 100, **extra) -> ElementoBasura:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_bytes(b"x" * tamano)
    return ElementoBasura(ruta, tamano, "archivos", **extra)


@pytest.fixture
def destino(tmp_path: Path) -> Path:
    carpeta = tmp_path / "destino"
    carpeta.mkdir()
    return carpeta


def test_por_defecto_solo_simula(tmp_path, destino):
    a = elemento(tmp_path / "origen" / "a.bin", 100)
    resultado = mover([a], destino)  # sin indicar nada: simulación

    assert resultado.simulacion and resultado.bytes_movidos == 100
    assert resultado.movidos == [(a, destino / "a.bin")]
    assert a.ruta.exists() and list(destino.iterdir()) == []


def test_mover_archivo_y_carpeta(tmp_path, destino):
    archivo = elemento(tmp_path / "origen" / "a.bin", 100)
    carpeta = ElementoBasura(tmp_path / "origen" / "fotos", 50, "archivos", es_carpeta=True)
    elemento(carpeta.ruta / "viaje" / "b.jpg", 50)

    resultado = mover([archivo, carpeta], destino, simulacion=False)

    assert not archivo.ruta.exists() and not carpeta.ruta.exists()
    assert (destino / "a.bin").read_bytes() == b"x" * 100
    assert (destino / "fotos" / "viaje" / "b.jpg").stat().st_size == 50
    assert len(resultado.movidos) == 2 and resultado.bytes_movidos == 150


def test_nunca_sobrescribe(tmp_path, destino):
    (destino / "foto.jpg").write_bytes(b"ya estaba")
    uno = elemento(tmp_path / "a" / "foto.jpg", 10)
    dos = elemento(tmp_path / "b" / "foto.jpg", 20)

    resultado = mover([uno, dos], destino, simulacion=False)

    assert (destino / "foto.jpg").read_bytes() == b"ya estaba"
    assert (destino / "foto (1).jpg").stat().st_size == 10
    assert (destino / "foto (2).jpg").stat().st_size == 20
    assert [nueva.name for _, nueva in resultado.movidos] == ["foto (1).jpg", "foto (2).jpg"]


def test_la_simulacion_tambien_evita_nombres_repetidos(tmp_path, destino):
    uno = elemento(tmp_path / "a" / "foto.jpg")
    dos = elemento(tmp_path / "b" / "foto.jpg")
    nombres = [nueva.name for _, nueva in mover([uno, dos], destino).movidos]
    assert nombres == ["foto.jpg", "foto (1).jpg"]


def test_rechazos(tmp_path, destino, monkeypatch):
    informativo = elemento(tmp_path / "o" / "papelera.bin", limpiable=False)
    inexistente = ElementoBasura(tmp_path / "o" / "no-esta.bin", 10, "archivos")
    ya_esta = elemento(destino / "ya.bin")
    contenedora = ElementoBasura(tmp_path, 10, "archivos", es_carpeta=True)  # contiene al destino
    normal = elemento(tmp_path / "o" / "normal.bin")

    resultado = mover([informativo, inexistente, ya_esta, contenedora, normal], destino,
                      simulacion=False)

    assert [e for e, _ in resultado.movidos] == [normal]
    motivos = {e.ruta.name: motivo for e, motivo in resultado.omitidos}
    assert "informativo" in motivos["papelera.bin"]
    assert "no existe" in motivos["no-esta.bin"]
    assert "ya está" in motivos["ya.bin"]
    assert "dentro de sí misma" in motivos[tmp_path.name]
    assert informativo.ruta.exists() and ya_esta.ruta.exists()


def test_carpeta_personal_no_se_puede_mover(destino):
    resultado = mover([ElementoBasura(Path.home(), 1, "archivos", es_carpeta=True)], destino,
                      simulacion=False)
    assert resultado.movidos == [] and "protegida" in resultado.omitidos[0][1]


def test_destino_no_valido(tmp_path):
    with pytest.raises(ValueError, match="no existe"):
        validar_destino(tmp_path / "no-existe")
    with pytest.raises(ValueError, match="no existe"):
        validar_destino("")
    archivo = tmp_path / "archivo.txt"
    archivo.write_text("x")
    with pytest.raises(ValueError, match="no existe"):
        validar_destino(archivo)


def test_destino_en_carpeta_del_sistema(tmp_path, monkeypatch):
    monkeypatch.setattr(modulo_mover, "dentro_de_carpeta_critica", lambda ruta: True)
    with pytest.raises(ValueError, match="sistema"):
        validar_destino(tmp_path)


def test_sin_espacio_en_el_destino(tmp_path, destino, monkeypatch):
    a = elemento(tmp_path / "o" / "a.bin", 5000)
    monkeypatch.setattr(modulo_mover, "_mismo_disco", lambda ruta, carpeta: False)
    monkeypatch.setattr(modulo_mover.shutil, "disk_usage",
                        lambda ruta: shutil._ntuple_diskusage(10_000, 9_000, 1_000))
    with pytest.raises(ValueError, match="espacio"):
        mover([a], destino, simulacion=False)
    assert a.ruta.exists()


def test_archivo_en_uso_no_detiene_el_resto(tmp_path, destino, monkeypatch):
    real = shutil.move

    def mover_con_bloqueo(origen, nuevo):
        if "bloqueado" in origen:
            raise PermissionError("en uso")
        return real(origen, nuevo)
    monkeypatch.setattr(modulo_mover.shutil, "move", mover_con_bloqueo)

    bloqueado = elemento(tmp_path / "o" / "bloqueado.bin", 500)
    libre = elemento(tmp_path / "o" / "libre.bin", 100)
    resultado = mover([bloqueado, libre], destino, simulacion=False)

    assert [e for e, _ in resultado.movidos] == [libre] and resultado.bytes_movidos == 100
    assert "en uso" in resultado.omitidos[0][1] and bloqueado.ruta.exists()


def test_copia_interrumpida_no_deja_restos(tmp_path, destino, monkeypatch):
    def copia_a_medias(origen, nuevo):
        Path(nuevo).write_bytes(b"medio")
        raise OSError("disco desconectado")
    monkeypatch.setattr(modulo_mover.shutil, "move", copia_a_medias)

    a = elemento(tmp_path / "o" / "a.bin", 500)
    resultado = mover([a], destino, simulacion=False)

    assert resultado.movidos == [] and a.ruta.stat().st_size == 500
    assert list(destino.iterdir()) == []


def test_carpeta_movida_a_medias_no_borra_nada(tmp_path, destino, monkeypatch):
    def a_medias(origen, nuevo):
        shutil.copytree(origen, nuevo)
        os.remove(os.path.join(origen, "libre.bin"))  # el otro archivo "estaba en uso"
        raise PermissionError("en uso")
    monkeypatch.setattr(modulo_mover.shutil, "move", a_medias)

    carpeta = ElementoBasura(tmp_path / "o" / "datos", 300, "archivos", es_carpeta=True)
    elemento(carpeta.ruta / "libre.bin", 200)
    elemento(carpeta.ruta / "en_uso.bin", 100)
    resultado = mover([carpeta], destino, simulacion=False)

    assert resultado.movidos == [] and "solo en parte" in resultado.omitidos[0][1]
    assert (carpeta.ruta / "en_uso.bin").exists()             # sigue en el origen
    assert (destino / "datos" / "libre.bin").exists()         # y la copia no se borró


# ------------------------------------------------------------ terminal

@pytest.fixture
def videos(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setattr("core.basura.reglas_del_sistema", lambda: [])
    raiz = tmp_path / "raiz"
    for nombre, tamano in (("peli.mp4", 3000), ("clip.mkv", 800), ("foto.jpg", 2000),
                           ("copias/uno.bin", 4000), ("copias/dos.bin", 4000)):
        archivo = raiz.joinpath(*nombre.split("/"))
        archivo.parent.mkdir(parents=True, exist_ok=True)
        archivo.write_bytes(b"x" * tamano)
    return raiz


def test_cli_mover_simulacion(videos, destino, capsys, monkeypatch):
    def sin_preguntas(*_):
        raise AssertionError("en simulación no se debe pedir confirmación")
    monkeypatch.setattr("builtins.input", sin_preguntas)

    assert ejecutar(["mover", str(videos), "-d", str(destino), "--tipo", "videos", "--dry-run"]) == 0
    salida = capsys.readouterr().out
    assert "peli.mp4" in salida and "clip.mkv" in salida and "foto.jpg" not in salida
    assert "SIMULACIÓN" in salida and list(destino.iterdir()) == []


@pytest.mark.parametrize("respuesta", ["", "si", "mover", "ELIMINAR"])
def test_cli_mover_sin_confirmar(videos, destino, monkeypatch, respuesta):
    monkeypatch.setattr("builtins.input", lambda *_: respuesta)
    assert ejecutar(["mover", str(videos), "-d", str(destino), "--tipo", "videos"]) == 1
    assert (videos / "peli.mp4").exists() and list(destino.iterdir()) == []


def test_cli_mover_por_tipo_y_tamano(videos, destino, capsys, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *_: "MOVER")
    assert ejecutar(["mover", str(videos), "-d", str(destino),
                     "--tipo", "videos", "--min-mb", "0.001"]) == 0
    assert sorted(p.name for p in destino.iterdir()) == ["peli.mp4"]   # clip.mkv es más pequeño
    assert (videos / "clip.mkv").exists() and (videos / "foto.jpg").exists()
    assert "Movidos a" in capsys.readouterr().out


def test_cli_mover_duplicados(videos, destino, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *_: "MOVER")
    assert ejecutar(["mover", str(videos), "-d", str(destino),
                     "-c", "duplicados", "--min-mb", "0"]) == 0
    # Se mueve una sola copia; la otra (el original) se queda.
    assert len(list(destino.iterdir())) == 1
    assert len(list((videos / "copias").iterdir())) == 1


def test_cli_mover_argumentos_invalidos(videos, destino, tmp_path, capsys):
    assert ejecutar(["mover", str(videos), "-d", str(destino)]) == 2                 # falta qué mover
    assert ejecutar(["mover", str(videos), "-d", str(tmp_path / "no"), "--tipo", "videos"]) == 2
    assert ejecutar(["mover", str(videos), "-d", str(destino), "-c", "cache"]) == 2  # no aplica
    assert ejecutar(["mover", str(videos), "-d", str(destino), "--tipo", "comprimidos"]) == 0
    assert "No hay nada que mover" in capsys.readouterr().out
