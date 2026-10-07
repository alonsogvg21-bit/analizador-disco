// Lógica de la página. Sin bibliotecas externas: funciona sin conexión a internet.
"use strict";

const TOKEN = document.querySelector('meta[name="token"]').content;
const $ = (selector) => document.querySelector(selector);

const NOMBRES_TIPO = {
  videos: ["Videos", "Películas y grabaciones: mp4, mkv, avi…"],
  imagenes: ["Imágenes", "Fotos y dibujos: jpg, png, gif…"],
  documentos: ["Documentos", "PDF, Word, Excel, texto…"],
  comprimidos: ["Comprimidos", "Archivos empaquetados: zip, rar, 7z…"],
  instaladores: ["Instaladores", "Programas para instalar e imágenes de disco: exe, msi, iso…"],
  codigo: ["Código", "Archivos de programación: py, js, html…"],
  otros: ["Otros", "Todo lo que no encaja en las demás clases (datos de programas, sin extensión…)."],
};

// ---------------------------------------------------------------- utilidades

// Crea un elemento. Los textos siempre entran con textContent, nunca como HTML:
// un nombre de archivo raro no puede inyectar nada en la página.
function el(etiqueta, propiedades = {}, ...hijos) {
  const nodo = document.createElement(etiqueta);
  for (const [clave, valor] of Object.entries(propiedades)) {
    if (clave === "clase") nodo.className = valor;
    else if (clave === "texto") nodo.textContent = valor;
    else if (clave.startsWith("on")) nodo.addEventListener(clave.slice(2), valor);
    else if (valor === true) nodo.setAttribute(clave, "");
    else if (valor !== false && valor != null) nodo.setAttribute(clave, valor);
  }
  for (const hijo of hijos) if (hijo != null) nodo.append(hijo);
  return nodo;
}

function tamanoLegible(bytes) {
  const unidades = ["B", "KB", "MB", "GB", "TB"];
  let valor = Math.max(bytes, 0), i = 0;
  while (valor >= 1024 && i < unidades.length - 1) { valor /= 1024; i++; }
  return i === 0 ? `${valor} B` : `${valor.toFixed(1)} ${unidades[i]}`;
}

const numero = (n) => n.toLocaleString("es");
const porcentaje = (parte, total) => (total ? (parte * 100) / total : 0);
const fecha = (segundos) => new Date(segundos * 1000).toLocaleDateString("es", { year: "numeric", month: "short", day: "numeric" });

async function api(ruta, opciones) {
  const respuesta = await fetch(ruta, opciones);
  const datos = await respuesta.json().catch(() => ({}));
  if (!respuesta.ok) throw new Error(datos.error || `Error ${respuesta.status}`);
  return datos;
}

const enviar = (ruta, cuerpo = {}) => api(ruta, {
  method: "POST",
  headers: { "Content-Type": "application/json", "X-Token": TOKEN },
  body: JSON.stringify(cuerpo),
});

function barra(porc, clase = "barra-dato") {
  return el("div", { clase }, el("span", { style: `width:${Math.min(Math.max(porc, 0), 100)}%` }));
}

function mostrarAviso(texto) {
  $("#aviso").textContent = texto || "";
  $("#aviso").hidden = !texto;
}

// ---------------------------------------------------------------- tema claro / oscuro

function temaActual() {
  return document.documentElement.dataset.tema
    || (matchMedia("(prefers-color-scheme: dark)").matches ? "oscuro" : "claro");
}

function pintarBotonTema() {
  $("#btn-tema").textContent = temaActual() === "oscuro" ? "Modo claro" : "Modo oscuro";
}

$("#btn-tema").addEventListener("click", () => {
  const nuevo = temaActual() === "oscuro" ? "claro" : "oscuro";
  document.documentElement.dataset.tema = nuevo;
  try { localStorage.setItem("tema", nuevo); } catch (e) { /* modo privado: no se guarda */ }
  pintarBotonTema();
});

// ---------------------------------------------------------------- discos

function estadoDisco(porc) {
  if (porc < 70) return ["bueno", "Con espacio de sobra"];
  if (porc < 90) return ["aviso-color", "Se está llenando"];
  return ["critico", "Casi lleno"];
}

