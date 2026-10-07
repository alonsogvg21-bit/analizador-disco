// Sección "Salud de los discos": una tarjeta por disco con semáforo, medidores
// de temperatura y de vida restante, y botones de autoprueba.
// Los datos vienen de /api/salud (que usa smartctl). Todo es lectura.
// Usa las funciones comunes de app.js (el, api, enviar, $, tamanoLegible, numero).
"use strict";

// Color y símbolo del semáforo. El estado también va escrito, nunca solo el color.
const SEMAFORO = {
  bueno: ["bueno", "✓"], precaucion: ["aviso-color", "!"], malo: ["critico", "✕"], desconocido: ["neutro", "?"],
};

function medidor(titulo, porcentaje, valor, clase, nota) {
  const barra = el("div", { clase: "barra-uso", role: "meter", "aria-label": titulo,
    "aria-valuemin": 0, "aria-valuemax": 100, "aria-valuenow": Math.round(porcentaje), "aria-valuetext": valor },
    el("span", { clase, style: `width:${Math.min(Math.max(porcentaje, 0), 100)}%` }));
  return el("div", { clase: "medidor" },
    el("div", { clase: "medidor-cabecera" }, el("span", { texto: titulo }), el("strong", { texto: valor })),
    barra,
    nota ? el("span", { clase: "suave", texto: nota }) : null);
}

function fila(etiqueta, valor) {
  return el("div", { clase: "dato" }, el("dt", { texto: etiqueta }), el("dd", { texto: valor }));
}

const oSinDato = (valor, formato = numero) => (valor === null || valor === undefined ? "sin dato" : formato(valor));

function tarjetaSalud(d) {
  const [clase, simbolo] = SEMAFORO[d.estado] || SEMAFORO.desconocido;
  const tarjeta = el("article", { clase: "tarjeta salud" },
    el("div", { clase: "salud-cabecera" },
      el("span", { clase: `semaforo ${clase}`, "aria-hidden": "true", texto: simbolo }),
      el("div", {},
        el("strong", { clase: "salud-estado", texto: d.nombre_estado }),
        el("div", { clase: "salud-modelo", texto: d.modelo || "Modelo desconocido" }),
        el("div", { clase: "suave", texto: d.dispositivo }))));

  if (d.error) {
    // Lo que no necesita permisos se muestra igualmente: de qué disco se trata.
    if (d.falta_permiso && (d.modelo || d.capacidad)) {
      const tipoBasico = d.es_ssd ? "SSD" : d.es_ssd === false ? "Disco duro" : "Disco";
      tarjeta.append(el("p", { clase: "suave", texto: `${tipoBasico} · ${tamanoLegible(d.capacidad)} · ${d.interfaz}` }));
    }
    tarjeta.append(el("p", { texto: d.error }));
    if (d.falta_permiso) {
      tarjeta.append(
        el("p", { clase: "suave", texto: saludActual.explicacion || "" }),
        el("button", { clase: "boton principal", type: "button", texto: "Dar permiso y leer salud",
          onclick: darPermiso }));
    }
    return tarjeta;
  }

  const tipo = d.es_nvme ? "SSD NVMe" : d.es_ssd ? "SSD" : d.es_ssd === false ? "Disco duro" : "Disco";
  tarjeta.append(el("p", { clase: "suave", texto: `${tipo} · ${tamanoLegible(d.capacidad)} · ${d.interfaz}` }));

  // Medidor de temperatura: la barra se llena hasta el límite configurado.
  if (d.temperatura !== null) {
    const caliente = d.temperatura >= d.limite_temperatura;
    tarjeta.append(medidor("Temperatura", (d.temperatura / d.limite_temperatura) * 100, `${d.temperatura} °C`,
      caliente ? "critico" : d.temperatura >= d.limite_temperatura - 8 ? "aviso-color" : "bueno",
      `${caliente ? "Por encima del límite" : "Límite"}: ${d.limite_temperatura} °C`));
  }
  // Medidor de vida restante (solo SSD).
  if (d.vida_restante !== null) {
    tarjeta.append(medidor("Vida restante", d.vida_restante, `${d.vida_restante} %`,
      d.vida_restante <= 5 ? "critico" : d.vida_restante <= 20 ? "aviso-color" : "bueno",
      "Desgaste estimado por el propio disco"));
  }

  const horas = d.horas_encendido;
  const datos = el("dl", { clase: "datos" },
    fila("Horas de uso", horas === null ? "sin dato" : `${numero(horas)} (${(horas / 8766).toFixed(1)} años)`),
    fila("Encendidos", oSinDato(d.ciclos_encendido) + (d.nota_encendidos ? " *" : "")),
    d.es_nvme ? fila("Errores de medio", oSinDato(d.errores_de_medio)) : null,
    d.es_nvme ? null : fila("Sectores reasignados", oSinDato(d.sectores_reasignados)),
    d.es_nvme ? null : fila("Sectores pendientes", oSinDato(d.sectores_pendientes)),
    d.es_nvme ? null : fila("Sectores incorregibles", oSinDato(d.sectores_incorregibles)),
    fila("Firmware", d.firmware || "sin dato"),
    fila("Número de serie", d.serie || "sin dato"));
  tarjeta.append(datos);

  if (d.nota_encendidos) {
    tarjeta.append(el("p", { clase: "suave", texto: `* ${d.nota_encendidos}` }));
  }
  if (d.motivos.length) {
    tarjeta.append(el("ul", { clase: "motivos" }, ...d.motivos.map((m) => el("li", { texto: m }))));
  }

  const p = d.autoprueba;
  const textoPrueba = !p ? "Todavía no se ha hecho ninguna autoprueba."
    : p.en_curso ? `Autoprueba en curso: falta un ${p.porcentaje_restante} %.`
    : `Última autoprueba: ${p.resultado}${p.correcta === false ? " (con error)" : ""}`
      + (p.horas !== null ? `, a las ${numero(p.horas)} h de uso.` : ".");
  const aviso = el("p", { clase: "suave", role: "status" });
  const lanzar = (tipoPrueba) => async () => {
    aviso.textContent = "Iniciando… Si el disco lo exige, el sistema te pedirá permisos de administrador.";
    try {
      // Si este disco se leyó con permisos, la autoprueba también los necesita.
      aviso.textContent = (await enviar("/api/salud/prueba", {
        dispositivo: d.dispositivo, tipo: tipoPrueba, elevar: saludActual.conPermiso })).mensaje;
    }
    catch (error) { aviso.textContent = error.message; }
  };
  tarjeta.append(
    el("p", { clase: "suave", texto: textoPrueba }),
    el("div", { clase: "salud-botones" },
      el("button", { clase: "boton secundario", type: "button", texto: "Prueba corta", disabled: Boolean(p && p.en_curso),
        title: "Unos 2 minutos. No escribe datos en el disco.", onclick: lanzar("corta") }),
      el("button", { clase: "boton secundario", type: "button", texto: "Prueba larga", disabled: Boolean(p && p.en_curso),
        title: "Recorre todo el disco; puede tardar horas. No escribe datos.", onclick: lanzar("larga") })),
    aviso);
  return tarjeta;
}

