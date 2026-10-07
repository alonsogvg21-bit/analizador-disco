"""Convierte la guía de uso (docs/GUIA_DE_USO.md) en PDF (docs/GUIA_DE_USO.pdf).

La guía se escribe y se corrige en el archivo .md; el PDF se genera a partir
de él con este script, para que los dos digan siempre lo mismo:

    pip install markdown
    python herramientas/generar_guia_pdf.py

Hace falta tener instalado Microsoft Edge, Google Chrome o Chromium: el PDF
lo imprime el navegador, sin abrir ninguna ventana. No es una dependencia del
programa, solo de este script.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DOCS = RAIZ / "docs"
ORIGEN = DOCS / "GUIA_DE_USO.md"
DESTINO = DOCS / "GUIA_DE_USO.pdf"

sys.path.insert(0, str(RAIZ))
from utils.info import NOMBRE, VERSION  # noqa: E402

NAVEGADORES = (
    "msedge", "chrome", "google-chrome", "chromium", "chromium-browser",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
)

ESTILO = """
@page { size: A4; margin: 18mm 16mm 18mm 16mm; }
* { box-sizing: border-box; }
body { font-family: "Segoe UI", "Noto Sans", "DejaVu Sans", Arial, sans-serif; font-size: 10.5pt;
       line-height: 1.5; color: #111; margin: 0; }
h1 { font-size: 24pt; margin: 0 0 4pt; }
h2 { font-size: 16pt; margin: 22pt 0 8pt; padding-bottom: 4pt; border-bottom: 2px solid #2a78d6;
     break-after: avoid; }
h3 { font-size: 12.5pt; margin: 16pt 0 6pt; break-after: avoid; }
p, li { orphans: 3; widows: 3; }
ul, ol { padding-left: 20pt; }
li { margin: 2pt 0; }
a { color: #1c5cab; text-decoration: none; }
hr { border: 0; border-top: 1px solid #ccc; margin: 16pt 0; }
img { max-width: 100%; border: 1px solid #ccc; border-radius: 4px; margin: 6pt 0; break-inside: avoid; }
code { font-family: Consolas, "DejaVu Sans Mono", monospace; font-size: 9.5pt; background: #f0f0ee;
       padding: 1px 4px; border-radius: 3px; }
pre { background: #f0f0ee; border: 1px solid #ddd; border-radius: 4px; padding: 8pt 10pt;
      white-space: pre-wrap; word-break: break-word; break-inside: avoid; }
pre code { background: none; padding: 0; }
table { border-collapse: collapse; width: 100%; margin: 8pt 0; font-size: 9.5pt; }
th, td { border: 1px solid #c8c8c4; padding: 5pt 7pt; text-align: left; vertical-align: top; }
th { background: #e8eef7; }
tr { break-inside: avoid; }
blockquote { margin: 10pt 0; padding: 8pt 12pt; background: #eef4fc; border-left: 4px solid #2a78d6; }
blockquote p { margin: 0; }
.portada { color: #555; margin: 0 0 14pt; }
"""


def ancla(texto: str, separador: str = "-") -> str:
    """Identificador de un título con las mismas reglas que GitHub, para que los enlaces
    internos del .md ("#9-salud-del-disco") funcionen también dentro del PDF."""
    return re.sub(r"[^\w\- ]", "", texto.lower()).replace(" ", separador)


_BLOQUE_EN_LISTA = re.compile(r"^(?P<margen> +)```[^\n]*\n(?P<codigo>.*?)\n(?P=margen)```[ \t]*$",
                              re.MULTILINE | re.DOTALL)


def _bloques_dentro_de_listas(texto_md: str) -> str:
    """Los bloques ``` que van dentro de un paso numerado (con margen) no los entiende la
    biblioteca 'markdown'. Se pasan a su otra forma de escribir código: 8 espacios de margen."""
    def convertir(bloque: re.Match) -> str:
        margen = len(bloque.group("margen"))
        return "\n".join(" " * 8 + linea[margen:] for linea in bloque.group("codigo").split("\n"))
    return _BLOQUE_EN_LISTA.sub(convertir, texto_md)


def a_html(texto_md: str) -> str:
    try:
        import markdown
    except ImportError:
        raise SystemExit("Falta la biblioteca 'markdown':  pip install markdown") from None
    texto_md = _bloques_dentro_de_listas(texto_md)
    cuerpo = markdown.markdown(
        texto_md, extensions=["tables", "fenced_code", "sane_lists", "toc"],
        extension_configs={"toc": {"slugify": ancla}})
    # Debajo del título, de qué versión del programa es la guía.
    cuerpo = cuerpo.replace("</h1>", f'</h1>\n<p class="portada">{NOMBRE} {VERSION}</p>', 1)
    return (f'<!DOCTYPE html>\n<html lang="es"><head><meta charset="utf-8">'
            f"<title>Guía de uso de {NOMBRE}</title><style>{ESTILO}</style></head>"
            f"<body>{cuerpo}</body></html>")


def buscar_navegador() -> str:
    for candidato in NAVEGADORES:
        encontrado = shutil.which(candidato) or (candidato if Path(candidato).is_file() else None)
        if encontrado:
            return encontrado
    raise SystemExit("No se encontró Edge, Chrome ni Chromium para imprimir el PDF.")


def main() -> int:
    html = a_html(ORIGEN.read_text(encoding="utf-8"))
    # El HTML intermedio se deja junto al .md para que encuentre las imágenes (capturas/...).
    intermedio = DOCS / "_guia_temporal.html"
    intermedio.write_text(html, encoding="utf-8")
    try:
        with tempfile.TemporaryDirectory() as perfil:   # perfil vacío: no toca el del usuario
            subprocess.run(
                [buscar_navegador(), "--headless=new", "--disable-gpu", f"--user-data-dir={perfil}",
                 "--no-pdf-header-footer", f"--print-to-pdf={DESTINO}", intermedio.as_uri()],
                check=True, capture_output=True, timeout=180)
    finally:
        intermedio.unlink(missing_ok=True)
    if not DESTINO.is_file() or DESTINO.stat().st_size < 10_000:
        raise SystemExit("El navegador no generó el PDF.")
    print(f"Guía generada: {DESTINO}  ({DESTINO.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
