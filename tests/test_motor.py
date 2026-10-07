"""Pruebas del motor. Todas trabajan sobre carpetas temporales (tmp_path)."""

from __future__ import annotations

import csv
import os
import threading
import time
from pathlib import Path

import pytest

from core import basura as modulo_basura
from core.basura import (
    ANTIGUOS, DUPLICADOS, REGENERABLES, archivos_antiguos, detectar_basura, medir_ruta,
)
from core.carpetas import contenido_de
from core.discos import resumen_discos
from core.duplicados import buscar_duplicados, hash_archivo
from core.escaner import archivos_mas_pesados, escanear
from core.modelos import a_dict
from core.reglas import linux, windows
from core.reglas.base import CACHE, TEMPORALES, ReglaUbicacion
from core.reporte import exportar_csv, exportar_html, reunir_datos
from core.tipos import clasificar, resumen_por_tipo
from utils.formato import porcentaje, tamano_legible
from utils.seguridad import carpetas_criticas, es_ruta_protegida
from utils.sistema import LINUX, WINDOWS


def crear(ruta: Path, tamano: int, relleno: bytes = b"x") -> Path:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_bytes(relleno * tamano)
    return ruta


@pytest.fixture
def arbol(tmp_path: Path) -> Path:
    """
    raiz/
      suelto.txt (10)
      fotos/a.jpg (300)  fotos/viaje/b.png (200)
      proyecto/main.py (50)  proyecto/node_modules/lib/x.js (1000)
    """
    raiz = tmp_path / "raiz"
    crear(raiz / "suelto.txt", 10)
    crear(raiz / "fotos" / "a.jpg", 300)
    crear(raiz / "fotos" / "viaje" / "b.png", 200)
    crear(raiz / "proyecto" / "main.py", 50)
    crear(raiz / "proyecto" / "node_modules" / "lib" / "x.js", 1000)
    return raiz


# ------------------------------------------------------------ utilidades

def test_tamano_legible():
    assert tamano_legible(0) == "0 B"
    assert tamano_legible(1023) == "1023 B"
    assert tamano_legible(1536) == "1.5 KB"
    assert tamano_legible(5 * 1024**3) == "5.0 GB"


def test_porcentaje_sin_total():
    assert porcentaje(5, 0) == 0.0
    assert porcentaje(1, 4) == 25.0


# ------------------------------------------------------------ discos

def test_resumen_discos():
    discos = resumen_discos()
    assert discos, "debería existir al menos un disco"
    for d in discos:
        assert d.total > 0
        assert 0 <= d.porcentaje <= 100


# ------------------------------------------------------------ escáner y carpetas

def test_escaneo_totales(arbol):
    r = escanear(arbol)
    assert r.num_archivos == 5
    assert r.tamano_total == 1560
    assert r.errores == 0


def test_carpetas_ordenadas_y_acumuladas(arbol):
    r = escanear(arbol)
    nivel = contenido_de(r)
    assert [c.ruta.name for c in nivel.subcarpetas] == ["proyecto", "fotos"]
    assert [c.tamano for c in nivel.subcarpetas] == [1050, 500]
    assert nivel.tamano_archivos_directos == 10


def test_profundizar_un_nivel(arbol):
    r = escanear(arbol)
    fotos = contenido_de(r, arbol / "fotos")
    assert fotos.tamano == 500
    assert fotos.tamano_archivos_directos == 300
    assert [(c.ruta.name, c.tamano) for c in fotos.subcarpetas] == [("viaje", 200)]


def test_carpeta_fuera_del_escaneo(arbol, tmp_path):
    with pytest.raises(KeyError):
        contenido_de(escanear(arbol), tmp_path / "no-existe")


def test_escanear_ruta_invalida(tmp_path):
    with pytest.raises(NotADirectoryError):
        escanear(tmp_path / "no-existe")


def test_top_archivos(arbol):
    top = archivos_mas_pesados(escanear(arbol), 2)
    assert [a.nombre for a in top] == ["x.js", "a.jpg"]