async function cargarDiscos() {
  const discos = await api("/api/discos");
  $("#discos").replaceChildren(...discos.map((d) => {
    const [clase, etiqueta] = estadoDisco(d.porcentaje);
    const uso = barra(d.porcentaje, "barra-uso");
    uso.firstChild.className = clase; // verde, amarillo o rojo según lo lleno que esté
    return el("article", { clase: "tarjeta disco" },
      el("div", { clase: "disco-cabecera" },
        el("span", { clase: "disco-nombre", texto: d.punto_montaje }),
        el("span", { clase: "disco-porcentaje", texto: `${Math.round(d.porcentaje)}%` })),
      uso,
      el("span", { clase: "estado" }, el("i", { clase }), etiqueta),
      el("p", { clase: "suave", texto: `${tamanoLegible(d.usado)} usados de ${tamanoLegible(d.total)} · ${tamanoLegible(d.libre)} libres` }),
      el("button", { clase: "boton secundario", type: "button", texto: "Analizar este disco",
        onclick: () => elegirRuta(d.punto_montaje) }));
  }));
}

async function cargarSugerencias() {
  const sugerencias = await api("/api/sugerencias");
  $("#sugerencias").replaceChildren(...sugerencias.map((s) =>
    el("button", { clase: "boton secundario", type: "button", texto: s.nombre, title: s.ruta,
      onclick: () => elegirRuta(s.ruta) })));
  if (!$("#ruta").value && sugerencias.length) $("#ruta").value = sugerencias[0].ruta;
}

function elegirRuta(ruta) {
  $("#ruta").value = ruta;
  $("#titulo-escaneo").scrollIntoView({ behavior: "smooth", block: "start" });
  $("#btn-escanear").focus({ preventScroll: true });
}

// ---------------------------------------------------------------- escaneo y progreso

let temporizador = null;

$("#btn-escanear").addEventListener("click", async () => {
  mostrarAviso("");
  try {
    const estado = await enviar("/api/escanear", {
      ruta: $("#ruta").value, duplicados: $("#con-duplicados").checked,
    });
    $("#resultados").hidden = true;
    pintarEstado(estado);
    vigilar();
  } catch (error) {
    mostrarAviso(error.message);
  }
});

$("#btn-cancelar").addEventListener("click", () => enviar("/api/cancelar").catch(() => {}));

function vigilar() {
  clearInterval(temporizador);
  temporizador = setInterval(async () => {
    let estado;
    try { estado = await api("/api/estado"); } catch (e) { return; }
    pintarEstado(estado);
    if (!["escaneando", "basura"].includes(estado.fase)) {
      clearInterval(temporizador);
      if (estado.fase === "listo") cargarResultados();
    }
  }, 500);
}

function pintarEstado(estado) {
  const enCurso = ["escaneando", "basura"].includes(estado.fase);
  $("#progreso").hidden = !enCurso;
  $("#btn-escanear").disabled = enCurso;
  // Aviso de disco de red: el escaneo irá más lento.
  $("#progreso-aviso").textContent = estado.aviso || "";
  $("#progreso-aviso").hidden = !estado.aviso;

  if (estado.fase === "escaneando") {
    $(".barra-progreso").classList.add("indefinida");
    $("#progreso-relleno").style.width = "";
    $("#progreso-texto").textContent = `Contando archivos… ${numero(estado.archivos)} encontrados`;
    $("#progreso-carpeta").textContent = estado.carpeta_actual || "";
  } else if (estado.fase === "basura") {
    // Al comparar duplicados sí se conoce el total: la barra muestra el avance real.
    const conTotal = estado.total > 0;
    $(".barra-progreso").classList.toggle("indefinida", !conTotal);
    $("#progreso-relleno").style.width = conTotal ? `${porcentaje(estado.hechos, estado.total)}%` : "";
    $("#progreso-texto").textContent = conTotal
      ? `Comparando posibles duplicados… ${numero(estado.hechos)} de ${numero(estado.total)}`
      : "Buscando archivos basura…";
    $("#progreso-carpeta").textContent = "";
  } else if (estado.fase === "cancelado") {
    mostrarAviso("Escaneo cancelado.");
  } else if (estado.fase === "error") {
    mostrarAviso(`No se pudo completar el escaneo: ${estado.error}`);
  }
}

// ---------------------------------------------------------------- resultados

