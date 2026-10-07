"""Pruebas del árbol en JSON que alimenta el mapa de bloques."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.arbol import AGRUPADO, arbol_json, preparar_indice
from core.escaner import escanear


@pytest.fixture
def arbol(tmp_path: Path) -> Path:
    """
    raiz/                         (3660)
      suelto.txt        10
      vacio.txt          0
      fotos/                      (500)
        a.jpg          300
        viaje/b.png    200
      proyecto/                   (3150)
        main.py         50
        video.mp4     2000
        node_modules/lib/x.js  1100
    """
    raiz = tmp_path / "raiz"
    for relativa, tamano in (
        ("suelto.txt", 10), ("vacio.txt", 0),
        ("fotos/a.jpg", 300), ("fotos/viaje/b.png", 200),
        ("proyecto/main.py", 50), ("proyecto/video.mp4", 2000),
        ("proyecto/node_modules/lib/x.js", 1100),
    ):
        archivo = raiz.joinpath(*relativa.split("/"))
        archivo.parent.mkdir(parents=True, exist_ok=True)
        archivo.write_bytes(b"x" * tamano)
    return raiz


def por_nombre(nodo: dict) -> dict:
    return {hijo["nombre"]: hijo for hijo in nodo["hijos"]}


def test_estructura_y_tamanos(arbol):
    datos = arbol_json(escanear(arbol), niveles=2)

    assert datos["nombre"] == "raiz" and datos["tamano"] == 3660 and datos["es_carpeta"]
    # De mayor a menor, mezclando carpetas y archivos; lo que mide 0 no aparece.
    assert [(h["nombre"], h["tamano"], h["es_carpeta"]) for h in datos["hijos"]] == [
        ("proyecto", 3150, True), ("fotos", 500, True), ("suelto.txt", 10, False)]
    assert datos["num_archivos"] == 7

    fotos = por_nombre(datos)["fotos"]
    assert [(h["nombre"], h["tamano"]) for h in fotos["hijos"]] == [("a.jpg", 300), ("viaje", 200)]


def test_los_hijos_suman_el_tamano_del_padre(arbol):
    def comprobar(nodo):
        if "hijos" in nodo:
            assert sum(h["tamano"] for h in nodo["hijos"]) == nodo["tamano"]
            for hijo in nodo["hijos"]:
                comprobar(hijo)
    comprobar(arbol_json(escanear(arbol), niveles=3))


@pytest.mark.parametrize("niveles, profundidad", [(1, 1), (2, 2), (3, 3), (0, 1), (99, 3)])
def test_limite_de_niveles(arbol, niveles, profundidad):
    """Nunca se devuelven más niveles de los pedidos, ni más de 3."""
    def profundidad_de(nodo):
        return 1 + max(map(profundidad_de, nodo["hijos"]), default=0) if "hijos" in nodo else 0
    assert profundidad_de(arbol_json(escanear(arbol), niveles=niveles)) == profundidad


def test_carpeta_en_el_limite_no_trae_hijos(arbol):
    datos = arbol_json(escanear(arbol), niveles=1)
    proyecto = por_nombre(datos)["proyecto"]
    assert "hijos" not in proyecto and proyecto["tamano"] == 3150


def test_consultar_una_subcarpeta(arbol):
    datos = arbol_json(escanear(arbol), arbol / "proyecto", niveles=1)
    assert [h["nombre"] for h in datos["hijos"]] == ["video.mp4", "node_modules", "main.py"]
    assert [m["nombre"] for m in datos["migas"]] == ["raiz", "proyecto"]
    assert datos["migas"][0]["ruta"] == str(arbol)
    assert datos["migas"][1]["ruta"] == str(arbol / "proyecto")


def test_migas_de_la_raiz(arbol):
    assert arbol_json(escanear(arbol))["migas"] == [{"nombre": "raiz", "ruta": str(arbol)}]


def test_tipos(arbol):
    datos = arbol_json(escanear(arbol), niveles=2)
    hijos = por_nombre(datos)
    assert hijos["suelto.txt"]["tipo"] == "documentos"
    # Una carpeta toma el tipo que más espacio ocupa dentro, contando subcarpetas.
    assert hijos["fotos"]["tipo"] == "imagenes"
    assert hijos["proyecto"]["tipo"] == "videos"            # 2000 de video frente a 1150 de código
    assert por_nombre(hijos["proyecto"])["node_modules"]["tipo"] == "codigo"
    assert datos["tipo"] == "videos"


def test_elementos_pequenos_se_agrupan(tmp_path):
    for indice in range(1, 11):  # archivos de 1 a 10 bytes
        (tmp_path / f"f{indice:02}.bin").write_bytes(b"x" * indice)

    datos = arbol_json(escanear(tmp_path), niveles=1, max_hijos=3)

    *mayores, resto = datos["hijos"]
    assert [h["tamano"] for h in mayores] == [10, 9, 8]
    assert resto["tipo"] == AGRUPADO and resto["agrupado"] and resto["ruta"] is None
    assert resto["tamano"] == 28 and "7 elementos" in resto["nombre"]
    assert sum(h["tamano"] for h in datos["hijos"]) == datos["tamano"] == 55


def test_es_json_valido(arbol):
    datos = arbol_json(escanear(arbol), niveles=3)
    assert json.loads(json.dumps(datos)) == datos


def test_carpeta_fuera_del_escaneo(arbol, tmp_path):
    with pytest.raises(KeyError):
        arbol_json(escanear(arbol), tmp_path / "otra")


def test_carpeta_vacia(tmp_path):
    datos = arbol_json(escanear(tmp_path))
    assert datos["tamano"] == 0 and datos["hijos"] == [] and datos["tipo"] == "otros"


def test_el_indice_se_calcula_una_sola_vez(arbol):
    resultado = escanear(arbol)
    assert preparar_indice(resultado) is preparar_indice(resultado)
