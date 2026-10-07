"""Pruebas de lo añadido para distribuir el programa a otras personas:
registro de acciones, carpetas protegidas ampliadas, doble confirmación,
permisos de administrador solo para la salud y rutas del paquete."""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import pytest

from cli.comandos import ejecutar
from core import limpieza, registro
from core.basura import ANTIGUOS, DUPLICADOS, REGENERABLES, detectar_basura
from core.elevacion import EXPLICACION, leer_salud_con_permisos, volcar_salud
from core.escaner import escanear
from core.limpieza import UMBRAL_DOBLE_CONFIRMACION, limpiar, requiere_doble_confirmacion
from core.modelos import ElementoBasura
from core.mover import mover
from core.salud import BUENO, DESCONOCIDO, ErrorSalud, interpretar
from tests.test_salud import SmartctlFalso, ejemplo
from utils import rutas
from utils.seguridad import carpetas_personales, en_carpeta_personal, es_ruta_protegida

GB = 1024 ** 3


def crear(ruta: Path, tamano: int = 100, relleno: bytes = b"x") -> Path:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_bytes(relleno * tamano)
    return ruta


# ------------------------------------------------------------ 9. carpetas protegidas ampliadas

@pytest.fixture
def perfiles(tmp_path: Path):
    """Usuarios/ana (con Documentos, Escritorio, Imágenes y Descargas) y Usuarios/luis."""
    ana = tmp_path / "Usuarios" / "ana"
    for nombre in ("Documents", "Escritorio", "Imágenes", "Downloads", "proyectos"):
        (ana / nombre).mkdir(parents=True)
    (ana / "OneDrive - Empresa" / "Documentos").mkdir(parents=True)
    (tmp_path / "Usuarios" / "luis" / "Documents").mkdir(parents=True)
    return ana


def test_carpetas_personales(perfiles):
    nombres = sorted(str(p.relative_to(perfiles)) for p in carpetas_personales(perfiles))
    assert nombres == sorted(["Documents", "Escritorio", "Imágenes",
                              str(Path("OneDrive - Empresa") / "Documentos")])


def test_carpetas_personales_en_linux_con_otro_nombre(tmp_path):
    home = tmp_path / "home" / "ana"
    (home / ".config").mkdir(parents=True)
    (home / "Papeles").mkdir()
    (home / ".config" / "user-dirs.dirs").write_text(
        'XDG_DOCUMENTS_DIR="$HOME/Papeles"\nXDG_MUSIC_DIR="$HOME/Musica"\nXDG_DESKTOP_DIR="$HOME"\n',
        encoding="utf-8")
    assert carpetas_personales(home) == [home / "Papeles"]


def test_las_carpetas_personales_no_se_pueden_mover_ni_borrar(perfiles):
    def protegida(ruta):
        return es_ruta_protegida(ruta, criticas=[], home=perfiles)

    assert protegida(perfiles / "Documents") and protegida(perfiles / "Escritorio")
    assert protegida(perfiles / "OneDrive - Empresa" / "Documentos")
    # Su contenido sí se puede tocar si el usuario lo elige a mano y lo confirma.
    assert not protegida(perfiles / "Documents" / "informe.pdf")
    assert not protegida(perfiles / "Downloads") and not protegida(perfiles / "proyectos" / "x")


def test_el_perfil_de_otro_usuario_esta_protegido(perfiles):
    otro = perfiles.parent / "luis"

    def protegida(ruta):
        return es_ruta_protegida(ruta, criticas=[], home=perfiles)

    assert protegida(otro) and protegida(otro / "Documents" / "privado.txt")
    assert protegida(perfiles.parent / "Public" / "algo.txt")
    assert not protegida(perfiles.parent.parent / "datos" / "algo.txt")   # fuera de los perfiles


