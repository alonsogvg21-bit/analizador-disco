"""Pruebas de la interfaz web usando el cliente de pruebas de Flask."""

from __future__ import annotations

from pathlib import Path

import pytest

from web.app import crear_app
from web.tareas import LISTO, GestorEscaneo


@pytest.fixture
def arbol(tmp_path: Path) -> Path:
    raiz = tmp_path / "raiz"
    for relativa, tamano in (
        ("suelto.txt", 10),
        ("fotos/a.jpg", 300),
        ("fotos/viaje/b.png", 200),
        ("proyecto/node_modules/x.js", 1000),
    ):
        archivo = raiz.joinpath(*relativa.split("/"))
        archivo.parent.mkdir(parents=True, exist_ok=True)
        archivo.write_bytes(b"x" * tamano)
    return raiz


@pytest.fixture
def app(monkeypatch):
    # Sin reglas del sistema, para no depender del equipo donde corre la prueba.
    monkeypatch.setattr("core.basura.reglas_del_sistema", lambda: [])
    return crear_app(GestorEscaneo())


@pytest.fixture
def cliente(app):
    return app.test_client()


@pytest.fixture
def token(app):
    return {"X-Token": app.config["TOKEN"]}


@pytest.fixture
def escaneado(app, cliente, token, arbol):
    """Cliente con un escaneo ya terminado."""
    assert cliente.post("/api/escanear", json={"ruta": str(arbol)}, headers=token).status_code == 202
    app.config["GESTOR"].esperar(30)
    assert cliente.get("/api/estado").get_json()["fase"] == LISTO
    return cliente


def test_pagina_inicio(cliente, app):
    respuesta = cliente.get("/")
    assert respuesta.status_code == 200
    assert app.config["TOKEN"] in respuesta.get_data(as_text=True)


def test_discos(cliente):
    discos = cliente.get("/api/discos").get_json()
    assert discos and discos[0]["total"] > 0


def test_post_sin_token_rechazado(cliente, arbol):
    assert cliente.post("/api/escanear", json={"ruta": str(arbol)}).status_code == 403
    assert cliente.post("/api/escanear", json={"ruta": str(arbol)},
                        headers={"X-Token": "falso"}).status_code == 403


def test_host_externo_rechazado(cliente):
    assert cliente.get("/api/discos", headers={"Host": "sitio-malicioso.com"}).status_code == 403


def test_ruta_invalida(cliente, token, tmp_path):
    assert cliente.post("/api/escanear", json={"ruta": ""}, headers=token).status_code == 400
    respuesta = cliente.post("/api/escanear", json={"ruta": str(tmp_path / "no")}, headers=token)
    assert respuesta.status_code == 400 and "no existe" in respuesta.get_json()["error"]


def test_sin_escaneo_no_hay_resultado(cliente):
    for ruta in ("/api/resultado", "/api/carpetas", "/api/arbol", "/api/basura", "/api/reporte"):
        assert cliente.get(ruta).status_code == 404


def test_resultado(escaneado):
    datos = escaneado.get("/api/resultado").get_json()
    assert datos["tamano_total"] == 1510 and datos["num_archivos"] == 4
    assert datos["top"][0]["ruta"].endswith("x.js")
    assert {t["tipo"]: t["tamano"] for t in datos["tipos"]}["imagenes"] == 500


def test_carpetas_por_niveles(escaneado, arbol):
    raiz = escaneado.get("/api/carpetas").get_json()
    assert [c["nombre"] for c in raiz["subcarpetas"]] == ["proyecto", "fotos"]
    assert raiz["tamano_archivos_directos"] == 10
    fotos = next(c for c in raiz["subcarpetas"] if c["nombre"] == "fotos")
    assert fotos["tiene_subcarpetas"]

    nivel = escaneado.get("/api/carpetas", query_string={"ruta": fotos["ruta"]}).get_json()
    assert [(c["nombre"], c["tamano"], c["tiene_subcarpetas"]) for c in nivel["subcarpetas"]] == [
        ("viaje", 200, False)]
    assert escaneado.get("/api/carpetas", query_string={"ruta": str(arbol.parent)}).status_code == 404