const saludActual = { explicacion: "", conPermiso: false };

// Una sola petición de permisos lee todos los discos. Cancelarla no es un error.
async function darPermiso() {
  const nota = $("#salud-nota");
  nota.hidden = true;
  $("#btn-salud").disabled = true;
  try {
    const datos = await enviar("/api/salud/permiso");
    if (datos.cancelado) {
      nota.hidden = false;
      nota.textContent = datos.mensaje;
    } else {
      saludActual.conPermiso = true;
      pintarSalud(datos);
    }
  } catch (error) {
    nota.hidden = false;
    nota.textContent = error.message;
  } finally {
    $("#btn-salud").disabled = false;
  }
}

function pintarSalud(datos) {
  const caja = $("#salud"), nota = $("#salud-nota");
  nota.hidden = true;
  saludActual.explicacion = datos.explicacion || saludActual.explicacion;
  if (!datos.disponible) {
    // Falta smartctl: se muestran los pasos para instalarlo.
    caja.replaceChildren(el("div", { clase: "tarjeta" },
      el("strong", { texto: "No se puede leer la salud de los discos todavía" }),
      el("pre", { clase: "instrucciones", texto: datos.instrucciones })));
    return;
  }
  if (!datos.discos.length) {
    caja.replaceChildren(el("p", { clase: "suave", texto: "No se detectó ningún disco." }));
    return;
  }
  caja.replaceChildren(...datos.discos.map(tarjetaSalud));
  if (datos.alertas && datos.alertas.length) {
    nota.hidden = false;
    nota.textContent = `Se han enviado ${datos.alertas.length} ${datos.alertas.length === 1 ? "alerta" : "alertas"}: `
      + datos.alertas.map((a) => a.titulo).join("; ");
  }
}

async function cargarSalud(revisar) {
  saludActual.conPermiso = false;
  const boton = $("#btn-salud");
  boton.disabled = true;
  boton.textContent = "Leyendo discos…";
  try {
    pintarSalud(revisar ? await enviar("/api/salud/revisar") : await api("/api/salud"));
  } catch (error) {
    $("#salud").replaceChildren(el("p", { clase: "aviso", texto: `No se pudo leer la salud de los discos: ${error.message}` }));
  } finally {
    boton.disabled = false;
    boton.textContent = "Actualizar";
  }
}

document.addEventListener("DOMContentLoaded", () => {
  $("#btn-salud").addEventListener("click", () => cargarSalud(true));
  cargarSalud(false);
});
