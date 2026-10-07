"""Interfaz de terminal.

Aquí no hay lógica de análisis: cada comando llama al motor (core) y solo
se encarga de mostrar el resultado. Todos los comandos son de solo lectura,
excepto 'limpiar'.
"""

from __future__ import annotations

import argparse
import os
import smtplib
import sys
import time
from datetime import datetime
from pathlib import Path

from core.basura import ANTIGUOS, DUPLICADOS, MB, REGENERABLES, detectar_basura
from core.historial import comparar, escaneo_cercano, guardar_escaneo, listar_escaneos
from core.limpieza import ResultadoLimpieza, limpiar
from core.modelos import ElementoBasura
from core.mover import ResultadoMovimiento, mover, validar_destino
from utils.seguridad import es_ruta_protegida
from core.reglas.base import CACHE, TEMPORALES
from core.carpetas import contenido_de
from core.consulta import ORDENES, listar_archivos
from core.discos import resumen_discos
from core.duplicados import buscar_duplicados
from core.escaner import escanear
from core.modelos import CategoriaBasura, ResultadoEscaneo
from core.alertas import (
    VARIABLE_CLAVE, enviar_correo, guardar_config, leer_config, notificar_escritorio,
)
from core.alertas import revisar as revisar_alertas
from core.programador import (
    FRECUENCIAS, ErrorProgramador, crear_tarea, crear_tarea_salud, listar_tareas, quitar_tarea,
)
from core.salud import (
    NOMBRES_ESTADO, TIPOS_DE_PRUEBA, ErrorSalud, SaludDisco, iniciar_autoprueba, leer_todos,
)
from core.reporte import exportar_csv, exportar_html, reunir_datos
from core.reporte_pdf import exportar_pdf
from utils.red import AVISO_RED, es_ruta_de_red
from core.tipos import TIPOS, clasificar, resumen_por_tipo
from utils.formato import diferencia_en_mb, fecha_legible, porcentaje, tamano_legible

ANCHO_BARRA = 24

# Lo que el comando 'limpiar' acepta. Papelera, descargas y registros son
# solo informativos y no aparecen aquí.
CATEGORIAS_LIMPIABLES = (TEMPORALES, CACHE, REGENERABLES, DUPLICADOS, ANTIGUOS)
# Estas tres salen del escaneo de una carpeta; sin RUTA no hay dónde buscarlas.
CATEGORIAS_CON_RUTA = {REGENERABLES, DUPLICADOS, ANTIGUOS}
PALABRA_CONFIRMACION = "ELIMINAR"
PALABRA_MOVER = "MOVER"


# ---------------------------------------------------------------- ayudas de salida

def _barra(porc: float, ancho: int = ANCHO_BARRA) -> str:
    llenos = round(max(0.0, min(porc, 100.0)) * ancho / 100)
    return "[" + "#" * llenos + "-" * (ancho - llenos) + "]"


def _titulo(texto: str) -> None:
    print(f"\n{texto}\n{'=' * len(texto)}")


class _Progreso:
    """Línea de avance en stderr, para no ensuciar la salida si se redirige a un archivo."""

    def __init__(self, activo: bool) -> None:
        # Solo se dibuja en una terminal real y si no se pidió --silencioso.
        self.activo = activo and sys.stderr.isatty()
        self._ultimo = 0.0

    def escaneo(self, archivos: int, carpeta: str) -> None:
        self._escribir(f"Escaneando... {archivos:,} archivos")

    def hashes(self, hechos: int, total: int) -> None:
        self._escribir(f"Comparando posibles duplicados... {hechos:,} de {total:,}")

    def _escribir(self, texto: str) -> None:
        ahora = time.monotonic()
        if self.activo and ahora - self._ultimo >= 0.1:
            self._ultimo = ahora
            sys.stderr.write(f"\r{texto:<70}")
            sys.stderr.flush()

    def fin(self) -> None:
        if self.activo:
            sys.stderr.write("\r" + " " * 70 + "\r")
            sys.stderr.flush()


def _escanear(args: argparse.Namespace, progreso: _Progreso) -> ResultadoEscaneo:
    if es_ruta_de_red(args.ruta):
        print(f"Aviso: {AVISO_RED}", file=sys.stderr)
    resultado = escanear(args.ruta, progreso=progreso.escaneo)
    progreso.fin()
    return resultado


def _pie(resultado: ResultadoEscaneo) -> None:
    """Avisos comunes al final de un análisis."""
    if resultado.errores:
        print(f"\nNota: {resultado.errores} elementos no se pudieron leer "
              "(sin permisos o en uso) y se ignoraron.")
    if resultado.bytes_en_nube:
        print(f"Nota: {tamano_legible(resultado.bytes_en_nube)} están solo en la nube "
              "(OneDrive) y no ocupan disco; no se cuentan.")


# ---------------------------------------------------------------- comandos

def cmd_resumen(args: argparse.Namespace) -> int:
    _titulo("Discos")
    for d in resumen_discos():
        print(f"{d.punto_montaje:<12} {_barra(d.porcentaje)} {d.porcentaje:5.1f}%   "
              f"usado {tamano_legible(d.usado):>9} de {tamano_legible(d.total):>9}   "
              f"libre {tamano_legible(d.libre):>9}")
    return 0


