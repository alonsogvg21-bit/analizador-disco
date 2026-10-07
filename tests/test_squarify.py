"""Pruebas del cálculo de rectángulos del treemap. No abren ninguna ventana ni usan Qt."""

from __future__ import annotations

import itertools
import random

import pytest

from desktop.squarify import Rect, bloque_en, calcular_rectangulos, disponer_arbol

TOLERANCIA = 1e-6


def se_solapan(a: Rect, b: Rect) -> bool:
    return (a.x < b.x + b.ancho - TOLERANCIA and b.x < a.x + a.ancho - TOLERANCIA
            and a.y < b.y + b.alto - TOLERANCIA and b.y < a.y + a.alto - TOLERANCIA)


def comprobar_reparto(valores, x, y, ancho, alto):
    """Propiedades que debe cumplir cualquier reparto correcto."""
    rects = calcular_rectangulos(valores, x, y, ancho, alto)
    assert len(rects) == len(valores)
    total = sum(v for v in valores if v > 0)
    for valor, r in zip(valores, rects):
        if valor > 0:
            # 1. El área de cada bloque es proporcional a su valor.
            assert r.area == pytest.approx(valor / total * ancho * alto, rel=1e-6)
            # 2. Ningún bloque se sale del espacio disponible.
            assert r.x >= x - TOLERANCIA and r.y >= y - TOLERANCIA
            assert r.x + r.ancho <= x + ancho + TOLERANCIA and r.y + r.alto <= y + alto + TOLERANCIA
        else:
            assert r.area == 0
    # 3. Los bloques no se pisan entre sí.
    visibles = [r for r in rects if r.area > 0]
    for a, b in itertools.combinations(visibles, 2):
        assert not se_solapan(a, b)
    # 4. Entre todos llenan el espacio completo, sin huecos.
    assert sum(r.area for r in visibles) == pytest.approx(ancho * alto, rel=1e-6)
    return rects


def test_areas_proporcionales():
    rects = comprobar_reparto([6, 6, 4, 3, 2, 2, 1], 0, 0, 600, 400)
    assert rects[0].area == pytest.approx(6 / 24 * 600 * 400)
    assert rects[6].area == pytest.approx(1 / 24 * 600 * 400)


def test_ejemplo_clasico_del_algoritmo():
    """El ejemplo del artículo original: 6,6,4,3,2,2,1 en un rectángulo de 6x4."""
    rects = calcular_rectangulos([6, 6, 4, 3, 2, 2, 1], 0, 0, 6, 4)
    # Los dos primeros forman una columna a la izquierda, de 3 de ancho y 2 de alto cada uno.
    assert (rects[0].x, rects[0].ancho, rects[0].alto) == pytest.approx((0, 3, 2))
    assert (rects[1].x, rects[1].y, rects[1].ancho, rects[1].alto) == pytest.approx((0, 2, 3, 2))


def test_se_respeta_el_orden_de_entrada():
    valores = [1, 50, 3, 20]
    rects = comprobar_reparto(valores, 0, 0, 300, 200)
    areas = [r.area for r in rects]
    assert sorted(range(4), key=areas.__getitem__) == [0, 2, 3, 1]   # de menor a mayor


def test_cuatro_iguales_en_un_cuadrado_son_cuadrados():
    for r in comprobar_reparto([5, 5, 5, 5], 0, 0, 200, 200):
        assert (r.ancho, r.alto) == pytest.approx((100, 100))


def test_bloques_razonablemente_cuadrados():
    """Lo que distingue a 'squarified' de repartir en tiras: nada queda muy alargado."""
    rects = comprobar_reparto([30, 25, 20, 10, 8, 4, 3], 0, 0, 800, 500)
    for r in rects:
        assert max(r.ancho / r.alto, r.alto / r.ancho) < 4


def test_un_solo_elemento_ocupa_todo():
    (r,) = comprobar_reparto([42], 10, 20, 300, 100)
    assert (r.x, r.y, r.ancho, r.alto) == pytest.approx((10, 20, 300, 100))


def test_con_desplazamiento_y_espacio_vertical():
    comprobar_reparto([9, 5, 3, 1], 50, 70, 120, 480)


@pytest.mark.parametrize("valores", [[], [0, 0], [-5, 0]])
def test_sin_valores_positivos(valores):
    assert all(r.area == 0 for r in calcular_rectangulos(valores, 0, 0, 100, 100))


def test_ceros_y_negativos_no_estorban():
    rects = comprobar_reparto([10, 0, 5, -3], 0, 0, 150, 100)
    assert rects[1].area == 0 and rects[3].area == 0