def test_no_sigue_enlaces(arbol, tmp_path):
    externo = crear(tmp_path / "externo" / "grande.bin", 5000).parent
    try:
        os.symlink(externo, arbol / "enlace", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("este sistema no permite crear enlaces simbólicos")
    assert escanear(arbol).tamano_total == 1560


def test_cancelar(arbol):
    evento = threading.Event()
    evento.set()
    r = escanear(arbol, cancelar=evento)
    assert r.cancelado and r.num_archivos == 0


def test_progreso(arbol):
    avisos = []
    escanear(arbol, progreso=lambda n, ruta: avisos.append(n), avisar_cada=1)
    assert avisos[-1] == 5


# ------------------------------------------------------------ tipos

@pytest.mark.parametrize("nombre, tipo", [
    ("peli.MKV", "videos"), ("foto.jpeg", "imagenes"), ("informe.pdf", "documentos"),
    ("copia.zip", "comprimidos"), ("setup.exe", "instaladores"), ("app.py", "codigo"),
    ("datos.xyz", "otros"), ("sin_extension", "otros"),
])
def test_clasificar(nombre, tipo):
    assert clasificar(nombre) == tipo


def test_resumen_por_tipo(arbol):
    resumen = {t.tipo: t for t in resumen_por_tipo(escanear(arbol).archivos)}
    assert resumen["imagenes"].tamano == 500 and resumen["imagenes"].cantidad == 2
    assert resumen["codigo"].tamano == 1050
    assert resumen["documentos"].tamano == 10
    assert resumen["videos"].cantidad == 0


# ------------------------------------------------------------ duplicados

def test_duplicados(tmp_path):
    grande = 100_000  # mayor que el hash parcial: obliga al hash completo
    crear(tmp_path / "a" / "original.bin", grande, b"a")
    crear(tmp_path / "b" / "copia.bin", grande, b"a")
    crear(tmp_path / "c" / "otra_copia.bin", grande, b"a")
    # Mismo tamaño y mismo comienzo, pero distinto final: NO es duplicado.
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "parecido.bin").write_bytes(b"a" * (grande - 1) + b"z")
    crear(tmp_path / "e" / "unico.bin", 777)

    grupos = buscar_duplicados(escanear(tmp_path).archivos)
    assert len(grupos) == 1
    assert sorted(p.name for p in grupos[0].archivos) == ["copia.bin", "original.bin", "otra_copia.bin"]
    assert grupos[0].espacio_recuperable == 2 * grande


def test_duplicados_ignora_vacios_y_regenerables(tmp_path):
    crear(tmp_path / "vacio1.txt", 0)
    crear(tmp_path / "vacio2.txt", 0)
    crear(tmp_path / "p1" / "node_modules" / "lib.js", 500)
    crear(tmp_path / "p2" / "node_modules" / "lib.js", 500)
    assert buscar_duplicados(escanear(tmp_path).archivos) == []


def test_duplicados_enlace_duro(tmp_path):
    original = crear(tmp_path / "original.bin", 2000)
    try:
        os.link(original, tmp_path / "enlace.bin")
    except (OSError, NotImplementedError):
        pytest.skip("este sistema no permite enlaces duros")
    assert buscar_duplicados(escanear(tmp_path).archivos) == []


def test_hash_archivo_inexistente(tmp_path):
    assert hash_archivo(tmp_path / "no-existe") is None


# ------------------------------------------------------------ basura

def test_medir_ruta(arbol):
    assert medir_ruta(arbol) == (1560, 5)
    assert medir_ruta(arbol / "suelto.txt") == (10, 1)
    assert medir_ruta(arbol / "no-existe") == (0, 0)


def test_regenerables(arbol):
    categorias = {c.clave: c for c in detectar_basura(escanear(arbol), reglas=[])}
    regenerables = categorias[REGENERABLES].elementos
    assert [(e.ruta.name, e.tamano) for e in regenerables] == [("node_modules", 1000)]
    assert regenerables[0].es_carpeta


def test_archivos_antiguos(tmp_path):
    viejo = crear(tmp_path / "viejo.bin", 5000)
    crear(tmp_path / "nuevo.bin", 5000)
    hace_dos_anios = time.time() - 2 * 365 * 86400
    os.utime(viejo, (hace_dos_anios, hace_dos_anios))

    antiguos = archivos_antiguos(escanear(tmp_path), tamano_minimo=1)
    assert [e.ruta.name for e in antiguos] == ["viejo.bin"]
    # Con el tamaño mínimo por defecto (1 MB) no entra.
    assert archivos_antiguos(escanear(tmp_path)) == []