def test_arbol_para_el_mapa(escaneado, arbol):
    datos = escaneado.get("/api/arbol").get_json()
    assert datos["tamano"] == 1510
    assert [h["nombre"] for h in datos["hijos"]] == ["proyecto", "fotos", "suelto.txt"]
    fotos = datos["hijos"][1]
    assert fotos["tipo"] == "imagenes" and [h["nombre"] for h in fotos["hijos"]] == ["a.jpg", "viaje"]
    assert "hijos" not in fotos["hijos"][1]  # por defecto, solo dos niveles

    nivel = escaneado.get("/api/arbol", query_string={"ruta": fotos["ruta"], "niveles": 1}).get_json()
    assert [m["nombre"] for m in nivel["migas"]] == ["raiz", "fotos"]

    assert escaneado.get("/api/arbol", query_string={"ruta": str(arbol.parent)}).status_code == 404
    assert escaneado.get("/api/arbol", query_string={"niveles": "muchos"}).status_code == 400


def test_basura(escaneado):
    categorias = {c["clave"]: c for c in escaneado.get("/api/basura").get_json()}
    (elemento,) = categorias["regenerables"]["elementos"]
    assert elemento["ruta"].endswith("node_modules") and elemento["tamano"] == 1000
    assert elemento["id"] == "regenerables-0" and elemento["limpiable"]


@pytest.mark.parametrize("formato, tipo", [("html", "text/html"), ("csv", "text/csv")])
def test_reporte(escaneado, formato, tipo):
    respuesta = escaneado.get("/api/reporte", query_string={"formato": formato})
    assert respuesta.status_code == 200 and respuesta.mimetype == tipo
    assert "attachment" in respuesta.headers["Content-Disposition"]
    assert b"node_modules" in respuesta.data


def test_reporte_formato_invalido(escaneado):
    assert escaneado.get("/api/reporte", query_string={"formato": "exe"}).status_code == 400


def test_cancelar(app, cliente, token, arbol):
    assert cliente.post("/api/cancelar").status_code == 403  # también exige token
    assert cliente.post("/api/escanear", json={"ruta": str(arbol)}, headers=token).status_code == 202
    assert cliente.post("/api/cancelar", headers=token).status_code == 200
    app.config["GESTOR"].esperar(30)
    # Según lo rápido que vaya el hilo, la cancelación llega a tiempo o no.
    assert cliente.get("/api/estado").get_json()["fase"] in ("listo", "cancelado")


# ------------------------------------------------------------ limpieza

@pytest.fixture
def papelera_falsa(monkeypatch):
    """Sustituye la papelera real por un borrado dentro de la carpeta temporal."""
    import shutil
    monkeypatch.setattr("core.limpieza.send2trash", shutil.rmtree)


def test_limpiar_exige_token_y_escaneo(cliente, token):
    assert cliente.post("/api/limpiar", json={"ids": ["regenerables-0"]}).status_code == 403
    assert cliente.post("/api/limpiar", json={"ids": ["regenerables-0"]}, headers=token).status_code == 404


def test_limpiar_simula_por_defecto(escaneado, token, arbol, papelera_falsa):
    respuesta = escaneado.post("/api/limpiar", json={"ids": ["regenerables-0"]}, headers=token)
    datos = respuesta.get_json()
    assert respuesta.status_code == 200 and datos["simulacion"]
    assert datos["bytes_liberados"] == 1000
    assert (arbol / "proyecto" / "node_modules").exists()


def test_limpiar_real_exige_confirmacion(escaneado, token, arbol, papelera_falsa):
    respuesta = escaneado.post(
        "/api/limpiar", json={"ids": ["regenerables-0"], "simulacion": False}, headers=token)
    assert respuesta.status_code == 400
    assert (arbol / "proyecto" / "node_modules").exists()