def _imprimir_nivel(resultado: ResultadoEscaneo, ruta: Path, total: int,
                    niveles: int, limite: int, sangria: int = 0) -> None:
    nivel = contenido_de(resultado, ruta)
    margen = "    " * sangria
    for carpeta in nivel.subcarpetas[:limite]:
        # En el primer nivel se muestra la ruta completa; debajo basta el nombre.
        nombre = str(carpeta.ruta) if sangria == 0 else carpeta.ruta.name
        print(f"{margen}{tamano_legible(carpeta.tamano):>10}  "
              f"{porcentaje(carpeta.tamano, total):5.1f}%  {nombre}")
        if niveles > 1:
            _imprimir_nivel(resultado, carpeta.ruta, total, niveles - 1, limite, sangria + 1)
    ocultas = len(nivel.subcarpetas) - limite
    if ocultas > 0:
        print(f"{margen}{'':>10}          ... y {ocultas} carpetas más")
    if sangria == 0 and nivel.tamano_archivos_directos:
        print(f"{tamano_legible(nivel.tamano_archivos_directos):>10}  "
              f"{porcentaje(nivel.tamano_archivos_directos, total):5.1f}%  (archivos sueltos)")


def cmd_carpetas(args: argparse.Namespace) -> int:
    resultado = _escanear(args, _Progreso(not args.silencioso))
    _titulo(f"Carpetas de {resultado.raiz} — {tamano_legible(resultado.tamano_total)}")
    _imprimir_nivel(resultado, resultado.raiz, resultado.tamano_total,
                    args.profundidad, args.limite)
    _pie(resultado)
    return 0


_TITULOS_ORDEN = {
    ("tamano", False): "más pesados", ("tamano", True): "más pequeños",
    ("modificado", False): "modificados más recientemente",
    ("modificado", True): "que llevan más tiempo sin modificarse",
    ("accedido", False): "abiertos más recientemente",
    ("accedido", True): "que llevan más tiempo sin abrirse",
}


def cmd_top(args: argparse.Namespace) -> int:
    resultado = _escanear(args, _Progreso(not args.silencioso))
    archivos = listar_archivos(
        resultado, orden=args.orden, descendente=not args.ascendente,
        tipos=args.tipo, tamano_minimo=int(args.min_mb * MB), limite=args.cantidad,
    )
    filtros = []
    if args.tipo:
        filtros.append("tipo " + ", ".join(args.tipo))
    if args.min_mb:
        filtros.append(f"desde {args.min_mb:g} MB")
    _titulo(f"Los {args.cantidad} archivos {_TITULOS_ORDEN[args.orden, args.ascendente]} "
            f"de {resultado.raiz}" + (f" ({'; '.join(filtros)})" if filtros else ""))
    print(f"{'':>4} {'Tamaño':>10}  {'Modificado':<16}  {'Último acceso':<16}  Archivo")
    for posicion, archivo in enumerate(archivos, 1):
        print(f"{posicion:>3}. {tamano_legible(archivo.tamano):>10}  "
              f"{fecha_legible(archivo.modificado):<16}  "
              f"{fecha_legible(archivo.accedido):<16}  {archivo.ruta}")
    if not archivos:
        print("Ningún archivo cumple esos filtros.")
    _pie(resultado)
    return 0


def cmd_tipos(args: argparse.Namespace) -> int:
    resultado = _escanear(args, _Progreso(not args.silencioso))
    _titulo(f"Tipos de archivo en {resultado.raiz}")
    for tipo in resumen_por_tipo(resultado.archivos):
        porc = porcentaje(tipo.tamano, resultado.tamano_total)
        print(f"{tipo.tipo:<13} {_barra(porc)} {porc:5.1f}%  "
              f"{tamano_legible(tipo.tamano):>10}  {tipo.cantidad:>9,} archivos")
    _pie(resultado)
    return 0


def _imprimir_basura(categorias: list[CategoriaBasura], limite: int) -> None:
    liberable = 0
    for categoria in categorias:
        if not categoria.elementos:
            continue
        liberable += categoria.tamano_limpiable
        _titulo(f"{categoria.nombre} — {tamano_legible(categoria.tamano_total)} "
                f"({len(categoria.elementos)} elementos)")
        print(categoria.descripcion)
        mayores = sorted(categoria.elementos, key=lambda e: e.tamano, reverse=True)
        for elemento in mayores[:limite]:
            marca = "" if elemento.limpiable else "  [solo informativo]"
            print(f"  {tamano_legible(elemento.tamano):>10}  {elemento.ruta}{marca}")
            if elemento.detalle:
                print(f"  {'':>10}    {elemento.detalle}")
        if len(mayores) > limite:
            print(f"  {'':>10}  ... y {len(mayores) - limite} más "
                  "(usa --limite o el comando 'reporte' para verlos todos)")

    print(f"\nEspacio que se podría liberar: {tamano_legible(liberable)}")
    print("Solo se ha analizado: no se ha borrado ni movido nada.")


def cmd_basura(args: argparse.Namespace) -> int:
    progreso = _Progreso(not args.silencioso)
    resultado = None
    if args.ruta:
        resultado = _escanear(args, progreso)
    categorias = detectar_basura(
        resultado,
        dias_antiguedad=args.dias,
        tamano_minimo_antiguos=int(args.min_mb * MB),
        tamano_minimo_duplicados=int(args.min_mb * MB),
        incluir_duplicados=not args.sin_duplicados,
        progreso=progreso.hashes,
    )
    progreso.fin()
    _imprimir_basura(categorias, args.limite)
    if resultado is None:
        print("\nSin una RUTA solo se revisan las ubicaciones conocidas (temporales, caché, "
              "papelera).\nPara buscar también duplicados, archivos antiguos y carpetas "
              "regenerables, indica una carpeta.")
    else:
        _pie(resultado)
    return 0