def test_lo_personal_nunca_se_sugiere_como_basura(tmp_path):
    raiz = tmp_path / "ana"
    documentos = raiz / "Documentos"
    hace_mucho = (0, 0)
    for relleno, carpeta in ((b"1", documentos), (b"2", raiz / "trabajo")):
        # Contenido distinto en cada carpeta, para que no cuenten como duplicados entre sí.
        os.utime(crear(carpeta / "viejo.bin", 5000, relleno), hace_mucho)
        crear(carpeta / "copia-a.bin", 3000, b"d")
        crear(carpeta / "copia-b.bin", 3000, b"d")
        crear(carpeta / "web" / "node_modules" / "x.js", 2000)

    resultado = escanear(raiz)
    opciones = dict(reglas=[], tamano_minimo_antiguos=1, tamano_minimo_duplicados=1)

    con_proteccion = {c.clave: c.elementos for c in detectar_basura(
        resultado, personales=[documentos], **opciones)}
    for clave in (REGENERABLES, DUPLICADOS, ANTIGUOS):
        rutas_sugeridas = [e.ruta for e in con_proteccion[clave]]
        assert rutas_sugeridas, clave
        assert not any(en_carpeta_personal(r, [documentos]) for r in rutas_sugeridas), clave

    # Sin la protección sí aparecerían: la diferencia es exactamente lo de Documentos.
    sin_proteccion = {c.clave: c.elementos for c in detectar_basura(resultado, personales=[], **opciones)}
    assert len(sin_proteccion[REGENERABLES]) == 2 and len(con_proteccion[REGENERABLES]) == 1


# ------------------------------------------------------------ 10. doble confirmación por encima de 1 GB

