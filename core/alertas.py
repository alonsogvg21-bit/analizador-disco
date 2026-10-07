"""Alertas de salud: notificación de escritorio y correo opcional.

Se avisa cuando un disco pasa a Precaución o Malo, o cuando su temperatura
alcanza el límite. Para no repetir el mismo aviso en cada revisión, se guarda
el último estado conocido de cada disco y solo se avisa de los CAMBIOS.

La contraseña del correo nunca se guarda en disco: se lee de la variable de
entorno ANALIZADOR_DISCO_SMTP_CLAVE.
"""

from __future__ import annotations

import json
import os
import smtplib
import ssl
import subprocess
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, fields
from email.message import EmailMessage
from pathlib import Path

from core.historial import carpeta_de_datos
from core.salud import GRAVEDAD, MALO, NOMBRES_ESTADO, PRECAUCION, SaludDisco, Umbrales
from utils.sistema import LINUX, WINDOWS, sistema_actual

VARIABLE_CLAVE = "ANALIZADOR_DISCO_SMTP_CLAVE"


@dataclass(slots=True)
class ConfigAlertas:
    escritorio: bool = True
    # None = automático (55 °C en SATA, 70 °C en NVMe).
    temperatura_limite: int | None = None
    correo_activo: bool = False
    smtp_servidor: str = ""
    smtp_puerto: int = 587
    smtp_usuario: str = ""
    smtp_tls: bool = True
    correo_de: str = ""
    correo_para: str = ""

    def umbrales(self) -> Umbrales:
        return Umbrales(temperatura=self.temperatura_limite)


@dataclass(slots=True)
class Alerta:
    disco: str
    estado: str
    titulo: str
    texto: str


@dataclass(slots=True)
class ResultadoRevision:
    alertas: list[Alerta]
    # Problemas al avisar (correo mal configurado, etc.). No impiden la revisión.
    fallos_de_envio: list[str]


# ---------------------------------------------------------------- configuración y memoria

def _archivo(nombre: str) -> Path:
    return carpeta_de_datos() / nombre