def cmd_duplicados(args: argparse.Namespace) -> int:
    progreso = _Progreso(not args.silencioso)
    resultado = _escanear(args, progreso)
    grupos = buscar_duplicados(resultado.archivos, int(args.min_mb * MB), progreso.hashes)
    progreso.fin()

    recuperable = sum(g.espacio_recuperable for g in grupos)
    _titulo(f"Duplicados en {resultado.raiz} — {len(grupos)} grupos, "
            f"{tamano_legible(recuperable)} recuperables")
    for grupo in grupos[:args.limite]:
        print(f"\n{tamano_legible(grupo.tamano)} x {len(grupo.archivos)} copias "
              f"(sobran {tamano_legible(grupo.espacio_recuperable)})")
        for indice, ruta in enumerate(grupo.archivos):
            print(f"  {'original' if indice == 0 else 'copia   '}  {ruta}")
    if len(grupos) > args.limite:
        print(f"\n... y {len(grupos) - args.limite} grupos más (usa --limite).")
    if not grupos:
        print("No se encontraron duplicados.")
    _pie(resultado)
    return 0


def cmd_reporte(args: argparse.Namespace) -> int:
    progreso = _Progreso(not args.silencioso)
    resultado = _escanear(args, progreso)
    categorias = detectar_basura(
        resultado, incluir_duplicados=not args.sin_duplicados, progreso=progreso.hashes)
    progreso.fin()
    datos = reunir_datos(resultado, categorias)

    carpeta = Path(args.salida)
    base = f"reporte-disco-{datetime.now():%Y%m%d-%H%M%S}"
    if args.formato in ("html", "ambos", "todos"):
        print("Reporte HTML:", exportar_html(datos, carpeta / f"{base}.html").resolve())
    if args.formato in ("csv", "ambos", "todos"):
        print("Reporte CSV: ", exportar_csv(datos, carpeta / f"{base}.csv").resolve())
    if args.formato in ("pdf", "todos"):
        print("Reporte PDF: ", exportar_pdf(datos, carpeta / f"{base}.pdf").resolve())
    _pie(resultado)
    return 0


# ---------------------------------------------------------------- salud de los discos (SMART)

def _imprimir_salud(disco: SaludDisco) -> None:
    def dato(valor, sufijo: str = "") -> str:
        return "sin dato" if valor is None else f"{valor:,}{sufijo}"

    print(f"\n{disco.dispositivo} — {disco.modelo or 'modelo desconocido'}   "
          f"[{NOMBRES_ESTADO[disco.estado].upper()}]")
    if disco.error:
        print(f"  {disco.error}")
        return
    tipo = "SSD NVMe" if disco.es_nvme else "SSD" if disco.es_ssd else "Disco duro" if disco.es_ssd is False else "?"
    print(f"  {tipo} · {tamano_legible(disco.capacidad)} · {disco.interfaz} · "
          f"firmware {disco.firmware} · serie {disco.serie}")
    anios = f" ({disco.horas_encendido / 8766:.1f} años)" if disco.horas_encendido else ""
    print(f"  Temperatura: {dato(disco.temperatura, ' °C')} (límite {disco.limite_temperatura} °C)   "
          f"Horas de uso: {dato(disco.horas_encendido)}{anios}   "
          f"Encendidos: {dato(disco.ciclos_encendido)}")
    if disco.es_nvme:
        print(f"  Errores de medio: {dato(disco.errores_de_medio)}")
    else:
        print(f"  Sectores reasignados: {dato(disco.sectores_reasignados)}   "
              f"pendientes: {dato(disco.sectores_pendientes)}   "
              f"incorregibles: {dato(disco.sectores_incorregibles)}")
    if disco.vida_restante is not None:
        print(f"  Vida restante del SSD: {_barra(disco.vida_restante, 20)} {disco.vida_restante} %")
    prueba = disco.autoprueba
    if prueba is None:
        print("  Autoprueba: todavía no se ha hecho ninguna.")
    elif prueba.en_curso:
        print(f"  Autoprueba: en curso, falta un {prueba.porcentaje_restante} %.")
    else:
        veredicto = "correcta" if prueba.correcta else "CON ERROR" if prueba.correcta is False else "?"
        cuando = f" (a las {prueba.horas:,} h de uso)" if prueba.horas is not None else ""
        print(f"  Última autoprueba: {prueba.tipo} — {prueba.resultado} [{veredicto}]{cuando}")
    for motivo in disco.motivos:
        print(f"  ! {motivo}")


def _si_o_no(texto: str) -> bool:
    if texto.lower() in ("si", "sí", "s", "on", "1"):
        return True
    if texto.lower() in ("no", "n", "off", "0"):
        return False
    raise argparse.ArgumentTypeError("escribe 'si' o 'no'")


def _temperatura(texto: str) -> int | None:
    if texto.lower() in ("auto", "automatico", "automático"):
        return None
    valor = int(texto)
    if not 20 <= valor <= 100:
        raise argparse.ArgumentTypeError("usa un valor entre 20 y 100, o 'auto'")
    return valor


_SIN_CAMBIO = object()  # distingue "no se indicó la opción" de "se indicó 'auto'"