def test_limpiar_real(escaneado, token, arbol, papelera_falsa):
    respuesta = escaneado.post(
        "/api/limpiar", headers=token,
        json={"ids": ["regenerables-0"], "simulacion": False, "confirmado": True})
    datos = respuesta.get_json()
    assert respuesta.status_code == 200 and not datos["simulacion"]
    assert datos["bytes_liberados"] == 1000 and len(datos["enviados"]) == 1
    assert not (arbol / "proyecto" / "node_modules").exists()
    assert (arbol / "fotos" / "a.jpg").exists()

    # Lo enviado ya no se ofrece, ni se puede volver a pedir.
    categorias = {c["clave"]: c for c in escaneado.get("/api/basura").get_json()}
    assert categorias["regenerables"]["elementos"] == []
    repetido = escaneado.post(
        "/api/limpiar", headers=token,
        json={"ids": ["regenerables-0"], "simulacion": False, "confirmado": True})
    assert repetido.status_code == 400


def test_limpiar_no_acepta_rutas(escaneado, token, arbol, papelera_falsa):
    """La página no puede pedir que se borre una ruta cualquiera: solo identificadores."""
    victima = arbol / "fotos"
    for ids in ([str(victima)], [], "regenerables-0", None):
        respuesta = escaneado.post(
            "/api/limpiar", headers=token,
            json={"ids": ids, "simulacion": False, "confirmado": True})
        assert respuesta.status_code == 400
    assert victima.exists()


# ------------------------------------------------------------ tabla de archivos

def test_archivos_con_orden_y_filtros(escaneado):
    todos = escaneado.get("/api/archivos").get_json()
    assert [a["tamano"] for a in todos] == [1000, 300, 200, 10]
    assert todos[0]["id"] == "archivo:" + todos[0]["ruta"] and todos[0]["tipo"] == "codigo"
    assert {"modificado", "accedido"} <= set(todos[0])

    imagenes = escaneado.get("/api/archivos", query_string={
        "tipos": "imagenes", "orden": "tamano", "sentido": "asc"}).get_json()
    assert [a["tamano"] for a in imagenes] == [200, 300]

    assert len(escaneado.get("/api/archivos", query_string={"limite": 1}).get_json()) == 1
    grandes = escaneado.get("/api/archivos", query_string={"min_mb": 0.0005}).get_json()
    assert [a["tamano"] for a in grandes] == [1000]

    for malo in ({"orden": "nombre"}, {"tipos": "musica"}, {"min_mb": "mucho"}):
        assert escaneado.get("/api/archivos", query_string=malo).status_code == 400


# ------------------------------------------------------------ mover

def test_mover_simula_por_defecto(escaneado, token, arbol, tmp_path):
    destino = tmp_path / "destino"
    destino.mkdir()
    foto = "archivo:" + str(arbol / "fotos" / "a.jpg")
    respuesta = escaneado.post("/api/mover", json={"ids": [foto], "destino": str(destino)},
                               headers=token)
    datos = respuesta.get_json()
    assert respuesta.status_code == 200 and datos["simulacion"] and datos["bytes_movidos"] == 300
    assert (arbol / "fotos" / "a.jpg").exists() and list(destino.iterdir()) == []


def test_mover_real(escaneado, token, arbol, tmp_path):
    destino = tmp_path / "destino"
    destino.mkdir()
    foto = "archivo:" + str(arbol / "fotos" / "a.jpg")
    cuerpo = {"ids": [foto, "regenerables-0"], "destino": str(destino), "simulacion": False}

    assert escaneado.post("/api/mover", json=cuerpo, headers=token).status_code == 400  # sin confirmar
    assert escaneado.post("/api/mover", json=cuerpo).status_code == 403                 # sin token

    respuesta = escaneado.post("/api/mover", json={**cuerpo, "confirmado": True}, headers=token)
    datos = respuesta.get_json()
    assert respuesta.status_code == 200 and len(datos["movidos"]) == 2
    assert (destino / "a.jpg").exists() and (destino / "node_modules" / "x.js").exists()
    assert not (arbol / "fotos" / "a.jpg").exists()

    # Lo movido desaparece de la tabla de archivos y de la lista de basura.
    assert all(not a["ruta"].endswith("a.jpg") for a in escaneado.get("/api/archivos").get_json())
    categorias = {c["clave"]: c for c in escaneado.get("/api/basura").get_json()}
    assert categorias["regenerables"]["elementos"] == []