def leer_config() -> ConfigAlertas:
    try:
        guardado = json.loads(_archivo("alertas.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ConfigAlertas()
    conocidos = {campo.name for campo in fields(ConfigAlertas)}
    return ConfigAlertas(**{k: v for k, v in guardado.items() if k in conocidos})


def guardar_config(config: ConfigAlertas) -> None:
    archivo = _archivo("alertas.json")
    archivo.parent.mkdir(parents=True, exist_ok=True)
    archivo.write_text(json.dumps(asdict(config), ensure_ascii=False, indent=2), encoding="utf-8")


def _leer_memoria() -> dict:
    try:
        return json.loads(_archivo("salud_estado.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _guardar_memoria(memoria: dict) -> None:
    archivo = _archivo("salud_estado.json")
    archivo.parent.mkdir(parents=True, exist_ok=True)
    archivo.write_text(json.dumps(memoria, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------- decidir qué avisar

def detectar_alertas(discos: Iterable[SaludDisco], memoria: dict) -> tuple[list[Alerta], dict]:
    """Compara con la revisión anterior y devuelve (alertas nuevas, memoria actualizada).

    Se avisa si:
      - el estado empeora hasta Precaución o Malo (o ya lo estaba la primera vez que se ve), o
      - la temperatura alcanza el límite y en la revisión anterior no lo alcanzaba.
    Un disco que sigue igual que la última vez no vuelve a avisar.
    """
    alertas: list[Alerta] = []
    nueva = dict(memoria)

    for disco in discos:
        if disco.error:
            continue  # sin datos no se puede decir nada; se conserva lo anterior
        previo = memoria.get(disco.clave, {})
        caliente = (disco.temperatura is not None and disco.limite_temperatura is not None
                    and disco.temperatura >= disco.limite_temperatura)

        empeora = (disco.estado in (PRECAUCION, MALO)
                   and GRAVEDAD[disco.estado] > GRAVEDAD.get(previo.get("estado", ""), 0))
        se_calienta = caliente and not previo.get("caliente", False)

        if empeora or se_calienta:
            nombre = disco.modelo or disco.dispositivo
            titulo = (f"Disco en estado {NOMBRES_ESTADO[disco.estado]}: {nombre}" if empeora
                      else f"Temperatura alta en el disco {nombre}")
            texto = " ".join(disco.motivos) or f"{disco.temperatura} °C"
            alertas.append(Alerta(disco.clave, disco.estado, titulo, texto))

        nueva[disco.clave] = {"estado": disco.estado, "caliente": caliente,
                              "modelo": disco.modelo, "dispositivo": disco.dispositivo}
    return alertas, nueva


# ---------------------------------------------------------------- canales de aviso

# Notificación de Windows. El título y el texto se pasan por variables de
# entorno, no dentro del comando, para que su contenido nunca se ejecute.
_TOAST_WINDOWS = r"""
$ErrorActionPreference = 'Stop'
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
$xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$textos = $xml.GetElementsByTagName('text')
$textos.Item(0).AppendChild($xml.CreateTextNode($env:AD_TITULO)) | Out-Null
$textos.Item(1).AppendChild($xml.CreateTextNode($env:AD_TEXTO)) | Out-Null
$app = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show([Windows.UI.Notifications.ToastNotification]::new($xml))
"""


def notificar_escritorio(titulo: str, texto: str, sistema: str | None = None,
                         ejecutar: Callable[..., object] = subprocess.run) -> bool:
    """Muestra una notificación del sistema. Devuelve False si no se pudo."""
    sistema = sistema or sistema_actual()
    try:
        if sistema == WINDOWS:
            entorno = {**os.environ, "AD_TITULO": titulo, "AD_TEXTO": texto[:250]}
            proceso = ejecutar(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", _TOAST_WINDOWS],
                env=entorno, capture_output=True, timeout=30)
        elif sistema == LINUX:
            proceso = ejecutar(
                ["notify-send", "--urgency=critical", "--app-name=Analizador de disco",
                 titulo, texto],
                capture_output=True, timeout=30)
        else:
            return False
    except (OSError, subprocess.SubprocessError):
        return False
    return getattr(proceso, "returncode", 1) == 0


def enviar_correo(config: ConfigAlertas, asunto: str, cuerpo: str,
                  cliente: Callable[..., smtplib.SMTP] = smtplib.SMTP) -> None:
    """Envía un correo por SMTP. Lanza ValueError si falta configuración u OSError si falla el envío."""
    faltan = [nombre for nombre, valor in (
        ("servidor SMTP", config.smtp_servidor), ("remitente", config.correo_de),
        ("destinatario", config.correo_para)) if not valor]
    if faltan:
        raise ValueError("Falta configurar: " + ", ".join(faltan) + ".")

    mensaje = EmailMessage()
    mensaje["Subject"] = asunto
    mensaje["From"] = config.correo_de
    mensaje["To"] = config.correo_para
    mensaje.set_content(cuerpo)

    with cliente(config.smtp_servidor, config.smtp_puerto, timeout=30) as servidor:
        if config.smtp_tls:
            servidor.starttls(context=ssl.create_default_context())
        if config.smtp_usuario:
            clave = os.environ.get(VARIABLE_CLAVE)
            if not clave:
                raise ValueError(
                    f"Falta la contraseña del correo: defínela en la variable de entorno {VARIABLE_CLAVE}.")
            servidor.login(config.smtp_usuario, clave)
        servidor.send_message(mensaje)


# ---------------------------------------------------------------- revisión completa

def revisar(
    discos: Iterable[SaludDisco],
    config: ConfigAlertas | None = None,
    notificar: Callable[[str, str], bool] = notificar_escritorio,
    correo: Callable[[ConfigAlertas, str, str], None] = enviar_correo,
) -> ResultadoRevision:
    """Detecta cambios respecto a la última revisión y avisa por los canales activos."""
    config = config or leer_config()
    alertas, memoria = detectar_alertas(discos, _leer_memoria())
    _guardar_memoria(memoria)
    fallos: list[str] = []

    if alertas and config.escritorio:
        for alerta in alertas:
            if not notificar(alerta.titulo, alerta.texto):
                fallos.append("No se pudo mostrar la notificación de escritorio.")
                break

    if alertas and config.correo_activo:
        asunto = ("Analizador de disco: " + alertas[0].titulo if len(alertas) == 1
                  else f"Analizador de disco: {len(alertas)} avisos de salud de discos")
        cuerpo = "\n\n".join(f"{a.titulo}\n{a.texto}" for a in alertas)
        try:
            correo(config, asunto, cuerpo)
        except (ValueError, OSError, smtplib.SMTPException) as problema:
            fallos.append(f"No se pudo enviar el correo: {problema}")

    return ResultadoRevision(alertas, fallos)