def _cmd_salud_alertas(args: argparse.Namespace) -> int:
    config = leer_config()
    cambios = {
        "escritorio": args.escritorio, "correo_activo": args.correo,
        "smtp_servidor": args.smtp_servidor, "smtp_puerto": args.smtp_puerto,
        "smtp_usuario": args.smtp_usuario, "smtp_tls": args.smtp_tls,
        "correo_de": args.correo_de, "correo_para": args.correo_para,
    }
    cambios = {campo: valor for campo, valor in cambios.items() if valor is not None}
    if args.temperatura is not _SIN_CAMBIO:
        cambios["temperatura_limite"] = args.temperatura
    if cambios:
        for campo, valor in cambios.items():
            setattr(config, campo, valor)
        guardar_config(config)
        print("Configuración guardada.")

    limite = "automático (55 °C en SATA, 70 °C en NVMe)" if config.temperatura_limite is None \
        else f"{config.temperatura_limite} °C"
    _titulo("Alertas de salud")
    print(f"Notificación de escritorio: {'sí' if config.escritorio else 'no'}")
    print(f"Límite de temperatura:      {limite}")
    print(f"Correo:                     {'sí' if config.correo_activo else 'no'}")
    if config.correo_activo or config.smtp_servidor:
        print(f"  Servidor SMTP:  {config.smtp_servidor or '(sin configurar)'}:{config.smtp_puerto} "
              f"({'con' if config.smtp_tls else 'sin'} cifrado TLS)")
        print(f"  Usuario:        {config.smtp_usuario or '(ninguno)'}")
        print(f"  De / para:      {config.correo_de or '(sin configurar)'} -> "
              f"{config.correo_para or '(sin configurar)'}")
        print(f"  Contraseña:     variable de entorno {VARIABLE_CLAVE} "
              f"({'definida' if os.environ.get(VARIABLE_CLAVE) else 'NO definida'})")

    if args.probar:
        print("\nEnviando un aviso de prueba...")
        titulo, texto = "Analizador de disco: aviso de prueba", "Si ves esto, las alertas funcionan."
        if config.escritorio:
            print("  Escritorio:", "mostrado" if notificar_escritorio(titulo, texto) else "no se pudo mostrar")
        if config.correo_activo:
            try:
                enviar_correo(config, titulo, texto)
                print(f"  Correo: enviado a {config.correo_para}")
            except (ValueError, OSError, smtplib.SMTPException) as problema:
                print(f"  Correo: no se pudo enviar ({problema})")
                return 1
    return 0


def cmd_salud(args: argparse.Namespace) -> int:
    """Salud SMART de los discos. Todo es lectura: no se escribe nada en ellos."""
    accion = args.accion or "ver"
    try:
        if accion == "alertas":
            return _cmd_salud_alertas(args)
        if accion == "programar":
            tarea = crear_tarea_salud(args.frecuencia, args.hora)
            cuando = "cada lunes" if tarea.frecuencia == "semanal" else "cada día"
            print(f"Revisión de salud programada {cuando} a las {tarea.hora}.")
            print(f"Para quitarla:  python main.py cli programar quitar {tarea.nombre}")
            return 0
        if accion == "prueba":
            print(iniciar_autoprueba(args.disco, args.tipo))
            return 0

        config = leer_config()
        discos = leer_todos(umbrales=config.umbrales())
        if not discos:
            print("smartctl no detectó ningún disco.")
            return 0
        _titulo("Salud de los discos")
        for disco in discos:
            _imprimir_salud(disco)

        if accion == "revisar":
            revision = revisar_alertas(discos, config)
            print(f"\nAlertas nuevas: {len(revision.alertas)}")
            for alerta in revision.alertas:
                print(f"  {alerta.titulo}. {alerta.texto}")
            for fallo in revision.fallos_de_envio:
                print(f"  Aviso: {fallo}", file=sys.stderr)
    except (ErrorSalud, ErrorProgramador) as problema:
        print(f"\n{problema}", file=sys.stderr)
        return 1
    return 0


# ---------------------------------------------------------------- escaneos programados

def cmd_programar(args: argparse.Namespace) -> int:
    """Crea, lista o quita escaneos periódicos en el programador de tareas del sistema."""
    try:
        if args.accion == "crear":
            tarea = crear_tarea(args.ruta, args.frecuencia, args.hora)
            cuando = "cada lunes" if tarea.frecuencia == "semanal" else "cada día"
            print(f"Tarea creada: {tarea.nombre}")
            print(f"Se escaneará {tarea.ruta} {cuando} a las {tarea.hora} "
                  "y el resultado se guardará en el historial.")
            print("Para quitarla:  python main.py cli programar quitar " + tarea.nombre)
        elif args.accion == "listar":
            tareas = listar_tareas()
            if not tareas:
                print("No hay escaneos programados.")
                return 0
            _titulo("Escaneos programados")
            for tarea in tareas:
                print(f"{tarea.nombre:<42} {tarea.frecuencia:<8} {tarea.hora:<6} {tarea.ruta}")
        else:
            if quitar_tarea(args.nombre):
                print(f"Tarea quitada: {args.nombre}")
            else:
                print(f"No existe ninguna tarea llamada {args.nombre}.")
                return 1
    except ErrorProgramador as problema:
        print(f"Error: {problema}", file=sys.stderr)
        return 1
    return 0


# ---------------------------------------------------------------- historial

def cmd_guardar(args: argparse.Namespace) -> int:
    """Escanea y guarda el resultado en el historial (lo usan los escaneos programados)."""
    resultado = _escanear(args, _Progreso(not args.silencioso))
    anteriores = listar_escaneos(resultado.raiz)
    guardado = guardar_escaneo(resultado)
    print(f"Escaneo guardado ({guardado.fecha:%Y-%m-%d %H:%M}): {resultado.raiz} ocupa "
          f"{tamano_legible(guardado.tamano_total)} en {guardado.num_archivos:,} archivos.")
    if anteriores:
        previo = anteriores[-1]
        print(f"Cambio desde el escaneo anterior ({previo.fecha:%Y-%m-%d %H:%M}): "
              f"{diferencia_en_mb(guardado.tamano_total - previo.tamano_total)}")
    _pie(resultado)
    return 0


def cmd_historial(args: argparse.Namespace) -> int:
    escaneos = listar_escaneos(args.ruta.resolve() if args.ruta else None)
    if not escaneos:
        print("Todavía no hay escaneos guardados. Usa el comando 'guardar' o escanea desde la web.")
        return 0
    _titulo("Escaneos guardados")
    print(f"{'Id':>4}  {'Fecha':<16}  {'Tamaño':>10}  {'Cambio':>14}  Carpeta")
    ultimo_por_raiz: dict[str, int] = {}
    for escaneo in escaneos:
        previo = ultimo_por_raiz.get(escaneo.raiz)
        cambio = "" if previo is None else diferencia_en_mb(escaneo.tamano_total - previo)
        ultimo_por_raiz[escaneo.raiz] = escaneo.tamano_total
        print(f"{escaneo.id:>4}  {escaneo.fecha:%Y-%m-%d %H:%M}  "
              f"{tamano_legible(escaneo.tamano_total):>10}  {cambio:>14}  {escaneo.raiz}")
    return 0


