// Mapa de bloques (treemap). Los datos vienen de /api/arbol, que los saca del motor.
// d3-hierarchy (en static/vendor) solo calcula la posición de cada bloque; el
// dibujo se hace aquí con elementos HTML normales.
// Usa las funciones comunes de app.js (el, api, $, tamanoLegible, NOMBRES_TIPO).
"use strict";

const TIPOS_MAPA = ["videos", "imagenes", "documentos", "comprimidos", "instaladores", "codigo", "otros", "varios"];
const ALTO_CABECERA = 22;   // franja con el nombre de cada carpeta
const MIN_ANCHO_TEXTO = 56; // por debajo de esto el nombre no cabe y no se escribe
const MIN_ALTO_TEXTO = 20;

const mapa = { datos: null, pendiente: false };

function nombreTipo(tipo) {
  if (tipo === "varios") return "Varios pequeños";
  return (NOMBRES_TIPO[tipo] || [tipo])[0];
}

// ---------------------------------------------------------------- carga

async function cargarMapa(ruta) {
  const contenedor = $("#mapa");
  contenedor.setAttribute("aria-busy", "true");
  try {
    mapa.datos = await api(`/api/arbol?niveles=2&ruta=${encodeURIComponent(ruta || "")}`);
    pintarMigas(mapa.datos.migas);
    dibujarMapa();
  } catch (error) {
    contenedor.replaceChildren(el("p", { clase: "mapa-vacio", texto: `No se pudo cargar el mapa: ${error.message}` }));
  } finally {
    contenedor.removeAttribute("aria-busy");
  }
}

// Ruta de navegación: cada parte es un botón para volver a esa carpeta.
function pintarMigas(migas) {
  const partes = [];
  migas.forEach((miga, i) => {
    if (i > 0) partes.push(el("span", { clase: "separador", texto: "›", "aria-hidden": "true" }));
    const esActual = i === migas.length - 1;
    partes.push(esActual
      ? el("span", { clase: "miga actual", texto: miga.nombre, "aria-current": "page", title: miga.ruta })
      : el("button", { clase: "miga", type: "button", texto: miga.nombre, title: miga.ruta,
          onclick: () => cargarMapa(miga.ruta) }));
  });
  $("#mapa-migas").replaceChildren(...partes);
}

function pintarLeyenda() {
  if ($("#mapa-leyenda").children.length) return;
  $("#mapa-leyenda").replaceChildren(...TIPOS_MAPA.map((tipo) =>
    el("span", { clase: "leyenda-item" },
      el("i", { clase: `muestra tipo-${tipo}` }), nombreTipo(tipo))));
}

// ---------------------------------------------------------------- dibujo

function dibujarMapa() {
  const contenedor = $("#mapa");
  const datos = mapa.datos;
  if (!datos || $("#panel-mapa").hidden) return;
  pintarLeyenda();
  ocultarInfo();

  const ancho = contenedor.clientWidth, alto = contenedor.clientHeight;
  if (!datos.hijos || !datos.hijos.length) {
    contenedor.replaceChildren(el("p", { clase: "mapa-vacio", texto: "Esta carpeta está vacía." }));
    return;
  }

  // El área de cada bloque es proporcional a su tamaño. Solo cuentan las hojas:
  // el tamaño de una carpeta abierta es la suma de lo que contiene.
  const raiz = d3.hierarchy(datos, (d) => d.hijos)
    .sum((d) => (d.hijos ? 0 : d.tamano))
    .sort((a, b) => b.value - a.value);
  d3.treemap()
    .size([ancho, alto])
    .paddingInner(2)
    .paddingOuter((d) => (d.depth === 1 ? 2 : 0))
    .paddingTop((d) => (d.depth === 1 ? ALTO_CABECERA : 0))
    .round(true)(raiz);

  const bloques = [];
  for (const nodo of raiz.descendants()) {
    if (nodo.depth === 0) continue;
    const w = nodo.x1 - nodo.x0, h = nodo.y1 - nodo.y0;
    if (w < 2 || h < 2) continue; // demasiado pequeño para verse
    bloques.push(nodo.children ? bloqueGrupo(nodo, w, h) : bloqueHoja(nodo, w, h));
  }
  contenedor.replaceChildren(...bloques);
}

function colocar(elemento, nodo, w, h) {
  elemento.style.cssText = `left:${nodo.x0}px;top:${nodo.y0}px;width:${w}px;height:${h}px`;
  return elemento;
}