@pytest.mark.parametrize("ancho, alto", [(0, 100), (100, 0), (-10, 50)])
def test_espacio_sin_superficie(ancho, alto):
    assert all(r.area == 0 for r in calcular_rectangulos([3, 2, 1], 0, 0, ancho, alto))


def test_muchos_valores_al_azar():
    generador = random.Random(7)
    for _ in range(20):
        valores = [generador.uniform(0.5, 1000) for _ in range(generador.randint(1, 40))]
        comprobar_reparto(valores, 0, 0, generador.uniform(50, 1600), generador.uniform(50, 900))


def test_valores_muy_desiguales():
    """Un archivo enorme junto a otros diminutos: nada se sale ni se solapa."""
    rects = calcular_rectangulos([10**12, 1, 1, 1], 0, 0, 1000, 600)
    assert rects[0].area == pytest.approx(1000 * 600, rel=1e-9)
    for r in rects:
        assert r.x >= -TOLERANCIA and r.y >= -TOLERANCIA
        assert r.x + r.ancho <= 1000 + TOLERANCIA and r.y + r.alto <= 600 + TOLERANCIA
    for a, b in itertools.combinations(rects, 2):
        assert not se_solapan(a, b)


# ------------------------------------------------------------ árbol de dos niveles

@pytest.fixture
def arbol() -> dict:
    return {"nombre": "raiz", "ruta": "/raiz", "tamano": 1000, "es_carpeta": True, "hijos": [
        {"nombre": "videos", "ruta": "/raiz/videos", "tamano": 700, "es_carpeta": True, "hijos": [
            {"nombre": "a.mp4", "ruta": "/raiz/videos/a.mp4", "tamano": 500, "es_carpeta": False},
            {"nombre": "b.mp4", "ruta": "/raiz/videos/b.mp4", "tamano": 200, "es_carpeta": False},
        ]},
        {"nombre": "suelto.zip", "ruta": "/raiz/suelto.zip", "tamano": 290, "es_carpeta": False},
        {"nombre": "mini", "ruta": "/raiz/mini", "tamano": 10, "es_carpeta": True, "hijos": [
            {"nombre": "x.txt", "ruta": "/raiz/mini/x.txt", "tamano": 10, "es_carpeta": False}]},
        {"nombre": "vacia", "ruta": "/raiz/vacia", "tamano": 0, "es_carpeta": True, "hijos": []},
    ]}


def test_disponer_arbol(arbol):
    bloques = disponer_arbol(arbol, 800, 500)
    por_nombre = {b.nodo["nombre"]: b for b in bloques}

    assert "vacia" not in por_nombre                       # lo que mide 0 no se dibuja
    assert por_nombre["videos"].es_grupo                    # carpeta con contenido y con sitio
    assert not por_nombre["suelto.zip"].es_grupo
    assert not por_nombre["mini"].es_grupo and "x.txt" not in por_nombre   # demasiado pequeña

    # Cada bloque recuerda su carpeta padre, que es la referencia del porcentaje.
    assert por_nombre["a.mp4"].padre["nombre"] == "videos"
    assert por_nombre["videos"].padre["nombre"] == "raiz"

    # Los hijos quedan dentro del marco de su carpeta, por debajo de la cabecera.
    marco = por_nombre["videos"].rect
    for nombre in ("a.mp4", "b.mp4"):
        r = por_nombre[nombre].rect
        assert r.x >= marco.x and r.x + r.ancho <= marco.x + marco.ancho + TOLERANCIA
        assert r.y >= marco.y + 18 - TOLERANCIA and r.y + r.alto <= marco.y + marco.alto + TOLERANCIA
    assert por_nombre["a.mp4"].rect.area == pytest.approx(2.5 * por_nombre["b.mp4"].rect.area)


def test_disponer_arbol_vacio():
    assert disponer_arbol({"nombre": "x", "tamano": 0, "hijos": []}, 800, 500) == []
    assert disponer_arbol({"nombre": "x", "tamano": 0}, 800, 500) == []


def test_bloque_en(arbol):
    bloques = disponer_arbol(arbol, 800, 500)
    por_nombre = {b.nodo["nombre"]: b for b in bloques}

    hoja = por_nombre["a.mp4"].rect
    assert bloque_en(bloques, hoja.x + hoja.ancho / 2, hoja.y + hoja.alto / 2).nodo["nombre"] == "a.mp4"
    # Sobre la cabecera de la carpeta se obtiene la carpeta, no un archivo.
    marco = por_nombre["videos"].rect
    assert bloque_en(bloques, marco.x + 10, marco.y + 5).nodo["nombre"] == "videos"
    assert bloque_en(bloques, -5, -5) is None and bloque_en(bloques, 5000, 5000) is None