def test_ubicaciones_conocidas(tmp_path):
    temp = tmp_path / "temp"
    antier = time.time() - 2 * 86400
    # Con fecha de hace dos días: los temporales recientes no son limpiables.
    for ruta in (crear(temp / "a.tmp", 100), crear(temp / "sesion" / "b.tmp", 400), temp / "sesion"):
        os.utime(ruta, (antier, antier))
    logs = tmp_path / "logs"
    crear(logs / "sistema.log", 900)
    reglas = [
        ReglaUbicacion(TEMPORALES, "Temporales", temp),
        ReglaUbicacion(CACHE, "Caché inexistente", tmp_path / "no-existe"),
        ReglaUbicacion("logs", "Registros", logs, limpiable=False, nota="Solo lectura."),
    ]
    categorias = {c.clave: c for c in detectar_basura(None, reglas=reglas)}

    temporales = categorias[TEMPORALES]
    assert [(e.ruta.name, e.tamano, e.limpiable) for e in temporales.elementos] == [
        ("sesion", 400, True), ("a.tmp", 100, True),
    ]
    assert temporales.tamano_total == 500
    assert categorias[CACHE].elementos == []

    # Una ubicación informativa es un solo elemento, y nunca limpiable.
    (registro,) = categorias["logs"].elementos
    assert (registro.tamano, registro.limpiable) == (900, False)
    assert categorias["logs"].tamano_limpiable == 0


def test_temporal_reciente_no_es_limpiable(tmp_path):
    temp = tmp_path / "temp"
    antier = time.time() - 2 * 86400
    os.utime(crear(temp / "viejo.tmp", 100), (antier, antier))
    crear(temp / "recien_creado.tmp", 200)
    # Carpeta antigua con un archivo reciente dentro: cuenta como reciente.
    crear(temp / "sesion" / "activo.tmp", 300)
    os.utime(temp / "sesion", (antier, antier))

    regla = ReglaUbicacion(TEMPORALES, "Temporales", temp)
    limpiables = {e.ruta.name: e.limpiable for e in modulo_basura.elementos_de_regla(regla)}
    assert limpiables == {"viejo.tmp": True, "recien_creado.tmp": False, "sesion": False}

    # La regla de las 24 horas solo aplica a temporales, no a la caché.
    cache = ReglaUbicacion(CACHE, "Caché", temp)
    assert all(e.limpiable for e in modulo_basura.elementos_de_regla(cache))


def test_sin_doble_conteo(tmp_path):
    """Un archivo dentro de una ubicación conocida no se repite en otras categorías."""
    temp = tmp_path / "temp"
    for nombre in ("uno.bin", "dos.bin"):
        viejo = crear(temp / nombre, 3000)
        os.utime(viejo, (0, 0))
    categorias = {c.clave: c for c in detectar_basura(
        escanear(tmp_path), reglas=[ReglaUbicacion(TEMPORALES, "Temporales", temp)],
        tamano_minimo_antiguos=1, tamano_minimo_duplicados=1,
    )}
    assert len(categorias[TEMPORALES].elementos) == 2
    assert categorias[DUPLICADOS].elementos == []
    assert categorias[ANTIGUOS].elementos == []


def test_ubicacion_informativa_no_oculta_su_contenido(tmp_path):
    """Dentro de Descargas (solo informativa) sí se buscan duplicados y antiguos."""
    descargas = tmp_path / "Downloads"
    for nombre in ("uno.bin", "dos.bin"):
        os.utime(crear(descargas / nombre, 3000), (0, 0))
    regla = ReglaUbicacion("descargas", "Descargas", descargas, limpiable=False)
    categorias = {c.clave: c for c in detectar_basura(
        escanear(tmp_path), reglas=[regla],
        tamano_minimo_antiguos=1, tamano_minimo_duplicados=1,
    )}
    assert len(categorias[DUPLICADOS].elementos) == 1
    assert len(categorias[ANTIGUOS].elementos) == 1  # la otra copia ya salió como duplicado


def test_elemento_protegido_no_es_limpiable(arbol, monkeypatch):
    monkeypatch.setattr(modulo_basura, "es_ruta_protegida", lambda ruta: True)
    categorias = {c.clave: c for c in detectar_basura(escanear(arbol), reglas=[])}
    assert all(not e.limpiable for e in categorias[REGENERABLES].elementos)


# ------------------------------------------------------------ seguridad

def test_ruta_protegida(tmp_path):
    critica = tmp_path / "sistema"
    (critica / "dentro").mkdir(parents=True)
    libre = tmp_path / "libre"
    libre.mkdir()
    home = tmp_path / "home" / "ana"
    (home / "docs").mkdir(parents=True)

    def protegida(ruta):
        return es_ruta_protegida(ruta, criticas=[critica], home=home)

    assert protegida(critica)
    assert protegida(critica / "dentro" / "archivo.dll")
    assert protegida(tmp_path)               # contiene a la carpeta crítica
    assert protegida(Path(tmp_path.anchor))  # raíz del disco
    assert protegida(home)
    assert protegida(home.parent)
    assert not protegida(home / "docs")
    assert not protegida(libre)