def cmd_comparar(args: argparse.Namespace) -> int:
    raiz = args.ruta.resolve()
    escaneos = listar_escaneos(raiz)
    if len(escaneos) < 2:
        print(f"Hacen falta al menos dos escaneos guardados de {raiz} "
              f"(hay {len(escaneos)}). Usa el comando 'guardar'.")
        return 1

    # Sin fechas: los dos últimos. Con fechas: el escaneo más cercano a cada una.
    antes = escaneo_cercano(raiz, args.desde) if args.desde else escaneos[-2]
    despues = escaneo_cercano(raiz, args.hasta) if args.hasta else escaneos[-1]
    if antes.id == despues.id:
        print("Las dos fechas corresponden al mismo escaneo; elige fechas más separadas.")
        return 1

    comparacion = comparar(antes.id, despues.id, minimo=int(args.min_mb * MB))
    antes, despues = comparacion.antes, comparacion.despues
    _titulo(f"Cambios en {raiz}")
    print(f"Antes:   {antes.fecha:%Y-%m-%d %H:%M}  {tamano_legible(antes.tamano_total):>10}")
    print(f"Después: {despues.fecha:%Y-%m-%d %H:%M}  {tamano_legible(despues.tamano_total):>10}")
    print(f"Cambio total: {diferencia_en_mb(comparacion.diferencia_total)}")

    for titulo, cambios in (
        ("Carpetas que crecieron", [c for c in comparacion.cambios if c.diferencia > 0]),
        ("Carpetas que disminuyeron", [c for c in comparacion.cambios if c.diferencia < 0]),
    ):
        if not cambios:
            continue
        print(f"\n{titulo}:")
        for cambio in cambios[:args.limite]:
            nota = "  (nueva)" if cambio.antes == 0 else "  (ya no existe)" if cambio.despues == 0 else ""
            print(f"  {diferencia_en_mb(cambio.diferencia):>14}  {cambio.ruta}{nota}")
        if len(cambios) > args.limite:
            print(f"  {'':>14}  ... y {len(cambios) - args.limite} más (usa --limite)")
    if not comparacion.cambios:
        print("\nNinguna carpeta cambió de tamaño.")
    return 0


def cmd_limpiar(args: argparse.Namespace) -> int:
    """Único comando que puede modificar el disco. Siempre lista y pide confirmación."""
    categorias_pedidas = [c.strip().lower() for c in args.categorias.split(",") if c.strip()]
    desconocidas = sorted(set(categorias_pedidas) - set(CATEGORIAS_LIMPIABLES))
    if desconocidas:
        print(f"Categorías no válidas: {', '.join(desconocidas)}. "
              f"Opciones: {', '.join(CATEGORIAS_LIMPIABLES)}", file=sys.stderr)
        return 2
    necesitan_ruta = sorted(set(categorias_pedidas) & CATEGORIAS_CON_RUTA)
    if necesitan_ruta and not args.ruta:
        print(f"Para limpiar {', '.join(necesitan_ruta)} hay que indicar una RUTA "
              "donde buscarlos.", file=sys.stderr)
        return 2

    # 1. Analizar (solo lectura).
    resultado = _escanear(args, _Progreso(not args.silencioso)) if args.ruta else None
    elegidos = _basura_elegida(args, resultado, categorias_pedidas)
    if not elegidos:
        print("No hay nada que limpiar en esas categorías.")
        return 0

    # 2. Mostrar la lista exacta, sin recortar.
    total = _listar_elegidos("Elementos que se enviarían a la papelera", elegidos)
    print(f"\nTotal: {len(elegidos)} elementos, {tamano_legible(total)} a liberar.")

    # 3. Simulación: se termina aquí sin tocar nada.
    if args.dry_run:
        simulado = limpiar(elegidos, simulacion=True)
        _mostrar_omitidos(simulado)
        print(f"\nSIMULACIÓN: se habrían enviado {len(simulado.enviados)} elementos "
              f"({tamano_legible(simulado.bytes_liberados)}). No se ha tocado nada.")
        return 0

    # 4. Confirmación escrita.
    print("\nSe enviarán a la papelera (se pueden recuperar desde ahí).")
    try:
        respuesta = input(f'Escribe "{PALABRA_CONFIRMACION}" para continuar: ')
    except EOFError:
        respuesta = ""
    if respuesta.strip() != PALABRA_CONFIRMACION:
        print("No se confirmó. No se ha tocado nada.")
        return 1

    # 5. Limpieza real.
    hecho = limpiar(elegidos, simulacion=False)
    _mostrar_omitidos(hecho)
    print(f"\nEnviados a la papelera: {len(hecho.enviados)} elementos. "
          f"Espacio liberado: {tamano_legible(hecho.bytes_liberados)}.")
    print("El espacio no vuelve al disco hasta que vacíes la papelera.")
    return 0


def _basura_elegida(args: argparse.Namespace, resultado: ResultadoEscaneo | None,
                    categorias_pedidas: list[str]) -> list[ElementoBasura]:
    """Elementos limpiables de las categorías pedidas (solo analiza, no toca nada)."""
    progreso = _Progreso(not args.silencioso)
    categorias = detectar_basura(
        resultado,
        dias_antiguedad=args.dias,
        tamano_minimo_antiguos=int(args.min_mb * MB),
        tamano_minimo_duplicados=int(args.min_mb * MB),
        incluir_duplicados=DUPLICADOS in categorias_pedidas,
        progreso=progreso.hashes,
    )
    progreso.fin()
    return [
        elemento
        for categoria in categorias if categoria.clave in categorias_pedidas
        for elemento in categoria.elementos if elemento.limpiable
    ]