async function cargarResultados() {
  const [resultado, basura] = await Promise.all([api("/api/resultado"), api("/api/basura")]);

  $("#resumen-texto").textContent =
    `${resultado.raiz} ocupa ${tamanoLegible(resultado.tamano_total)} en ${numero(resultado.num_archivos)} archivos.`;
  const notas = [];
  if (resultado.errores) notas.push(`${numero(resultado.errores)} elementos no se pudieron leer (sin permisos o en uso) y se ignoraron.`);
  if (resultado.bytes_en_nube) notas.push(`${tamanoLegible(resultado.bytes_en_nube)} están solo en la nube (OneDrive) y no ocupan disco.`);
  $("#resumen-notas").textContent = notas.join(" ");

  pintarTipos(resultado);
  cargarArchivos();
  pintarBasura(basura);
  $("#arbol").replaceChildren(await nivelDeCarpetas(""));

  $("#resultados").hidden = false;
  window.dispatchEvent(new CustomEvent("resultados-listos")); // lo escucha mapa.js
  $("#resultados").scrollIntoView({ behavior: "smooth", block: "start" });
}

function pintarTipos(resultado) {
  $("#tipos").replaceChildren(...resultado.tipos.map((t) => {
    const [nombre, explicacion] = NOMBRES_TIPO[t.tipo] || [t.tipo, ""];
    const porc = porcentaje(t.tamano, resultado.tamano_total);
    return el("div", { clase: "fila-tipo", title: explicacion },
      el("span", { texto: nombre }),
      barra(porc),
      el("span", { clase: "valor",
        texto: `${tamanoLegible(t.tamano)} · ${porc.toFixed(1)}% · ${numero(t.cantidad)} archivos` }));
  }));
}

// Tabla de archivos: el servidor ordena y filtra; aquí solo se pinta.
const vista = { orden: "tamano", sentido: "desc", filas: [] };

async function cargarArchivos() {
  const parametros = new URLSearchParams({
    orden: vista.orden, sentido: vista.sentido, tipos: $("#filtro-tipo").value,
    min_mb: $("#filtro-min").value || 0, limite: $("#filtro-limite").value,
  });
  try {
    vista.filas = await api(`/api/archivos?${parametros}`);
    $("#archivos-aviso").hidden = vista.filas.length > 0;
    $("#archivos-aviso").textContent = "Ningún archivo cumple esos filtros.";
  } catch (error) {
    vista.filas = [];
    $("#archivos-aviso").hidden = false;
    $("#archivos-aviso").textContent = error.message;
  }
  pintarArchivos();
}

function pintarArchivos() {
  // La flecha del encabezado indica por qué columna se ordena y en qué sentido.
  document.querySelectorAll("#tabla-archivos .orden").forEach((boton) => {
    const activa = boton.dataset.orden === vista.orden;
    boton.closest("th").setAttribute("aria-sort",
      activa ? (vista.sentido === "asc" ? "ascending" : "descending") : "none");
  });

  $("#archivos").replaceChildren(...vista.filas.map((a, i) => {
    const casilla = el("input", { type: "checkbox", "aria-label": a.ruta });
    casilla.checked = seleccion.has(a.id);
    casilla.addEventListener("change", () => {
      if (casilla.checked) seleccion.set(a.id, { ruta: a.ruta, tamano: a.tamano }); else seleccion.delete(a.id);
      actualizarContador();
    });
    return el("tr", {},
      el("td", {}, casilla),
      el("td", { clase: "num", texto: i + 1 }),
      el("td", { clase: "ruta", texto: a.ruta }),
      el("td", { texto: (NOMBRES_TIPO[a.tipo] || [a.tipo])[0] }),
      el("td", { clase: "num", texto: tamanoLegible(a.tamano) }),
      el("td", { clase: "num", texto: fecha(a.modificado) }),
      el("td", { clase: "num", texto: fecha(a.accedido) }));
  }));
  $("#archivos-todos").checked = vista.filas.length > 0 && vista.filas.every((a) => seleccion.has(a.id));
}

document.querySelectorAll("#tabla-archivos .orden").forEach((boton) => {
  boton.addEventListener("click", () => {
    if (vista.orden === boton.dataset.orden) vista.sentido = vista.sentido === "desc" ? "asc" : "desc";
    else { vista.orden = boton.dataset.orden; vista.sentido = "desc"; }
    cargarArchivos();
  });
});
for (const control of ["#filtro-tipo", "#filtro-min", "#filtro-limite"]) {
  $(control).addEventListener("change", cargarArchivos);
}
$("#filtro-tipo").append(...Object.entries(NOMBRES_TIPO).map(([tipo, [nombre]]) =>
  el("option", { value: tipo, texto: nombre })));
