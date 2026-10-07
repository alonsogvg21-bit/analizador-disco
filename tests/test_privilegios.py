"""Pruebas del ayudante de salud y de la petición de permisos.

Nunca se piden permisos de verdad: la elevación se sustituye por una función
que hace de "proceso con privilegios", y smartctl por las salidas de ejemplo.
"""

from __future__ import annotations

import inspect
import json
import os
from pathlib import Path

import pytest

import main
from cli.comandos import ejecutar
from core import ayudante, discos_fisicos, privilegios, salud
from core.ayudante import (
    ACCIONES, AccionNoPermitida, ejecutar_accion, main_ayudante, responder, validar_disco,
)
from core.privilegios import (
    PermisoCancelado, SinAgenteDePermisos, ejecutar_ayudante, explicacion,
    iniciar_autoprueba_con_permiso, leer_salud_con_permiso, mensaje_cancelado,
    resultado_a_diccionario,
)
from core.salud import BUENO, DESCONOCIDO, ErrorSalud, completar_datos_basicos, interpretar
from tests.test_salud import SmartctlFalso, ejemplo
from utils.sistema import LINUX, WINDOWS

PELIGROSOS = [
    "/dev/sda; rm -rf /", "../../etc/passwd", "sda", "", " ", "/dev/sda ", " /dev/sda",
    "/dev/sda\n", "/dev/sda1", "/dev/sda/../sdb", "/dev/nvme0n1p1", "/dev/mapper/root",
    "/dev/sd", "/dev/SDA", "-d", "--all", "/dev/sda -X", "$(reboot)", "`id`", "/dev/sda|cat",
    "/dev/sda&&id", "/etc/passwd", "C:\\Windows", "\\\\.\\PhysicalDrive", "\\\\.\\PhysicalDrive0\\x",
    "\\\\.\\PhysicalDrive-1", "\\\\servidor\\recurso", "\\\\.\\C:", "/dev/" + "a" * 100, None, 7, ["/dev/sda"],
]


@pytest.fixture
def smart(monkeypatch):
    """smartctl de mentira: sda necesita permisos; los otros dos se leen bien."""
    falso = SmartctlFalso({"/dev/sda": "hdd_sano", "/dev/sdb": "ssd_sata", "/dev/nvme0": "nvme_sano"})
    monkeypatch.setattr(salud, "buscar_smartctl", lambda: "/usr/sbin/smartctl")
    monkeypatch.setattr(salud, "_ejecutar", falso)
    return falso


# ------------------------------------------------------------ validación del nombre del disco

@pytest.mark.parametrize("nombre", ["/dev/sda", "/dev/sdz", "/dev/sdaa", "/dev/nvme0", "/dev/nvme12",
                                    "/dev/nvme0n1", "/dev/hda"])
def test_nombres_validos_en_linux(nombre):
    assert validar_disco(nombre, LINUX) == nombre


@pytest.mark.parametrize("nombre, esperado", [
    ("\\\\.\\PhysicalDrive0", "/dev/sda"), ("\\\\.\\PhysicalDrive1", "/dev/sdb"),
    ("\\\\.\\PhysicalDrive25", "/dev/sdz"), ("\\\\.\\PhysicalDrive26", "/dev/sdaa"),
    ("/dev/sda", "/dev/sda"), ("/dev/sdb", "/dev/sdb"),
])
def test_nombres_validos_en_windows(nombre, esperado):
    """PhysicalDriveN se traduce al nombre con el que smartctl llama a ese mismo disco."""
    assert validar_disco(nombre, WINDOWS) == esperado


@pytest.mark.parametrize("sistema", [LINUX, WINDOWS])
@pytest.mark.parametrize("nombre", PELIGROSOS)
def test_nombres_rechazados(nombre, sistema):
    with pytest.raises(ErrorSalud, match="no es válido"):
        validar_disco(nombre, sistema)


def test_cada_sistema_solo_acepta_sus_nombres():
    with pytest.raises(ErrorSalud):
        validar_disco("\\\\.\\PhysicalDrive0", LINUX)
    with pytest.raises(ErrorSalud):
        validar_disco("/dev/nvme0", WINDOWS)       # en Windows smartctl no usa ese nombre