// Carpeta abierta: un marco con su nombre arriba y sus hijos dibujados dentro.
function bloqueGrupo(nodo, w, h) {
  const d = nodo.data;
  const cabecera = el("button", { clase: "grupo-nombre", type: "button",
    texto: w >= MIN_ANCHO_TEXTO ? `${d.nombre} · ${tamanoLegible(d.tamano)}` : "",
    "aria-label": descripcion(nodo), onclick: () => cargarMapa(d.ruta) });
  conInfo(cabecera, nodo);
  return colocar(el("div", { clase: "bloque grupo" }, cabecera), nodo, w, h);
}

// Archivo, carpeta sin abrir o grupo de pequeños: un bloque del color de su tipo.
function bloqueHoja(nodo, w, h) {
  const d = nodo.data;
  const hijos = [];
  if (w >= MIN_ANCHO_TEXTO && h >= MIN_ALTO_TEXTO) {
    hijos.push(el("span", { clase: "bloque-nombre", texto: d.nombre }));
    if (h >= 38) hijos.push(el("span", { clase: "bloque-tamano", texto: tamanoLegible(d.tamano) }));
  }
  const clase = `bloque hoja tipo-${d.tipo}${d.es_carpeta ? " carpeta" : ""}`;
  const bloque = d.es_carpeta
    ? el("button", { clase, type: "button", "aria-label": descripcion(nodo),
        onclick: () => cargarMapa(d.ruta) }, ...hijos)
    : el("div", { clase, tabindex: "0", role: "img", "aria-label": descripcion(nodo) }, ...hijos);
  conInfo(bloque, nodo);
  return colocar(bloque, nodo, w, h);
}

// ---------------------------------------------------------------- información al pasar el ratón

function lineasInfo(nodo) {
  const d = nodo.data, padre = nodo.parent.data;
  const porc = padre.tamano ? (d.tamano * 100) / padre.tamano : 0;
  let clase;
  if (d.agrupado) clase = "Elementos pequeños agrupados";
  else if (d.es_carpeta) clase = `Carpeta · sobre todo ${nombreTipo(d.tipo).toLowerCase()}`;
  else clase = `Archivo · ${nombreTipo(d.tipo)}`;
  return [d.nombre, clase, tamanoLegible(d.tamano),
    `${porc < 0.1 && porc > 0 ? "menos del 0.1" : porc.toFixed(1)}% de ${padre.nombre}`];
}

const descripcion = (nodo) => lineasInfo(nodo).join(", ") + (nodo.data.es_carpeta ? ". Pulsa para entrar." : "");

function conInfo(elemento, nodo) {
  elemento.addEventListener("mousemove", (evento) => { evento.stopPropagation(); mostrarInfo(nodo, evento.clientX, evento.clientY); });
  elemento.addEventListener("mouseleave", ocultarInfo);
  elemento.addEventListener("focus", () => {
    const caja = elemento.getBoundingClientRect();
    mostrarInfo(nodo, caja.left + 12, caja.top + 12);
  });
  elemento.addEventListener("blur", ocultarInfo);
}

function mostrarInfo(nodo, x, y) {
  const info = $("#mapa-info");
  const [nombre, clase, tamano, parte] = lineasInfo(nodo);
  info.replaceChildren(
    el("strong", { texto: nombre }),
    el("span", { texto: clase }),
    el("span", { texto: `${tamano} · ${parte}` }),
    nodo.data.es_carpeta ? el("span", { clase: "suave", texto: "Clic para entrar" }) : null);
  info.hidden = false;
  // Se coloca junto al cursor, sin salirse de la ventana.
  const margen = 14, ancho = info.offsetWidth, alto = info.offsetHeight;
  const izquierda = x + margen + ancho > innerWidth ? Math.max(4, x - margen - ancho) : x + margen;
  const arriba = y + margen + alto > innerHeight ? Math.max(4, y - margen - alto) : y + margen;
  info.style.left = `${izquierda}px`;
  info.style.top = `${arriba}px`;
}

function ocultarInfo() { $("#mapa-info").hidden = true; }

// ---------------------------------------------------------------- conexión con el resto de la página

// app.js avisa cuando hay un escaneo nuevo y cuando se cambia de pestaña.
window.addEventListener("resultados-listos", () => {
  mapa.datos = null;
  if (!$("#panel-mapa").hidden) cargarMapa("");
});

window.addEventListener("pestana-abierta", (evento) => {
  if (evento.detail !== "panel-mapa") return;
  if (mapa.datos) dibujarMapa(); else if (!$("#resultados").hidden) cargarMapa("");
});

// Si cambia el tamaño de la ventana, se recalculan los bloques con los mismos datos.
window.addEventListener("resize", () => {
  if (mapa.pendiente) return;
  mapa.pendiente = true;
  requestAnimationFrame(() => { mapa.pendiente = false; dibujarMapa(); });
});
