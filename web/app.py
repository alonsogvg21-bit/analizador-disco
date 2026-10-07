"""Interfaz web local (Flask).

Seguridad:
- El servidor escucha solo en 127.0.0.1: no es accesible desde la red.
- Se rechazan peticiones cuyo encabezado Host no sea local (evita ataques
  de "DNS rebinding" desde páginas externas).
- Las peticiones que cambian algo (POST) exigen un token que solo conoce la
  página servida por este programa; otra web abierta en el navegador no
  puede lanzar escaneos ni, más adelante, limpiezas.
"""

from __future__ import annotations

import logging
import secrets
import socket
import tempfile
import threading
import webbrowser
from datetime import datetime
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, request, send_file

from core.arbol import arbol_json
from core.carpetas import contenido_de
from core.consulta import listar_archivos
from core.tipos import clasificar
from core.discos import resumen_discos
from core.historial import comparar, listar_escaneos
from core.limpieza import limpiar, requiere_doble_confirmacion
from core.programador import ErrorProgramador, crear_tarea, listar_tareas, quitar_tarea
from core.reporte_pdf import exportar_pdf
from core.alertas import leer_config
from core.alertas import revisar as revisar_alertas
from core.salud import (
    NOMBRES_ESTADO, ErrorSalud, SmartctlNoInstalado, iniciar_autoprueba, leer_todos,
)
from core.modelos import ElementoBasura
from core.mover import mover
from core.consulta import buscar_archivo
from utils.rutas import ruta_recurso
from utils.seguridad import es_ruta_protegida
from core.modelos import a_dict
from core.reporte import exportar_csv, exportar_html, reunir_datos
from utils.sistema import carpeta_descargas, carpeta_usuario
from web.tareas import LISTO, GestorEscaneo

HOST = "127.0.0.1"
HOSTS_PERMITIDOS = {"127.0.0.1", "localhost"}
# Una categoría puede tener miles de elementos diminutos; a la página solo
# se envían los más grandes.
MAX_ELEMENTOS_POR_CATEGORIA = 200
MAX_ARCHIVOS_EN_TABLA = 500
MAX_CAMBIOS = 100
# Los archivos de la tabla se identifican por su ruta, con este prefijo, para
# distinguirlos de los elementos de basura (que usan "categoria-numero").
PREFIJO_ARCHIVO = "archivo:"