def test_el_disco_debe_aparecer_en_el_escaneo(smart):
    """Aunque el nombre tenga buena forma, solo vale si smartctl lo detecta."""
    with pytest.raises(ErrorSalud, match="no está entre los que detecta"):
        ejecutar_accion("leer-smart", ["/dev/sdq"], sistema=LINUX)
    with pytest.raises(ErrorSalud, match="no está entre los que detecta"):
        ejecutar_accion("iniciar-autoprueba", ["/dev/sdq", "corta"], sistema=LINUX)
    assert not any("/dev/sdq" in comando for comando in smart.comandos)   # nunca llegó a smartctl


# ------------------------------------------------------------ acciones del ayudante

def test_solo_existen_cuatro_acciones():
    assert ACCIONES == ("listar-discos", "leer-smart", "iniciar-autoprueba", "resultado-autoprueba")


@pytest.mark.parametrize("accion", ["borrar", "ejecutar", "leer-smart;id", "", "LEER-SMART", "sh", "-t",
                                    "formatear", "listar-discos ", "../leer-smart", "cli"])
def test_acciones_que_no_estan_en_la_lista(accion, smart):
    with pytest.raises(AccionNoPermitida):
        ejecutar_accion(accion, ["/dev/sda"], sistema=LINUX)
    respuesta = responder(accion, ["/dev/sda"], sistema=LINUX)
    assert respuesta["ok"] is False and respuesta["motivo"] == "accion-no-permitida"
    assert smart.comandos == []                    # no se ejecutó nada


def test_listar_y_leer(smart):
    assert [d["name"] for d in ejecutar_accion("listar-discos", [])] == ["/dev/sda", "/dev/sdb", "/dev/nvme0"]
    with pytest.raises(ErrorSalud):
        ejecutar_accion("listar-discos", ["/dev/sda"])

    datos = ejecutar_accion("leer-smart", ["/dev/sda", "/dev/nvme0"], sistema=LINUX)
    assert list(datos) == ["/dev/sda", "/dev/nvme0"]
    assert interpretar(datos["/dev/nvme0"]).estado == BUENO
    # Se usa el tipo (-d) que informa el escaneo, y solo opciones de lectura.
    assert ["smartctl", "--json", "-a", "-d", "ata", "/dev/sda"] in smart.comandos
    assert ["smartctl", "--json", "-a", "-d", "nvme", "/dev/nvme0"] in smart.comandos


def test_leer_exige_al_menos_un_disco_y_todos_validos(smart):
    with pytest.raises(ErrorSalud):
        ejecutar_accion("leer-smart", [], sistema=LINUX)
    with pytest.raises(ErrorSalud, match="no es válido"):
        ejecutar_accion("leer-smart", ["/dev/sda", "/dev/sdb; id"], sistema=LINUX)
    assert not any("-a" in comando for comando in smart.comandos)   # ni siquiera se leyó el válido


def test_autoprueba_y_resultado(smart):
    respuesta = ejecutar_accion("iniciar-autoprueba", ["/dev/sda", "larga"], sistema=LINUX)
    assert "Autoprueba larga iniciada" in respuesta["mensaje"]
    assert smart.comandos[-1] == ["smartctl", "--json", "-t", "long", "-d", "ata", "/dev/sda"]

    for malos in (["/dev/sda"], ["/dev/sda", "destructiva"], ["/dev/sda", "corta", "extra"], []):
        with pytest.raises(ErrorSalud):
            ejecutar_accion("iniciar-autoprueba", malos, sistema=LINUX)

    resultado = ejecutar_accion("resultado-autoprueba", ["/dev/sda"], sistema=LINUX)
    assert resultado["disco"] == "/dev/sda" and resultado["autoprueba"]["correcta"] is True
    assert ejecutar_accion("resultado-autoprueba", ["/dev/sdb"], sistema=LINUX)["autoprueba"] is None


def test_el_ayudante_solo_imprime_json(smart, monkeypatch):
    monkeypatch.setattr(ayudante, "sistema_actual", lambda: LINUX)
    salidas = []
    assert main_ayudante(["listar-discos"], salidas.append) == 0
    assert main_ayudante(["formatear", "/dev/sda"], salidas.append) == 2
    assert main_ayudante([], salidas.append) == 2
    assert main_ayudante(["leer-smart", "/dev/sda; rm -rf /"], salidas.append) == 1
    respuestas = [json.loads(texto) for texto in salidas]      # todo es JSON válido
    assert [r["ok"] for r in respuestas] == [True, False, False, False]
    # La salida es ASCII puro, para que se lea igual con cualquier codificación...
    assert all(texto.isascii() for texto in salidas)
    assert "no es válido" in respuestas[3]["error"]          # ...y los acentos se recuperan al leerla
    assert "Traceback" not in "".join(salidas)