def _listar_elegidos(titulo: str, elegidos: list[ElementoBasura]) -> int:
    """Imprime la lista exacta, sin recortar, y devuelve el tamaño total."""
    _titulo(titulo)
    for elemento in elegidos:
        tipo = "carpeta" if elemento.es_carpeta else "archivo"
        print(f"  {tamano_legible(elemento.tamano):>10}  [{elemento.categoria}] {tipo}  {elemento.ruta}")
    return sum(e.tamano for e in elegidos)


def cmd_mover(args: argparse.Namespace) -> int:
    """Mueve archivos a otra carpeta o disco. Siempre lista y pide confirmación."""
    categorias_pedidas = [c.strip().lower() for c in (args.categorias or "").split(",") if c.strip()]
    desconocidas = sorted(set(categorias_pedidas) - CATEGORIAS_CON_RUTA)
    if desconocidas:
        print(f"Categorías no válidas para mover: {', '.join(desconocidas)}. "
              f"Opciones: {', '.join(sorted(CATEGORIAS_CON_RUTA))}", file=sys.stderr)
        return 2
    if not categorias_pedidas and not args.tipo and args.min_mb is None:
        print("Indica qué mover: --categorias, --tipo y/o --min-mb.", file=sys.stderr)
        return 2
    try:
        destino = validar_destino(args.destino)
    except ValueError as problema:
        print(f"Error: {problema}", file=sys.stderr)
        return 2

    # 1. Analizar (solo lectura).
    resultado = _escanear(args, _Progreso(not args.silencioso))
    if categorias_pedidas:
        args.min_mb = 1.0 if args.min_mb is None else args.min_mb
        elegidos = _basura_elegida(args, resultado, categorias_pedidas)
        if args.tipo:
            elegidos = [e for e in elegidos if not e.es_carpeta and clasificar(e.ruta) in args.tipo]
    else:
        # Sin categorías: los archivos que cumplan los filtros de tipo y tamaño.
        elegidos = [
            ElementoBasura(a.path, a.tamano, "archivos", limpiable=not es_ruta_protegida(a.ruta))
            for a in listar_archivos(resultado, tipos=args.tipo,
                                     tamano_minimo=int((args.min_mb or 0) * MB), limite=None)
        ]
    if not elegidos:
        print("No hay nada que mover con esos criterios.")
        return 0

    # 2. Lista exacta.
    total = _listar_elegidos(f"Elementos que se moverían a {destino}", elegidos)
    print(f"\nTotal: {len(elegidos)} elementos, {tamano_legible(total)}.")

    # 3. Simulación, o 4. confirmación escrita y 5. movimiento real.
    try:
        if args.dry_run:
            simulado = mover(elegidos, destino, simulacion=True)
            _mostrar_omitidos(simulado)
            print(f"\nSIMULACIÓN: se habrían movido {len(simulado.movidos)} elementos "
                  f"({tamano_legible(simulado.bytes_movidos)}). No se ha tocado nada.")
            return 0

        try:
            respuesta = input(f'\nEscribe "{PALABRA_MOVER}" para continuar: ')
        except EOFError:
            respuesta = ""
        if respuesta.strip() != PALABRA_MOVER:
            print("No se confirmó. No se ha tocado nada.")
            return 1
        hecho = mover(elegidos, destino, simulacion=False)
    except ValueError as problema:  # por ejemplo, no hay espacio en el destino
        print(f"\nError: {problema}", file=sys.stderr)
        return 1

    _mostrar_omitidos(hecho)
    print(f"\nMovidos a {destino}: {len(hecho.movidos)} elementos "
          f"({tamano_legible(hecho.bytes_movidos)}).")
    return 0


def _mostrar_omitidos(resultado: ResultadoLimpieza | ResultadoMovimiento) -> None:
    if resultado.omitidos:
        print(f"\nOmitidos ({len(resultado.omitidos)}):")
        for elemento, motivo in resultado.omitidos:
            print(f"  {elemento.ruta}  — {motivo}")


# ---------------------------------------------------------------- argumentos

def _carpeta(texto: str) -> Path:
    """Valida que el argumento RUTA sea una carpeta que existe."""
    ruta = Path(texto).expanduser()
    if not ruta.is_dir():
        raise argparse.ArgumentTypeError(f"no existe o no es una carpeta: {texto}")
    return ruta


def _lista_de_tipos(texto: str) -> list[str]:
    """Convierte 'videos,imagenes' en una lista y comprueba que los tipos existan."""
    tipos = [t.strip().lower() for t in texto.split(",") if t.strip()]
    desconocidos = sorted(set(tipos) - set(TIPOS))
    if desconocidos:
        raise argparse.ArgumentTypeError(
            f"tipo no válido: {', '.join(desconocidos)} (opciones: {', '.join(TIPOS)})")
    return tipos


def _no_negativo(texto: str) -> float:
    valor = float(texto)
    if valor < 0:
        raise argparse.ArgumentTypeError("no puede ser negativo")
    return valor


def _fecha(texto: str) -> datetime:
    """Acepta AAAA-MM-DD o AAAA-MM-DD HH:MM."""
    try:
        return datetime.fromisoformat(texto.strip())
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"fecha no válida: {texto} (usa AAAA-MM-DD, por ejemplo 2026-10-06)") from None


def _positivo(texto: str) -> int:
    valor = int(texto)
    if valor < 1:
        raise argparse.ArgumentTypeError("debe ser 1 o mayor")
    return valor


