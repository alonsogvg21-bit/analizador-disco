"""Salud del disco: una tarjeta por disco con semáforo, medidores y autopruebas.

Los datos vienen de core.salud (smartctl). Todo es lectura.

La aplicación nunca pide permisos por su cuenta: ni al abrirse ni al entrar
en esta sección. Solo si un disco los exige aparece en su tarjeta el botón
"Dar permiso y leer salud", y es al pulsarlo cuando el sistema los pide.
Lo que se ejecuta con permisos es únicamente el ayudante (core/ayudante.py).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFormLayout, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from core.alertas import leer_config, revisar
from core.privilegios import (
    PermisoCancelado, explicacion, iniciar_autoprueba_con_permiso, leer_salud_con_permiso,
)
from core.salud import (
    BUENO, MALO, NOMBRES_ESTADO, PRECAUCION, SaludDisco, SmartctlNoInstalado, iniciar_autoprueba,
    leer_todos,
)
from desktop import estilos
from desktop.componentes import (
    Tarjeta, barra_de_nivel, etiqueta, limpiar_caja, pagina_con_desplazamiento,
)
from utils.formato import tamano_legible

# Color y símbolo del semáforo. El estado también va escrito al lado.
SEMAFORO = {BUENO: ("bueno", "✓"), PRECAUCION: ("aviso", "!"), MALO: ("critico", "✕")}
TEXTO_BOTON_PERMISO = "Dar permiso y leer salud"


def _leer(avisar: bool):
    """Se ejecuta en segundo plano: lee los discos y, si se pide, envía las alertas nuevas."""
    config = leer_config()
    discos = leer_todos(umbrales=config.umbrales())
    alertas = revisar(discos, config).alertas if avisar else []
    return discos, alertas


def _leer_con_permiso():
    """Se ejecuta en segundo plano: una sola petición de permisos para todos los discos."""
    return leer_salud_con_permiso(leer_config().umbrales()), []


class VistaSalud(QWidget):
    def __init__(self, ventana) -> None:
        super().__init__()
        self.ventana = ventana
        self._cargado = False
        # True si la última lectura necesitó permisos: las autopruebas también los necesitarán.
        self._con_permiso = False
        self._botones_permiso: list[QPushButton] = []

        contenido = QWidget()
        caja = QVBoxLayout(contenido)
        caja.setContentsMargins(28, 24, 28, 24)
        caja.setSpacing(12)
        cabecera = QHBoxLayout()
        titulos = QVBoxLayout()
        titulos.addWidget(etiqueta("Salud del disco", "titulo"))
        titulos.addWidget(etiqueta(
            "Lo que cada disco informa sobre sí mismo (SMART). Solo se lee: no se escribe nada en ellos.",
            "suave", ajustar=True))
        cabecera.addLayout(titulos, 1)
        self._actualizar = QPushButton("Actualizar")
        self._actualizar.clicked.connect(lambda: self.cargar(avisar=True))
        cabecera.addWidget(self._actualizar, alignment=Qt.AlignmentFlag.AlignTop)
        caja.addLayout(cabecera)

        self._nota = etiqueta("", "nota", ajustar=True)
        self._nota.hide()
        caja.addWidget(self._nota)
        self._rejilla = QGridLayout()
        self._rejilla.setSpacing(14)
        caja.addLayout(self._rejilla)
        caja.addStretch(1)

        exterior = QVBoxLayout(self)
        exterior.setContentsMargins(0, 0, 0, 0)
        exterior.addWidget(pagina_con_desplazamiento(contenido))

    def al_mostrar(self) -> None:
        if not self._cargado:
            self.cargar(avisar=False)

    # ------------------------------------------------------------ lectura normal (sin permisos)

    def cargar(self, avisar: bool) -> None:
        self._cargado = True
        self._con_permiso = False
        self._ocupado(True)
        self.ventana.lanzar(_leer, avisar, al_terminar=self._mostrar, al_fallar=self._fallo)

    def _ocupado(self, ocupado: bool) -> None:
        self._actualizar.setEnabled(not ocupado)
        self._actualizar.setText("Leyendo discos…" if ocupado else "Actualizar")
        for boton in self._botones_permiso:
            boton.setEnabled(not ocupado)

    def _fallo(self, problema: Exception) -> None:
        self._ocupado(False)
        limpiar_caja(self._rejilla)
        self._botones_permiso = []
        tarjeta = Tarjeta()
        titulo = ("No se puede leer la salud de los discos todavía"
                  if isinstance(problema, SmartctlNoInstalado) else "No se pudo leer la salud de los discos")
        tarjeta.caja.addWidget(etiqueta(titulo, "subtitulo"))
        tarjeta.caja.addWidget(etiqueta(str(problema), ajustar=True))
        self._rejilla.addWidget(tarjeta, 0, 0)

    def _mostrar(self, datos) -> None:
        discos, alertas = datos
        limpiar_caja(self._rejilla)
        self._botones_permiso = []
        if not discos:
            self._rejilla.addWidget(etiqueta("No se detectó ningún disco.", "suave"), 0, 0)
        for indice, disco in enumerate(discos):
            self._rejilla.addWidget(self._tarjeta(disco), indice // 2, indice % 2)
        self._rejilla.setColumnStretch(0, 1)
        self._rejilla.setColumnStretch(1, 1)
        self._ocupado(False)
        self._nota.setVisible(bool(alertas))
        if alertas:
            self._nota.setText(f"Se han enviado {len(alertas)} alertas: " + "; ".join(a.titulo for a in alertas))
        self.ventana.estado(f"Salud leída de {len(discos)} discos.")

    # ------------------------------------------------------------ lectura con permisos (solo al pulsar)

    def dar_permiso(self) -> None:
        """El usuario ha pulsado el botón: se piden los permisos una vez y se leen todos los discos."""
        self._nota.hide()
        self._ocupado(True)
        self.ventana.estado("Esperando a que concedas los permisos…")
        self.ventana.lanzar(_leer_con_permiso, al_terminar=self._leido_con_permiso,
                            al_fallar=self._sin_permiso)

    def _leido_con_permiso(self, datos) -> None:
        self._con_permiso = True
        self._mostrar(datos)

    def _sin_permiso(self, problema: Exception) -> None:
        """Cancelar la petición no es un error: se explica con calma y el botón sigue disponible."""
        self._ocupado(False)
        self._nota.setText(str(problema))
        self._nota.show()
        self.ventana.estado("No se concedieron los permisos." if isinstance(problema, PermisoCancelado)
                            else "No se pudieron pedir los permisos.")

    # ------------------------------------------------------------ tarjeta de un disco

    def _tarjeta(self, d: SaludDisco) -> Tarjeta:
        tarjeta = Tarjeta()
        nivel, simbolo = SEMAFORO.get(d.estado, ("", "?"))
        fondo = estilos.color(nivel) if nivel else estilos.color("pista")
        semaforo = QLabel(simbolo)
        semaforo.setFixedSize(44, 44)
        semaforo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        semaforo.setStyleSheet(
            f"background: {fondo.name()}; color: {estilos.tinta_sobre(fondo).name()}; "
            "border-radius: 22px; font-size: 16pt; font-weight: 700;")
        cabecera = QHBoxLayout()
        cabecera.addWidget(semaforo)
        textos = QVBoxLayout()
        textos.setSpacing(0)
        textos.addWidget(etiqueta(NOMBRES_ESTADO[d.estado], "subtitulo"))
        textos.addWidget(etiqueta(d.modelo or "Modelo desconocido"))
        textos.addWidget(etiqueta(d.dispositivo, "suave"))
        cabecera.addLayout(textos, 1)
        tarjeta.caja.addLayout(cabecera)

        tipo = "SSD NVMe" if d.es_nvme else "SSD" if d.es_ssd else "Disco duro" if d.es_ssd is False else "Disco"

        if d.error:
            if d.falta_permiso:
                # Lo que no necesita permisos se muestra igualmente.
                if d.capacidad or d.interfaz:
                    datos = " · ".join(p for p in (tipo, tamano_legible(d.capacidad) if d.capacidad else "",
                                                   d.interfaz) if p)
                    tarjeta.caja.addWidget(etiqueta(datos, "suave"))
                tarjeta.caja.addWidget(etiqueta(d.error, ajustar=True))
                tarjeta.caja.addWidget(etiqueta(explicacion(), "suave", ajustar=True))
                boton = QPushButton(TEXTO_BOTON_PERMISO)
                boton.setObjectName("principal")
                boton.clicked.connect(self.dar_permiso)
                self._botones_permiso.append(boton)
                tarjeta.caja.addWidget(boton, alignment=Qt.AlignmentFlag.AlignLeft)
            else:
                tarjeta.caja.addWidget(etiqueta(d.error, "suave", ajustar=True))
            tarjeta.caja.addStretch(1)
            return tarjeta

        tarjeta.caja.addWidget(etiqueta(f"{tipo} · {tamano_legible(d.capacidad)} · {d.interfaz}", "suave"))

        def medidor(titulo: str, porcentaje: float, valor: str, nivel_barra: str, nota: str) -> None:
            fila = QHBoxLayout()
            fila.addWidget(etiqueta(titulo))
            fila.addStretch(1)
            fila.addWidget(etiqueta(valor, "subtitulo"))
            tarjeta.caja.addLayout(fila)
            tarjeta.caja.addWidget(barra_de_nivel(porcentaje, nivel_barra))
            tarjeta.caja.addWidget(etiqueta(nota, "suave"))

        if d.temperatura is not None:
            caliente = d.temperatura >= d.limite_temperatura
            medidor("Temperatura", d.temperatura / d.limite_temperatura * 100, f"{d.temperatura} °C",
                    "critico" if caliente else "aviso" if d.temperatura >= d.limite_temperatura - 8 else "bueno",
                    f"{'Por encima del límite' if caliente else 'Límite'}: {d.limite_temperatura} °C")
        if d.vida_restante is not None:
            medidor("Vida restante", d.vida_restante, f"{d.vida_restante} %",
                    "critico" if d.vida_restante <= 5 else "aviso" if d.vida_restante <= 20 else "bueno",
                    "Desgaste estimado por el propio disco")

        def dato(valor) -> str:
            return "sin dato" if valor is None else f"{valor:,}"

        datos = QFormLayout()
        datos.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        datos.setFormAlignment(Qt.AlignmentFlag.AlignLeft)
        horas = d.horas_encendido
        filas = [("Horas de uso", "sin dato" if horas is None else f"{horas:,} ({horas / 8766:.1f} años)"),
                 ("Encendidos", dato(d.ciclos_encendido) + (" *" if d.nota_encendidos else ""))]
        if d.es_nvme:
            filas.append(("Errores de medio", dato(d.errores_de_medio)))
        else:
            filas += [("Sectores reasignados", dato(d.sectores_reasignados)),
                      ("Sectores pendientes", dato(d.sectores_pendientes)),
                      ("Sectores incorregibles", dato(d.sectores_incorregibles))]
        filas += [("Firmware", d.firmware or "sin dato"), ("Número de serie", d.serie or "sin dato")]
        for nombre, valor in filas:
            datos.addRow(etiqueta(nombre, "suave"), etiqueta(valor))
        tarjeta.caja.addLayout(datos)
        if d.nota_encendidos:
            tarjeta.caja.addWidget(etiqueta(f"* {d.nota_encendidos}", "suave", ajustar=True))

        for motivo in d.motivos:
            tarjeta.caja.addWidget(etiqueta(f"•  {motivo}", ajustar=True))

        p = d.autoprueba
        if p is None:
            texto = "Todavía no se ha hecho ninguna autoprueba."
        elif p.en_curso:
            texto = f"Autoprueba en curso: falta un {p.porcentaje_restante} %."
        else:
            cuando = f", a las {p.horas:,} h de uso" if p.horas is not None else ""
            texto = f"Última autoprueba: {p.resultado}{' (con error)' if p.correcta is False else ''}{cuando}."
        tarjeta.caja.addWidget(etiqueta(texto, "suave", ajustar=True))

        aviso = etiqueta("", "suave", ajustar=True)
        botones = QHBoxLayout()
        for tipo_prueba, titulo, ayuda in (
            ("corta", "Prueba corta", "Unos 2 minutos. No escribe datos en el disco."),
            ("larga", "Prueba larga", "Recorre todo el disco; puede tardar horas. No escribe datos."),
        ):
            boton = QPushButton(titulo)
            boton.setToolTip(ayuda)
            boton.setEnabled(not (p and p.en_curso))
            boton.clicked.connect(lambda _=False, t=tipo_prueba: self._probar(d.dispositivo, t, aviso))
            botones.addWidget(boton)
        botones.addStretch(1)
        tarjeta.caja.addLayout(botones)
        tarjeta.caja.addWidget(aviso)
        tarjeta.caja.addStretch(1)
        return tarjeta

    def _probar(self, dispositivo: str, tipo: str, aviso: QLabel) -> None:
        aviso.setText("Iniciando…")
        # Si los discos se leyeron con permisos, la autoprueba también los necesita.
        funcion = iniciar_autoprueba_con_permiso if self._con_permiso else iniciar_autoprueba
        self.ventana.lanzar(funcion, dispositivo, tipo, al_terminar=aviso.setText,
                            al_fallar=lambda problema: aviso.setText(str(problema)))

    def al_cambiar_tema(self) -> None:
        if self._cargado and not self._con_permiso:
            self.cargar(avisar=False)   # el semáforo lleva colores del tema
