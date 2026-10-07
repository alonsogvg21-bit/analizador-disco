"""Cálculo de los rectángulos del treemap (algoritmo "squarified").

Este módulo es geometría pura: no importa Qt ni abre ventanas, así que se
puede probar con pytest. El dibujo está en desktop/treemap.py.

La idea del algoritmo: se van colocando los elementos, de mayor a menor, en
filas apoyadas sobre el lado más corto del espacio libre. A cada fila se le
añaden elementos mientras eso haga los rectángulos más cuadrados; cuando el
siguiente los alargaría, la fila se cierra y se empieza otra en lo que queda.
Los bloques cuadrados se comparan a ojo mucho mejor que las tiras finas.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(slots=True)
class Rect:
    x: float
    y: float
    ancho: float
    alto: float

    @property
    def area(self) -> float:
        return self.ancho * self.alto

    def contiene(self, px: float, py: float) -> bool:
        return self.x <= px < self.x + self.ancho and self.y <= py < self.y + self.alto


@dataclass(slots=True)
class Bloque:
    """Un rectángulo del mapa junto con el nodo del árbol que representa."""
    rect: Rect
    nodo: dict
    padre: dict
    es_grupo: bool = False  # carpeta abierta: marco con nombre y sus hijos dentro


def _peor_proporcion(fila: list[float], lado: float) -> float:
    """Lo alargado que queda el rectángulo menos cuadrado de la fila (1 = cuadrado perfecto)."""
    suma = sum(fila)
    if suma <= 0 or lado <= 0:
        return float("inf")
    return max(max(lado * lado * area / (suma * suma), suma * suma / (lado * lado * area))
               for area in fila)


def calcular_rectangulos(
    valores: Sequence[float], x: float, y: float, ancho: float, alto: float
) -> list[Rect]:
    """Reparte el rectángulo (x, y, ancho, alto) entre los valores, en proporción a cada uno.

    Devuelve un Rect por valor, EN EL MISMO ORDEN en que se recibieron. Los
    valores que no son positivos reciben un rectángulo de área cero.
    """
    resultado = [Rect(x, y, 0.0, 0.0) for _ in valores]
    total = sum(v for v in valores if v > 0)
    if total <= 0 or ancho <= 0 or alto <= 0:
        return resultado

    escala = ancho * alto / total
    # (área en píxeles, posición original), de mayor a menor.
    # A igual tamaño se conserva el orden de entrada.
    pendientes = sorted(((v * escala, i) for i, v in enumerate(valores) if v > 0),
                        key=lambda par: (-par[0], par[1]))

    libre = Rect(x, y, ancho, alto)
    fila: list[tuple[float, int]] = []

    def colocar_fila(ultima: bool = False) -> None:
        suma = sum(area for area, _ in fila)
        if libre.ancho >= libre.alto:
            # Espacio apaisado: la fila es una columna a la izquierda.
            # La última fila se queda con todo lo que sobra: así los errores de
            # redondeo acumulados nunca dejan un hueco ni sacan un bloque fuera.
            grosor = libre.ancho if ultima else min(suma / libre.alto, libre.ancho)
            cursor = libre.y
            for area, indice in fila:
                # Se reparte el lado como fracción (y no dividiendo por el grosor)
                # para que los decimales no saquen ningún bloque del espacio.
                largo = libre.alto * area / suma
                resultado[indice] = Rect(libre.x, cursor, grosor, largo)
                cursor += largo
            libre.x += grosor
            libre.ancho -= grosor
        else:
            # Espacio vertical: la fila es una franja arriba.
            grosor = libre.alto if ultima else min(suma / libre.ancho, libre.alto)
            cursor = libre.x
            for area, indice in fila:
                largo = libre.ancho * area / suma
                resultado[indice] = Rect(cursor, libre.y, largo, grosor)
                cursor += largo
            libre.y += grosor
            libre.alto -= grosor

    for elemento in pendientes:
        lado = min(libre.ancho, libre.alto)
        areas = [area for area, _ in fila]
        if not fila or _peor_proporcion(areas + [elemento[0]], lado) <= _peor_proporcion(areas, lado):
            fila.append(elemento)
        else:
            colocar_fila()
            fila = [elemento]
    if fila:
        colocar_fila(ultima=True)
    return resultado


def disponer_arbol(
    arbol: dict,
    ancho: float,
    alto: float,
    alto_cabecera: float = 18.0,
    minimo_grupo: float = 48.0,
    margen: float = 2.0,
) -> list[Bloque]:
    """Convierte el árbol de core.arbol.arbol_json() en bloques listos para dibujar.

    Se dibujan dos niveles: los hijos de la carpeta actual y, dentro de cada
    subcarpeta que traiga contenido y tenga sitio, sus propios hijos bajo una
    cabecera con el nombre. Las carpetas demasiado pequeñas para eso se
    dibujan como un bloque simple.
    """
    hijos = [h for h in arbol.get("hijos", []) if h.get("tamano", 0) > 0]
    bloques: list[Bloque] = []
    rects = calcular_rectangulos([h["tamano"] for h in hijos], 0.0, 0.0, ancho, alto)

    for hijo, rect in zip(hijos, rects):
        nietos = [n for n in hijo.get("hijos", []) if n.get("tamano", 0) > 0]
        cabe = rect.ancho >= minimo_grupo and rect.alto >= minimo_grupo
        if not nietos or not cabe:
            bloques.append(Bloque(rect, hijo, arbol))
            continue

        bloques.append(Bloque(rect, hijo, arbol, es_grupo=True))
        interior = calcular_rectangulos(
            [n["tamano"] for n in nietos],
            rect.x + margen, rect.y + alto_cabecera,
            rect.ancho - 2 * margen, rect.alto - alto_cabecera - margen)
        bloques.extend(Bloque(r, nieto, hijo) for nieto, r in zip(nietos, interior))
    return bloques


def bloque_en(bloques: Sequence[Bloque], px: float, py: float) -> Bloque | None:
    """El bloque más interno que hay bajo un punto (una hoja antes que el grupo que la contiene)."""
    encontrado = None
    for bloque in bloques:
        if bloque.rect.contiene(px, py):
            if not bloque.es_grupo:
                return bloque
            encontrado = bloque
    return encontrado
