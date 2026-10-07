// Pestaña "Historial": gráfica de uso en el tiempo, comparación entre dos escaneos
// y escaneos programados. Los datos vienen de /api/historial, /api/comparar y
// /api/programados. Usa las funciones comunes de app.js (el, api, enviar, $...).
"use strict";

const historial = { raiz: null, escaneos: [], cargado: false };
const MB = 1024 * 1024;

const fechaHora = (iso) => new Date(iso).toLocaleString("es", {
  year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
const fechaCorta = (iso) => new Date(iso).toLocaleDateString("es", { year: "2-digit", month: "short", day: "numeric" });
const cambioEnMb = (bytes) => `${bytes > 0 ? "▲ +" : bytes < 0 ? "▼ −" : ""}${(Math.abs(bytes) / MB).toLocaleString("es", {
  minimumFractionDigits: 1, maximumFractionDigits: 1 })} MB`;

async function cargarHistorial() {
  const datos = await api("/api/historial");
  historial.raiz = datos.raiz;
  historial.escaneos = datos.escaneos;
  historial.cargado = true;
  pintarGraficaDeUso();
  pintarSelectores();
  await compararElegidos();
  cargarProgramados();
}

// ---------------------------------------------------------------- gráfica de línea

function svg(etiqueta, atributos = {}, texto) {
  const nodo = document.createElementNS("http://www.w3.org/2000/svg", etiqueta);
  for (const [clave, valor] of Object.entries(atributos)) nodo.setAttribute(clave, valor);
  if (texto != null) nodo.textContent = texto;
  return nodo;
}

function pintarGraficaDeUso() {
  const contenedor = $("#grafica-uso");
  const puntos = historial.escaneos;
  $("#grafica-nota").hidden = puntos.length >= 2;
  $("#grafica-nota").textContent = puntos.length === 0
    ? "Todavía no hay escaneos guardados de esta carpeta."
    : "Solo hay un escaneo guardado. La línea aparecerá cuando haya al menos dos: vuelve a escanear otro día o programa un escaneo.";
  if (!puntos.length || $("#panel-historial").hidden) { contenedor.replaceChildren(); return; }

  const ancho = Math.max(contenedor.clientWidth, 320), alto = 260;
  const m = { izq: 70, der: 20, arr: 16, aba: 34 };
  const tiempos = puntos.map((p) => new Date(p.fecha).getTime());
  const valores = puntos.map((p) => p.tamano_total);
  const t0 = Math.min(...tiempos), t1 = Math.max(...tiempos);
  // El eje vertical se ajusta a los datos (con margen) para que los cambios se vean.
  let v0 = Math.min(...valores), v1 = Math.max(...valores);
  const holgura = (v1 - v0) * 0.15 || Math.max(v1 * 0.05, 1);
  v0 = Math.max(0, v0 - holgura); v1 += holgura;
  const x = (t) => (t1 === t0 ? (m.izq + ancho - m.der) / 2 : m.izq + ((t - t0) / (t1 - t0)) * (ancho - m.izq - m.der));
  const y = (v) => alto - m.aba - ((v - v0) / (v1 - v0)) * (alto - m.arr - m.aba);

  const dibujo = svg("svg", { viewBox: `0 0 ${ancho} ${alto}`, width: ancho, height: alto, role: "img",
    "aria-label": `Espacio ocupado por ${historial.raiz} en ${puntos.length} escaneos` });

  // Líneas de referencia discretas con su valor.
  for (let i = 0; i <= 3; i++) {
    const valor = v0 + ((v1 - v0) * i) / 3;
    dibujo.append(
      svg("line", { x1: m.izq, x2: ancho - m.der, y1: y(valor), y2: y(valor), class: "rejilla" }),
      svg("text", { x: m.izq - 8, y: y(valor) + 4, "text-anchor": "end", class: "eje" }, tamanoLegible(valor)));
  }
  // Fechas: primera y última (y la del medio si hay sitio).
  const marcas = puntos.length > 2 && ancho > 520 ? [0, Math.floor((puntos.length - 1) / 2), puntos.length - 1]
    : puntos.length > 1 ? [0, puntos.length - 1] : [0];
  marcas.forEach((i, posicion) => dibujo.append(svg("text", {
    x: x(tiempos[i]), y: alto - 10, class: "eje",
    "text-anchor": marcas.length === 1 ? "middle" : posicion === 0 ? "start" : posicion === marcas.length - 1 ? "end" : "middle",
  }, fechaCorta(puntos[i].fecha))));

  if (puntos.length > 1) {
    dibujo.append(svg("path", { class: "linea",
      d: puntos.map((p, i) => `${i ? "L" : "M"}${x(tiempos[i]).toFixed(1)},${y(valores[i]).toFixed(1)}`).join(" ") }));
  }
  puntos.forEach((p, i) => {
    const cx = x(tiempos[i]), cy = y(valores[i]);
    const anterior = i > 0 ? valores[i] - valores[i - 1] : null;
    const lineas = [fechaHora(p.fecha), tamanoLegible(p.tamano_total),
      anterior === null ? "Primer escaneo guardado" : `${cambioEnMb(anterior)} desde el anterior`];
    // La zona sensible es mayor que el punto, para acertar con el ratón o el dedo.
    const zona = svg("circle", { cx, cy, r: 14, class: "zona", tabindex: 0, role: "img", "aria-label": lineas.join(", ") });
    zona.addEventListener("mousemove", (e) => infoDeGrafica(lineas, e.clientX, e.clientY));
    zona.addEventListener("mouseleave", ocultarInfo);
    zona.addEventListener("focus", () => { const c = zona.getBoundingClientRect(); infoDeGrafica(lineas, c.right, c.bottom); });
    zona.addEventListener("blur", ocultarInfo);
    dibujo.append(svg("circle", { cx, cy, r: 4.5, class: "punto" }), zona);
  });
  contenedor.replaceChildren(dibujo);
}

// Reutiliza el recuadro flotante del mapa de bloques.
function infoDeGrafica([titulo, ...resto], px, py) {
  const info = $("#mapa-info");
  info.replaceChildren(el("strong", { texto: titulo }), ...resto.map((texto) => el("span", { texto })));
  info.hidden = false;
  const margen = 14;
  info.style.left = `${Math.max(4, px + margen + info.offsetWidth > innerWidth ? px - margen - info.offsetWidth : px + margen)}px`;
  info.style.top = `${Math.max(4, py + margen + info.offsetHeight > innerHeight ? py - margen - info.offsetHeight : py + margen)}px`;
}

// ---------------------------------------------------------------- comparar dos fechas

function pintarSelectores() {
  const opciones = () => historial.escaneos.map((e) =>
    el("option", { value: e.id, texto: `${fechaHora(e.fecha)} — ${tamanoLegible(e.tamano_total)}` }));
  $("#comparar-antes").replaceChildren(...opciones());
  $("#comparar-despues").replaceChildren(...opciones());
  const n = historial.escaneos.length;
  if (n >= 2) {
    // Por defecto, los dos últimos escaneos.
    $("#comparar-antes").value = historial.escaneos[n - 2].id;
    $("#comparar-despues").value = historial.escaneos[n - 1].id;
  }
}

async function compararElegidos() {
  const resumen = $("#comparar-resumen"), cuerpo = $("#cambios");
  cuerpo.replaceChildren();
  $("#tabla-cambios").hidden = true;
  if (historial.escaneos.length < 2) {
    resumen.textContent = "Hacen falta al menos dos escaneos guardados de esta carpeta para comparar.";
    return;
  }
  const antes = $("#comparar-antes").value, despues = $("#comparar-despues").value;
  if (antes === despues) { resumen.textContent = "Elige dos escaneos distintos."; return; }
  let c;
  try { c = await api(`/api/comparar?antes=${antes}&despues=${despues}`); }
  catch (error) { resumen.textContent = error.message; return; }

  const verbo = c.diferencia_total > 0 ? "creció" : c.diferencia_total < 0 ? "disminuyó" : "no cambió";
  resumen.textContent = `Entre el ${fechaHora(c.antes.fecha)} y el ${fechaHora(c.despues.fecha)} la carpeta ${verbo}`
    + (c.diferencia_total ? ` ${(Math.abs(c.diferencia_total) / MB).toLocaleString("es", { maximumFractionDigits: 1 })} MB` : "")
    + ` (de ${tamanoLegible(c.antes.tamano_total)} a ${tamanoLegible(c.despues.tamano_total)}).`
    + (c.cambios.length ? "" : " Ninguna subcarpeta cambió 1 MB o más.")
    + (c.total_cambios > c.cambios.length ? ` Se muestran los ${c.cambios.length} cambios mayores de ${c.total_cambios}.` : "");
  $("#tabla-cambios").hidden = c.cambios.length === 0;
  cuerpo.replaceChildren(...c.cambios.map((cambio) => el("tr", {},
    el("td", { clase: "ruta" }, cambio.ruta,
      cambio.antes === 0 ? el("span", { clase: "etiqueta", texto: "nueva" }) : null,
      cambio.despues === 0 ? el("span", { clase: "etiqueta", texto: "ya no existe" }) : null),
    el("td", { clase: "num", texto: tamanoLegible(cambio.antes) }),
    el("td", { clase: "num", texto: tamanoLegible(cambio.despues) }),
    el("td", { clase: "num", texto: cambioEnMb(cambio.diferencia) }))));
}

// ---------------------------------------------------------------- escaneos programados

async function cargarProgramados() {
  const lista = $("#programados");
  let tareas;
  try { tareas = await api("/api/programados"); }
  catch (error) { lista.replaceChildren(el("li", { clase: "suave", texto: error.message })); return; }
  if (!tareas.length) {
    lista.replaceChildren(el("li", { clase: "suave", texto: "No hay ningún escaneo programado." }));
    return;
  }
  lista.replaceChildren(...tareas.map((t) => el("li", {},
    el("span", { clase: "ruta" },
      el("strong", { texto: t.ruta }),
      el("span", { clase: "suave", texto: ` — ${t.frecuencia === "semanal" ? "cada lunes" : "cada día"} a las ${t.hora}` })),
    el("button", { clase: "boton secundario", type: "button", texto: "Quitar",
      "aria-label": `Quitar el escaneo programado de ${t.ruta}`,
      onclick: async () => {
        try { await enviar("/api/programados/quitar", { nombre: t.nombre }); } catch (e) { avisoProgramar(e.message); }
        cargarProgramados();
      } }))));
}

function avisoProgramar(texto) {
  $("#programar-aviso").textContent = texto || "";
  $("#programar-aviso").hidden = !texto;
}

function conectarHistorial() {
  $("#comparar-antes").addEventListener("change", compararElegidos);
  $("#comparar-despues").addEventListener("change", compararElegidos);
  $("#btn-programar").addEventListener("click", async () => {
    avisoProgramar("");
    try {
      await enviar("/api/programados", {
        ruta: historial.raiz, frecuencia: $("#programar-frecuencia").value, hora: $("#programar-hora").value });
    } catch (error) { avisoProgramar(error.message); }
    cargarProgramados();
  });
}
document.addEventListener("DOMContentLoaded", conectarHistorial);

// ---------------------------------------------------------------- conexión con el resto de la página

window.addEventListener("resultados-listos", () => {
  historial.cargado = false;
  if (!$("#panel-historial").hidden) cargarHistorial().catch(() => {});
});
window.addEventListener("pestana-abierta", (evento) => {
  if (evento.detail !== "panel-historial") return;
  if (historial.cargado) pintarGraficaDeUso(); else cargarHistorial().catch(() => {});
});
window.addEventListener("resize", () => { if (historial.cargado) pintarGraficaDeUso(); });