$("#archivos-todos").addEventListener("change", () => {
  for (const a of vista.filas) {
    if ($("#archivos-todos").checked) seleccion.set(a.id, { ruta: a.ruta, tamano: a.tamano });
    else seleccion.delete(a.id);
  }
  pintarArchivos();
  actualizarContador();
});

// Árbol de carpetas: cada nivel se pide al servidor solo cuando se despliega.
async function nivelDeCarpetas(ruta) {
  const nivel = await api(`/api/carpetas?ruta=${encodeURIComponent(ruta)}`);
  const lista = el("ul", { clase: "arbol-lista" });

  for (const carpeta of nivel.subcarpetas) {
    const item = el("li");
    const contenido = [
      el("span", { clase: "nombre", texto: carpeta.nombre, title: carpeta.ruta }),
      barra(porcentaje(carpeta.tamano, nivel.tamano)),
      el("span", { clase: "tamano", texto: tamanoLegible(carpeta.tamano) }),
    ];
    if (carpeta.tiene_subcarpetas) {
      const fila = el("button", { clase: "fila-carpeta", type: "button", "aria-expanded": "false" },
        el("span", { clase: "flecha", texto: "▸" }), ...contenido);
      fila.addEventListener("click", async () => {
        const abierto = fila.getAttribute("aria-expanded") === "true";
        fila.setAttribute("aria-expanded", String(!abierto));
        if (abierto) { item.querySelector(".arbol-lista")?.remove(); return; }
        try { item.append(await nivelDeCarpetas(carpeta.ruta)); }
        catch (e) { fila.setAttribute("aria-expanded", "false"); }
      });
      item.append(fila);
    } else {
      item.append(el("div", { clase: "fila-carpeta" }, el("span"), ...contenido));
    }
    lista.append(item);
  }

  if (nivel.tamano_archivos_directos > 0) {
    lista.append(el("li", {}, el("div", { clase: "fila-carpeta suave" }, el("span"),
      el("span", { clase: "nombre", texto: "(archivos sueltos en esta carpeta)" }),
      barra(porcentaje(nivel.tamano_archivos_directos, nivel.tamano)),
      el("span", { clase: "tamano", texto: tamanoLegible(nivel.tamano_archivos_directos) }))));
  }
  if (!lista.children.length) lista.append(el("li", { clase: "suave", texto: "Esta carpeta está vacía." }));
  return lista;
}

// ---------------------------------------------------------------- basura

const seleccion = new Map(); // id -> { ruta, tamano }

function totalSeleccionado() {
  let total = 0;
  for (const elemento of seleccion.values()) total += elemento.tamano;
  return total;
}

function actualizarContador() {
  const total = totalSeleccionado();
  $("#btn-limpiar").disabled = seleccion.size === 0;
  $("#btn-mover").disabled = seleccion.size === 0;
  $("#contador").textContent = seleccion.size
    ? `${numero(seleccion.size)} ${seleccion.size === 1 ? "elemento seleccionado" : "elementos seleccionados"} · se liberarían ${tamanoLegible(total)}`
    : "Nada seleccionado.";
}

function pintarBasura(categorias) {
  seleccion.clear();
  const conDatos = categorias.filter((c) => c.total_elementos > 0);
  $("#basura").replaceChildren(...conDatos.map(tarjetaCategoria));
  if (!conDatos.length) $("#basura").append(el("p", { texto: "No se encontró nada que limpiar." }));
  actualizarContador();
}

