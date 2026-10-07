"""Pruebas de la terminal: se ejecutan los comandos y se revisa lo que imprimen."""

from __future__ import annotations

from pathlib import Path

import pytest

import main
from cli.comandos import ejecutar


@pytest.fixture
def arbol(tmp_path: Path) -> Path:
    raiz = tmp_path / "raiz"
    for relativa, tamano in (
        ("suelto.txt", 10),
        ("fotos/a.jpg", 300),
        ("fotos/viaje/b.png", 200),
        ("proyecto/node_modules/x.js", 1000),
        ("copias/uno.bin", 4000),
        ("copias/dos.bin", 4000),
    ):
        archivo = raiz.joinpath(*relativa.split("/"))
        archivo.parent.mkdir(parents=True, exist_ok=True)
        archivo.write_bytes(b"x" * tamano)
    return raiz


def test_resumen(capsys):
    assert ejecutar(["resumen"]) == 0
    salida = capsys.readouterr().out
    assert "Discos" in salida and "libre" in salida


def test_carpetas(arbol, capsys):
    assert ejecutar(["carpetas", str(arbol)]) == 0
    salida = capsys.readouterr().out
    # De mayor a menor: copias (8000), proyecto (1000), fotos (500).
    assert salida.index("copias") < salida.index("proyecto") < salida.index("fotos")
    assert "(archivos sueltos)" in salida
    assert "viaje" not in salida  # con profundidad 1 no se baja de nivel


def test_carpetas_con_profundidad(arbol, capsys):
    assert ejecutar(["carpetas", str(arbol), "--profundidad", "2"]) == 0
    assert "viaje" in capsys.readouterr().out


def test_top(arbol, capsys):
    assert ejecutar(["top", str(arbol), "-n", "2"]) == 0
    salida = capsys.readouterr().out
    assert "uno.bin" in salida and "dos.bin" in salida and "a.jpg" not in salida


def test_tipos(arbol, capsys):
    assert ejecutar(["tipos", str(arbol)]) == 0
    salida = capsys.readouterr().out
    assert "imagenes" in salida and "otros" in salida


def test_duplicados(arbol, capsys):
    assert ejecutar(["duplicados", str(arbol), "--min-mb", "0"]) == 0
    salida = capsys.readouterr().out
    assert "1 grupos" in salida and "original" in salida and "copia" in salida


def test_basura(arbol, capsys, monkeypatch):
    # Sin reglas del sistema, para no depender del equipo donde corre la prueba.
    monkeypatch.setattr("core.basura.reglas_del_sistema", lambda: [])
    assert ejecutar(["basura", str(arbol), "--min-mb", "0"]) == 0
    salida = capsys.readouterr().out
    assert "Carpetas regenerables" in salida and "node_modules" in salida
    assert "Duplicados" in salida
    assert "no se ha borrado" in salida


def test_reporte(arbol, tmp_path, capsys, monkeypatch):
    monkeypatch.setattr("core.basura.reglas_del_sistema", lambda: [])
    salida = tmp_path / "reportes"
    assert ejecutar(["reporte", str(arbol), "--salida", str(salida)]) == 0
    assert len(list(salida.glob("reporte-disco-*.html"))) == 1
    assert len(list(salida.glob("reporte-disco-*.csv"))) == 1


def test_reporte_solo_csv(arbol, tmp_path, monkeypatch):
    monkeypatch.setattr("core.basura.reglas_del_sistema", lambda: [])
    salida = tmp_path / "reportes"
    assert ejecutar(["reporte", str(arbol), "-s", str(salida), "-f", "csv", "--sin-duplicados"]) == 0
    assert [p.suffix for p in salida.iterdir()] == [".csv"]


def test_ruta_inexistente(tmp_path, capsys):
    with pytest.raises(SystemExit) as salida:
        ejecutar(["top", str(tmp_path / "no-existe")])
    assert salida.value.code == 2
    assert "no existe" in capsys.readouterr().err