def test_modo_helper_en_main(smart, capsys, monkeypatch):
    monkeypatch.setattr(ayudante, "sistema_actual", lambda: LINUX)
    assert main.main(["--helper", "listar-discos"]) == 0
    assert json.loads(capsys.readouterr().out)["datos"][0]["name"] == "/dev/sda"
    assert main.main(["--helper", "cli", "limpiar"]) == 2       # el ayudante no da acceso al resto
    assert json.loads(capsys.readouterr().out)["motivo"] == "accion-no-permitida"


def test_sin_smartctl_el_ayudante_lo_dice_en_json(monkeypatch):
    monkeypatch.setattr(salud, "buscar_smartctl", lambda: None)
    respuesta = responder("listar-discos", [])
    assert respuesta["ok"] is False and respuesta["motivo"] == "sin-smartctl"


# ------------------------------------------------------------ archivo de resultado (Windows)

def nombre_valido(carpeta: Path) -> Path:
    return carpeta / ("analizador-disco-" + "0123456789abcdef" * 2 + ".json")


def test_el_ayudante_solo_rellena_el_archivo_vacio_que_le_dejan(tmp_path, smart, monkeypatch):
    monkeypatch.setattr(ayudante, "sistema_actual", lambda: LINUX)
    archivo = nombre_valido(tmp_path)
    archivo.touch()
    assert main_ayudante(["--salida", str(archivo), "listar-discos"]) == 0
    assert json.loads(archivo.read_text(encoding="utf-8"))["ok"] is True


def test_el_ayudante_no_escribe_en_rutas_arbitrarias(tmp_path, smart):
    importante = tmp_path / "importante.txt"
    importante.write_text("no tocar")
    no_existe = nombre_valido(tmp_path / "otra")
    con_contenido = nombre_valido(tmp_path)
    con_contenido.write_text("ya tiene algo")
    relativa = "analizador-disco-" + "a" * 32 + ".json"

    for destino in (importante, no_existe, con_contenido, relativa, tmp_path,
                    tmp_path / "analizador-disco-XYZ.json", "C:\\Windows\\win.ini", "/etc/passwd"):
        assert main_ayudante(["--salida", str(destino), "listar-discos"]) == 2, destino
    assert importante.read_text() == "no tocar" and con_contenido.read_text() == "ya tiene algo"
    assert not no_existe.exists() and not Path(relativa).exists()


def test_el_ayudante_no_sigue_enlaces(tmp_path, smart):
    victima = tmp_path / "victima.txt"
    victima.touch()
    enlace = nombre_valido(tmp_path)
    try:
        os.symlink(victima, enlace)
    except (OSError, NotImplementedError):
        pytest.skip("este sistema no permite crear enlaces simbólicos")
    assert main_ayudante(["--salida", str(enlace), "listar-discos"]) == 2
    assert victima.read_text() == ""


def test_el_ayudante_no_escribe_en_archivos_con_varios_nombres(tmp_path, smart):
    victima = tmp_path / "victima.txt"
    victima.touch()
    try:
        os.link(victima, nombre_valido(tmp_path))
    except (OSError, NotImplementedError):
        pytest.skip("este sistema no permite enlaces duros")
    assert main_ayudante(["--salida", str(nombre_valido(tmp_path)), "listar-discos"]) == 2
    assert victima.read_text() == ""


# ------------------------------------------------------------ garantías del código

def test_nunca_se_usa_shell_true():
    for modulo in (ayudante, privilegios, salud, discos_fisicos):
        codigo = inspect.getsource(modulo)
        assert "shell=True" not in codigo and "os.system" not in codigo, modulo.__name__


def test_smartctl_se_llama_por_su_ruta_absoluta(monkeypatch, tmp_path):
    llamadas = []

    class Proceso:
        returncode, stdout, stderr = 0, '{"devices": []}', ""

    monkeypatch.setattr(salud, "buscar_smartctl", lambda: str(tmp_path / "smartctl"))
    monkeypatch.setattr(salud.subprocess, "run", lambda comando, **opciones: llamadas.append((comando, opciones)) or Proceso())
    salud.listar_discos()
    comando, opciones = llamadas[0]
    assert isinstance(comando, list) and os.path.isabs(comando[0])
    assert opciones.get("shell", False) is False


