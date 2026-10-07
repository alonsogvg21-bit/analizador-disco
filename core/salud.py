"""Salud de los discos con SMART.

SMART es un sistema de autodiagnóstico que llevan los propios discos: van
anotando contadores (horas encendido, sectores dañados, temperatura, desgaste)
y este módulo solo los LEE mediante el programa smartctl (smartmontools).
Nada de lo que hay aquí escribe datos en el disco.

Las reglas del estado general están en evaluar_estado(), una por línea.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from utils.sistema import WINDOWS, sistema_actual

BUENO = "bueno"
PRECAUCION = "precaucion"
MALO = "malo"
DESCONOCIDO = "desconocido"

NOMBRES_ESTADO = {
    BUENO: "Bueno", PRECAUCION: "Precaución", MALO: "Malo", DESCONOCIDO: "Sin datos",
}
# De menos a más grave, para comparar estados.
GRAVEDAD = {DESCONOCIDO: 0, BUENO: 1, PRECAUCION: 2, MALO: 3}

TIPOS_DE_PRUEBA = {"corta": "short", "larga": "long"}
# Más encendidos por hora de uso que esto no puede ser "encender el equipo".
ENCENDIDOS_POR_HORA_CREIBLES = 2

# Identificadores de los atributos SMART de discos SATA que se consultan.
ATR_REASIGNADOS = 5       # sectores dañados que el disco sustituyó por otros de reserva
ATR_PENDIENTES = 197      # sectores dudosos, a la espera de ser reasignados
ATR_INCORREGIBLES = 198   # sectores que no se pudieron leer ni corregir
# Atributos con los que cada fabricante de SSD SATA indica la vida restante.
# En todos, el valor normalizado baja de 100 (nuevo) hacia 0 (agotado).
ATR_VIDA_SSD = (231, 169, 202, 233, 177)

# Bits del código de salida de smartctl.
_SALIDA_NO_ABRE = 0b10

# ejecutar(comando) -> (código de salida, salida, error)
Ejecutor = Callable[[list[str]], "tuple[int, str, str]"]


class ErrorSalud(Exception):
    """No se pudo consultar la salud de los discos."""


class SmartctlNoInstalado(ErrorSalud):
    def __init__(self) -> None:
        super().__init__(instrucciones_de_instalacion())


@dataclass(slots=True)
class Umbrales:
    """Límites que deciden cuándo avisar. Se pueden cambiar desde la configuración de alertas."""
    # None = automático: 55 °C en discos SATA y 70 °C en NVMe, que trabajan más calientes.
    temperatura: int | None = None
    vida_precaucion: int = 20   # % de vida restante de un SSD
    vida_mala: int = 5

    def temperatura_para(self, es_nvme: bool) -> int:
        if self.temperatura is not None:
            return self.temperatura
        return 70 if es_nvme else 55


@dataclass(slots=True)
class Autoprueba:
    """Última autoprueba del disco (o la que está en marcha)."""
    tipo: str = ""
    resultado: str = ""
    correcta: bool | None = None       # None = en curso o desconocido
    en_curso: bool = False
    porcentaje_restante: int | None = None
    horas: int | None = None           # horas de uso que tenía el disco al hacerla


@dataclass(slots=True)
class SaludDisco:
    dispositivo: str
    modelo: str = ""
    serie: str = ""
    firmware: str = ""
    capacidad: int = 0                 # bytes
    interfaz: str = ""
    es_ssd: bool | None = None
    es_nvme: bool = False
    smart_correcto: bool | None = None  # veredicto del propio disco
    temperatura: int | None = None      # °C
    limite_temperatura: int | None = None
    horas_encendido: int | None = None
    ciclos_encendido: int | None = None
    sectores_reasignados: int | None = None
    sectores_pendientes: int | None = None
    sectores_incorregibles: int | None = None
    errores_de_medio: int | None = None  # solo NVMe
    vida_restante: int | None = None     # % (solo SSD)
    autoprueba: Autoprueba | None = None
    estado: str = DESCONOCIDO
    motivos: list[str] = field(default_factory=list)
    error: str = ""                      # por qué no hay datos, si no los hay
    falta_permiso: bool = False          # no se pudo leer por no ser administrador
    nota_encendidos: str = ""            # aclaración si el contador de encendidos no es fiable

    @property
    def clave(self) -> str:
        """Identificador estable del disco (el número de serie no cambia aunque cambie la letra)."""
        return self.serie or self.dispositivo


# ---------------------------------------------------------------- mensajes de ayuda

def instrucciones_de_instalacion(sistema: str | None = None) -> str:
    if (sistema or sistema_actual()) == WINDOWS:
        return (
            "Falta el programa smartctl (smartmontools). Para instalarlo en Windows:\n"
            "  1. Abre PowerShell y ejecuta:  winget install smartmontools.smartmontools\n"
            "     (o descarga el instalador desde https://www.smartmontools.org)\n"
            "  2. Cierra y vuelve a abrir la terminal para que se reconozca el comando.")
    return (
        "Falta el programa smartctl (smartmontools). Para instalarlo en Linux:\n"
        "  Debian / Ubuntu / Mint:  sudo apt install smartmontools\n"
        "  Fedora / RHEL:           sudo dnf install smartmontools\n"
        "  Arch / Manjaro:          sudo pacman -S smartmontools")


FALTA_PERMISO = "Para leer la salud de este disco el sistema exige permisos de administrador."


def instrucciones_de_permisos(sistema: str | None = None) -> str:
    """Cómo conseguir los permisos desde la terminal. (En el escritorio y la web hay un botón.)"""
    if (sistema or sistema_actual()) == WINDOWS:
        return ("Algunos discos exigen permisos de administrador. Añade --elevar para que "
                "Windows te los pida (verás el aviso de Control de cuentas de usuario):\n"
                "    salud --elevar")
    return ("Algunos discos exigen permisos de administrador. Añade --elevar para que el "
            "sistema te pida la contraseña, o ejecuta el comando con sudo:\n"
            "    salud --elevar")


# ---------------------------------------------------------------- llamar a smartctl

def buscar_smartctl() -> str | None:
    """Ruta ABSOLUTA de smartctl, o None si no está instalado.

    Se devuelve siempre la ruta completa para que nunca se ejecute, por error
    o por engaño, otro programa llamado igual que esté en la carpeta actual.
    """
    encontrado = shutil.which("smartctl")
    if encontrado:
        return os.path.abspath(encontrado)
    candidatos = [
        # El instalador de Windows no siempre añade la carpeta al PATH.
        Path(base) / "smartmontools" / "bin" / "smartctl.exe"
        for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")) if base
    ] + [
        # En Linux suele estar en sbin, que no siempre está en el PATH de un usuario normal.
        Path("/usr/sbin/smartctl"), Path("/usr/local/sbin/smartctl"), Path("/sbin/smartctl"),
    ]
    for candidato in candidatos:
        if candidato.is_file():
            return str(candidato)
    return None


def _ejecutar(comando: list[str]) -> tuple[int, str, str]:
    programa = buscar_smartctl()
    if programa is None:
        raise SmartctlNoInstalado()
    try:
        proceso = subprocess.run(
            [programa, *comando[1:]], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=60)
    except subprocess.TimeoutExpired:
        raise ErrorSalud("smartctl tardó demasiado en responder.") from None
    return proceso.returncode, proceso.stdout, proceso.stderr


def _consultar(argumentos: list[str], ejecutar: Ejecutor | None) -> dict:
    """Ejecuta 'smartctl --json ...' y devuelve su respuesta como diccionario."""
    _, salida, fallo = (ejecutar or _ejecutar)(["smartctl", "--json", *argumentos])
    try:
        return json.loads(salida)
    except ValueError:
        raise ErrorSalud(
            f"smartctl devolvió una respuesta que no se entiende: {(fallo or salida).strip()[:200]}"
        ) from None


def _mensajes(datos: dict) -> str:
    return " ".join(m.get("string", "") for m in datos.get("smartctl", {}).get("messages", []))


def _sin_permisos(datos: dict) -> bool:
    texto = _mensajes(datos).lower()
    # En Windows smartctl solo da el número: "Open failed, Error=5" (5 = acceso denegado).
    if texto.rstrip(". ").endswith("error=5"):
        return True
    return any(pista in texto for pista in (
        "permission denied", "access is denied", "acceso denegado", "operation not permitted",
        "requires admin", "administrator"))


# ---------------------------------------------------------------- interpretar la respuesta

def _atributo(datos: dict, identificador: int) -> dict | None:
    for atributo in datos.get("ata_smart_attributes", {}).get("table", []):
        if atributo.get("id") == identificador:
            return atributo
    return None


def _valor_bruto(datos: dict, identificador: int) -> int | None:
    """El contador real de un atributo (por ejemplo, cuántos sectores)."""
    atributo = _atributo(datos, identificador)
    return atributo["raw"]["value"] if atributo else None


def _interfaz(datos: dict) -> str:
    protocolo = datos.get("device", {}).get("protocol", "")
    if protocolo == "NVMe":
        version = datos.get("nvme_version", {}).get("string", "")
        return f"NVMe {version}".strip()
    if protocolo == "ATA":
        partes = [datos.get("sata_version", {}).get("string", "") or "SATA",
                  datos.get("interface_speed", {}).get("current", {}).get("string", "")]
        return ", ".join(p for p in partes if p)
    return protocolo or datos.get("device", {}).get("type", "")


def _autoprueba(datos: dict) -> Autoprueba | None:
    # --- NVMe ---
    registro = datos.get("nvme_self_test_log")
    if registro:
        en_marcha = registro.get("current_self_test_operation", {})
        if en_marcha.get("value", 0):
            completado = registro.get("current_self_test_completion_percent", 0)
            return Autoprueba(tipo=en_marcha.get("string", ""), resultado="En curso",
                              en_curso=True, porcentaje_restante=100 - completado)
        tabla = registro.get("table", [])
        if tabla:
            ultima = tabla[0]
            codigo = ultima.get("self_test_result", {}).get("value")
            return Autoprueba(
                tipo=ultima.get("self_test_code", {}).get("string", ""),
                resultado=ultima.get("self_test_result", {}).get("string", ""),
                correcta=codigo == 0 if codigo is not None else None,
                horas=ultima.get("power_on_hours"))
        return None

    # --- SATA ---
    actual = datos.get("ata_smart_data", {}).get("self_test", {}).get("status", {})
    if "remaining_percent" in actual:
        return Autoprueba(resultado="En curso", en_curso=True,
                          porcentaje_restante=actual["remaining_percent"])
    tabla = datos.get("ata_smart_self_test_log", {}).get("standard", {}).get("table", [])
    if tabla:
        ultima = tabla[0]
        estado = ultima.get("status", {})
        return Autoprueba(
            tipo=ultima.get("type", {}).get("string", ""),
            resultado=estado.get("string", ""),
            correcta=estado.get("passed"),
            horas=ultima.get("lifetime_hours"))
    return None


def evaluar_estado(disco: SaludDisco, datos: dict, umbrales: Umbrales) -> tuple[str, list[str]]:
    """Decide el estado general. Devuelve (estado, motivos).

    MALO (hay que copiar los datos y cambiar el disco):
      - El propio disco declara que SMART ha fallado.
      - Algún atributo está por debajo de su umbral de fallo ahora mismo.
      - Un NVMe tiene activado algún aviso crítico.
      - La última autoprueba terminó con error.
      - A un SSD le queda un 5 % de vida o menos.
    PRECAUCIÓN (funciona, pero conviene vigilarlo y tener copia):
      - Hay sectores reasignados, pendientes o incorregibles (más de 0).
      - Un NVMe ha registrado errores de medio (más de 0).
      - A un SSD le queda un 20 % de vida o menos.
      - La temperatura alcanza el límite configurado.
    BUENO: nada de lo anterior.
    """
    malo: list[str] = []
    precaucion: list[str] = []

    if disco.smart_correcto is False:
        malo.append("El disco informa de que su autodiagnóstico SMART ha fallado.")
    fallando = [a.get("name", "") for a in datos.get("ata_smart_attributes", {}).get("table", [])
                if a.get("when_failed") == "now"]
    if fallando:
        malo.append("Atributos por debajo de su umbral de fallo: " + ", ".join(fallando) + ".")
    if datos.get("nvme_smart_health_information_log", {}).get("critical_warning", 0):
        malo.append("El disco NVMe tiene activado un aviso crítico.")
    if disco.autoprueba and disco.autoprueba.correcta is False:
        malo.append(f"La última autoprueba terminó con error: {disco.autoprueba.resultado}.")

    if disco.vida_restante is not None:
        if disco.vida_restante <= umbrales.vida_mala:
            malo.append(f"Al SSD le queda solo un {disco.vida_restante} % de vida.")
        elif disco.vida_restante <= umbrales.vida_precaucion:
            precaucion.append(f"Al SSD le queda un {disco.vida_restante} % de vida.")

    for cantidad, nombre in (
        (disco.sectores_reasignados, "sectores reasignados"),
        (disco.sectores_pendientes, "sectores pendientes de reasignar"),
        (disco.sectores_incorregibles, "sectores incorregibles"),
        (disco.errores_de_medio, "errores de medio"),
    ):
        if cantidad:
            precaucion.append(f"Hay {cantidad} {nombre}.")

    if disco.temperatura is not None and disco.temperatura >= disco.limite_temperatura:
        precaucion.append(
            f"Temperatura alta: {disco.temperatura} °C (límite {disco.limite_temperatura} °C).")

    if malo:
        return MALO, malo + precaucion
    if precaucion:
        return PRECAUCION, precaucion
    return BUENO, []


def interpretar(datos: dict, dispositivo: str = "", umbrales: Umbrales | None = None) -> SaludDisco:
    """Convierte la respuesta JSON de 'smartctl -a' en un SaludDisco. No ejecuta nada."""
    umbrales = umbrales or Umbrales()
    disco = SaludDisco(dispositivo=dispositivo or datos.get("device", {}).get("name", ""))

    tiene_smart = any(clave in datos for clave in (
        "ata_smart_attributes", "nvme_smart_health_information_log", "smart_status"))
    if not tiene_smart:
        codigo = datos.get("smartctl", {}).get("exit_status", 0)
        if _sin_permisos(datos):
            disco.error = FALTA_PERMISO
            disco.falta_permiso = True
        elif codigo & _SALIDA_NO_ABRE:
            disco.error = "No se pudo abrir el disco: " + (_mensajes(datos) or "sin más detalles") + "."
        else:
            disco.error = ("Este disco no ofrece datos SMART (suele pasar con memorias USB y "
                           "algunas cajas externas).")
        # Aun sin SMART, a veces se conoce el modelo.
        disco.modelo = datos.get("model_name", "")
        disco.capacidad = datos.get("user_capacity", {}).get("bytes", 0)
        return disco

    nvme = datos.get("nvme_smart_health_information_log", {})
    disco.es_nvme = bool(nvme) or datos.get("device", {}).get("protocol") == "NVMe"
    disco.modelo = datos.get("model_name", "")
    disco.serie = datos.get("serial_number", "")
    disco.firmware = datos.get("firmware_version", "")
    disco.capacidad = datos.get("user_capacity", {}).get("bytes", 0)
    disco.interfaz = _interfaz(datos)
    # rotation_rate 0 = sin partes giratorias, es decir, SSD.
    if disco.es_nvme:
        disco.es_ssd = True
    elif "rotation_rate" in datos:
        disco.es_ssd = datos["rotation_rate"] == 0
    disco.smart_correcto = datos.get("smart_status", {}).get("passed")
    disco.temperatura = datos.get("temperature", {}).get("current")
    disco.limite_temperatura = umbrales.temperatura_para(disco.es_nvme)
    disco.horas_encendido = datos.get("power_on_time", {}).get("hours")
    disco.ciclos_encendido = datos.get("power_cycle_count")
    if (disco.horas_encendido and disco.ciclos_encendido
            and disco.ciclos_encendido / disco.horas_encendido > ENCENDIDOS_POR_HORA_CREIBLES):
        # El número es el que da el disco (se ha comparado con smartctl), pero
        # nadie enciende un equipo varias veces por hora durante años. Algunos
        # SSD, sobre todo en portátiles, suman aquí cada vez que el sistema los
        # duerme para ahorrar energía. No indica ningún problema de salud.
        disco.nota_encendidos = (
            "Este disco también cuenta como encendido cada vez que el sistema lo pone en reposo "
            "para ahorrar energía, así que la cifra no equivale a arranques del equipo.")

    if disco.es_nvme:
        disco.errores_de_medio = nvme.get("media_errors")
        if "percentage_used" in nvme:
            # NVMe informa del desgaste consumido; puede pasar de 100.
            disco.vida_restante = max(0, 100 - nvme["percentage_used"])
    else:
        disco.sectores_reasignados = _valor_bruto(datos, ATR_REASIGNADOS)
        disco.sectores_pendientes = _valor_bruto(datos, ATR_PENDIENTES)
        disco.sectores_incorregibles = _valor_bruto(datos, ATR_INCORREGIBLES)
        if disco.es_ssd:
            for identificador in ATR_VIDA_SSD:
                atributo = _atributo(datos, identificador)
                if atributo is not None:
                    disco.vida_restante = max(0, min(100, atributo["value"]))
                    break

    disco.autoprueba = _autoprueba(datos)
    disco.estado, disco.motivos = evaluar_estado(disco, datos, umbrales)
    return disco


# ---------------------------------------------------------------- funciones públicas

def listar_discos(ejecutar: Ejecutor | None = None) -> list[dict]:
    """Discos que smartctl detecta: [{'name': '/dev/sda', 'type': 'ata'}, ...]."""
    datos = _consultar(["--scan"], ejecutar)
    vistos, discos = set(), []
    for dispositivo in datos.get("devices", []):
        nombre = dispositivo.get("name")
        if nombre and nombre not in vistos:
            vistos.add(nombre)
            discos.append({"name": nombre, "type": dispositivo.get("type", "")})
    return discos


def leer_crudo(nombre: str, tipo: str = "", ejecutar: Ejecutor | None = None) -> dict:
    """La respuesta de 'smartctl -a' tal cual, sin interpretar. Solo lectura."""
    return _consultar(["-a"] + (["-d", tipo] if tipo else []) + [nombre], ejecutar)


def leer_disco(nombre: str, tipo: str = "", ejecutar: Ejecutor | None = None,
               umbrales: Umbrales | None = None) -> SaludDisco:
    """Lee toda la información SMART de un disco (smartctl -a). Solo lectura."""
    argumentos = ["-a"] + (["-d", tipo] if tipo else []) + [nombre]
    try:
        return interpretar(_consultar(argumentos, ejecutar), nombre, umbrales)
    except SmartctlNoInstalado:
        raise
    except ErrorSalud as problema:
        return SaludDisco(dispositivo=nombre, error=str(problema))


def leer_todos(ejecutar: Ejecutor | None = None, umbrales: Umbrales | None = None) -> list[SaludDisco]:
    """Salud de todos los discos detectados. Lanza SmartctlNoInstalado si falta el programa."""
    discos = [leer_disco(d["name"], d["type"], ejecutar, umbrales) for d in listar_discos(ejecutar)]
    completar_datos_basicos(discos)
    return discos


def completar_datos_basicos(discos: list[SaludDisco], basicos: dict[str, dict] | None = None) -> None:
    """Rellena modelo, capacidad y tipo de los discos que no se pudieron leer por falta de permisos.

    Esos datos se obtienen del sistema sin privilegios, para que la tarjeta
    diga al menos de qué disco se trata.
    """
    pendientes = [d for d in discos if d.falta_permiso]
    if not pendientes:
        return
    if basicos is None:
        from core.discos_fisicos import info_basica
        basicos = info_basica()
    for disco in pendientes:
        dato = basicos.get(disco.dispositivo)
        if dato:
            disco.modelo = disco.modelo or dato.get("modelo", "")
            disco.capacidad = disco.capacidad or dato.get("capacidad", 0)
            disco.interfaz = disco.interfaz or dato.get("interfaz", "")
            if disco.es_ssd is None:
                disco.es_ssd = dato.get("es_ssd")


def iniciar_autoprueba(nombre: str, tipo: str = "corta", ejecutar: Ejecutor | None = None) -> str:
    """Pide al disco que se pruebe a sí mismo y devuelve un mensaje para el usuario.

    La autoprueba la hace el propio disco leyendo su superficie y comprobando
    su electrónica: no escribe ni modifica los datos guardados, y el disco se
    puede seguir usando mientras tanto. La corta dura unos 2 minutos; la larga
    recorre todo el disco y puede tardar horas.
    """
    if tipo not in TIPOS_DE_PRUEBA:
        raise ErrorSalud(f"Tipo de prueba no válido: {tipo}. Opciones: {', '.join(TIPOS_DE_PRUEBA)}")
    # Solo se aceptan discos que smartctl haya detectado: así el nombre recibido
    # nunca puede ser otra cosa (una opción, otra ruta...).
    conocidos = {d["name"]: d["type"] for d in listar_discos(ejecutar)}
    if nombre not in conocidos:
        raise ErrorSalud(f"No existe el disco {nombre}. Discos detectados: {', '.join(conocidos) or 'ninguno'}")
    return mandar_autoprueba(nombre, conocidos[nombre], tipo, ejecutar)


class FaltaPermiso(ErrorSalud):
    """El sistema no deja hacer eso sin permisos de administrador."""


def mandar_autoprueba(nombre: str, tipo_dispositivo: str, tipo: str, ejecutar: Ejecutor | None = None) -> str:
    """Envía la orden de autoprueba a un disco YA validado. No comprueba el nombre."""
    argumentos = ["-t", TIPOS_DE_PRUEBA[tipo]]
    if tipo_dispositivo:
        argumentos += ["-d", tipo_dispositivo]
    datos = _consultar(argumentos + [nombre], ejecutar)

    codigo = datos.get("smartctl", {}).get("exit_status", 0)
    if _sin_permisos(datos):
        raise FaltaPermiso(FALTA_PERMISO)
    if codigo != 0:
        raise ErrorSalud("El disco no pudo iniciar la autoprueba: "
                         + (_mensajes(datos) or f"código {codigo}") + ".")
    minutos = datos.get("ata_smart_data", {}).get("self_test", {}).get("polling_minutes", {}).get(
        "short" if tipo == "corta" else "extended")
    duracion = f" Duración estimada: {minutos} minutos." if minutos else ""
    return (f"Autoprueba {tipo} iniciada en {nombre}.{duracion} "
            "Consulta el resultado más tarde con la opción de ver la salud.")