def test_requiere_doble_confirmacion():
    def elementos(*tamanos):
        return [ElementoBasura(Path(f"/x/{i}"), t, "archivos") for i, t in enumerate(tamanos)]

    assert UMBRAL_DOBLE_CONFIRMACION == GB
    assert not requiere_doble_confirmacion(elementos(GB))             # justo 1 GB todavía no
    assert requiere_doble_confirmacion(elementos(GB + 1))
    assert requiere_doble_confirmacion(elementos(GB // 2, GB // 2, 1))  # cuenta el total
    assert not requiere_doble_confirmacion([])


@pytest.fixture
def carpeta_grande(tmp_path, monkeypatch):
    """Un node_modules pequeño que el programa cree que pesa 2 GB."""
    monkeypatch.setattr("core.basura.reglas_del_sistema", lambda: [])
    monkeypatch.setattr("core.limpieza.send2trash", shutil.rmtree)
    monkeypatch.setattr("cli.comandos.requiere_doble_confirmacion", lambda elementos: True)
    raiz = tmp_path / "raiz"
    crear(raiz / "proyecto" / "node_modules" / "x.js", 1000)
    return raiz


def test_cli_pide_confirmar_dos_veces(carpeta_grande, capsys, monkeypatch):
    respuestas = iter(["ELIMINAR", "CONFIRMO"])
    preguntas = []
    monkeypatch.setattr("builtins.input", lambda texto="": preguntas.append(texto) or next(respuestas))
    assert ejecutar(["limpiar", str(carpeta_grande), "-c", "regenerables"]) == 0
    assert len(preguntas) == 2 and "CONFIRMO" in preguntas[1]
    assert "más de 1 GB" in capsys.readouterr().out
    assert not (carpeta_grande / "proyecto" / "node_modules").exists()


@pytest.mark.parametrize("segunda", ["", "ELIMINAR", "si", "confirmo"])
def test_cli_sin_segunda_confirmacion_no_toca_nada(carpeta_grande, monkeypatch, segunda):
    respuestas = iter(["ELIMINAR", segunda])
    monkeypatch.setattr("builtins.input", lambda texto="": next(respuestas))
    assert ejecutar(["limpiar", str(carpeta_grande), "-c", "regenerables"]) == 1
    assert (carpeta_grande / "proyecto" / "node_modules").exists()


def test_web_exige_la_segunda_confirmacion(tmp_path, monkeypatch):
    from web.app import crear_app
    from web.tareas import GestorEscaneo
    monkeypatch.setattr("core.basura.reglas_del_sistema", lambda: [])
    monkeypatch.setattr("core.limpieza.send2trash", shutil.rmtree)
    monkeypatch.setattr("web.app.requiere_doble_confirmacion", lambda elementos: True)
    raiz = tmp_path / "raiz"
    crear(raiz / "proyecto" / "node_modules" / "x.js", 1000)

    app = crear_app(GestorEscaneo())
    cliente, token = app.test_client(), {"X-Token": app.config["TOKEN"]}
    cliente.post("/api/escanear", json={"ruta": str(raiz)}, headers=token)
    app.config["GESTOR"].esperar(30)
    cuerpo = {"ids": ["regenerables-0"], "simulacion": False, "confirmado": True}

    rechazo = cliente.post("/api/limpiar", json=cuerpo, headers=token)
    assert rechazo.status_code == 400 and "segunda vez" in rechazo.get_json()["error"]
    assert (raiz / "proyecto" / "node_modules").exists()
    # La simulación no necesita la segunda confirmación.
    assert cliente.post("/api/limpiar", json={"ids": ["regenerables-0"]}, headers=token).status_code == 200

    aceptado = cliente.post("/api/limpiar", json={**cuerpo, "confirmado_doble": True}, headers=token)
    assert aceptado.status_code == 200 and not (raiz / "proyecto" / "node_modules").exists()


# ------------------------------------------------------------ 11. registro de acciones

def lineas_del_registro() -> list[list[str]]:
    return [linea.split("\t") for linea in registro.ultimas_lineas()]


def test_el_registro_esta_en_la_carpeta_de_datos(datos_aislados):
    assert registro.ruta_registro() == datos_aislados / "registro.log"
    assert registro.ultimas_lineas() == []


def test_papelera_y_simulacion_quedan_registradas(tmp_path, monkeypatch):
    monkeypatch.setattr(limpieza, "send2trash", os.remove)
    bueno = ElementoBasura(crear(tmp_path / "a.tmp", 300), 300, "temporales")
    informativo = ElementoBasura(crear(tmp_path / "b.tmp", 50), 50, "temporales", limpiable=False)

    limpiar([bueno, informativo])                       # simulación
    limpiar([bueno, informativo], simulacion=False)     # de verdad

    lineas = lineas_del_registro()
    assert [(l[1], l[2]) for l in lineas] == [
        ("simulación de papelera", "hecho"), ("simulación de papelera", "omitido"),
        ("papelera", "hecho"), ("papelera", "omitido")]
    fecha, _, _, tamano, ruta, detalle = lineas[2]
    assert (tamano, ruta) == ("300", str(bueno.ruta)) and len(fecha) == 19
    assert "informativo" in lineas[3][5]


def test_mover_queda_registrado(tmp_path):
    destino = tmp_path / "destino"
    destino.mkdir()
    elemento = ElementoBasura(crear(tmp_path / "origen" / "foto.jpg", 80), 80, "archivos")
    mover([elemento], destino, simulacion=False)
    (linea,) = lineas_del_registro()
    assert linea[1:3] == ["mover", "hecho"] and str(destino / "foto.jpg") in linea[5]


def test_el_registro_no_rompe_nada_si_no_se_puede_escribir(tmp_path, monkeypatch):
    monkeypatch.setattr(limpieza, "send2trash", os.remove)
    # La "carpeta" de datos es en realidad un archivo: no se puede crear nada dentro.
    estorbo = tmp_path / "no-es-carpeta"
    estorbo.write_text("x")
    monkeypatch.setenv("ANALIZADOR_DISCO_DATOS", str(estorbo))
    elemento = ElementoBasura(crear(tmp_path / "a.tmp"), 100, "temporales")
    assert len(limpiar([elemento], simulacion=False).enviados) == 1 and not elemento.ruta.exists()


def test_el_registro_rota_al_crecer(monkeypatch):
    monkeypatch.setattr(registro, "TAMANO_MAXIMO", 200)
    for numero in range(12):
        registro.anotar("papelera", "hecho", 1, f"/ruta/archivo-{numero}.tmp")
    assert registro.ruta_registro().with_name("registro.log.1").exists()
    assert registro.ruta_registro().stat().st_size < 400


def test_el_registro_no_admite_lineas_falsas():
    registro.anotar("papelera", "hecho", 1, "nombre\ncon salto\tde línea", "detalle\nraro")
    assert len(registro.ultimas_lineas()) == 1


# ------------------------------------------------------------ 12. permisos solo para la salud

def test_la_falta_de_permisos_se_marca_en_el_disco():
    assert interpretar(ejemplo("sin_permisos_windows_real"), "/dev/sdb").falta_permiso is True
    assert interpretar(ejemplo("usb_sin_smart")).falta_permiso is False
    assert interpretar(ejemplo("hdd_sano")).falta_permiso is False


def test_volcar_salud_no_sobrescribe(tmp_path):
    destino = tmp_path / "salud.json"
    assert volcar_salud(destino, SmartctlFalso()) == 3
    datos = json.loads(destino.read_text(encoding="utf-8"))
    assert [d["nombre"] for d in datos] == ["/dev/sda", "/dev/sdb", "/dev/nvme0"]
    with pytest.raises(FileExistsError):
        volcar_salud(destino, SmartctlFalso())


def test_leer_salud_con_permisos(datos_aislados):
    comandos = []

    def proceso_elevado(comando):
        """Hace lo que haría el proceso con permisos: escribir el archivo pedido."""
        comandos.append(comando)
        volcar_salud(comando[-1], SmartctlFalso({"/dev/sda": "hdd_sano", "/dev/sdb": "ssd_sata",
                                                 "/dev/nvme0": "nvme_sano"}))
        return 0

    discos = leer_salud_con_permisos(lanzar=proceso_elevado)
    assert [d.estado for d in discos] == [BUENO, BUENO, BUENO]
    # Lo único que se ejecuta con permisos es la lectura; nada más.
    assert comandos[0][-4:-1] == ["cli", "salud", "volcar"]
    assert Path(comandos[0][-1]).parent == datos_aislados
    assert list(datos_aislados.glob("salud-*.json")) == []          # el archivo temporal se borra


def test_si_no_se_conceden_los_permisos(datos_aislados):
    with pytest.raises(ErrorSalud, match="No se concedieron"):
        leer_salud_con_permisos(lanzar=lambda comando: 1)
    assert "administrador" in EXPLICACION and "No se escribe" in EXPLICACION


def test_cli_salud_volcar(tmp_path, capsys, monkeypatch):
    from core import salud
    monkeypatch.setattr(salud, "_ejecutar", SmartctlFalso())
    destino = tmp_path / "volcado.json"
    assert ejecutar(["salud", "volcar", str(destino)]) == 0 and destino.exists()
    assert ejecutar(["salud", "volcar", str(destino)]) == 1          # ya existe: no se toca
    assert interpretar(json.loads(destino.read_text(encoding="utf-8"))[0]["datos"]).estado != DESCONOCIDO


# ------------------------------------------------------------ 1. rutas en desarrollo y empaquetado

def test_rutas_en_desarrollo():
    assert not rutas.empaquetado()
    assert rutas.ruta_recurso("desktop", "recursos", "icono.png").is_file()
    for archivo in ("LICENSE", "NOTICE"):
        assert rutas.ruta_recurso(archivo).is_file()


def test_rutas_dentro_del_ejecutable(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert rutas.empaquetado() and rutas.carpeta_base() == tmp_path
    assert rutas.ruta_recurso("web", "static") == tmp_path / "web" / "static"


def test_notice_declara_lo_importante():
    texto = rutas.ruta_recurso("NOTICE").read_text(encoding="utf-8")
    for esperado in ("no envía datos a ningún servidor", "PySide6", "LGPL", "smartmontools",
                     "NO viene incluido", "psutil", "Send2Trash", "fpdf2", "d3-hierarchy"):
        assert esperado in texto, esperado