def test_buscar_smartctl_devuelve_ruta_absoluta():
    encontrado = salud.buscar_smartctl()
    assert encontrado is None or os.path.isabs(encontrado)


# ------------------------------------------------------------ elevación simulada

def proceso_con_privilegios(registro: list):
    """Hace de proceso elevado: ejecuta el ayudante y devuelve su JSON, como haría el sistema."""
    def lanzar(comando):
        registro.append(comando)
        posicion = comando.index("--helper") + 1
        accion, argumentos = comando[posicion], comando[posicion + 1:]
        return 0, json.dumps(responder(accion, argumentos, sistema=LINUX))
    return lanzar


def test_elevacion_con_exito(smart, monkeypatch):
    monkeypatch.setattr(ayudante, "sistema_actual", lambda: LINUX)
    monkeypatch.setattr(privilegios, "AYUDANTE_INSTALADO", Path("/no/existe"))
    lanzados = []
    discos = leer_salud_con_permiso(lanzar=proceso_con_privilegios(lanzados), administrador=False)

    assert [d.estado for d in discos] == [BUENO, BUENO, BUENO]
    # Una sola petición de permisos para los tres discos.
    assert len(lanzados) == 1
    assert lanzados[0][-4:] == ["leer-smart", "/dev/sda", "/dev/sdb", "/dev/nvme0"]
    assert "--helper" in lanzados[0]


def test_cancelar_los_permisos_no_es_un_error_del_programa(smart):
    def usuario_dice_que_no(comando):
        raise PermisoCancelado(mensaje_cancelado(WINDOWS))

    with pytest.raises(PermisoCancelado) as cancelado:
        leer_salud_con_permiso(lanzar=usuario_dice_que_no, administrador=False)
    texto = str(cancelado.value)
    assert "No pasa nada" in texto and "volver a pulsar" in texto
    assert "Traceback" not in texto and "error" not in texto.lower()
    assert isinstance(cancelado.value, ErrorSalud)             # las interfaces lo tratan aparte
    assert not any("-a" in comando for comando in smart.comandos)   # sin permiso no se leyó nada


def test_si_ya_soy_administrador_no_se_eleva(smart, monkeypatch):
    monkeypatch.setattr(ayudante, "sistema_actual", lambda: LINUX)

    def no_debe_llamarse(comando):
        raise AssertionError("ya se es administrador: no hay que pedir permisos")

    discos = leer_salud_con_permiso(lanzar=no_debe_llamarse, administrador=True)
    assert len(discos) == 3
    assert "iniciada" in iniciar_autoprueba_con_permiso("/dev/sda", "corta", lanzar=no_debe_llamarse,
                                                        administrador=True)


def test_ejecutar_ayudante_rechaza_acciones_antes_de_pedir_permisos():
    def no_debe_llamarse(comando):
        raise AssertionError("no se piden permisos para una acción inventada")
    with pytest.raises(AccionNoPermitida):
        ejecutar_ayudante("borrar-todo", lanzar=no_debe_llamarse, administrador=False)


def test_errores_del_ayudante_y_respuestas_raras(smart):
    with pytest.raises(ErrorSalud, match="no está entre"):
        ejecutar_ayudante("leer-smart", "/dev/sdq", administrador=False,
                          lanzar=lambda c: (1, json.dumps(responder("leer-smart", ["/dev/sdq"], sistema=LINUX))))
    for salida in ("", "   ", "esto no es JSON", "[1, 2]", '{"sin": "ok"}'):
        with pytest.raises(ErrorSalud):
            ejecutar_ayudante("listar-discos", lanzar=lambda c, s=salida: (0, s), administrador=False)
    assert resultado_a_diccionario('{"ok": true, "datos": [1]}') == {"ok": True, "datos": [1]}


def test_en_linux_el_ayudante_instalado_tiene_prioridad(monkeypatch, tmp_path):
    lanzador = tmp_path / "ayudante"
    lanzador.write_text("#!/bin/sh\n")
    monkeypatch.setattr(privilegios, "sistema_actual", lambda: LINUX)
    monkeypatch.setattr(privilegios, "AYUDANTE_INSTALADO", lanzador)
    assert privilegios.comando_del_ayudante() == [str(lanzador)]
    monkeypatch.setattr(privilegios, "AYUDANTE_INSTALADO", tmp_path / "no-existe")
    assert privilegios.comando_del_ayudante()[-1] == "--helper"