def test_ruta_protegida_ignora_mayusculas_en_windows(tmp_path):
    if os.path.normcase("A") == "A":
        pytest.skip("solo aplica a sistemas que no distinguen mayúsculas")
    critica = tmp_path / "Sistema"
    critica.mkdir()
    assert es_ruta_protegida(str(critica).upper(), criticas=[critica], home=tmp_path / "h")


def test_carpetas_criticas_por_sistema():
    entorno = {"SystemRoot": r"C:\Windows", "ProgramFiles": r"C:\Program Files",
               "ProgramFiles(x86)": r"C:\Program Files (x86)"}
    nombres = {p.name for p in carpetas_criticas(WINDOWS, entorno)}
    assert nombres == {"Windows", "Program Files", "Program Files (x86)"}

    nombres = {p.name for p in carpetas_criticas(LINUX)}
    assert {"bin", "boot", "etc", "usr", "lib", "sys", "proc"} <= nombres


# ------------------------------------------------------------ reglas por sistema

def test_reglas_windows(tmp_path):
    local = tmp_path / "AppData" / "Local"
    (local / "Google" / "Chrome" / "User Data" / "Default").mkdir(parents=True)
    (local / "Microsoft" / "Edge" / "User Data" / "Profile 1").mkdir(parents=True)
    (local / "Mozilla" / "Firefox" / "Profiles" / "abc.default").mkdir(parents=True)
    entorno = {"TEMP": str(tmp_path / "Temp"), "SystemRoot": str(tmp_path / "Windows"),
               "LOCALAPPDATA": str(local)}

    reglas = windows.obtener_reglas(entorno, home=tmp_path, unidades=[tmp_path])
    por_ruta = {r.ruta: r for r in reglas}

    assert por_ruta[tmp_path / "Temp"].limpiable
    assert not por_ruta[tmp_path / "Windows" / "Temp"].limpiable
    assert not por_ruta[tmp_path / "Windows" / "Prefetch"].limpiable
    assert not por_ruta[tmp_path / "$Recycle.Bin"].limpiable
    assert not por_ruta[tmp_path / "Downloads"].limpiable
    nombres = " ".join(r.nombre for r in reglas)
    assert "Chrome" in nombres and "Edge" in nombres and "Firefox" in nombres
    assert local / "Mozilla" / "Firefox" / "Profiles" / "abc.default" / "cache2" in por_ruta


def test_reglas_linux(tmp_path):
    home = tmp_path / "home" / "ana"
    reglas = linux.obtener_reglas(home=home, raiz=tmp_path)
    por_ruta = {r.ruta: r for r in reglas}

    assert por_ruta[tmp_path / "tmp"].limpiable
    assert por_ruta[home / ".cache"].limpiable
    assert not por_ruta[home / ".local" / "share" / "Trash"].limpiable
    assert not por_ruta[tmp_path / "var" / "cache" / "apt" / "archives"].limpiable
    assert not por_ruta[tmp_path / "var" / "log"].limpiable
    assert not por_ruta[tmp_path / "var" / "log" / "journal"].limpiable


# ------------------------------------------------------------ reporte

def test_reportes(arbol, tmp_path):
    crear(arbol / "tom & jerry.txt", 20)  # el "&" debe salir escapado en el HTML
    r = escanear(arbol)
    datos = reunir_datos(r, detectar_basura(r, reglas=[]))

    ruta_csv = exportar_csv(datos, tmp_path / "salida" / "reporte.csv")
    with ruta_csv.open(encoding="utf-8-sig", newline="") as archivo:
        filas = list(csv.DictReader(archivo))
    secciones = {f["seccion"] for f in filas}
    assert {"disco", "carpeta", "archivo_pesado", "tipo", "basura"} <= secciones
    pesado = next(f for f in filas if f["seccion"] == "archivo_pesado")
    assert pesado["nombre"] == "x.js" and pesado["tamano_bytes"] == "1000"

    ruta_html = exportar_html(datos, tmp_path / "salida" / "reporte.html")
    html = ruta_html.read_text(encoding="utf-8")
    assert "node_modules" in html
    assert "tom &amp; jerry.txt" in html and "tom & jerry" not in html


def test_a_dict(arbol):
    datos = a_dict(contenido_de(escanear(arbol)))
    assert datos["tamano"] == 1560
    assert isinstance(datos["ruta"], str)
    assert isinstance(datos["subcarpetas"][0]["ruta"], str)
