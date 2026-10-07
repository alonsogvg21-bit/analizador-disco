"""Pruebas de los escaneos programados.

Nunca se toca el programador real del sistema: en lugar de ejecutar schtasks
o crontab se usa un ejecutor falso que apunta los comandos recibidos.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from cli import comandos
from cli.comandos import ejecutar
from core.programador import (
    MARCA_CRON, ErrorProgramador, TareaProgramada, comando_de_escaneo, crear_tarea,
    linea_cron, linea_de_comando_windows, listar_tareas, nombre_de_tarea, quitar_tarea,
)
from utils.sistema import LINUX, WINDOWS


class SchtasksFalso:
    """Imita a schtasks: recuerda las tareas creadas."""

    def __init__(self):
        self.tareas: dict[str, list[str]] = {}
        self.comandos: list[list[str]] = []

    def __call__(self, comando, entrada=None):
        self.comandos.append(comando)
        accion = comando[1]
        if accion == "/Create":
            self.tareas[comando[comando.index("/TN") + 1]] = comando
            return 0, "", ""
        if accion == "/Query":
            filas = ['"\\Microsoft\\Windows\\Otra","N/D","Listo"']
            filas += [f'"\\{nombre}","06/10/2026 9:00:00","Listo"' for nombre in self.tareas]
            return 0, "\n".join(filas) + "\n", ""
        if accion == "/Delete":
            return (0, "", "") if self.tareas.pop(comando[comando.index("/TN") + 1], None) else (1, "", "no existe")
        raise AssertionError(comando)


class CrontabFalso:
    """Imita a crontab: guarda el texto del crontab del usuario."""

    def __init__(self, contenido: str | None = None):
        self.contenido = contenido

    def __call__(self, comando, entrada=None):
        if comando == ["crontab", "-l"]:
            return (1, "", "no crontab for user") if self.contenido is None else (0, self.contenido, "")
        if comando == ["crontab", "-"]:
            self.contenido = entrada
            return 0, "", ""
        raise AssertionError(comando)


# ------------------------------------------------------------ piezas

def test_nombre_de_tarea_estable_y_seguro(tmp_path):
    carpeta = tmp_path / "Mis vídeos & fotos"
    nombre = nombre_de_tarea(carpeta)
    assert nombre == nombre_de_tarea(carpeta) != nombre_de_tarea(tmp_path / "otra")
    assert all(c.isalnum() or c == "-" for c in nombre) and nombre.isascii()


def test_comando_de_escaneo(tmp_path):
    comando = comando_de_escaneo(tmp_path)
    assert comando[0] == sys.executable and Path(comando[1]).name == "main.py"
    assert comando[2:] == ["cli", "--silencioso", "guardar", str(tmp_path)]


def test_linea_de_comando_windows():
    linea = linea_de_comando_windows(
        [r"C:\Program Files\Python\python.exe", r"C:\app\main.py", "cli", "guardar", "D:\\"])
    # La barra final de D:\ se duplica para no escapar la comilla de cierre.
    assert linea == r'"C:\Program Files\Python\python.exe" "C:\app\main.py" cli guardar "D:\\"'


def test_linea_cron():
    diaria = linea_cron(TareaProgramada("fotos-12345678", "/home/ana/fotos 100%", "diaria", "07:05"))
    assert diaria.startswith("5 7 * * * ")
    assert diaria.endswith(MARCA_CRON + "fotos-12345678")
    assert r"100\%" in diaria and "'/home/ana/fotos 100\\%'" in diaria   # espacio y % protegidos
    assert linea_cron(TareaProgramada("x", "/tmp", "semanal", "23:30")).startswith("30 23 * * 1 ")


# ------------------------------------------------------------ Windows

def test_windows_crear_listar_quitar(tmp_path):
    falso = SchtasksFalso()
    tarea = crear_tarea(tmp_path, "semanal", "18:30", sistema=WINDOWS, ejecutar=falso)

    comando = falso.comandos[0]
    assert comando[:4] == ["schtasks", "/Create", "/TN", f"AnalizadorDisco\\{tarea.nombre}"]
    assert comando[comando.index("/ST") + 1] == "18:30"
    assert comando[comando.index("/SC") + 1] == "WEEKLY" and "MON" in comando
    # La tarea ejecuta un .cmd corto; el comando completo está dentro de ese archivo.
    lanzador = Path(comando[comando.index("/TR") + 1].strip('"'))
    contenido = lanzador.read_text(encoding="utf-8")
    assert lanzador.suffix == ".cmd" and str(tmp_path.resolve()) in contenido and "guardar" in contenido

    # Solo se listan las tareas propias, con los detalles guardados al crearlas.
    assert listar_tareas(sistema=WINDOWS, ejecutar=falso) == [
        TareaProgramada(tarea.nombre, str(tmp_path.resolve()), "semanal", "18:30")]

    assert quitar_tarea(tarea.nombre, sistema=WINDOWS, ejecutar=falso) is True
    assert not lanzador.exists()
    assert listar_tareas(sistema=WINDOWS, ejecutar=falso) == []
    assert quitar_tarea(tarea.nombre, sistema=WINDOWS, ejecutar=falso) is False


def test_windows_diaria_y_error_del_sistema(tmp_path):
    falso = SchtasksFalso()
    crear_tarea(tmp_path, sistema=WINDOWS, ejecutar=falso)
    assert falso.comandos[0][-2:] == ["/SC", "DAILY"]

    with pytest.raises(ErrorProgramador, match="Acceso denegado"):
        crear_tarea(tmp_path, sistema=WINDOWS, ejecutar=lambda c, e=None: (1, "", "Acceso denegado"))


def test_windows_admite_carpetas_con_ruta_larga(tmp_path):
    """El comando que recibe schtasks es corto aunque la carpeta tenga una ruta larga."""
    larga = tmp_path / ("carpeta-con-un-nombre-muy-largo-" * 2)
    larga.mkdir()
    falso = SchtasksFalso()
    crear_tarea(larga, sistema=WINDOWS, ejecutar=falso)
    comando = falso.comandos[0]
    assert len(comando[comando.index("/TR") + 1]) <= 261


# ------------------------------------------------------------ Linux

def test_linux_crear_respeta_el_crontab_existente(tmp_path):
    falso = CrontabFalso("0 3 * * * /usr/bin/copia-de-seguridad\n")
    tarea = crear_tarea(tmp_path, "diaria", "09:00", sistema=LINUX, ejecutar=falso)

    lineas = falso.contenido.splitlines()
    assert lineas[0] == "0 3 * * * /usr/bin/copia-de-seguridad"
    assert lineas[1].startswith("0 9 * * * ") and lineas[1].endswith(MARCA_CRON + tarea.nombre)

    # Volver a crearla la reemplaza, no la duplica.
    crear_tarea(tmp_path, "semanal", "10:15", sistema=LINUX, ejecutar=falso)
    lineas = falso.contenido.splitlines()
    assert len(lineas) == 2 and lineas[1].startswith("15 10 * * 1 ")
    assert [t.hora for t in listar_tareas(sistema=LINUX, ejecutar=falso)] == ["10:15"]


def test_linux_quitar_solo_la_linea_propia(tmp_path):
    falso = CrontabFalso()  # el usuario todavía no tiene crontab
    tarea = crear_tarea(tmp_path, sistema=LINUX, ejecutar=falso)
    falso.contenido += "0 3 * * * /usr/bin/copia-de-seguridad\n"

    assert quitar_tarea(tarea.nombre, sistema=LINUX, ejecutar=falso) is True
    assert falso.contenido == "0 3 * * * /usr/bin/copia-de-seguridad\n"
    assert quitar_tarea(tarea.nombre, sistema=LINUX, ejecutar=falso) is False
    assert listar_tareas(sistema=LINUX, ejecutar=falso) == []


# ------------------------------------------------------------ validaciones

@pytest.mark.parametrize("frecuencia, hora", [
    ("mensual", "09:00"), ("diaria", "9"), ("diaria", "25:00"), ("diaria", "09:60"),
    ("diaria", "09:00 & calc"),
])
def test_valores_no_validos(tmp_path, frecuencia, hora):
    falso = SchtasksFalso()
    with pytest.raises(ErrorProgramador):
        crear_tarea(tmp_path, frecuencia, hora, sistema=WINDOWS, ejecutar=falso)
    assert falso.comandos == []  # no se llegó a ejecutar nada


def test_carpeta_inexistente_y_sistema_no_soportado(tmp_path):
    with pytest.raises(ErrorProgramador, match="no existe"):
        crear_tarea(tmp_path / "no", sistema=WINDOWS, ejecutar=SchtasksFalso())
    with pytest.raises(ErrorProgramador, match="Windows y Linux"):
        listar_tareas(sistema="otro")


@pytest.mark.parametrize("nombre", ["", "..\\Microsoft\\Windows\\Defrag", "a b", "x;rm -rf", "*"])
def test_quitar_rechaza_nombres_ajenos(nombre):
    falso = SchtasksFalso()
    with pytest.raises(ErrorProgramador, match="no válido"):
        quitar_tarea(nombre, sistema=WINDOWS, ejecutar=falso)
    assert falso.comandos == []


# ------------------------------------------------------------ terminal

def test_cli_programar(tmp_path, capsys, monkeypatch):
    falso = SchtasksFalso()
    for nombre, funcion in (("crear_tarea", crear_tarea), ("listar_tareas", listar_tareas),
                            ("quitar_tarea", quitar_tarea)):
        monkeypatch.setattr(comandos, nombre,
                            lambda *a, _f=funcion, **k: _f(*a, sistema=WINDOWS, ejecutar=falso, **k))

    assert ejecutar(["programar", "listar"]) == 0
    assert "No hay escaneos programados" in capsys.readouterr().out

    assert ejecutar(["programar", "crear", str(tmp_path), "--frecuencia", "semanal", "--hora", "20:00"]) == 0
    salida = capsys.readouterr().out
    nombre = nombre_de_tarea(tmp_path.resolve())
    assert nombre in salida and "cada lunes a las 20:00" in salida

    assert ejecutar(["programar", "listar"]) == 0
    assert nombre in capsys.readouterr().out
    assert ejecutar(["programar", "quitar", nombre]) == 0
    assert ejecutar(["programar", "quitar", nombre]) == 1
    assert ejecutar(["programar", "crear", str(tmp_path), "--hora", "tarde"]) == 1