def test_mover_solo_acepta_archivos_del_escaneo(escaneado, token, arbol, tmp_path):
    destino = tmp_path / "destino"
    destino.mkdir()
    ajeno = tmp_path / "ajeno.txt"
    ajeno.write_text("no pertenece al escaneo")
    for ids in (["archivo:" + str(ajeno)], [str(ajeno)], ["archivo:" + str(arbol / "fotos")]):
        respuesta = escaneado.post(
            "/api/mover", headers=token,
            json={"ids": ids, "destino": str(destino), "simulacion": False, "confirmado": True})
        assert respuesta.status_code == 400
    assert ajeno.exists() and (arbol / "fotos").exists()


def test_mover_destino_invalido(escaneado, token, arbol, tmp_path):
    foto = "archivo:" + str(arbol / "fotos" / "a.jpg")
    respuesta = escaneado.post("/api/mover", headers=token,
                               json={"ids": [foto], "destino": str(tmp_path / "no-existe")})
    assert respuesta.status_code == 400 and "no existe" in respuesta.get_json()["error"]


def test_papelera_acepta_archivos_de_la_tabla(escaneado, token, arbol, monkeypatch):
    import os
    monkeypatch.setattr("core.limpieza.send2trash", os.remove)
    foto = "archivo:" + str(arbol / "fotos" / "a.jpg")
    respuesta = escaneado.post("/api/limpiar", headers=token,
                               json={"ids": [foto], "simulacion": False, "confirmado": True})
    assert respuesta.status_code == 200 and respuesta.get_json()["bytes_liberados"] == 300
    assert not (arbol / "fotos" / "a.jpg").exists()


# ------------------------------------------------------------ historial, programados, red y PDF

def test_cada_escaneo_se_guarda_en_el_historial(app, cliente, token, arbol):
    assert cliente.get("/api/historial").get_json() == {"raiz": None, "escaneos": []}
    for _ in range(2):
        cliente.post("/api/escanear", json={"ruta": str(arbol)}, headers=token)
        app.config["GESTOR"].esperar(30)
        (arbol / "fotos" / f"nueva{_}.jpg").write_bytes(b"x" * 2 * 1024 * 1024)

    datos = cliente.get("/api/historial").get_json()
    assert datos["raiz"] == str(arbol) and len(datos["escaneos"]) == 2
    primero, segundo = datos["escaneos"]
    assert segundo["tamano_total"] - primero["tamano_total"] == 2 * 1024 * 1024

    comparacion = cliente.get("/api/comparar", query_string={
        "antes": primero["id"], "despues": segundo["id"]}).get_json()
    assert comparacion["diferencia_total"] == 2 * 1024 * 1024
    assert [(Path(c["ruta"]).name, c["diferencia"]) for c in comparacion["cambios"]] == [
        ("fotos", 2 * 1024 * 1024)]

    assert cliente.get("/api/comparar", query_string={"antes": "x", "despues": 1}).status_code == 400
    assert cliente.get("/api/comparar", query_string={"antes": 1, "despues": 999}).status_code == 400


def test_programados_desde_la_web(cliente, token, arbol, monkeypatch):
    from core import programador
    from tests.test_programador import SchtasksFalso
    from utils.sistema import WINDOWS
    falso = SchtasksFalso()
    for nombre in ("crear_tarea", "listar_tareas", "quitar_tarea"):
        real = getattr(programador, nombre)
        monkeypatch.setattr(f"web.app.{nombre}",
                            lambda *a, _f=real, **k: _f(*a, sistema=WINDOWS, ejecutar=falso, **k))

    assert cliente.get("/api/programados").get_json() == []
    cuerpo = {"ruta": str(arbol), "frecuencia": "semanal", "hora": "08:15"}
    assert cliente.post("/api/programados", json=cuerpo).status_code == 403          # sin token
    creada = cliente.post("/api/programados", json=cuerpo, headers=token)
    assert creada.status_code == 201 and creada.get_json()["hora"] == "08:15"
    assert [t["frecuencia"] for t in cliente.get("/api/programados").get_json()] == ["semanal"]

    assert cliente.post("/api/programados", json={**cuerpo, "hora": "tarde"}, headers=token).status_code == 400
    nombre = creada.get_json()["nombre"]
    assert cliente.post("/api/programados/quitar", json={"nombre": nombre}, headers=token).status_code == 200
    assert cliente.post("/api/programados/quitar", json={"nombre": nombre}, headers=token).status_code == 404
    assert cliente.post("/api/programados/quitar", json={"nombre": "..\\otra"}, headers=token).status_code == 400