def crear_app(gestor: GestorEscaneo | None = None) -> Flask:
    # Las carpetas se indican a mano para que se encuentren también dentro del ejecutable.
    app = Flask(__name__, template_folder=str(ruta_recurso("web", "templates")),
                static_folder=str(ruta_recurso("web", "static")))
    app.config["TOKEN"] = secrets.token_urlsafe(32)
    app.config["GESTOR"] = gestor = gestor or GestorEscaneo()

    def error(mensaje: str, codigo: int):
        return jsonify(error=mensaje), codigo

    @app.before_request
    def proteger():
        if request.host.split(":")[0] not in HOSTS_PERMITIDOS:
            abort(403)
        if request.method == "POST" and not secrets.compare_digest(
            request.headers.get("X-Token", ""), app.config["TOKEN"]
        ):
            return error("Petición no autorizada. Recarga la página.", 403)
        return None

    def resultado_o_error():
        if gestor.resultado is None or gestor.estado()["fase"] != LISTO:
            return None
        return gestor.resultado

    def seleccion_de_la_peticion(datos: dict):
        """Convierte los identificadores recibidos en elementos del último escaneo.

        Devuelve (elementos, simulacion, error). Solo se aceptan elementos de
        basura detectados o archivos que el escaneo encontró: la página no
        puede pedir que se toque una ruta cualquiera. Sin 'confirmado', nunca
        se pasa de la simulación.
        """
        ids = datos.get("ids")
        if not isinstance(ids, list) or not ids:
            return None, True, error("No hay nada seleccionado.", 400)
        elegidos = []
        for identificador in dict.fromkeys(map(str, ids)):
            if identificador in gestor.elementos:
                elegidos.append(gestor.elementos[identificador])
            elif identificador.startswith(PREFIJO_ARCHIVO):
                archivo = buscar_archivo(gestor.resultado, identificador[len(PREFIJO_ARCHIVO):])
                if archivo is not None:
                    elegidos.append(ElementoBasura(
                        archivo.path, archivo.tamano, "archivos",
                        limpiable=not es_ruta_protegida(archivo.ruta)))
        if not elegidos:
            return None, True, error("La selección ya no es válida. Vuelve a escanear.", 400)

        simulacion = bool(datos.get("simulacion", True))
        if not simulacion and datos.get("confirmado") is not True:
            return None, simulacion, error("Falta la confirmación.", 400)
        if (not simulacion and requiere_doble_confirmacion(elegidos)
                and datos.get("confirmado_doble") is not True):
            return None, simulacion, error(
                "Son más de 1 GB: hace falta confirmar por segunda vez.", 400)
        return elegidos, simulacion, None

    # ------------------------------------------------------------ página

    @app.get("/")
    def inicio():
        return render_template("index.html", token=app.config["TOKEN"])

    # ------------------------------------------------------------ datos

    @app.get("/api/discos")
    def discos():
        return jsonify(a_dict(resumen_discos()))

    @app.get("/api/sugerencias")
    def sugerencias():
        """Carpetas habituales para elegir con un clic."""
        home = carpeta_usuario()
        candidatas = [
            ("Carpeta personal", home),
            ("Descargas", carpeta_descargas(home)),
            ("Documentos", home / "Documents"),
            ("Escritorio", home / "Desktop"),
        ]
        return jsonify([
            {"nombre": nombre, "ruta": str(ruta)} for nombre, ruta in candidatas if ruta.is_dir()
        ])

    @app.post("/api/escanear")
    def iniciar_escaneo():
        datos = request.get_json(silent=True) or {}
        texto = str(datos.get("ruta", "")).strip()
        if not texto:
            return error("Escribe o elige una carpeta.", 400)
        ruta = Path(texto).expanduser()
        if not ruta.is_dir():
            return error(f"La carpeta no existe: {texto}", 400)
        if not gestor.iniciar(ruta, con_duplicados=bool(datos.get("duplicados", True))):
            return error("Ya hay un escaneo en marcha.", 409)
        return jsonify(gestor.estado()), 202

    @app.post("/api/cancelar")
    def cancelar():
        gestor.cancelar()
        return jsonify(ok=True)

    @app.get("/api/estado")
    def estado():
        return jsonify(gestor.estado())

    @app.get("/api/resultado")
    def resultado():
        r = resultado_o_error()
        if r is None:
            return error("Todavía no hay un escaneo terminado.", 404)
        return jsonify(
            raiz=str(r.raiz), tamano_total=r.tamano_total, num_archivos=r.num_archivos,
            errores=r.errores, bytes_en_nube=r.bytes_en_nube,
            tipos=a_dict(gestor.tipos),
            top=[{"ruta": a.ruta, "tamano": a.tamano, "modificado": a.modificado}
                 for a in gestor.top],
        )

    @app.get("/api/archivos")
    def archivos():
        """Tabla de archivos con orden y filtros. No vuelve a escanear."""
        r = resultado_o_error()
        if r is None:
            return error("Todavía no hay un escaneo terminado.", 404)
        argumentos = request.args
        try:
            min_mb = float(argumentos.get("min_mb") or 0)
            limite = min(max(int(argumentos.get("limite") or 50), 1), MAX_ARCHIVOS_EN_TABLA)
            lista = listar_archivos(
                r,
                orden=argumentos.get("orden", "tamano"),
                descendente=argumentos.get("sentido", "desc") != "asc",
                tipos=[t for t in argumentos.get("tipos", "").split(",") if t],
                tamano_minimo=int(max(min_mb, 0) * 1024 * 1024),
                limite=limite,
            )
        except ValueError as problema:
            return error(str(problema), 400)
        return jsonify([
            {"id": PREFIJO_ARCHIVO + a.ruta, "ruta": a.ruta, "tamano": a.tamano,
             "tipo": clasificar(a.ruta), "modificado": a.modificado, "accedido": a.accedido}
            for a in lista
        ])

    @app.get("/api/carpetas")
    def carpetas():
        """Un nivel del árbol. La página lo pide cada vez que se despliega una carpeta."""
        r = resultado_o_error()
        if r is None:
            return error("Todavía no hay un escaneo terminado.", 404)
        try:
            nivel = contenido_de(r, request.args.get("ruta") or None)
        except KeyError:
            return error("Esa carpeta no forma parte del escaneo.", 404)
        return jsonify(
            ruta=str(nivel.ruta), tamano=nivel.tamano,
            tamano_archivos_directos=nivel.tamano_archivos_directos,
            subcarpetas=[
                {"ruta": str(c.ruta), "nombre": c.ruta.name, "tamano": c.tamano,
                 "num_archivos": c.num_archivos,
                 "tiene_subcarpetas": bool(r.hijos.get(str(c.ruta)))}
                for c in nivel.subcarpetas
            ],
        )

    @app.get("/api/arbol")
    def arbol():
        """Dos niveles del árbol para el mapa de bloques. Al entrar en una carpeta se pide otra vez."""
        r = resultado_o_error()
        if r is None:
            return error("Todavía no hay un escaneo terminado.", 404)
        try:
            niveles = int(request.args.get("niveles", 2))
        except ValueError:
            return error("El número de niveles no es válido.", 400)
        try:
            return jsonify(arbol_json(r, request.args.get("ruta") or None, niveles=niveles))
        except KeyError:
            return error("Esa carpeta no forma parte del escaneo.", 404)

    @app.get("/api/basura")
    def basura():
        if resultado_o_error() is None:
            return error("Todavía no hay un escaneo terminado.", 404)
        # Índice inverso para recuperar el identificador de cada elemento.
        ids = {id(elemento): clave for clave, elemento in gestor.elementos.items()}
        salida = []
        for categoria in gestor.categorias:
            ordenados = sorted(categoria.elementos, key=lambda e: e.tamano, reverse=True)
            visibles = ordenados[:MAX_ELEMENTOS_POR_CATEGORIA]
            ocultos = ordenados[MAX_ELEMENTOS_POR_CATEGORIA:]
            salida.append({
                "clave": categoria.clave, "nombre": categoria.nombre,
                "descripcion": categoria.descripcion,
                "tamano_total": categoria.tamano_total,
                "tamano_limpiable": categoria.tamano_limpiable,
                "total_elementos": len(ordenados),
                "ocultos": len(ocultos),
                "tamano_ocultos": sum(e.tamano for e in ocultos),
                "elementos": [
                    {"id": ids[id(e)], "ruta": str(e.ruta), "tamano": e.tamano,
                     "limpiable": e.limpiable, "es_carpeta": e.es_carpeta, "detalle": e.detalle}
                    for e in visibles
                ],
            })
        return jsonify(salida)

    @app.post("/api/limpiar")
    def limpiar_seleccion():
        """Envía a la papelera los elementos elegidos en la página.

        Solo se aceptan identificadores de elementos que este servidor detectó
        en el último escaneo: la página no puede pedir que se borre una ruta
        cualquiera. Sin 'confirmado', nunca se pasa de la simulación.
        """
        if resultado_o_error() is None:
            return error("Todavía no hay un escaneo terminado.", 404)
        if gestor.en_curso():
            return error("Espera a que termine el escaneo.", 409)

        datos = request.get_json(silent=True) or {}
        elegidos, simulacion, problema = seleccion_de_la_peticion(datos)
        if problema:
            return problema

        hecho = limpiar(elegidos, simulacion=simulacion)
        if not simulacion:
            gestor.quitar(hecho.enviados)
        return jsonify(
            simulacion=hecho.simulacion,
            bytes_liberados=hecho.bytes_liberados,
            enviados=[str(e.ruta) for e in hecho.enviados],
            omitidos=[{"ruta": str(e.ruta), "motivo": motivo} for e, motivo in hecho.omitidos],
        )

    @app.post("/api/mover")
    def mover_seleccion():
        """Mueve los elementos elegidos a otra carpeta. Mismas garantías que /api/limpiar."""
        if resultado_o_error() is None:
            return error("Todavía no hay un escaneo terminado.", 404)
        if gestor.en_curso():
            return error("Espera a que termine el escaneo.", 409)

        datos = request.get_json(silent=True) or {}
        elegidos, simulacion, problema = seleccion_de_la_peticion(datos)
        if problema:
            return problema
        try:
            hecho = mover(elegidos, str(datos.get("destino", "")), simulacion=simulacion)
        except ValueError as fallo:
            return error(str(fallo), 400)

        if not simulacion:
            gestor.quitar([elemento for elemento, _ in hecho.movidos])
        return jsonify(
            simulacion=hecho.simulacion,
            destino=str(hecho.destino),
            bytes_movidos=hecho.bytes_movidos,
            movidos=[{"ruta": str(e.ruta), "nueva": str(nueva)} for e, nueva in hecho.movidos],
            omitidos=[{"ruta": str(e.ruta), "motivo": motivo} for e, motivo in hecho.omitidos],
        )

    @app.get("/api/reporte")
    def reporte():
        r = resultado_o_error()
        if r is None:
            return error("Todavía no hay un escaneo terminado.", 404)
        formato = request.args.get("formato", "html")
        exportadores = {
            "html": (exportar_html, "text/html"),
            "csv": (exportar_csv, "text/csv"),
            "pdf": (exportar_pdf, "application/pdf"),
        }
        if formato not in exportadores:
            return error("Formato no válido.", 400)
        exportar, tipo = exportadores[formato]
        datos = reunir_datos(r, gestor.categorias)
        nombre = f"reporte-disco-{datetime.now():%Y%m%d-%H%M%S}.{formato}"
        destino = Path(tempfile.mkdtemp(prefix="analizador-disco-")) / nombre
        exportar(datos, destino)
        # El tipo se indica a mano: Windows a veces registra .csv como archivo de Excel.
        return send_file(destino, as_attachment=True, download_name=nombre, mimetype=tipo)

    # ------------------------------------------------------------ historial

    def escaneo_a_json(escaneo):
        return {"id": escaneo.id, "raiz": escaneo.raiz, "fecha": escaneo.fecha.isoformat(),
                "tamano_total": escaneo.tamano_total, "num_archivos": escaneo.num_archivos}

    @app.get("/api/historial")
    def historial():
        """Escaneos guardados de una carpeta (por defecto, la del último escaneo)."""
        raiz = request.args.get("raiz") or (str(gestor.resultado.raiz) if gestor.resultado else None)
        if raiz is None:
            return jsonify(raiz=None, escaneos=[])
        return jsonify(raiz=raiz, escaneos=[escaneo_a_json(e) for e in listar_escaneos(raiz)])

    @app.get("/api/comparar")
    def comparar_escaneos():
        try:
            comparacion = comparar(int(request.args.get("antes", "")),
                                   int(request.args.get("despues", "")), minimo=1024 * 1024)
        except ValueError as problema:
            mensaje = str(problema)
            return error(mensaje if "escaneo" in mensaje else "Elige dos escaneos.", 400)
        return jsonify(
            antes=escaneo_a_json(comparacion.antes),
            despues=escaneo_a_json(comparacion.despues),
            diferencia_total=comparacion.diferencia_total,
            total_cambios=len(comparacion.cambios),
            cambios=[{"ruta": c.ruta, "antes": c.antes, "despues": c.despues,
                      "diferencia": c.diferencia} for c in comparacion.cambios[:MAX_CAMBIOS]],
        )

    # ------------------------------------------------------------ salud de los discos (SMART)

    def salud_a_json(avisar: bool):
        """Lee la salud de todos los discos. Con avisar=True, además envía las alertas nuevas."""
        config = leer_config()
        try:
            discos = leer_todos(umbrales=config.umbrales())
        except SmartctlNoInstalado as problema:
            return jsonify(disponible=False, instrucciones=str(problema), discos=[], alertas=[])
        except ErrorSalud as problema:
            return error(str(problema), 500)
        alertas = revisar_alertas(discos, config).alertas if avisar else []
        return jsonify(
            disponible=True,
            discos=[{**a_dict(d), "nombre_estado": NOMBRES_ESTADO[d.estado]} for d in discos],
            alertas=[a_dict(a) for a in alertas],
        )

    @app.get("/api/salud")
    def salud():
        return salud_a_json(avisar=False)

    @app.post("/api/salud/revisar")
    def salud_revisar():
        """Lo usa el botón Actualizar: vuelve a leer y avisa si algo ha empeorado."""
        return salud_a_json(avisar=True)

    @app.post("/api/salud/prueba")
    def salud_prueba():
        datos = request.get_json(silent=True) or {}
        try:
            mensaje = iniciar_autoprueba(str(datos.get("dispositivo", "")), str(datos.get("tipo", "corta")))
        except ErrorSalud as problema:
            return error(str(problema), 400)
        return jsonify(mensaje=mensaje)

    # ------------------------------------------------------------ escaneos programados

    @app.get("/api/programados")
    def programados():
        try:
            return jsonify([a_dict(t) for t in listar_tareas()])
        except ErrorProgramador as problema:
            return error(str(problema), 500)

    @app.post("/api/programados")
    def programar():
        datos = request.get_json(silent=True) or {}
        try:
            tarea = crear_tarea(str(datos.get("ruta", "")), str(datos.get("frecuencia", "diaria")),
                                str(datos.get("hora", "09:00")))
        except ErrorProgramador as problema:
            return error(str(problema), 400)
        return jsonify(a_dict(tarea)), 201

    @app.post("/api/programados/quitar")
    def desprogramar():
        datos = request.get_json(silent=True) or {}
        try:
            quitada = quitar_tarea(str(datos.get("nombre", "")))
        except ErrorProgramador as problema:
            return error(str(problema), 400)
        return jsonify(ok=quitada) if quitada else error("Esa tarea ya no existe.", 404)

    return app


def _puerto_libre(preferido: int, intentos: int = 20) -> int:
    """Devuelve el primer puerto disponible a partir del preferido."""
    for puerto in range(preferido, preferido + intentos):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as prueba:
            try:
                prueba.bind((HOST, puerto))
                return puerto
            except OSError:
                continue
    raise OSError(f"No hay puertos libres entre {preferido} y {preferido + intentos - 1}.")


def iniciar(puerto: int = 5000, abrir_navegador: bool = True) -> int:
    """Arranca el servidor local y, si se pide, abre el navegador."""
    puerto = _puerto_libre(puerto)
    direccion = f"http://{HOST}:{puerto}"
    # Sin esto, la consola se llena con una línea por cada consulta de progreso.
    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    print(f"Analizador de disco abierto en {direccion}")
    print("Solo es accesible desde este equipo. Pulsa Ctrl+C para cerrarlo.")
    if abrir_navegador:
        threading.Timer(0.8, webbrowser.open, args=(direccion,)).start()

    crear_app().run(host=HOST, port=puerto, debug=False, threaded=True)
    return 0