function tarjetaCategoria(categoria) {
  const casillas = [];

  const filas = categoria.elementos.map((e) => {
    const casilla = el("input", { type: "checkbox", disabled: !e.limpiable, "aria-label": e.ruta });
    casilla.addEventListener("change", () => {
      if (casilla.checked) seleccion.set(e.id, { ruta: e.ruta, tamano: e.tamano }); else seleccion.delete(e.id);
      actualizarContador();
    });
    if (e.limpiable) casillas.push(casilla);
    return el("label", { clase: "fila-basura" }, casilla,
      el("span", { clase: "info" },
        el("span", { clase: "ruta", texto: e.ruta }),
        e.limpiable ? null : el("span", { clase: "etiqueta", texto: "solo informativo" }),
        e.detalle ? el("span", { clase: "suave", texto: e.detalle, style: "display:block" }) : null),
      el("span", { clase: "tamano", texto: tamanoLegible(e.tamano) }));
  });

  const cuerpo = el("div", { clase: "categoria-cuerpo" }, el("p", { clase: "suave", texto: categoria.descripcion }));
  if (casillas.length) {
    const todas = el("input", { type: "checkbox" });
    todas.addEventListener("change", () => {
      for (const casilla of casillas) {
        if (casilla.checked !== todas.checked) { casilla.checked = todas.checked; casilla.dispatchEvent(new Event("change")); }
      }
    });
    cuerpo.append(el("label", { clase: "casilla" }, todas, el("strong", { texto: "Seleccionar todo lo de esta lista" })));
  }
  cuerpo.append(...filas);
  if (categoria.ocultos) {
    cuerpo.append(el("p", { clase: "suave", style: "margin-top:12px",
      texto: `Se muestran los ${numero(categoria.elementos.length)} más grandes. Hay ${numero(categoria.ocultos)} más pequeños que suman ${tamanoLegible(categoria.tamano_ocultos)}; están en el reporte CSV.` }));
  }

  return el("details", { clase: "tarjeta categoria" },
    el("summary", {},
      el("strong", { texto: categoria.nombre }),
      el("span", { clase: "suave", texto: `${tamanoLegible(categoria.tamano_total)} · ${numero(categoria.total_elementos)} ${categoria.total_elementos === 1 ? "elemento" : "elementos"}` })),
    cuerpo);
}

// ---------------------------------------------------------------- papelera y mover, con confirmación

let accion = "papelera"; // o "mover"
const plural = (n) => `${numero(n)} ${n === 1 ? "elemento" : "elementos"}`;

// Paso 1: los botones solo abren la ventana con la lista exacta. No tocan nada.
function abrirDialogo(nuevaAccion) {
  accion = nuevaAccion;
  const mover = accion === "mover";
  const elegidos = [...seleccion.values()].sort((a, b) => b.tamano - a.tamano);
  $("#dialogo-titulo").textContent = mover ? "¿Mover a otra carpeta?" : "¿Enviar a la papelera?";
  $("#dialogo-resumen").textContent = mover
    ? `Vas a mover ${plural(elegidos.length)} (${tamanoLegible(totalSeleccionado())}).`
    : `Vas a enviar ${plural(elegidos.length)} a la papelera. Se liberarían ${tamanoLegible(totalSeleccionado())}.`;
  $("#dialogo-lista").replaceChildren(...elegidos.map((e) => el("li", {},
    el("span", { clase: "ruta", texto: e.ruta }),
    el("span", { clase: "tamano", texto: tamanoLegible(e.tamano) }))));
  $("#campo-destino").hidden = !mover;
  $("#nota-mover").hidden = !mover;
  $("#nota-papelera").hidden = mover;
  $("#dialogo-error").hidden = true;
  $("#solo-simular").checked = true;   // por seguridad, se empieza siempre simulando
  pintarBotonConfirmar();
  $("#dialogo").showModal();
  // El foco nunca empieza en la acción peligrosa.
  (mover ? $("#destino") : $("#dialogo-cancelar")).focus();
}
$("#btn-limpiar").addEventListener("click", () => abrirDialogo("papelera"));
$("#btn-mover").addEventListener("click", () => abrirDialogo("mover"));

function pintarBotonConfirmar() {
  const boton = $("#dialogo-confirmar");
  boton.textContent = $("#solo-simular").checked ? "Simular"
    : accion === "mover" ? "Sí, mover" : "Sí, enviar a la papelera";
  boton.classList.toggle("peligro", accion !== "mover");
  boton.classList.toggle("principal", accion === "mover");
}
$("#solo-simular").addEventListener("change", pintarBotonConfirmar);
$("#dialogo-cancelar").addEventListener("click", () => $("#dialogo").close());