def test_linux_sin_pkexec_ofrece_sudo(monkeypatch):
    monkeypatch.setattr(privilegios.shutil, "which", lambda nombre: None)
    with pytest.raises(SinAgenteDePermisos, match="sudo"):
        privilegios._lanzar_linux(["/usr/lib/analizador-disco/ayudante", "listar-discos"])


@pytest.mark.parametrize("codigo, salida, esperado", [
    (126, "", PermisoCancelado),          # se cerró la ventana de contraseña
    (127, "", SinAgenteDePermisos),       # no hay agente de polkit
])
def test_codigos_de_pkexec(monkeypatch, codigo, salida, esperado):
    class Proceso:
        returncode, stdout = codigo, salida

    monkeypatch.setattr(privilegios.shutil, "which", lambda nombre: "/usr/bin/pkexec")
    monkeypatch.setattr(privilegios.subprocess, "run", lambda *a, **k: Proceso())
    with pytest.raises(esperado):
        privilegios._lanzar_linux(["/usr/lib/analizador-disco/ayudante", "listar-discos"])


def test_pkexec_recibe_una_lista_de_argumentos(monkeypatch):
    llamadas = []

    class Proceso:
        returncode, stdout = 0, '{"ok": true, "datos": []}'

    monkeypatch.setattr(privilegios.shutil, "which", lambda nombre: "/usr/bin/pkexec")
    monkeypatch.setattr(privilegios.subprocess, "run", lambda comando, **k: llamadas.append((comando, k)) or Proceso())
    assert privilegios._lanzar_linux(["/usr/lib/analizador-disco/ayudante", "leer-smart", "/dev/sda"])[0] == 0
    comando, opciones = llamadas[0]
    assert comando == ["pkexec", "/usr/lib/analizador-disco/ayudante", "leer-smart", "/dev/sda"]
    assert opciones.get("shell", False) is False


def test_mensajes_distintos_segun_el_sistema():
    assert "Control de cuentas" in explicacion(WINDOWS) and "contraseña" in explicacion(LINUX)
    for sistema in (WINDOWS, LINUX):
        assert "No se escribe" in explicacion(sistema) and "administrador" in explicacion(sistema)
        assert "PowerShell" not in explicacion(sistema) and "cierra" not in explicacion(sistema).lower()
    assert mensaje_cancelado(WINDOWS) != mensaje_cancelado(LINUX)


def test_politica_de_polkit():
    import xml.etree.ElementTree as ET
    archivo = Path(__file__).parent.parent / "instalador" / "linux" / "io.github.alonsogvg21bit.analizador-disco.policy"
    accion = ET.parse(archivo).getroot().find("action")
    assert accion.find("defaults/allow_active").text == "auth_admin_keep"
    assert accion.find("annotate").text == str(privilegios.AYUDANTE_INSTALADO).replace("\\", "/")
    mensaje = accion.find("message").text
    assert "No se escribe" in mensaje or "no se escribe" in mensaje
    assert str(privilegios.AYUDANTE_INSTALADO.parent).replace("\\", "/") == "/usr/lib/analizador-disco"


# ------------------------------------------------------------ datos sin permisos y "Encendidos"

def test_sin_permisos_se_muestra_lo_que_no_los_necesita():
    disco = interpretar(ejemplo("sin_permisos_windows_real"), "/dev/sdb")
    assert disco.falta_permiso and disco.estado == DESCONOCIDO and disco.modelo == ""
    assert "PowerShell" not in disco.error and "administrador" in disco.error

    completar_datos_basicos([disco], {"/dev/sdb": {
        "modelo": "Kingston XS1000", "capacidad": 1000204886016, "es_ssd": True, "interfaz": "USB"}})
    assert (disco.modelo, disco.capacidad, disco.es_ssd, disco.interfaz) == (
        "Kingston XS1000", 1000204886016, True, "USB")

    sano = interpretar(ejemplo("hdd_sano"))
    completar_datos_basicos([sano], {"/dev/sda": {"modelo": "OTRO"}})
    assert sano.modelo == "WDC WD10EZEX-08WN4A0"            # lo leído por SMART no se pisa


