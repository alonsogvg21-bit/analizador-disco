"""Árbol de carpetas y archivos con tamaños, listo para convertir a JSON.

Lo usa el mapa de bloques (treemap) de la interfaz web. No vuelve a leer el
disco: todo sale del ResultadoEscaneo que ya produjo el escáner, y los tipos
se obtienen con la misma función clasificar() del resto del motor.

Para que no se ponga lento en discos grandes, cada consulta devuelve solo
unos pocos niveles y, en cada carpeta, solo los elementos más grandes; el
resto se suma en un único bloque "más pequeños".
"""

from __future__ import annotations

import heapq
import os
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from core.carpetas import buscar_clave
from core.modelos import InfoArchivo, ResultadoEscaneo
from core.tipos import OTROS, TIPOS, clasificar

NIVELES_MAXIMOS = 3
# Tipo del bloque que agrupa los elementos pequeños que no se muestran uno a uno.
AGRUPADO = "varios"

_POSICION_TIPO = {tipo: indice for indice, tipo in enumerate(TIPOS)}


@dataclass
class IndiceArbol:
    """Datos auxiliares que se calculan una vez por escaneo."""
    # carpeta -> archivos que están directamente dentro
    archivos: dict[str, list[InfoArchivo]] = field(default_factory=lambda: defaultdict(list))
    # carpeta -> tipo que más espacio ocupa dentro de ella (contando subcarpetas)
    tipo_dominante: dict[str, str] = field(default_factory=dict)


def preparar_indice(resultado: ResultadoEscaneo) -> IndiceArbol:
    """Construye (o recupera) el índice del árbol. Recorre los archivos una sola vez."""
    if resultado.indice_arbol is not None:
        return resultado.indice_arbol

    indice = IndiceArbol()
    # Bytes de cada tipo por carpeta, en el mismo orden que TIPOS.
    bytes_por_tipo: dict[str, list[int]] = {}

    for archivo in resultado.archivos:
        carpeta = os.path.dirname(archivo.ruta)
        indice.archivos[carpeta].append(archivo)
        if carpeta not in bytes_por_tipo:
            bytes_por_tipo[carpeta] = [0] * len(TIPOS)
        bytes_por_tipo[carpeta][_POSICION_TIPO[clasificar(archivo.ruta)]] += archivo.tamano

    # Se recorren las carpetas de arriba abajo y luego se suman de abajo arriba,
    # igual que hace el escáner con los tamaños.
    orden: list[tuple[str, str | None]] = []
    pila: list[tuple[str, str | None]] = [(str(resultado.raiz), None)]
    while pila:
        carpeta, padre = pila.pop()
        orden.append((carpeta, padre))
        pila.extend((hija, carpeta) for hija in resultado.hijos.get(carpeta, ()))

    for carpeta, padre in reversed(orden):
        propios = bytes_por_tipo.get(carpeta)
        if propios is None:
            indice.tipo_dominante[carpeta] = OTROS
            continue
        mayor = max(range(len(TIPOS)), key=propios.__getitem__)
        indice.tipo_dominante[carpeta] = TIPOS[mayor] if propios[mayor] else OTROS
        if padre is not None:
            del_padre = bytes_por_tipo.setdefault(padre, [0] * len(TIPOS))
            for posicion, cantidad in enumerate(propios):
                del_padre[posicion] += cantidad

    resultado.indice_arbol = indice
    return indice


def arbol_json(
    resultado: ResultadoEscaneo,
    ruta: str | os.PathLike | None = None,
    niveles: int = 2,
    max_hijos: int = 30,
) -> dict:
    """Devuelve el árbol de 'ruta' (por defecto la raíz del escaneo) como diccionario.

    El resultado solo contiene textos, números, listas y diccionarios, así que
    se puede pasar directamente a json.dumps().

    - niveles: cuántos niveles de contenido incluir (entre 1 y 3).
    - max_hijos: máximo de elementos que se detallan en cada carpeta.

    Cada nodo tiene: nombre, ruta, tamano, es_carpeta y tipo. Las carpetas
    añaden num_archivos y, si están dentro de los niveles pedidos, 'hijos'.
    El nodo raíz incluye además 'migas': el camino desde la raíz del escaneo.
    Lanza KeyError si la carpeta no pertenece al escaneo.
    """
    clave = buscar_clave(resultado, ruta if ruta is not None else resultado.raiz)
    if clave is None:
        raise KeyError(f"La carpeta no forma parte del escaneo: {ruta}")

    niveles = max(1, min(int(niveles), NIVELES_MAXIMOS))
    max_hijos = max(1, int(max_hijos))
    indice = preparar_indice(resultado)

    def nodo_carpeta(carpeta: str, restantes: int) -> dict:
        nodo = {
            "nombre": os.path.basename(carpeta) or carpeta,
            "ruta": carpeta,
            "tamano": resultado.tamano_carpetas[carpeta],
            "es_carpeta": True,
            "tipo": indice.tipo_dominante.get(carpeta, OTROS),
            "num_archivos": resultado.archivos_por_carpeta[carpeta],
        }
        if restantes > 0:
            nodo["hijos"] = hijos_de(carpeta, restantes - 1)
        return nodo

    def hijos_de(carpeta: str, restantes: int) -> list[dict]:
        # (tamaño, es_carpeta, carpeta o archivo). Lo que mide 0 no se dibuja.
        candidatos: list[tuple[int, bool, object]] = [
            (resultado.tamano_carpetas[hija], True, hija)
            for hija in resultado.hijos.get(carpeta, ())
            if resultado.tamano_carpetas[hija] > 0
        ]
        candidatos += [
            (archivo.tamano, False, archivo)
            for archivo in indice.archivos.get(carpeta, ())
            if archivo.tamano > 0
        ]
        mayores = heapq.nlargest(max_hijos, candidatos, key=lambda c: c[0])

        nodos = []
        for tamano, es_carpeta, elemento in mayores:
            if es_carpeta:
                nodos.append(nodo_carpeta(elemento, restantes))
            else:
                nodos.append({
                    "nombre": elemento.nombre, "ruta": elemento.ruta, "tamano": tamano,
                    "es_carpeta": False, "tipo": clasificar(elemento.ruta),
                })

        ocultos = len(candidatos) - len(mayores)
        if ocultos > 0:
            nodos.append({
                "nombre": f"({ocultos} elementos más pequeños)", "ruta": None,
                "tamano": sum(c[0] for c in candidatos) - sum(c[0] for c in mayores),
                "es_carpeta": False, "tipo": AGRUPADO, "agrupado": True,
            })
        return nodos

    arbol = nodo_carpeta(clave, niveles)
    arbol["migas"] = _migas(resultado.raiz, clave)
    return arbol


def _migas(raiz: Path, clave: str) -> list[dict]:
    """Camino desde la raíz del escaneo hasta la carpeta, para la ruta de navegación."""
    migas = [{"nombre": raiz.name or str(raiz), "ruta": str(raiz)}]
    actual = raiz
    for parte in Path(clave).relative_to(raiz).parts:
        actual = actual / parte
        migas.append({"nombre": parte, "ruta": str(actual)})
    return migas
