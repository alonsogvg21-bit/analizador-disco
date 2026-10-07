"""Pruebas de la aplicación de escritorio.

Se ejecutan sin pantalla (plataforma "offscreen" de Qt): crean la ventana de
verdad, escanean una carpeta temporal en su hilo y comprueban lo que muestran
las vistas. No aparece ninguna ventana.
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox  # noqa: E402

from desktop import estilos  # noqa: E402
from desktop.acciones import MOVER, PAPELERA, DialogoConfirmacion, elemento_de  # noqa: E402
from desktop.treemap import descripcion  # noqa: E402
from desktop.ventana import VentanaPrincipal  # noqa: E402


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def arbol(tmp_path: Path) -> Path:
    raiz = tmp_path / "raiz"
    for relativa, tamano in (
        ("suelto.txt", 10), ("fotos/a.jpg", 3000), ("fotos/viaje/b.png", 2000),
        ("videos/peli.mp4", 9000), ("proyecto/node_modules/x.js", 1000),
        ("copias/uno.bin", 4000), ("copias/dos.bin", 4000),
    ):
        archivo = raiz.joinpath(*relativa.split("/"))
        archivo.parent.mkdir(parents=True, exist_ok=True)
        archivo.write_bytes(b"x" * tamano)
    return raiz


def esperar(app, condicion, segundos: float = 20) -> None:
    limite = time.monotonic() + segundos
    while not condicion():
        assert time.monotonic() < limite, "la ventana no terminó a tiempo"
        app.processEvents()
        time.sleep(0.01)


@pytest.fixture
def ventana(app, monkeypatch):
    monkeypatch.setattr("core.basura.reglas_del_sistema", lambda: [])
    # Las pruebas nunca consultan los discos reales del equipo.
    monkeypatch.setattr("core.salud.buscar_smartctl", lambda: None)
    # Los avisos emergentes bloquearían la prueba esperando un clic.
    monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: 0)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: 0)
    from desktop.errores import DialogoError
    monkeypatch.setattr(DialogoError, "exec", lambda self: 0)
    v = VentanaPrincipal()
    v.resize(1100, 720)
    v.show()
    app.processEvents()
    yield v
    v.close()


@pytest.fixture
def escaneada(app, ventana, arbol):
    ventana.escanear(str(arbol))
    esperar(app, lambda: ventana.resultado is not None and not ventana.escaneando())
    app.processEvents()
    return ventana


def confirmar_sin_preguntar(monkeypatch, simulacion: bool, destino: str = "") -> None:
    """Sustituye la ventana de confirmación por un 'sí' automático."""
    def aceptar(self):
        self.destino = destino
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(DialogoConfirmacion, "exec", aceptar)
    monkeypatch.setattr(DialogoConfirmacion, "simulacion", property(lambda self: simulacion))


# ------------------------------------------------------------ 1. ventana y navegación

def test_secciones_de_la_barra_lateral(ventana):
    nombres = [ventana.lateral.item(i).text() for i in range(ventana.lateral.count())]
    assert nombres == ["Inicio", "Explorar espacio", "Archivos basura", "Duplicados", "Historial",
                       "Salud del disco", "Configuración"]
    for fila, nombre in enumerate(nombres):
        ventana.lateral.setCurrentRow(fila)
        assert ventana.paginas.currentWidget() is ventana.vistas[nombre]


def test_inicio_muestra_los_discos(ventana):
    assert ventana.vistas["Inicio"]._rejilla.count() >= 1
    assert ventana.vistas["Inicio"]._boton.text() == "Escanear"


def test_carpeta_inexistente_no_inicia_nada(ventana, tmp_path):
    ventana.escanear(str(tmp_path / "no-existe"))
    ventana.escanear("")
    assert not ventana.escaneando() and ventana.resultado is None


# ------------------------------------------------------------ 2. escaneo con hilos

def test_escaneo_en_segundo_plano(escaneada, arbol):
    assert escaneada.resultado.tamano_total == 23010 and escaneada.resultado.num_archivos == 7
    assert escaneada.paginas.currentWidget() is escaneada.vistas["Explorar espacio"]
    assert "23010" in escaneada._mensaje.text() or "22.5 KB" in escaneada._mensaje.text()
    assert escaneada._progreso.isHidden() and escaneada._cancelar.isHidden()
    assert escaneada.vistas["Inicio"]._boton.isEnabled()


def test_cancelar_escaneo(app, ventana, arbol):
    ventana.escanear(str(arbol))
    ventana.cancelar_escaneo()
    esperar(app, lambda: not ventana.escaneando())
    app.processEvents()
    # Según lo rápido que vaya el hilo, la cancelación llega a tiempo o no; nunca se cuelga.
    assert ventana._progreso.isHidden()


# ------------------------------------------------------------ 3. treemap

def test_mapa_de_bloques_y_navegacion(app, escaneada, arbol):
    vista = escaneada.vistas["Explorar espacio"]
    nombres = {b.nodo["nombre"] for b in vista.mapa.bloques()}
    assert {"videos", "copias", "fotos", "peli.mp4", "a.jpg"} <= nombres

    def migas():
        textos = []
        for i in range(vista._migas.count()):
            widget = vista._migas.itemAt(i).widget()
            if widget is not None and widget.objectName() == "miga":
                textos.append(widget.text())
        return textos

    assert migas() == ["raiz"]
    vista.abrir(str(arbol / "fotos"))
    app.processEvents()
    assert migas() == ["raiz", "fotos"]
    assert {b.nodo["nombre"] for b in vista.mapa.bloques()} >= {"a.jpg", "viaje"}

    # Clic sobre el bloque de la carpeta "viaje": el mapa entra en ella.
    bloque = next(b for b in vista.mapa.bloques() if b.nodo["nombre"] == "viaje")
    centro = QPoint(int(bloque.rect.x + bloque.rect.ancho / 2), int(bloque.rect.y + 6))
    QTest.mouseClick(vista.mapa, Qt.MouseButton.LeftButton, pos=centro)
    app.processEvents()
    assert migas() == ["raiz", "fotos", "viaje"]


def test_texto_del_recuadro_flotante(escaneada):
    vista = escaneada.vistas["Explorar espacio"]
    bloque = next(b for b in vista.mapa.bloques() if b.nodo["nombre"] == "peli.mp4")
    texto = descripcion(bloque)
    assert "peli.mp4" in texto and "Archivo · Videos" in texto and "100.0 % de videos" in texto
    carpeta = next(b for b in vista.mapa.bloques() if b.nodo["nombre"] == "videos")
    assert "39.1 % de raiz" in descripcion(carpeta) and "Clic para entrar" in descripcion(carpeta)


def test_arbol_de_carpetas_se_carga_al_desplegar(app, escaneada):
    arbol_widget = escaneada.vistas["Explorar espacio"].arbol
    filas = [arbol_widget.topLevelItem(i) for i in range(arbol_widget.topLevelItemCount())]
    assert [f.text(0) for f in filas][:2] == ["videos", "copias"]          # de mayor a menor
    assert filas[0].text(2) == "39.1 %"
    fotos = next(f for f in filas if f.text(0) == "fotos")
    assert fotos.child(0).text(0) == "…"                                   # todavía sin cargar
    fotos.setExpanded(True)
    app.processEvents()
    assert [fotos.child(i).text(0) for i in range(fotos.childCount())] == [
        "viaje", "(archivos sueltos en esta carpeta)"]
    assert fotos.child(0).text(2) == "40.0 %"                              # respecto a "fotos"


def test_grafica_de_tipos(escaneada):
    filas = escaneada.vistas["Explorar espacio"].grafica_tipos._filas
    assert filas[0][0] == "Videos" and filas[0][1] == pytest.approx(39.1, abs=0.1)
    assert {f[0] for f in filas} >= {"Imágenes", "Código", "Otros"}


# ------------------------------------------------------------ 4. tablas y filtros

def columna(tabla, numero: int) -> list[str]:
    return [tabla.item(fila, numero).text() for fila in range(tabla.rowCount())]


def test_tabla_con_orden_y_filtros(app, escaneada):
    vista = escaneada.vistas["Explorar espacio"]
    tabla = vista.tabla
    assert Path(columna(tabla, 0)[0]).name == "peli.mp4" and tabla.rowCount() == 7

    vista._ordenar_por(2)                       # mismo campo: invierte el orden
    assert Path(columna(tabla, 0)[0]).name == "suelto.txt"
    vista._ordenar_por(3)                       # por fecha de modificación
    assert vista._orden == "modificado" and vista._descendente is True
    vista._ordenar_por(0)                       # la columna del nombre no se ordena
    assert vista._orden == "modificado"

    vista._ordenar_por(2)
    vista._tipo.setCurrentIndex(vista._tipo.findData("imagenes"))
    assert sorted(Path(r).name for r in columna(tabla, 0)) == ["a.jpg", "b.png"]
    assert set(columna(tabla, 1)) == {"Imágenes"}

    vista._tipo.setCurrentIndex(0)
    vista._minimo.setValue(1)                   # 1 MB: ninguno llega
    vista._llenar_tabla()
    assert tabla.rowCount() == 0


def test_elemento_de_solo_acepta_lo_escaneado(escaneada, arbol, tmp_path):
    resultado = escaneada.resultado
    archivo = elemento_de(resultado, str(arbol / "fotos" / "a.jpg"))
    assert archivo.tamano == 3000 and not archivo.es_carpeta
    carpeta = elemento_de(resultado, str(arbol / "fotos"))
    assert carpeta.tamano == 5000 and carpeta.es_carpeta
    ajeno = tmp_path / "ajeno.txt"
    ajeno.write_text("x")
    assert elemento_de(resultado, str(ajeno)) is None
    assert elemento_de(None, str(arbol)) is None


# ------------------------------------------------------------ 5. basura y limpieza

def filas_de(arbol_widget, nombre_categoria: str):
    for i in range(arbol_widget.topLevelItemCount()):
        grupo = arbol_widget.topLevelItem(i)
        if grupo.text(0).startswith(nombre_categoria):
            return grupo, [grupo.child(j) for j in range(grupo.childCount())]
    raise AssertionError(f"no está la categoría {nombre_categoria}")


def test_basura_casillas_y_contador(app, escaneada):
    vista = escaneada.vistas["Archivos basura"]
    assert vista._contador.text() == "Nada seleccionado." and not vista._papelera.isEnabled()

    grupo, filas = filas_de(vista.arbol, "Carpetas regenerables")
    assert filas[0].text(0).endswith("node_modules")
    filas[0].setCheckState(0, Qt.CheckState.Checked)
    app.processEvents()
    assert "1 elemento seleccionado" in vista._contador.text() and "1000 B" in vista._contador.text()
    assert vista._papelera.isEnabled()

    # Marcar o desmarcar la categoría hace lo mismo con todos sus elementos.
    grupo.setCheckState(0, Qt.CheckState.Unchecked)
    app.processEvents()
    assert filas[0].checkState(0) == Qt.CheckState.Unchecked and vista.seleccionados() == []
    assert vista._contador.text() == "Nada seleccionado."
    grupo.setCheckState(0, Qt.CheckState.Checked)
    app.processEvents()
    assert filas[0].checkState(0) == Qt.CheckState.Checked
    assert sum(e.tamano for e in vista.seleccionados()) == 1000


def test_simulacion_no_toca_nada(app, escaneada, arbol, monkeypatch):
    def prohibido(ruta):
        raise AssertionError("en simulación no se debe llamar a la papelera")
    monkeypatch.setattr("core.limpieza.send2trash", prohibido)
    confirmar_sin_preguntar(monkeypatch, simulacion=True)

    vista = escaneada.vistas["Archivos basura"]
    _, filas = filas_de(vista.arbol, "Carpetas regenerables")
    filas[0].setCheckState(0, Qt.CheckState.Checked)
    escaneada.realizar(PAPELERA, vista.seleccionados())
    esperar(app, lambda: "Simulación" in escaneada._mensaje.text())
    assert (arbol / "proyecto" / "node_modules").exists()
    assert "No se ha tocado nada" in escaneada._mensaje.text()


def test_enviar_a_la_papelera(app, escaneada, arbol, monkeypatch):
    monkeypatch.setattr("core.limpieza.send2trash", shutil.rmtree)
    confirmar_sin_preguntar(monkeypatch, simulacion=False)

    vista = escaneada.vistas["Archivos basura"]
    _, filas = filas_de(vista.arbol, "Carpetas regenerables")
    filas[0].setCheckState(0, Qt.CheckState.Checked)
    escaneada.realizar(PAPELERA, vista.seleccionados())
    esperar(app, lambda: "en la papelera" in escaneada._mensaje.text())
    app.processEvents()

    assert not (arbol / "proyecto" / "node_modules").exists()
    assert (arbol / "fotos" / "a.jpg").exists()
    # La categoría desaparece de la lista porque ya no le queda nada.
    with pytest.raises(AssertionError):
        filas_de(vista.arbol, "Carpetas regenerables")


def test_sin_confirmar_no_se_hace_nada(app, escaneada, arbol, monkeypatch):
    def prohibido(*_):
        raise AssertionError("sin confirmación no se debe tocar nada")
    monkeypatch.setattr("core.limpieza.send2trash", prohibido)
    monkeypatch.setattr("desktop.ventana.limpiar", prohibido)
    monkeypatch.setattr(DialogoConfirmacion, "exec", lambda self: QDialog.DialogCode.Rejected)
    escaneada.realizar(PAPELERA, [elemento_de(escaneada.resultado, str(arbol / "fotos" / "a.jpg"))])
    app.processEvents()
    assert (arbol / "fotos" / "a.jpg").exists()


def test_mover_desde_la_tabla(app, escaneada, arbol, tmp_path, monkeypatch):
    destino = tmp_path / "destino"
    destino.mkdir()
    confirmar_sin_preguntar(monkeypatch, simulacion=False, destino=str(destino))

    vista = escaneada.vistas["Explorar espacio"]
    fila = next(f for f in range(vista.tabla.rowCount())
                if vista.tabla.item(f, 0).text().endswith("peli.mp4"))
    vista.tabla.selectRow(fila)
    escaneada.realizar(MOVER, vista._seleccion_tabla())
    esperar(app, lambda: "Movidos" in escaneada._mensaje.text())
    app.processEvents()

    assert (destino / "peli.mp4").exists() and not (arbol / "videos" / "peli.mp4").exists()
    assert all(not r.endswith("peli.mp4") for r in columna(vista.tabla, 0))    # sale de la tabla


def test_lo_protegido_no_se_ofrece(escaneada, monkeypatch):
    llamadas = []
    monkeypatch.setattr(DialogoConfirmacion, "exec", lambda self: llamadas.append(1) or QDialog.DialogCode.Rejected)
    from core.modelos import ElementoBasura
    escaneada.realizar(PAPELERA, [ElementoBasura(Path.home(), 1, "carpetas", es_carpeta=True, limpiable=False)])
    assert llamadas == []          # ni siquiera se llega a preguntar


def test_dialogo_de_confirmacion(app, escaneada, arbol, tmp_path):
    elementos = [elemento_de(escaneada.resultado, str(arbol / "fotos" / "a.jpg")),
                 elemento_de(escaneada.resultado, str(arbol / "videos"))]
    # Por seguridad, la ventana se abre con «Solo simular» ya marcado.
    dialogo = DialogoConfirmacion(escaneada, elementos, PAPELERA)
    assert dialogo._confirmar.text() == "Simular" and dialogo.simulacion
    dialogo._simular.setChecked(False)
    assert dialogo._confirmar.text() == "Sí, enviar a la papelera" and not dialogo.simulacion
    assert DialogoConfirmacion(escaneada, elementos, PAPELERA, simular=False).simulacion is False

    mover = DialogoConfirmacion(escaneada, elementos, MOVER)
    mover._campo_destino.setText(str(tmp_path / "no-existe"))
    mover._aceptar()
    assert mover.result() != QDialog.DialogCode.Accepted and "no existe" in mover._aviso.text()
    mover._campo_destino.setText(str(tmp_path))
    mover._aceptar()
    assert mover.result() == QDialog.DialogCode.Accepted and mover.destino == str(tmp_path.resolve())


# ------------------------------------------------------------ duplicados, historial y salud

def test_duplicados(app, escaneada, arbol):
    vista = escaneada.vistas["Duplicados"]
    vista._minimo.setValue(0)
    vista.buscar()
    esperar(app, lambda: vista._buscar.isEnabled())
    app.processEvents()
    assert len(vista._grupos) == 1 and vista.arbol.topLevelItemCount() == 1
    grupo = vista.arbol.topLevelItem(0)
    assert grupo.child(0).text(2) == "original (se conserva)" and grupo.child(1).text(2) == "copia"
    # El original no tiene casilla.
    assert not grupo.child(0).flags() & Qt.ItemFlag.ItemIsUserCheckable

    vista._marcar_todas(True)
    assert len(vista.seleccionados()) == 1 and "3.9 KB" in vista._contador.text()


def test_historial_tras_dos_escaneos(app, escaneada, arbol):
    (arbol / "fotos" / "nueva.jpg").write_bytes(b"x" * 2 * 1024 * 1024)
    escaneada.escanear(str(arbol))
    esperar(app, lambda: not escaneada.escaneando() and escaneada.resultado.num_archivos == 8)
    escaneada.ir_a("Historial")
    app.processEvents()
    vista = escaneada.vistas["Historial"]
    assert len(vista._escaneos) == 2 and len(vista.grafica._puntos) == 2
    assert "creció 2.0 MB" in vista._resumen.text()
    assert vista.tabla.rowCount() == 1 and vista.tabla.item(0, 0).text().endswith("fotos")
    assert "+2.0 MB" in vista.tabla.item(0, 3).text()


def test_salud_sin_smartctl(app, ventana, monkeypatch):
    monkeypatch.setattr("core.salud.buscar_smartctl", lambda: None)
    ventana.ir_a("Salud del disco")
    vista = ventana.vistas["Salud del disco"]
    esperar(app, lambda: vista._actualizar.isEnabled())
    app.processEvents()
    assert vista._rejilla.count() == 1      # la tarjeta con los pasos de instalación


def test_salud_con_datos_de_ejemplo(app, ventana, monkeypatch):
    from core import salud
    from tests.test_salud import SmartctlFalso
    monkeypatch.setattr(salud, "_ejecutar", SmartctlFalso(
        {"/dev/sda": "hdd_reasignados", "/dev/sdb": "ssd_sata", "/dev/nvme0": "nvme_critico"}))
    ventana.ir_a("Salud del disco")
    vista = ventana.vistas["Salud del disco"]
    esperar(app, lambda: vista._actualizar.isEnabled())
    app.processEvents()
    assert vista._rejilla.count() == 3 and "3 discos" in ventana._mensaje.text()


# ------------------------------------------------------------ 6. estilos y modo oscuro

def test_modo_claro_y_oscuro(app, escaneada):
    escaneada.cambiar_tema("oscuro")
    assert estilos.es_oscuro() and estilos.color("fondo").name() == "#0d0d0d"
    assert escaneada.tema() == "oscuro"
    escaneada.cambiar_tema("claro")
    assert not estilos.es_oscuro() and estilos.color("fondo").name() == "#f4f4f1"
    # Cada tipo de archivo tiene color en los dos temas.
    for tipo in estilos.NOMBRES_TIPO:
        assert estilos.color_tipo(tipo).isValid()
    app.processEvents()
    assert not escaneada.grab().isNull()     # la ventana se puede pintar entera


def test_configuracion_guarda_preferencias(app, ventana):
    vista = ventana.vistas["Configuración"]
    vista._duplicados.setChecked(False)
    assert ventana.buscar_duplicados_al_escanear() is False
    vista._automatico.setChecked(False)
    vista._grados.setValue(48)
    from core.alertas import leer_config
    assert leer_config().temperatura_limite == 48
    vista._tema.setCurrentIndex(2)
    assert ventana.tema() == "oscuro"
    vista._tema.setCurrentIndex(1)


# ------------------------------------------------------------ icono, nombre y versión

def test_acerca_de_muestra_nombre_y_version(app, ventana):
    from desktop.acerca import DialogoAcercaDe, icono
    from utils.info import NOMBRE, VERSION
    assert not icono().isNull()                       # el archivo del icono existe y se carga
    assert ventana.windowTitle() == NOMBRE and not ventana.windowIcon().isNull()
    dialogo = DialogoAcercaDe(ventana)
    assert NOMBRE in dialogo.windowTitle() and dialogo.version.text() == f"Versión {VERSION}"
    textos = " ".join(e.text() for e in dialogo.findChildren(type(dialogo.version)))
    assert NOMBRE in textos and "Licencia MIT" in textos and "github.com" in textos


def test_f1_abre_acerca_de(app, ventana, monkeypatch):
    from desktop.acerca import DialogoAcercaDe
    abiertos = []
    monkeypatch.setattr(DialogoAcercaDe, "exec", lambda self: abiertos.append(self) or 0)
    QTest.keyClick(ventana, Qt.Key.Key_F1)
    assert len(abiertos) == 1


# ------------------------------------------------------------ uso por otras personas

def test_asistente_inicial(app, ventana):
    from desktop.asistente import PAGINAS, AsistenteInicial, mostrar_si_hace_falta
    asistente = AsistenteInicial(ventana)
    assert asistente.paginas.count() == len(PAGINAS) == 3
    todo = " ".join(parrafo for _, parrafos in PAGINAS for parrafo in parrafos)
    for esperado in ("solo lee", "simulación", "papelera", "no envía datos a ningún servidor",
                     "sin garantía", "confirmar dos veces", "administrador"):
        assert esperado in todo, esperado

    assert asistente.siguiente.text() == "Siguiente" and not asistente.atras.isEnabled()
    asistente._avanzar()
    asistente._avanzar()
    # Última página: no se puede empezar sin marcar la casilla.
    assert asistente.siguiente.text() == "Empezar" and not asistente.siguiente.isEnabled()
    asistente.entendido.setChecked(True)
    assert asistente.siguiente.isEnabled()
    asistente._avanzar()
    assert asistente.result() == QDialog.DialogCode.Accepted

    del mostrar_si_hace_falta


def test_el_asistente_solo_aparece_la_primera_vez(app, ventana, monkeypatch):
    from desktop import asistente
    veces = []
    monkeypatch.setattr(asistente.AsistenteInicial, "exec",
                        lambda self: veces.append(1) or QDialog.DialogCode.Accepted)
    assert asistente.mostrar_si_hace_falta(ventana) and asistente.mostrar_si_hace_falta(ventana)
    assert veces == [1]


def test_si_no_se_acepta_el_asistente_no_se_da_por_visto(app, ventana, monkeypatch):
    from desktop import asistente
    monkeypatch.setattr(asistente.AsistenteInicial, "exec", lambda self: QDialog.DialogCode.Rejected)
    assert asistente.mostrar_si_hace_falta(ventana) is False
    assert int(ventana.ajustes.value("asistente_visto", 0) or 0) == 0


def test_simulacion_activada_por_defecto(app, ventana):
    assert ventana.simular_por_defecto() is True
    ventana.vistas["Configuración"]._simular.setChecked(False)
    assert ventana.simular_por_defecto() is False
    ventana.vistas["Configuración"]._simular.setChecked(True)


def test_doble_confirmacion_en_el_escritorio(app, escaneada, arbol, monkeypatch):
    preguntas = []
    monkeypatch.setattr("core.limpieza.send2trash", shutil.rmtree)
    monkeypatch.setattr("desktop.ventana.requiere_doble_confirmacion", lambda elementos: True)
    confirmar_sin_preguntar(monkeypatch, simulacion=False)
    carpeta = elemento_de(escaneada.resultado, str(arbol / "proyecto" / "node_modules"))

    # Primera vez: se responde que no a la segunda pregunta. No se toca nada.
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: preguntas.append(a[2]) or QMessageBox.StandardButton.No)
    escaneada.realizar(PAPELERA, [carpeta])
    app.processEvents()
    assert len(preguntas) == 1 and "más de 1 GB" in preguntas[0]
    assert (arbol / "proyecto" / "node_modules").exists() and "Cancelado" in escaneada._mensaje.text()

    # Segunda vez: se confirma dos veces.
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    escaneada.realizar(PAPELERA, [carpeta])
    esperar(app, lambda: "en la papelera" in escaneada._mensaje.text())
    assert not (arbol / "proyecto" / "node_modules").exists()


def test_la_simulacion_no_pide_la_segunda_confirmacion(app, escaneada, arbol, monkeypatch):
    def prohibido(*a, **k):
        raise AssertionError("simular no debe pedir la segunda confirmación")
    monkeypatch.setattr(QMessageBox, "question", prohibido)
    monkeypatch.setattr("desktop.ventana.requiere_doble_confirmacion", lambda elementos: True)
    confirmar_sin_preguntar(monkeypatch, simulacion=True)
    escaneada.realizar(PAPELERA, [elemento_de(escaneada.resultado, str(arbol / "fotos" / "a.jpg"))])
    esperar(app, lambda: "Simulación" in escaneada._mensaje.text())


def test_errores_amigables_con_detalle_para_copiar(app, ventana):
    from desktop.errores import DialogoError, detalle_tecnico, mensaje_amigable
    from utils.info import VERSION
    assert "permisos" in mensaje_amigable(PermissionError(13, "Access is denied"))
    assert "ya no existe" in mensaje_amigable(FileNotFoundError(2, "No such file"))
    assert "espacio" in mensaje_amigable(OSError(28, "No space left on device"))
    assert mensaje_amigable(ValueError("La carpeta de destino no existe: X")) == "La carpeta de destino no existe: X"
    assert "inesperado" in mensaje_amigable(KeyError("x"))
    assert "Traceback" not in mensaje_amigable(ZeroDivisionError("division by zero"))

    try:
        1 / 0
    except ZeroDivisionError as problema:
        detalle = detalle_tecnico(problema)
    assert "ZeroDivisionError" in detalle and VERSION in detalle and "test_desktop.py" in detalle

    dialogo = DialogoError(ventana, "Mensaje claro.", detalle)
    assert dialogo.texto.isHidden()                       # el detalle no se muestra de entrada
    dialogo._alternar()
    assert not dialogo.texto.isHidden()
    dialogo._copiar()
    assert QApplication.clipboard().text() == detalle and dialogo.copiar.text() == "Copiado"


def test_un_error_no_previsto_no_cierra_el_programa(app, ventana, monkeypatch):
    import sys
    from desktop import errores
    mostrados = []
    monkeypatch.setattr(errores.DialogoError, "exec", lambda self: mostrados.append(self.mensaje.text()) or 0)
    anterior = sys.excepthook
    try:
        errores.instalar_gancho(ventana)
        try:
            raise RuntimeError("Fallo de prueba")
        except RuntimeError as problema:
            sys.excepthook(type(problema), problema, problema.__traceback__)
    finally:
        sys.excepthook = anterior
    assert mostrados == ["Fallo de prueba"]
    from core import registro
    assert any("error" in linea and "Fallo de prueba" in linea for linea in registro.ultimas_lineas())


def test_acerca_de_incluye_licencias_y_privacidad(app, ventana):
    from desktop.acerca import DialogoAcercaDe, DialogoTexto, texto_de
    dialogo = DialogoAcercaDe(ventana)
    textos = " ".join(e.text() for e in dialogo.findChildren(type(dialogo.version)))
    assert "no envía datos a ningún servidor" in textos
    botones = [b.text() for b in dialogo.findChildren(type(ventana._cancelar))]
    assert "Licencia" in botones and "Licencias de terceros" in botones
    assert "PySide6" in DialogoTexto(dialogo, "x", texto_de("NOTICE")).texto.toPlainText()
    assert "MIT License" in texto_de("LICENSE")
    assert "No se encontró" in texto_de("NO-EXISTE")


def botones_de_permiso(vista):
    from desktop.vistas.salud import TEXTO_BOTON_PERMISO
    return [b for b in vista.findChildren(type(vista._actualizar)) if b.text() == TEXTO_BOTON_PERMISO]


def cargar_salud(app, ventana, monkeypatch, discos):
    from core import salud
    from tests.test_salud import SmartctlFalso
    monkeypatch.setattr(salud, "buscar_smartctl", lambda: "smartctl")
    monkeypatch.setattr(salud, "_ejecutar", SmartctlFalso(discos))
    monkeypatch.setattr("core.discos_fisicos.info_basica", lambda: {
        "/dev/sdb": {"modelo": "Kingston XS1000", "capacidad": 1000204886016, "es_ssd": True, "interfaz": "USB"}})
    vista = ventana.vistas["Salud del disco"]
    vista.cargar(avisar=False)
    esperar(app, lambda: vista._actualizar.isEnabled())
    app.processEvents()
    return vista


PROTEGIDO = {"/dev/sda": "nvme_sano", "/dev/sdb": "sin_permisos_windows_real", "/dev/nvme0": "ssd_sata"}


def test_el_boton_de_permiso_solo_aparece_si_un_disco_lo_exige(app, ventana, monkeypatch):
    def prohibido(*a, **k):
        raise AssertionError("abrir la sección nunca pide permisos")
    monkeypatch.setattr("desktop.vistas.salud.leer_salud_con_permiso", prohibido)

    vista = cargar_salud(app, ventana, monkeypatch,
                         {"/dev/sda": "hdd_sano", "/dev/sdb": "ssd_sata", "/dev/nvme0": "nvme_sano"})
    assert botones_de_permiso(vista) == []                 # todo se lee sin permisos

    vista = cargar_salud(app, ventana, monkeypatch, PROTEGIDO)
    assert len(botones_de_permiso(vista)) == 1             # solo en la tarjeta del disco protegido
    textos = " ".join(e.text() for e in vista.findChildren(type(vista._nota)))
    assert "Kingston XS1000" in textos and "931.5 GB" in textos       # lo que no necesita permisos
    assert "No se escribe" in textos                                  # el porqué, en la propia tarjeta
    assert "PowerShell" not in textos and "Cierra el programa" not in textos


def test_dar_permiso_lee_todos_los_discos_de_una_vez(app, ventana, monkeypatch):
    from tests.test_salud import ejemplo
    from core.salud import interpretar
    vista = cargar_salud(app, ventana, monkeypatch, PROTEGIDO)
    peticiones = []

    def con_permiso(umbrales):
        peticiones.append(1)
        return [interpretar(ejemplo(nombre), disco) for disco, nombre in (
            ("/dev/sda", "nvme_sano"), ("/dev/sdb", "hdd_sano"), ("/dev/nvme0", "ssd_sata"))]
    monkeypatch.setattr("desktop.vistas.salud.leer_salud_con_permiso", con_permiso)

    botones_de_permiso(vista)[0].click()
    esperar(app, lambda: vista._actualizar.isEnabled())
    app.processEvents()
    assert peticiones == [1]                               # una sola petición
    assert botones_de_permiso(vista) == [] and vista._con_permiso is True
    assert "3 discos" in ventana._mensaje.text()


def test_cancelar_el_permiso_deja_el_boton_disponible(app, ventana, monkeypatch):
    from core.privilegios import PermisoCancelado, mensaje_cancelado
    from desktop.errores import DialogoError
    vista = cargar_salud(app, ventana, monkeypatch, PROTEGIDO)
    errores = []
    monkeypatch.setattr(DialogoError, "exec", lambda self: errores.append(1) or 0)

    def cancelar(umbrales):
        raise PermisoCancelado(mensaje_cancelado())
    monkeypatch.setattr("desktop.vistas.salud.leer_salud_con_permiso", cancelar)

    botones_de_permiso(vista)[0].click()
    esperar(app, lambda: vista._actualizar.isEnabled())
    app.processEvents()
    assert errores == []                                   # no se muestra como un error
    assert not vista._nota.isHidden() and "No pasa nada" in vista._nota.text()
    boton = botones_de_permiso(vista)[0]
    assert boton.isEnabled() and vista._con_permiso is False