def test_datos_basicos_en_linux(tmp_path):
    for nombre, modelo, sectores, giratorio in (
        ("sda", "ST1000DM010", "1953525168", "1"), ("sdb", "Samsung SSD 860", "976773168", "0"),
        ("nvme0n1", "KIOXIA KBG50", "1000215216", "0"), ("loop0", "", "100", "1"),
    ):
        bloque = tmp_path / nombre
        (bloque / "device").mkdir(parents=True)
        (bloque / "queue").mkdir()
        (bloque / "device" / "model").write_text(modelo + "\n")
        (bloque / "size").write_text(sectores + "\n")
        (bloque / "queue" / "rotational").write_text(giratorio + "\n")
    discos = discos_fisicos._linux(tmp_path)
    assert set(discos) == {"/dev/sda", "/dev/sdb", "/dev/nvme0"}         # loop0 no es un disco
    assert discos["/dev/sda"] == {"modelo": "ST1000DM010", "capacidad": 1000204886016,
                                  "es_ssd": False, "interfaz": "SATA/USB"}
    assert discos["/dev/sdb"]["es_ssd"] is True and discos["/dev/nvme0"]["interfaz"] == "NVMe"
    assert discos_fisicos._linux(tmp_path / "no-existe") == {}


def test_datos_basicos_en_windows():
    class Proceso:
        stdout = ('[{"DeviceId":"1","FriendlyName":"Kingston XS1000","Size":1000204886016,'
                  '"MediaType":"Unspecified","BusType":"USB"},{"DeviceId":"0","FriendlyName":'
                  '"KBG50ZNT512G LS KIOXIA","Size":512110190592,"MediaType":"SSD","BusType":"NVMe"}]')

    discos = discos_fisicos._windows(lambda *a, **k: Proceso())
    assert discos["/dev/sda"] == {"modelo": "KBG50ZNT512G LS KIOXIA", "capacidad": 512110190592,
                                  "es_ssd": True, "interfaz": "NVMe"}
    assert discos["/dev/sdb"]["modelo"] == "Kingston XS1000" and discos["/dev/sdb"]["es_ssd"] is None

    def falla(*a, **k):
        raise OSError("no hay PowerShell")
    assert discos_fisicos._windows(falla) == {}


def test_encendidos_coincide_con_smartctl_y_avisa_si_no_es_creible():
    """El dato real: 105.975 encendidos en 5.729 horas. Es lo que dice el disco; se explica."""
    crudo = ejemplo("nvme_real_kioxia")
    disco = interpretar(crudo)
    assert disco.ciclos_encendido == crudo["nvme_smart_health_information_log"]["power_cycles"] == 105975
    assert disco.horas_encendido == 5729
    assert "reposo" in disco.nota_encendidos and disco.estado == BUENO      # no afecta a la salud
    assert disco.motivos == []
    # Un disco con una cifra normal no lleva ninguna nota.
    assert interpretar(ejemplo("hdd_sano")).nota_encendidos == ""           # 1.843 en 16.312 h
    assert interpretar(ejemplo("nvme_sano")).nota_encendidos == ""


# ------------------------------------------------------------ terminal

@pytest.fixture
def smart_con_un_disco_protegido(monkeypatch):
    falso = SmartctlFalso({"/dev/sda": "nvme_sano", "/dev/sdb": "sin_permisos_windows_real",
                           "/dev/nvme0": "ssd_sata"})
    monkeypatch.setattr(salud, "buscar_smartctl", lambda: "/usr/sbin/smartctl")
    monkeypatch.setattr(salud, "_ejecutar", falso)
    monkeypatch.setattr("core.discos_fisicos.info_basica", lambda: {
        "/dev/sdb": {"modelo": "Kingston XS1000", "capacidad": 1000204886016, "es_ssd": True, "interfaz": "USB"}})
    return falso


def test_cli_explica_como_dar_permisos(smart_con_un_disco_protegido, capsys):
    assert ejecutar(["salud"]) == 0
    salida = capsys.readouterr().out
    assert "Kingston XS1000" in salida and "931.5 GB" in salida      # lo que no necesita permisos
    assert "--elevar" in salida and "administrador" in salida
    assert "PowerShell" not in salida and "Cierra el programa" not in salida


def test_cli_no_menciona_permisos_si_no_hacen_falta(smart, capsys):
    assert ejecutar(["salud"]) == 0
    assert "--elevar" not in capsys.readouterr().out