// Paso 2: solo al confirmar se llama al servidor.
$("#dialogo-confirmar").addEventListener("click", async () => {
  const simulacion = $("#solo-simular").checked;
  const boton = $("#dialogo-confirmar");
  const cuerpo = { ids: [...seleccion.keys()], simulacion, confirmado: !simulacion };
  // Más de 1 GB: se pregunta una segunda vez antes de tocar nada.
  if (!simulacion && totalSeleccionado() > 1024 ** 3) {
    const seguro = window.confirm(
      `Son ${tamanoLegible(totalSeleccionado())}, más de 1 GB.\n\n¿Seguro que quieres continuar?`);
    if (!seguro) return;
    cuerpo.confirmado_doble = true;
  }
  if (accion === "mover") cuerpo.destino = $("#destino").value;
  boton.disabled = true;
  boton.textContent = "Trabajando…";
  $("#dialogo-error").hidden = true;
  try {
    const hecho = await enviar(accion === "mover" ? "/api/mover" : "/api/limpiar", cuerpo);
    $("#dialogo").close();
    pintarResultadoAccion(hecho);
    if (!simulacion) {
      // Lo movido o enviado desaparece de las listas y se actualizan los discos.
      pintarBasura(await api("/api/basura"));
      cargarArchivos();
      cargarDiscos().catch(() => {});
    }
  } catch (error) {
    // Por ejemplo, la carpeta de destino no existe: se avisa sin cerrar la ventana.
    $("#dialogo-error").textContent = error.message;
    $("#dialogo-error").hidden = false;
  } finally {
    boton.disabled = false;
    pintarBotonConfirmar();
  }
});

function pintarResultadoAccion(hecho) {
  const caja = $("#resultado-accion");
  const movimiento = "movidos" in hecho;
  const hechos = movimiento ? hecho.movidos : hecho.enviados;
  let titulo;
  if (movimiento) {
    titulo = hecho.simulacion
      ? `Simulación: se habrían movido ${plural(hechos.length)} (${tamanoLegible(hecho.bytes_movidos)}) a ${hecho.destino}. No se ha tocado nada.`
      : `Listo: ${plural(hechos.length)} (${tamanoLegible(hecho.bytes_movidos)}) ahora en ${hecho.destino}.`;
  } else {
    titulo = hecho.simulacion
      ? `Simulación: se habrían enviado ${plural(hechos.length)} a la papelera (${tamanoLegible(hecho.bytes_liberados)}). No se ha tocado nada.`
      : `Listo: ${plural(hechos.length)} en la papelera. Espacio liberado: ${tamanoLegible(hecho.bytes_liberados)} (vuelve al disco al vaciar la papelera).`;
  }
  caja.hidden = false;
  caja.replaceChildren(el("strong", { texto: titulo }));
  if (hecho.omitidos.length) {
    caja.append(
      el("p", { clase: "suave", style: "margin:8px 0 0", texto: `${numero(hecho.omitidos.length)} no se tocaron:` }),
      el("ul", {}, ...hecho.omitidos.map((o) => el("li", { clase: "ruta", texto: `${o.ruta} — ${o.motivo}` }))));
  }
  if (!hecho.simulacion) {
    caja.append(el("p", { clase: "suave", style: "margin:8px 0 0",
      texto: "Los tamaños de carpetas, tipos y mapa son los del último escaneo; vuelve a escanear para actualizarlos." }));
  }
  caja.scrollIntoView({ behavior: "smooth", block: "center" });
}

// ---------------------------------------------------------------- pestañas

document.querySelectorAll('[role="tab"]').forEach((pestana) => {
  pestana.addEventListener("click", () => {
    document.querySelectorAll('[role="tab"]').forEach((otra) => {
      const activa = otra === pestana;
      otra.setAttribute("aria-selected", String(activa));
      $(`#${otra.dataset.panel}`).hidden = !activa;
    });
    window.dispatchEvent(new CustomEvent("pestana-abierta", { detail: pestana.dataset.panel }));
  });
});

// Permite abrir directamente una pestaña, p. ej. http://127.0.0.1:5000/#panel-basura
document.querySelector(`[role="tab"][data-panel="${location.hash.slice(1)}"]`)?.click();

// ---------------------------------------------------------------- arranque

pintarBotonTema();
cargarDiscos().catch((e) => mostrarAviso(e.message));
cargarSugerencias().catch(() => {});
// Si se recarga la página, se recupera el escaneo en marcha o el último terminado.
api("/api/estado").then((estado) => {
  pintarEstado(estado);
  if (["escaneando", "basura"].includes(estado.fase)) vigilar();
  else if (estado.fase === "listo") cargarResultados();
}).catch(() => {});
