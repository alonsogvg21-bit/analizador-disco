"""Pruebas de la salud de los discos.

No dependen de ningún disco real ni de tener smartctl instalado: usan salidas
de ejemplo de 'smartctl --json' guardadas en tests/datos_smart/, y un ejecutor
falso que las devuelve según el comando recibido.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cli import comandos
from cli.comandos import ejecutar
from core import alertas as modulo_alertas
from core import salud as modulo_salud
from core.alertas import (
    VARIABLE_CLAVE, ConfigAlertas, detectar_alertas, enviar_correo, guardar_config, leer_config,
    notificar_escritorio, revisar,
)
from core.programador import NOMBRE_TAREA_SALUD, crear_tarea_salud
from core.salud import (
    BUENO, DESCONOCIDO, MALO, PRECAUCION, ErrorSalud, SmartctlNoInstalado, Umbrales,
    iniciar_autoprueba, instrucciones_de_instalacion, instrucciones_de_permisos, interpretar,
    leer_todos, listar_discos,
)
from tests.test_programador import CrontabFalso, SchtasksFalso
from utils.sistema import LINUX, WINDOWS

DATOS = Path(__file__).parent / "datos_smart"


def ejemplo(nombre: str) -> dict:
    return json.loads((DATOS / f"{nombre}.json").read_text(encoding="utf-8"))


def disco(nombre: str, **umbrales):
    return interpretar(ejemplo(nombre), umbrales=Umbrales(**umbrales))


class SmartctlFalso:
    """Devuelve una salida guardada según el disco que se consulte."""

    def __init__(self, discos: dict[str, str] | None = None):
        self.discos = discos or {"/dev/sda": "hdd_sano", "/dev/sdb": "ssd_sata", "/dev/nvme0": "nvme_sano"}
        self.comandos: list[list[str]] = []

    def __call__(self, comando):
        self.comandos.append(comando)
        assert comando[:2] == ["smartctl", "--json"]
        if "--scan" in comando:
            return 0, (DATOS / "scan.json").read_text(encoding="utf-8"), ""
        if "-t" in comando:
            return 0, (DATOS / "iniciar_prueba.json").read_text(encoding="utf-8"), ""
        datos = ejemplo(self.discos[comando[-1]])
        return datos["smartctl"]["exit_status"], json.dumps(datos), ""


# ------------------------------------------------------------ datos de cada disco

def test_disco_duro_sata_sano():
    d = disco("hdd_sano")
    assert (d.modelo, d.firmware, d.serie) == ("WDC WD10EZEX-08WN4A0", "01.01A01", "WD-WCC6Y0ABC123")
    assert d.capacidad == 1000204886016 and d.interfaz == "SATA 3.1, 6.0 Gb/s"
    assert d.es_ssd is False and d.es_nvme is False and d.smart_correcto is True
    assert (d.temperatura, d.horas_encendido, d.ciclos_encendido) == (33, 16312, 1843)
    assert (d.sectores_reasignados, d.sectores_pendientes, d.sectores_incorregibles) == (0, 0, 0)
    assert d.vida_restante is None                     # no es un SSD
    assert d.autoprueba.correcta is True and d.autoprueba.horas == 16300
    assert d.estado == BUENO and d.motivos == []


def test_ssd_sata():
    d = disco("ssd_sata")
    assert d.es_ssd is True and d.es_nvme is False
    assert d.vida_restante == 87 and d.autoprueba is None
    assert d.estado == BUENO


def test_nvme_sano():
    d = disco("nvme_sano")
    assert d.es_nvme and d.es_ssd and d.interfaz == "NVMe 1.3"
    assert (d.temperatura, d.horas_encendido, d.ciclos_encendido) == (38, 4211, 934)
    assert d.vida_restante == 97 and d.errores_de_medio == 0
    assert d.sectores_reasignados is None              # ese contador no existe en NVMe
    assert d.autoprueba.correcta is True
    assert d.estado == BUENO


# ------------------------------------------------------------ reglas del estado general

def test_sectores_reasignados_o_pendientes_es_precaucion():
    d = disco("hdd_reasignados")
    assert (d.sectores_reasignados, d.sectores_pendientes) == (24, 8)
    assert d.estado == PRECAUCION
    assert any("24 sectores reasignados" in m for m in d.motivos)
    assert any("8 sectores pendientes" in m for m in d.motivos)


def test_smart_fallido_es_malo():
    d = disco("hdd_fallando")
    assert d.smart_correcto is False and d.estado == MALO
    texto = " ".join(d.motivos)
    assert "SMART ha fallado" in texto
    assert "Reallocated_Sector_Ct" in texto            # atributo bajo su umbral
    assert "autoprueba terminó con error" in texto
    assert "2040 sectores reasignados" in texto        # también se listan los avisos menores


def test_aviso_critico_de_nvme_es_malo():
    d = disco("nvme_critico")
    assert d.estado == MALO and d.vida_restante == 0 and d.errores_de_medio == 12
    texto = " ".join(d.motivos)
    assert "aviso crítico" in texto and "0 % de vida" in texto and "12 errores de medio" in texto


def test_poca_vida_de_ssd():
    assert disco("ssd_sata_gastado").estado == PRECAUCION            # 12 %: entre 5 y 20
    assert disco("ssd_sata_gastado", vida_mala=15).estado == MALO     # con un umbral más estricto
    assert disco("ssd_sata_gastado", vida_precaucion=10).estado == BUENO


def test_temperatura_alta_es_precaucion():
    d = disco("hdd_caliente")
    assert d.temperatura == 58 and d.limite_temperatura == 55 and d.estado == PRECAUCION
    assert "Temperatura alta" in d.motivos[0]
    assert disco("hdd_caliente", temperatura=60).estado == BUENO      # límite personalizado


def test_limite_de_temperatura_automatico_segun_el_tipo():
    assert disco("hdd_sano").limite_temperatura == 55
    assert disco("nvme_sano").limite_temperatura == 70
    assert disco("nvme_sano", temperatura=35).estado == PRECAUCION    # 38 °C con límite 35


def test_autoprueba_en_curso():
    sata = disco("hdd_autoprueba_en_curso").autoprueba
    assert sata.en_curso and sata.porcentaje_restante == 90 and sata.correcta is None
    nvme = disco("nvme_autoprueba_en_curso").autoprueba
    assert nvme.en_curso and nvme.porcentaje_restante == 65
    assert disco("hdd_autoprueba_en_curso").estado == BUENO


# ------------------------------------------------------------ casos sin datos

@pytest.mark.parametrize("nombre", ["sin_permisos_linux", "sin_permisos_windows"])
def test_sin_permisos(nombre):
    d = interpretar(ejemplo(nombre), "/dev/sda")
    assert d.estado == DESCONOCIDO and "administrador" in d.error and d.dispositivo == "/dev/sda"


def test_disco_sin_smart():
    d = disco("usb_sin_smart")
    assert d.estado == DESCONOCIDO and "no ofrece datos SMART" in d.error
    assert d.modelo == "General USB Flash Disk" and d.capacidad == 32010928128


def test_instrucciones_por_sistema():
    assert "winget install smartmontools" in instrucciones_de_instalacion(WINDOWS)
    assert "sudo apt install smartmontools" in instrucciones_de_instalacion(LINUX)
    # Ya no se pide cerrar el programa ni abrir PowerShell: se ofrece --elevar.
    for sistema in (WINDOWS, LINUX):
        texto = instrucciones_de_permisos(sistema)
        assert "--elevar" in texto and "PowerShell" not in texto and "Cierra" not in texto
    assert "Control de cuentas" in instrucciones_de_permisos(WINDOWS)
    assert "sudo" in instrucciones_de_permisos(LINUX)


def test_smartctl_no_instalado(monkeypatch):
    monkeypatch.setattr(modulo_salud, "buscar_smartctl", lambda: None)
    with pytest.raises(SmartctlNoInstalado, match="smartmontools"):
        leer_todos()


def test_respuesta_ilegible():
    with pytest.raises(ErrorSalud, match="no se entiende"):
        listar_discos(lambda comando: (1, "esto no es JSON", ""))


# ------------------------------------------------------------ llamadas a smartctl

def test_leer_todos_solo_usa_comandos_de_lectura():
    falso = SmartctlFalso()
    discos = leer_todos(falso)

    assert [d.dispositivo for d in discos] == ["/dev/sda", "/dev/sdb", "/dev/nvme0"]
    assert [d.estado for d in discos] == [BUENO, BUENO, BUENO]
    assert falso.comandos[0] == ["smartctl", "--json", "--scan"]
    assert falso.comandos[1] == ["smartctl", "--json", "-a", "-d", "ata", "/dev/sda"]
    # Ninguna opción de smartctl que cambie la configuración del disco.
    prohibidas = {"-s", "--smart", "-o", "-S", "--set", "-t", "-X"}
    assert not any(prohibidas & set(comando) for comando in falso.comandos)


def test_un_disco_sin_permisos_no_impide_ver_los_demas():
    falso = SmartctlFalso({"/dev/sda": "sin_permisos_linux", "/dev/sdb": "ssd_sata",
                           "/dev/nvme0": "nvme_critico"})
    assert [d.estado for d in leer_todos(falso)] == [DESCONOCIDO, BUENO, MALO]


@pytest.mark.parametrize("tipo, opcion", [("corta", "short"), ("larga", "long")])
def test_iniciar_autoprueba(tipo, opcion):
    falso = SmartctlFalso()
    mensaje = iniciar_autoprueba("/dev/sda", tipo, falso)
    assert falso.comandos[-1] == ["smartctl", "--json", "-t", opcion, "-d", "ata", "/dev/sda"]
    assert "iniciada" in mensaje and "minutos" in mensaje


@pytest.mark.parametrize("nombre", ["/dev/sdz", "-X", "/dev/sda; rm -rf /", ""])
def test_autoprueba_solo_en_discos_detectados(nombre):
    falso = SmartctlFalso()
    with pytest.raises(ErrorSalud, match="No existe el disco"):
        iniciar_autoprueba(nombre, "corta", falso)
    assert not any("-t" in comando for comando in falso.comandos)


def test_autoprueba_tipo_invalido_o_rechazada():
    with pytest.raises(ErrorSalud, match="no válido"):
        iniciar_autoprueba("/dev/sda", "destructiva", SmartctlFalso())

    def sin_permisos(comando):
        if "--scan" in comando:
            return 0, (DATOS / "scan.json").read_text(encoding="utf-8"), ""
        return 2, (DATOS / "sin_permisos_windows.json").read_text(encoding="utf-8"), ""
    with pytest.raises(ErrorSalud, match="administrador"):
        iniciar_autoprueba("/dev/sda", "corta", sin_permisos)


# ------------------------------------------------------------ alertas

def test_alerta_solo_cuando_el_estado_cambia():
    sano, dudoso, roto = disco("hdd_sano"), disco("hdd_reasignados"), disco("hdd_fallando")
    for d in (dudoso, roto):
        d.serie = sano.serie  # el mismo disco en tres momentos

    alertas, memoria = detectar_alertas([sano], {})
    assert alertas == []                                   # un disco bueno no avisa

    alertas, memoria = detectar_alertas([dudoso], memoria)
    assert [a.estado for a in alertas] == [PRECAUCION] and "Precaución" in alertas[0].titulo
    assert "24 sectores reasignados" in alertas[0].texto

    alertas, memoria = detectar_alertas([dudoso], memoria)
    assert alertas == []                                   # sigue igual: no se repite

    alertas, memoria = detectar_alertas([roto], memoria)
    assert [a.estado for a in alertas] == [MALO]           # empeora: avisa otra vez

    alertas, memoria = detectar_alertas([sano], memoria)
    assert alertas == []                                   # mejorar no avisa...
    alertas, memoria = detectar_alertas([dudoso], memoria)
    assert len(alertas) == 1                               # ...pero si vuelve a empeorar, sí


def test_alerta_de_temperatura():
    alertas, memoria = detectar_alertas([disco("hdd_caliente")], {})
    assert len(alertas) == 1 and "58 °C" in alertas[0].texto
    assert detectar_alertas([disco("hdd_caliente")], memoria)[0] == []   # sigue caliente: una sola vez

    # Un disco ya en Precaución por sectores que además se calienta: avisa por la temperatura.
    dudoso = disco("hdd_reasignados")
    _, memoria = detectar_alertas([dudoso], {})
    alertas, _ = detectar_alertas([disco("hdd_reasignados", temperatura=40)], memoria)
    assert len(alertas) == 1 and "Temperatura alta" in alertas[0].titulo


def test_disco_sin_datos_no_genera_alertas_ni_borra_la_memoria():
    _, memoria = detectar_alertas([disco("hdd_reasignados")], {})
    alertas, nueva = detectar_alertas([interpretar(ejemplo("sin_permisos_linux"), "/dev/sda")], memoria)
    assert alertas == [] and nueva == memoria


def test_revisar_avisa_por_los_canales_activos():
    notificaciones, correos = [], []
    config = ConfigAlertas(correo_activo=True, smtp_servidor="smtp.ejemplo.com",
                           correo_de="a@ejemplo.com", correo_para="b@ejemplo.com")

    def notificar(titulo, texto):
        notificaciones.append(titulo)
        return True

    primera = revisar([disco("hdd_reasignados"), disco("nvme_critico"), disco("ssd_sata")], config,
                      notificar=notificar, correo=lambda c, asunto, cuerpo: correos.append((asunto, cuerpo)))
    assert len(primera.alertas) == 2 and len(notificaciones) == 2 and primera.fallos_de_envio == []
    assert len(correos) == 1 and "2 avisos" in correos[0][0] and "aviso crítico" in correos[0][1]

    # La memoria queda guardada: una segunda revisión idéntica no avisa.
    segunda = revisar([disco("hdd_reasignados"), disco("nvme_critico")], config,
                      notificar=notificar, correo=lambda *a: correos.append(a))
    assert segunda.alertas == [] and len(notificaciones) == 2 and len(correos) == 1


def test_revisar_respeta_los_canales_desactivados_y_no_se_rompe_si_fallan():
    llamadas = []
    revisar([disco("hdd_reasignados")], ConfigAlertas(escritorio=False),
            notificar=lambda *a: llamadas.append(a), correo=lambda *a: llamadas.append(a))
    assert llamadas == []

    def correo_roto(*_):
        raise OSError("servidor inalcanzable")
    resultado = revisar([disco("nvme_critico")], ConfigAlertas(correo_activo=True),
                        notificar=lambda *a: False, correo=correo_roto)
    assert len(resultado.alertas) == 1 and len(resultado.fallos_de_envio) == 2
    assert "servidor inalcanzable" in resultado.fallos_de_envio[1]


def test_configuracion_se_guarda_sin_contrasena(datos_aislados):
    assert leer_config() == ConfigAlertas()
    guardar_config(ConfigAlertas(temperatura_limite=50, correo_activo=True, smtp_usuario="ana"))
    assert leer_config().temperatura_limite == 50 and leer_config().umbrales().temperatura == 50
    guardado = (datos_aislados / "alertas.json").read_text(encoding="utf-8")
    assert "clave" not in guardado and "password" not in guardado.lower()


class SmtpFalso:
    instancias: list["SmtpFalso"] = []

    def __init__(self, servidor, puerto, timeout=None):
        self.servidor, self.puerto, self.pasos, self.mensaje = servidor, puerto, [], None
        SmtpFalso.instancias.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def starttls(self, context=None):
        self.pasos.append("tls")

    def login(self, usuario, clave):
        self.pasos.append(("login", usuario, clave))

    def send_message(self, mensaje):
        self.mensaje = mensaje


def test_enviar_correo(monkeypatch):
    config = ConfigAlertas(correo_activo=True, smtp_servidor="smtp.ejemplo.com", smtp_puerto=587,
                           smtp_usuario="ana", correo_de="a@ejemplo.com", correo_para="b@ejemplo.com")
    monkeypatch.delenv(VARIABLE_CLAVE, raising=False)
    with pytest.raises(ValueError, match=VARIABLE_CLAVE):
        enviar_correo(config, "Asunto", "Cuerpo", cliente=SmtpFalso)

    monkeypatch.setenv(VARIABLE_CLAVE, "secreto")
    enviar_correo(config, "Disco en estado Malo", "Hay 12 errores.", cliente=SmtpFalso)
    enviado = SmtpFalso.instancias[-1]
    assert (enviado.servidor, enviado.puerto) == ("smtp.ejemplo.com", 587)
    assert enviado.pasos == ["tls", ("login", "ana", "secreto")]       # cifrado antes de la contraseña
    assert enviado.mensaje["To"] == "b@ejemplo.com" and "Malo" in enviado.mensaje["Subject"]

    with pytest.raises(ValueError, match="destinatario"):
        enviar_correo(ConfigAlertas(smtp_servidor="x", correo_de="a@x"), "a", "b", cliente=SmtpFalso)


def test_notificacion_de_escritorio_no_mete_el_texto_en_el_comando():
    llamadas = []

    class Proceso:
        returncode = 0

    def falso(comando, **opciones):
        llamadas.append((comando, opciones))
        return Proceso()

    peligroso = "'; Remove-Item C:\\ -Recurse; '"
    assert notificar_escritorio("Título", peligroso, sistema=WINDOWS, ejecutar=falso) is True
    comando, opciones = llamadas[0]
    assert comando[0] == "powershell" and peligroso not in " ".join(comando)
    assert opciones["env"]["AD_TEXTO"] == peligroso

    assert notificar_escritorio("Título", "Texto", sistema=LINUX, ejecutar=falso) is True
    assert llamadas[1][0][0] == "notify-send" and llamadas[1][0][-2:] == ["Título", "Texto"]
    assert notificar_escritorio("a", "b", sistema="otro", ejecutar=falso) is False

    def no_existe(comando, **opciones):
        raise FileNotFoundError
    assert notificar_escritorio("a", "b", sistema=LINUX, ejecutar=no_existe) is False


# ------------------------------------------------------------ revisión programada

def test_programar_revision_de_salud():
    falso = SchtasksFalso()
    tarea = crear_tarea_salud("diaria", "08:00", sistema=WINDOWS, ejecutar=falso)
    comando = falso.comandos[0]
    assert tarea.nombre == NOMBRE_TAREA_SALUD and comando[-2:] == ["/RL", "HIGHEST"]
    lanzador = Path(comando[comando.index("/TR") + 1].strip('"'))
    assert "cli salud revisar" in lanzador.read_text(encoding="utf-8")

    cron = CrontabFalso()
    crear_tarea_salud("semanal", "07:30", sistema=LINUX, ejecutar=cron)
    assert cron.contenido.startswith("30 7 * * 1 ") and "salud revisar" in cron.contenido


# ------------------------------------------------------------ terminal

@pytest.fixture
def smart_falso(monkeypatch):
    falso = SmartctlFalso({"/dev/sda": "hdd_reasignados", "/dev/sdb": "ssd_sata",
                           "/dev/nvme0": "nvme_sano"})
    monkeypatch.setattr(modulo_salud, "_ejecutar", falso)
    return falso


def test_cli_salud(smart_falso, capsys):
    assert ejecutar(["salud"]) == 0
    salida = capsys.readouterr().out
    assert "WDC WD10EZEX-08WN4A0" in salida and "[PRECAUCIÓN]" in salida and "[BUENO]" in salida
    assert "Sectores reasignados: 24" in salida and "Vida restante del SSD" in salida
    assert "Hay 24 sectores reasignados" in salida


def test_cli_salud_sin_smartctl(monkeypatch, capsys):
    monkeypatch.setattr(modulo_salud, "buscar_smartctl", lambda: None)
    assert ejecutar(["salud"]) == 1
    assert "smartmontools" in capsys.readouterr().err


def test_cli_salud_prueba(smart_falso, capsys):
    assert ejecutar(["salud", "prueba", "/dev/sda", "--tipo", "larga"]) == 0
    assert "Autoprueba larga iniciada" in capsys.readouterr().out
    assert ejecutar(["salud", "prueba", "/dev/sdz"]) == 1


def test_cli_salud_revisar_avisa_una_sola_vez(smart_falso, capsys, monkeypatch):
    avisos = []
    monkeypatch.setattr(modulo_alertas, "notificar_escritorio", lambda t, x: avisos.append(t) or True)
    monkeypatch.setattr(comandos, "revisar_alertas",
                        lambda discos, config: revisar(discos, config, notificar=modulo_alertas.notificar_escritorio))
    assert ejecutar(["salud", "revisar"]) == 0
    assert "Alertas nuevas: 1" in capsys.readouterr().out and len(avisos) == 1
    assert ejecutar(["salud", "revisar"]) == 0
    assert "Alertas nuevas: 0" in capsys.readouterr().out and len(avisos) == 1


def test_cli_salud_alertas(capsys):
    assert ejecutar(["salud", "alertas"]) == 0
    assert "automático" in capsys.readouterr().out

    assert ejecutar(["salud", "alertas", "--temperatura", "50", "--correo", "si",
                     "--smtp-servidor", "smtp.ejemplo.com", "--correo-de", "a@ejemplo.com",
                     "--correo-para", "b@ejemplo.com", "--escritorio", "no"]) == 0
    salida = capsys.readouterr().out
    assert "50 °C" in salida and "smtp.ejemplo.com:587" in salida and VARIABLE_CLAVE in salida
    config = leer_config()
    assert (config.temperatura_limite, config.correo_activo, config.escritorio) == (50, True, False)

    assert ejecutar(["salud", "alertas", "--temperatura", "auto"]) == 0
    assert leer_config().temperatura_limite is None and leer_config().correo_activo is True
    with pytest.raises(SystemExit):
        ejecutar(["salud", "alertas", "--temperatura", "500"])


# ------------------------------------------------------------ salidas reales (smartctl 7.5 en Windows 11)

def test_salida_real_sin_permisos_en_windows():
    """Sin administrador, smartctl en Windows solo dice 'Open failed, Error=5'."""
    d = interpretar(ejemplo("sin_permisos_windows_real"), "/dev/sdb")
    assert d.estado == DESCONOCIDO and "administrador" in d.error


def test_salida_real_de_un_nvme():
    d = disco("nvme_real_kioxia")
    assert d.modelo == "KBG50ZNT512G LS KIOXIA" and d.es_nvme and d.interfaz == "NVMe 1.4"
    assert d.smart_correcto is True and d.vida_restante == 82 and d.errores_de_medio == 0
    assert d.horas_encendido == 5729 and d.autoprueba is None   # nunca se ha hecho una autoprueba
    assert d.estado == BUENO