@pytest.mark.parametrize("argumentos", [["salud", "--elevar"], ["salud", "ver", "--elevar"],
                                        ["salud", "--elevar", "ver"]])
def test_cli_salud_elevar(smart, capsys, monkeypatch, argumentos):
    pedidos = []
    monkeypatch.setattr("cli.comandos.leer_salud_con_permiso",
                        lambda umbrales: pedidos.append(1) or [interpretar(ejemplo("ssd_sata"), "/dev/sdb")])
    assert ejecutar(argumentos) == 0
    assert pedidos == [1] and "Samsung SSD 860 EVO" in capsys.readouterr().out


def test_cli_sin_elevar_no_pide_permisos(smart, monkeypatch):
    def prohibido(*a, **k):
        raise AssertionError("sin --elevar no se piden permisos")
    monkeypatch.setattr("cli.comandos.leer_salud_con_permiso", prohibido)
    assert ejecutar(["salud"]) == 0


def test_cli_cancelar_los_permisos(smart, capsys, monkeypatch):
    def cancelar(umbrales):
        raise PermisoCancelado(mensaje_cancelado(LINUX))
    monkeypatch.setattr("cli.comandos.leer_salud_con_permiso", cancelar)
    assert ejecutar(["salud", "--elevar"]) == 0                 # no es un fallo
    capturado = capsys.readouterr()
    assert "No pasa nada" in capturado.out and capturado.err == ""


def test_cli_ya_no_existe_el_comando_interno_volcar(smart):
    with pytest.raises(SystemExit):
        ejecutar(["salud", "volcar", "archivo.json"])


# ------------------------------------------------------------ web

@pytest.fixture
def web(monkeypatch):
    from web.app import crear_app
    from web.tareas import GestorEscaneo
    app = crear_app(GestorEscaneo())
    return app.test_client(), {"X-Token": app.config["TOKEN"]}


def test_web_muestra_el_disco_sin_pedir_permisos(web, smart_con_un_disco_protegido, monkeypatch):
    def prohibido(*a, **k):
        raise AssertionError("ver la salud nunca pide permisos")
    monkeypatch.setattr("web.app.leer_salud_con_permiso", prohibido)
    cliente, _ = web
    datos = cliente.get("/api/salud").get_json()
    protegido = datos["discos"][1]
    assert protegido["falta_permiso"] and protegido["modelo"] == "Kingston XS1000"
    assert "PowerShell" not in protegido["error"] and "No se escribe" in datos["explicacion"]


def test_web_dar_permiso(web, smart, monkeypatch):
    cliente, token = web
    monkeypatch.setattr("web.app.leer_salud_con_permiso",
                        lambda umbrales: [interpretar(ejemplo("hdd_sano"), "/dev/sda")])
    assert cliente.post("/api/salud/permiso").status_code == 403            # exige el token
    datos = cliente.post("/api/salud/permiso", headers=token).get_json()
    assert datos["cancelado"] is False and datos["discos"][0]["estado"] == "bueno"


def test_web_cancelar_el_permiso_no_es_un_error(web, smart, monkeypatch):
    cliente, token = web

    def cancelar(umbrales):
        raise PermisoCancelado(mensaje_cancelado(WINDOWS))
    monkeypatch.setattr("web.app.leer_salud_con_permiso", cancelar)
    respuesta = cliente.post("/api/salud/permiso", headers=token)
    assert respuesta.status_code == 200 and respuesta.get_json()["cancelado"] is True
    assert "No pasa nada" in respuesta.get_json()["mensaje"]


# ------------------------------------------------------------ autopruebas que exigen permisos

def smartctl_que_no_deja_probar(comando):
    """Como el SSD real: se lee sin permisos, pero la autoprueba da 'Error=5' (acceso denegado)."""
    if "--scan" in comando:
        return 0, json.dumps({"devices": [{"name": "/dev/sda", "type": "nvme"}]}), ""
    if "-t" in comando:
        return 4, json.dumps({"smartctl": {"exit_status": 4, "messages": [{"severity": "error", "string":
            "NVMe Self-test cmd with type=0x1, nsid=0xffffffff failed: "
            "IOCTL_STORAGE_PROTOCOL_COMMAND(NVMe) failed, Error=5"}]}}), ""
    return 0, json.dumps(ejemplo("nvme_sano")), ""