def test_aviso_de_disco_de_red(app, cliente, token, arbol, monkeypatch):
    monkeypatch.setattr("web.tareas.es_ruta_de_red", lambda ruta: True)
    estado = cliente.post("/api/escanear", json={"ruta": str(arbol)}, headers=token).get_json()
    assert "disco de red" in estado["aviso"]
    app.config["GESTOR"].esperar(30)


def test_sin_aviso_en_disco_local(escaneado):
    assert escaneado.get("/api/estado").get_json()["aviso"] == ""


def test_reporte_pdf(escaneado):
    respuesta = escaneado.get("/api/reporte", query_string={"formato": "pdf"})
    assert respuesta.status_code == 200 and respuesta.mimetype == "application/pdf"
    assert respuesta.data.startswith(b"%PDF-")


# ------------------------------------------------------------ salud de los discos

@pytest.fixture
def smart_web(monkeypatch):
    from core import salud
    from tests.test_salud import SmartctlFalso
    falso = SmartctlFalso({"/dev/sda": "hdd_reasignados", "/dev/sdb": "ssd_sata",
                           "/dev/nvme0": "nvme_critico"})
    monkeypatch.setattr(salud, "_ejecutar", falso)
    avisos = []
    monkeypatch.setattr("core.alertas.notificar_escritorio", lambda t, x: avisos.append(t) or True)
    monkeypatch.setattr(
        "web.app.revisar_alertas",
        lambda discos, config: __import__("core.alertas", fromlist=["revisar"]).revisar(
            discos, config, notificar=lambda t, x: avisos.append(t) or True))
    return falso, avisos


def test_salud_en_la_web(cliente, token, smart_web):
    _, avisos = smart_web
    datos = cliente.get("/api/salud").get_json()
    assert datos["disponible"] and datos["alertas"] == [] and avisos == []   # ver no avisa
    estados = [(d["dispositivo"], d["estado"], d["nombre_estado"]) for d in datos["discos"]]
    assert estados == [("/dev/sda", "precaucion", "Precaución"), ("/dev/sdb", "bueno", "Bueno"),
                       ("/dev/nvme0", "malo", "Malo")]
    ssd = datos["discos"][1]
    assert ssd["vida_restante"] == 87 and ssd["temperatura"] == 29 and ssd["limite_temperatura"] == 55

    assert cliente.post("/api/salud/revisar").status_code == 403                # exige token
    revisado = cliente.post("/api/salud/revisar", headers=token).get_json()
    assert len(revisado["alertas"]) == 2 and len(avisos) == 2
    assert cliente.post("/api/salud/revisar", headers=token).get_json()["alertas"] == []


def test_salud_sin_smartctl_en_la_web(cliente, monkeypatch):
    monkeypatch.setattr("core.salud.buscar_smartctl", lambda: None)
    datos = cliente.get("/api/salud").get_json()
    assert datos["disponible"] is False and "smartmontools" in datos["instrucciones"]


def test_autoprueba_desde_la_web(cliente, token, smart_web):
    falso, _ = smart_web
    cuerpo = {"dispositivo": "/dev/sda", "tipo": "corta"}
    assert cliente.post("/api/salud/prueba", json=cuerpo).status_code == 403
    respuesta = cliente.post("/api/salud/prueba", json=cuerpo, headers=token)
    assert respuesta.status_code == 200 and "iniciada" in respuesta.get_json()["mensaje"]
    assert falso.comandos[-1][-4:] == ["short", "-d", "ata", "/dev/sda"]
    for malo in ({"dispositivo": "/dev/sdz"}, {"dispositivo": "/dev/sda", "tipo": "borrar"}, {}):
        assert cliente.post("/api/salud/prueba", json=malo, headers=token).status_code == 400