def test_main_sin_argumentos_abre_el_escritorio(monkeypatch):
    abierto = []
    monkeypatch.setattr("desktop.app.iniciar", lambda: abierto.append(True) or 0)
    assert main.main([]) == 0 and abierto == [True]


def test_main_ayuda(capsys):
    assert main.main(["--help"]) == 0
    salida = capsys.readouterr().out
    assert "python main.py cli" in salida and "python main.py web" in salida


@pytest.mark.parametrize("modo", ["web", "gui"])
def test_main_web(monkeypatch, modo):
    llamadas = []
    monkeypatch.setattr("web.app.iniciar", lambda puerto, abrir_navegador: llamadas.append((puerto, abrir_navegador)) or 0)
    assert main.main([modo, "--puerto", "5050", "--no-abrir"]) == 0
    assert llamadas == [(5050, False)]


def test_main_modo_desconocido(capsys):
    assert main.main(["otro"]) == 2
    assert main.main(["cli", "resumen"]) == 0


# ------------------------------------------------------------ limpiar

@pytest.fixture
def sin_reglas(monkeypatch):
    import shutil
    monkeypatch.setattr("core.basura.reglas_del_sistema", lambda: [])
    monkeypatch.setattr("core.limpieza.send2trash", shutil.rmtree)


def test_limpiar_simulacion(arbol, capsys, sin_reglas, monkeypatch):
    def sin_preguntas(*_):
        raise AssertionError("en simulación no se debe pedir confirmación")
    monkeypatch.setattr("builtins.input", sin_preguntas)

    assert ejecutar(["limpiar", str(arbol), "-c", "regenerables", "--dry-run"]) == 0
    salida = capsys.readouterr().out
    assert "node_modules" in salida and "SIMULACIÓN" in salida
    assert (arbol / "proyecto" / "node_modules").exists()


@pytest.mark.parametrize("respuesta", ["", "si", "eliminar", "s"])
def test_limpiar_sin_confirmar_no_toca_nada(arbol, capsys, sin_reglas, monkeypatch, respuesta):
    monkeypatch.setattr("builtins.input", lambda *_: respuesta)
    assert ejecutar(["limpiar", str(arbol), "-c", "regenerables"]) == 1
    assert "No se ha tocado nada" in capsys.readouterr().out
    assert (arbol / "proyecto" / "node_modules").exists()


def test_limpiar_confirmado(arbol, capsys, sin_reglas, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *_: "ELIMINAR")
    assert ejecutar(["limpiar", str(arbol), "-c", "regenerables"]) == 0
    salida = capsys.readouterr().out
    assert "Enviados a la papelera: 1 elementos" in salida
    assert not (arbol / "proyecto" / "node_modules").exists()
    # Las categorías no pedidas no se tocan (uno.bin y dos.bin son duplicados).
    assert (arbol / "copias" / "uno.bin").exists() and (arbol / "copias" / "dos.bin").exists()


def test_limpiar_sin_entrada_disponible(arbol, sin_reglas, monkeypatch):
    def sin_terminal(*_):
        raise EOFError
    monkeypatch.setattr("builtins.input", sin_terminal)
    assert ejecutar(["limpiar", str(arbol), "-c", "regenerables"]) == 1
    assert (arbol / "proyecto" / "node_modules").exists()


def test_limpiar_argumentos_invalidos(arbol, capsys, sin_reglas):
    assert ejecutar(["limpiar", str(arbol), "-c", "papelera"]) == 2      # solo informativa
    assert ejecutar(["limpiar", "-c", "duplicados"]) == 2                # falta la RUTA
    with pytest.raises(SystemExit):
        ejecutar(["limpiar", str(arbol)])                                # falta --categorias
    assert ejecutar(["limpiar", "-c", "cache"]) == 0                     # nada que limpiar
    assert "No hay nada que limpiar" in capsys.readouterr().out