def test_la_autoprueba_puede_exigir_permisos_aunque_la_lectura_no(monkeypatch):
    from core.salud import FaltaPermiso, iniciar_autoprueba, leer_todos
    monkeypatch.setattr(salud, "buscar_smartctl", lambda: "/usr/sbin/smartctl")
    monkeypatch.setattr(salud, "_ejecutar", smartctl_que_no_deja_probar)
    assert leer_todos()[0].estado == BUENO                       # leer funciona sin permisos
    with pytest.raises(FaltaPermiso, match="autoprueba") as fallo:
        iniciar_autoprueba("/dev/sda", "corta")
    assert "Error=5" not in str(fallo.value) and "administrador" in str(fallo.value)


def test_los_botones_de_prueba_piden_permiso_si_hace_falta(monkeypatch):
    from core.privilegios import iniciar_autoprueba_pidiendo_permiso
    monkeypatch.setattr(salud, "buscar_smartctl", lambda: "/usr/sbin/smartctl")
    monkeypatch.setattr(salud, "_ejecutar", smartctl_que_no_deja_probar)
    pedidos = []

    def con_privilegios(comando):
        pedidos.append(comando[-3:])
        return 0, json.dumps({"ok": True, "datos": {"mensaje": "Autoprueba corta iniciada en /dev/sda."}})

    mensaje = iniciar_autoprueba_pidiendo_permiso("/dev/sda", "corta", lanzar=con_privilegios,
                                                  administrador=False)
    assert "iniciada" in mensaje and pedidos == [["iniciar-autoprueba", "/dev/sda", "corta"]]


def test_si_la_prueba_no_exige_permisos_no_se_piden(smart):
    from core.privilegios import iniciar_autoprueba_pidiendo_permiso

    def no_debe_llamarse(comando):
        raise AssertionError("este disco deja lanzar la prueba sin permisos")
    assert "iniciada" in iniciar_autoprueba_pidiendo_permiso("/dev/sda", "larga", lanzar=no_debe_llamarse,
                                                             administrador=False)


def test_cancelar_los_permisos_de_una_prueba(monkeypatch):
    from core.privilegios import iniciar_autoprueba_pidiendo_permiso
    monkeypatch.setattr(salud, "buscar_smartctl", lambda: "/usr/sbin/smartctl")
    monkeypatch.setattr(salud, "_ejecutar", smartctl_que_no_deja_probar)

    def cancelar(comando):
        raise PermisoCancelado(mensaje_cancelado(WINDOWS))
    with pytest.raises(PermisoCancelado, match="No pasa nada"):
        iniciar_autoprueba_pidiendo_permiso("/dev/sda", "corta", lanzar=cancelar, administrador=False)


def test_web_la_prueba_pide_permiso_y_cancelar_no_es_error(web, monkeypatch):
    cliente, token = web
    llamadas = []

    def falso(disco, tipo, elevar_ya=False):
        llamadas.append((disco, tipo, elevar_ya))
        if tipo == "larga":
            raise PermisoCancelado(mensaje_cancelado(WINDOWS))
        return "Autoprueba corta iniciada en /dev/sda."
    monkeypatch.setattr("web.app.iniciar_autoprueba_pidiendo_permiso", falso)

    correcta = cliente.post("/api/salud/prueba", json={"dispositivo": "/dev/sda", "tipo": "corta"}, headers=token)
    assert correcta.status_code == 200 and "iniciada" in correcta.get_json()["mensaje"]
    cancelada = cliente.post("/api/salud/prueba", headers=token,
                             json={"dispositivo": "/dev/sda", "tipo": "larga", "elevar": True})
    assert cancelada.status_code == 200 and cancelada.get_json()["cancelado"] is True
    assert llamadas == [("/dev/sda", "corta", False), ("/dev/sda", "larga", True)]


def test_cli_prueba_sin_elevar_explica_que_hacer(monkeypatch, capsys):
    monkeypatch.setattr(salud, "buscar_smartctl", lambda: "/usr/sbin/smartctl")
    monkeypatch.setattr(salud, "_ejecutar", smartctl_que_no_deja_probar)
    assert ejecutar(["salud", "prueba", "/dev/sda"]) == 1
    error = capsys.readouterr().err
    assert "autoprueba" in error and "--elevar" in error and "Error=5" not in error
