"""Salud del disco: una tarjeta por disco con semáforo, medidores y autopruebas.

Los datos vienen de core.salud (smartctl). Todo es lectura.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFormLayout, QGridLayout, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from core.alertas import leer_config, revisar
from core.elevacion import EXPLICACION, leer_salud_con_permisos
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


def _leer(avisar: bool):
    """Se ejecuta en segundo plano: lee los discos y, si se pide, envía las alertas nuevas."""
    config = leer_config()
    discos = leer_todos(umbrales=config.umbrales())
    alertas = revisar(discos, config).alertas if avisar else []
    return discos, alertas


class VistaSalud(QWidget):
    def __init__(self, ventana) -> None:
        super().__init__()
        self.ventana = ventana
        self._cargado = False

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
        self._elevar = QPushButton("Leer con permisos de administrador…")
        self._elevar.setToolTip("Antes de pedirlos se explica para qué son.")
        self._elevar.clicked.connect(self.leer_con_permisos)
        self._elevar.hide()
        caja.addWidget(self._elevar, alignment=Qt.AlignmentFlag.AlignLeft)
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

    def cargar(self, avisar: bool) -> None:
        self._cargado = True
        self._actualizar.setEnabled(False)
        self._actualizar.setText("Leyendo discos…")
        self.ventana.lanzar(_leer, avisar, al_terminar=self._mostrar, al_fallar=self._fallo)

    def leer_con_permisos(self) -> None:
        """Explica por qué hacen falta los permisos y, solo si se acepta, los pide."""
        aviso = QMessageBox(self)
        aviso.setWindowTitle("Permisos de administrador")
        aviso.setIcon(QMessageBox.Icon.Information)
        aviso.setText(EXPLICACION)
        continuar = aviso.addButton("Continuar", QMessageBox.ButtonRole.AcceptRole)
        aviso.setDefaultButton(aviso.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole))
        aviso.exec()
        if aviso.clickedButton() is not continuar:
            return
        self._actualizar.setEnabled(False)
        self._elevar.setEnabled(False)
        self._actualizar.setText("Leyendo discos…")
        self.ventana.lanzar(
            lambda: (leer_salud_con_permisos(leer_config().umbrales()), []),
            al_terminar=self._mostrar, al_fallar=self._fallo_permisos)

    def _fallo_permisos(self, problema: Exception) -> None:
        self._fin()
        self._nota.setText(str(problema))
        self._nota.show()

    def _fin(self) -> None:
        self._elevar.setEnabled(True)
        self._actualizar.setEnabled(True)
        self._actualizar.setText("Actualizar")

    def _fallo(self, problema: Exception) -> None:
        self._fin()
        limpiar_caja(self._rejilla)
        tarjeta = Tarjeta()
        titulo = ("No se puede leer la salud de los discos todavía"
                  if isinstance(problema, SmartctlNoInstalado) else "No se pudo leer la salud de los discos")
        tarjeta.caja.addWidget(etiqueta(titulo, "subtitulo"))
        tarjeta.caja.addWidget(etiqueta(str(problema), ajustar=True))
        self._rejilla.addWidget(tarjeta, 0, 0)

    def _mostrar(self, datos) -> None:
        discos, alertas = datos
        self._fin()
        limpiar_caja(self._rejilla)
        if not discos:
            self._rejilla.addWidget(etiqueta("No se detectó ningún disco.", "suave"), 0, 0)
        for indice, disco in enumerate(discos):
            self._rejilla.addWidget(self._tarjeta(disco), indice // 2, indice % 2)
        # Solo si algún disco lo exige se ofrece leer con permisos de administrador.
        self._elevar.setVisible(any(d.falta_permiso for d in discos))
        self._rejilla.setColumnStretch(0, 1)
        self._rejilla.setColumnStretch(1, 1)
        self._nota.setVisible(bool(alertas))
        if alertas:
            self._nota.setText(f"Se han enviado {len(alertas)} alertas: " + "; ".join(a.titulo for a in alertas))
        self.ventana.estado(f"Salud leída de {len(discos)} discos.")

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

        if d.error:
            tarjeta.caja.addWidget(etiqueta(d.error, "suave", ajustar=True))
            tarjeta.caja.addStretch(1)
            return tarjeta

        tipo = "SSD NVMe" if d.es_nvme else "SSD" if d.es_ssd else "Disco duro" if d.es_ssd is False else "Disco"
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
                 ("Encendidos", dato(d.ciclos_encendido))]
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
        self.ventana.lanzar(iniciar_autoprueba, dispositivo, tipo,
                            al_terminar=aviso.setText, al_fallar=lambda problema: aviso.setText(str(problema)))

    def al_cambiar_tema(self) -> None:
        if self._cargado:
            self.cargar(avisar=False)   # el semáforo lleva colores del tema