def crear_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python main.py cli",
        description="Analiza el uso del disco y encuentra archivos basura. "
                    "Todos los comandos son de solo lectura salvo 'limpiar' y 'mover', "
                    "que siempre muestran la lista y piden confirmación.",
    )
    parser.add_argument("--silencioso", action="store_true",
                        help="no mostrar la línea de progreso")
    comandos = parser.add_subparsers(dest="comando", required=True, metavar="comando")

    def nuevo(nombre: str, funcion, ayuda: str, ruta: bool = True) -> argparse.ArgumentParser:
        sub = comandos.add_parser(nombre, help=ayuda, description=ayuda)
        sub.set_defaults(funcion=funcion)
        if ruta:
            sub.add_argument("ruta", type=_carpeta, metavar="RUTA", help="carpeta a analizar")
        return sub

    nuevo("resumen", cmd_resumen, "Espacio total, usado y libre de cada disco.", ruta=False)

    sub = nuevo("carpetas", cmd_carpetas, "Qué carpetas ocupan más dentro de RUTA.")
    sub.add_argument("-p", "--profundidad", type=_positivo, default=1,
                     help="niveles de subcarpetas a mostrar (por defecto 1)")
    sub.add_argument("-l", "--limite", type=_positivo, default=15,
                     help="carpetas por nivel (por defecto 15)")

    sub = nuevo("top", cmd_top, "Lista de archivos de RUTA, con orden y filtros "
                                "(por defecto, los más pesados).")
    sub.add_argument("-n", "--cantidad", type=_positivo, default=50,
                     help="cuántos archivos mostrar (por defecto 50)")
    sub.add_argument("-o", "--orden", choices=tuple(ORDENES), default="tamano",
                     help="ordenar por tamaño, fecha de modificación o fecha de último acceso")
    sub.add_argument("--ascendente", action="store_true",
                     help="invertir el orden: primero los más pequeños o los más antiguos")
    sub.add_argument("-t", "--tipo", type=_lista_de_tipos, default=None, metavar="LISTA",
                     help="solo estos tipos, separados por comas: " + ", ".join(TIPOS))
    sub.add_argument("--min-mb", type=_no_negativo, default=0.0,
                     help="solo archivos de al menos este tamaño en MB")

    nuevo("tipos", cmd_tipos, "Espacio por tipo de archivo (videos, imágenes, documentos...).")

    sub = nuevo("basura", cmd_basura, "Busca archivos basura por categorías.", ruta=False)
    sub.add_argument("ruta", type=_carpeta, nargs="?", metavar="RUTA",
                     help="carpeta donde buscar duplicados, archivos antiguos y carpetas "
                          "regenerables (opcional)")
    sub.add_argument("--dias", type=_positivo, default=365,
                     help="días sin uso para considerar un archivo antiguo (por defecto 365)")
    sub.add_argument("--min-mb", type=float, default=1.0,
                     help="tamaño mínimo en MB para duplicados y antiguos (por defecto 1)")
    sub.add_argument("--sin-duplicados", action="store_true",
                     help="no buscar duplicados (mucho más rápido)")
    sub.add_argument("-l", "--limite", type=_positivo, default=10,
                     help="elementos a mostrar por categoría (por defecto 10)")

    sub = nuevo("duplicados", cmd_duplicados, "Busca archivos idénticos dentro de RUTA.")
    sub.add_argument("--min-mb", type=float, default=1.0,
                     help="tamaño mínimo en MB (por defecto 1)")
    sub.add_argument("-l", "--limite", type=_positivo, default=20,
                     help="grupos a mostrar (por defecto 20)")

    sub = nuevo("reporte", cmd_reporte, "Genera un reporte completo en HTML, CSV y/o PDF.")
    sub.add_argument("-s", "--salida", default=".", metavar="CARPETA",
                     help="carpeta donde guardar el reporte (por defecto la actual)")
    sub.add_argument("-f", "--formato", choices=("html", "csv", "pdf", "ambos", "todos"),
                     default="ambos",
                     help="'ambos' = HTML y CSV (por defecto); 'todos' añade el PDF")
    sub.add_argument("--sin-duplicados", action="store_true",
                     help="no buscar duplicados (mucho más rápido)")

    nuevo("guardar", cmd_guardar,
          "Escanea RUTA y guarda el resultado en el historial, para comparar más adelante.")

    sub = nuevo("historial", cmd_historial, "Lista los escaneos guardados.", ruta=False)
    sub.add_argument("ruta", type=_carpeta, nargs="?", metavar="RUTA",
                     help="mostrar solo los escaneos de esta carpeta")

    sub = nuevo("comparar", cmd_comparar,
                "Compara dos escaneos guardados de RUTA: qué carpetas crecieron o disminuyeron. "
                "Sin fechas, compara los dos últimos.")
    sub.add_argument("--desde", type=_fecha, metavar="FECHA",
                     help="fecha inicial (AAAA-MM-DD); se usa el escaneo más cercano")
    sub.add_argument("--hasta", type=_fecha, metavar="FECHA",
                     help="fecha final (AAAA-MM-DD); se usa el escaneo más cercano")
    sub.add_argument("--min-mb", type=_no_negativo, default=1.0,
                     help="ignorar cambios menores de este tamaño en MB (por defecto 1)")
    sub.add_argument("-l", "--limite", type=_positivo, default=20,
                     help="carpetas a mostrar en cada lista (por defecto 20)")

    sub = nuevo("salud", cmd_salud,
                "Salud de los discos con SMART (requiere smartctl y permisos de administrador). "
                "Sin acción, muestra el estado de todos los discos.", ruta=False)
    acciones = sub.add_subparsers(dest="accion", metavar="acción")
    acciones.add_parser("ver", help="mostrar el estado de todos los discos (por defecto)")
    prueba = acciones.add_parser(
        "prueba", help="pedir al disco que se pruebe a sí mismo (no escribe datos)")
    prueba.add_argument("disco", metavar="DISCO", help="nombre que muestra 'salud', p. ej. /dev/sda")
    prueba.add_argument("--tipo", choices=tuple(TIPOS_DE_PRUEBA), default="corta",
                        help="corta (unos 2 minutos, por defecto) o larga (puede tardar horas)")
    acciones.add_parser("revisar", help="mostrar el estado y avisar si algo ha empeorado")
    alertas = acciones.add_parser("alertas", help="ver o cambiar la configuración de las alertas")
    alertas.add_argument("--temperatura", type=_temperatura, default=_SIN_CAMBIO, metavar="GRADOS",
                         help="límite de temperatura en °C, o 'auto'")
    alertas.add_argument("--escritorio", type=_si_o_no, metavar="si|no",
                         help="notificación de escritorio")
    alertas.add_argument("--correo", type=_si_o_no, metavar="si|no", help="aviso por correo")
    alertas.add_argument("--smtp-servidor", metavar="SERVIDOR")
    alertas.add_argument("--smtp-puerto", type=_positivo, metavar="PUERTO")
    alertas.add_argument("--smtp-usuario", metavar="USUARIO")
    alertas.add_argument("--smtp-tls", type=_si_o_no, metavar="si|no", help="cifrado STARTTLS")
    alertas.add_argument("--correo-de", metavar="DIRECCIÓN")
    alertas.add_argument("--correo-para", metavar="DIRECCIÓN")
    alertas.add_argument("--probar", action="store_true", help="enviar un aviso de prueba")
    programa = acciones.add_parser(
        "programar", help="revisar la salud periódicamente (terminal de administrador o sudo)")
    programa.add_argument("--frecuencia", choices=FRECUENCIAS, default="diaria")
    programa.add_argument("--hora", default="09:00", metavar="HH:MM")

    sub = nuevo("programar", cmd_programar,
                "Escaneos periódicos con el programador de tareas del sistema "
                "(Programador de tareas en Windows, cron en Linux).", ruta=False)
    acciones = sub.add_subparsers(dest="accion", required=True, metavar="acción")
    crear = acciones.add_parser("crear", help="programar el escaneo de una carpeta")
    crear.add_argument("ruta", type=_carpeta, metavar="RUTA", help="carpeta a escanear")
    crear.add_argument("--frecuencia", choices=FRECUENCIAS, default="diaria",
                       help="diaria (por defecto) o semanal (cada lunes)")
    crear.add_argument("--hora", default="09:00", metavar="HH:MM",
                       help="hora del escaneo (por defecto 09:00)")
    acciones.add_parser("listar", help="ver los escaneos programados")
    quitar = acciones.add_parser("quitar", help="quitar un escaneo programado")
    quitar.add_argument("nombre", metavar="NOMBRE", help="nombre que muestra 'programar listar'")

    sub = nuevo("limpiar", cmd_limpiar,
                "Envía basura a la papelera. Muestra la lista exacta y pide confirmación.",
                ruta=False)
    sub.add_argument("ruta", type=_carpeta, nargs="?", metavar="RUTA",
                     help="carpeta donde buscar regenerables, duplicados y antiguos")
    sub.add_argument("-c", "--categorias", required=True, metavar="LISTA",
                     help="qué limpiar, separado por comas: " + ", ".join(CATEGORIAS_LIMPIABLES))
    sub.add_argument("--dry-run", action="store_true",
                     help="simulación: muestra qué se haría sin tocar nada")
    sub.add_argument("--dias", type=_positivo, default=365,
                     help="días sin uso para considerar un archivo antiguo (por defecto 365)")
    sub.add_argument("--min-mb", type=float, default=1.0,
                     help="tamaño mínimo en MB para duplicados y antiguos (por defecto 1)")

    sub = nuevo("mover", cmd_mover,
                "Mueve archivos de RUTA a otra carpeta o disco. Muestra la lista exacta "
                "y pide confirmación.")
    sub.add_argument("-d", "--destino", required=True, metavar="CARPETA",
                     help="carpeta de destino (debe existir)")
    sub.add_argument("-c", "--categorias", metavar="LISTA",
                     help="mover basura de estas categorías: "
                          + ", ".join(sorted(CATEGORIAS_CON_RUTA)))
    sub.add_argument("-t", "--tipo", type=_lista_de_tipos, default=None, metavar="LISTA",
                     help="solo estos tipos, separados por comas: " + ", ".join(TIPOS))
    sub.add_argument("--min-mb", type=_no_negativo, default=None,
                     help="solo archivos de al menos este tamaño en MB")
    sub.add_argument("--dias", type=_positivo, default=365,
                     help="días sin uso para la categoría 'antiguos' (por defecto 365)")
    sub.add_argument("--dry-run", action="store_true",
                     help="simulación: muestra qué se haría sin tocar nada")

    return parser


def ejecutar(argumentos: list[str] | None = None) -> int:
    """Ejecuta un comando y devuelve el código de salida (0 = correcto)."""
    # Un nombre de archivo con caracteres que la consola no sabe mostrar
    # no debe detener el programa: se sustituye por '?'.
    for flujo in (sys.stdout, sys.stderr):
        if hasattr(flujo, "reconfigure"):
            flujo.reconfigure(errors="replace")

    args = crear_parser().parse_args(argumentos)
    try:
        return args.funcion(args)
    except KeyboardInterrupt:
        print("\nCancelado por el usuario.", file=sys.stderr)
        return 130
    except OSError as error:
        print(f"\nError: {error}", file=sys.stderr)
        return 1
