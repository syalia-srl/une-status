/* statusUNE — dashboard.
 * Fetches data.json and renders.  Vanilla JS, no build step.
 */
const DATA_URL = "data.json";
const REFRESH_MS = 5 * 60 * 1000;
const HAV_TZ = "America/Havana";

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const fmt = {
  int: (n) => n == null ? "—" : Number(n).toLocaleString("es-ES"),
  mw: (n) => n == null ? "—" : `${fmt.int(n)} MW`,
  hours: (mins) => mins == null ? "—" : `${(mins / 60).toFixed(1)} h`,
  pct: (n) => n == null ? "—" : `${n.toFixed(1)}%`,
  dt: (iso) => {
    if (!iso) return "—";
    const d = new Date(iso);
    return d.toLocaleString("es-CU", { timeZone: HAV_TZ, hour12: false, dateStyle: "short", timeStyle: "short" });
  },
  time: (iso) => {
    if (!iso) return "—";
    const d = new Date(iso);
    return d.toLocaleTimeString("es-CU", { timeZone: HAV_TZ, hour12: false, hour: "2-digit", minute: "2-digit" });
  },
  date: (iso) => {
    if (!iso) return "—";
    const d = new Date(iso);
    return d.toLocaleDateString("es-CU", { timeZone: HAV_TZ, day: "2-digit", month: "short" });
  },
  relative: (iso) => {
    if (!iso) return "—";
    const diff = (Date.now() - new Date(iso).getTime()) / 1000;
    if (diff < 60) return `hace ${Math.floor(diff)}s`;
    if (diff < 3600) return `hace ${Math.floor(diff / 60)} min`;
    if (diff < 86400) return `hace ${Math.floor(diff / 3600)} h`;
    return `hace ${Math.floor(diff / 86400)} d`;
  },
};

let charts = {};

async function load() {
  try {
    const r = await fetch(DATA_URL + "?t=" + Date.now(), { cache: "no-store" });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const data = await r.json();
    render(data);
    $("#error").classList.add("hidden");
  } catch (e) {
    console.error(e);
    $("#error").classList.remove("hidden");
  }
}

let lastData = null;
let counterInterval = null;

function render(data) {
  lastData = data;
  $("#generated-at").textContent = fmt.relative(data.generated_at);
  $("#as-of").textContent = data.current?.as_of ? fmt.relative(data.current.as_of) : "—";

  renderSen(data.current);
  renderCtes(data.current);
  renderBloques(data.current);
  renderAverias(data.current);
  renderExtras(data.current);
  renderHoy(data.day);
  renderSemana(data.week, data.history);
  renderMes(data.month, data.history);
  renderHistorico(data.all_time, data.history);
  startSenCounter();
}

function renderSen(cur) {
  const banner = $("#sen-banner");
  const stateEl = $("#sen-state");
  const subEl = $("#sen-sub");
  const sen = cur?.sen;
  banner.classList.remove("bg-emerald-50","border-emerald-500","text-emerald-900","dark:bg-emerald-950","dark:border-emerald-600","dark:text-emerald-100",
                         "bg-red-50","border-red-500","text-red-900","dark:bg-red-950","dark:border-red-600","dark:text-red-100",
                         "bg-slate-50","border-slate-300","text-slate-700","dark:bg-slate-900","dark:border-slate-700","dark:text-slate-200");
  if (!sen || !sen.state) {
    banner.classList.add("bg-slate-50","border-slate-300","text-slate-700","dark:bg-slate-900","dark:border-slate-700","dark:text-slate-200");
    stateEl.textContent = "DESCONOCIDO";
    subEl.textContent = "Sin reportes recientes.";
    return;
  }
  if (sen.state === "offline") {
    banner.classList.add("bg-red-50","border-red-500","text-red-900","dark:bg-red-950","dark:border-red-600","dark:text-red-100");
    stateEl.textContent = "OFFLINE";
    subEl.textContent = sen.since ? `Caída total del SEN desde ${fmt.dt(sen.since)} (${fmt.relative(sen.since)})` : "Desconexión total del SEN.";
  } else {
    banner.classList.add("bg-emerald-50","border-emerald-500","text-emerald-900","dark:bg-emerald-950","dark:border-emerald-600","dark:text-emerald-100");
    stateEl.textContent = "ONLINE";
    if (sen.last_recovered_at) {
      subEl.textContent = `Restablecido ${fmt.dt(sen.last_recovered_at)} (${fmt.relative(sen.last_recovered_at)})`;
    } else if (sen.last_outage_at) {
      subEl.textContent = `Última caída: ${fmt.dt(sen.last_outage_at)}`;
    } else {
      subEl.textContent = "Sin caídas registradas recientemente.";
    }
  }
}

function startSenCounter() {
  if (counterInterval) clearInterval(counterInterval);
  const tick = () => {
    const sen = lastData?.current?.sen;
    const el = $("#sen-counter");
    const wrap = $("#sen-counter-wrap");
    if (!el) return;
    // Anchor point: prefer last_outage_at (most precise); otherwise sen.since.
    const anchor = sen?.last_outage_at || sen?.since;
    if (!anchor) {
      el.textContent = "—";
      wrap.textContent = "Tiempo desde la última caída del SEN";
      return;
    }
    if (sen.state === "offline") {
      wrap.textContent = "Tiempo en curso de esta caída";
    } else {
      wrap.textContent = "Tiempo desde la última caída del SEN";
    }
    // anchor may be a YYYY-MM-DD (fallback from dailies) — normalize.
    const ts = anchor.length === 10 ? `${anchor}T00:00:00` : anchor;
    const diff = Math.max(0, Math.floor((Date.now() - new Date(ts).getTime()) / 1000));
    const d = Math.floor(diff / 86400);
    const h = Math.floor((diff % 86400) / 3600);
    const m = Math.floor((diff % 3600) / 60);
    const s = diff % 60;
    el.textContent = `${d}d ${String(h).padStart(2,"0")}h ${String(m).padStart(2,"0")}m ${String(s).padStart(2,"0")}s`;
  };
  tick();
  counterInterval = setInterval(tick, 1000);
}

function renderCtes(cur) {
  const grid = $("#ctes-grid");
  const empty = $("#ctes-empty");
  grid.innerHTML = "";
  const ctes = cur?.ctes || [];
  if (!ctes.length) {
    empty.classList.remove("hidden");
    return;
  }
  empty.classList.add("hidden");
  for (const c of ctes) {
    const klass = c.state === "online" ? "on" : c.state === "offline" ? "off" : "unk";
    const label = c.state === "online" ? "🟢 ONLINE" : c.state === "offline" ? "🔴 OFFLINE" : "🟡 PARCIAL";
    const card = document.createElement("div");
    card.className = `bloque-card ${klass} text-left`;
    card.innerHTML = `
      <div class="num text-xs">${escapeHtml(c.name)}</div>
      <div class="state text-base">${label}</div>
      <div class="meta">${c.online_units} en línea · ${c.offline_units} fuera</div>
      ${c.last_change_at ? `<div class="meta">cambio: ${fmt.relative(c.last_change_at)}</div>` : ""}
    `;
    grid.appendChild(card);
  }
}

function renderBloques(cur) {
  const grid = $("#bloques-grid");
  grid.innerHTML = "";
  if (!cur) return;
  $("#ahora-mw").textContent = cur.current_mw_affected != null
    ? `${fmt.mw(cur.current_mw_affected)} afectados`
    : "Sin datos recientes";
  for (const b of cur.bloques || []) {
    const card = document.createElement("div");
    const klass = b.state === "encendido" ? "on" : b.state === "apagado" ? "off" : "unk";
    card.className = `bloque-card ${klass}`;
    const stateLabel = b.state === "encendido" ? "🟢 ON" : b.state === "apagado" ? "🔴 OFF" : "⚪ ?";
    card.innerHTML = `
      <div class="num">Bloque ${b.id}</div>
      <div class="state">${stateLabel}</div>
      ${b.since ? `<div class="meta">desde ${fmt.time(b.since)} (${fmt.relative(b.since)})</div>` : ""}
      ${b.hours_off_today != null ? `<div class="meta">${b.hours_off_today.toFixed(1)} h apagado hoy</div>` : ""}
      ${b.emergency ? `<div class="meta" style="font-weight:600;color:#dc2626">⚠ EMERGENCIA</div>` : ""}
    `;
    grid.appendChild(card);
  }
}

function renderAverias(cur) {
  const list = $("#averias-list");
  list.innerHTML = "";
  const av = cur?.active_averias;
  if (!av || !av.averias?.length) {
    list.innerHTML = `<div class="text-slate-500">Sin averías reportadas recientemente.</div>`;
    return;
  }
  for (const a of av.averias.slice(0, 20)) {
    const row = document.createElement("div");
    row.innerHTML = `
      <span class="font-semibold">${escapeHtml(a.municipio || "?")}</span>
      ${a.direccion ? `<span class="text-slate-500"> — ${escapeHtml(a.direccion)}</span>` : ""}
      ${a.severity ? `<span class="text-xs text-slate-500"> [${a.severity}]</span>` : ""}
    `;
    list.appendChild(row);
  }
  if (av.ts) {
    const ts = document.createElement("div");
    ts.className = "text-xs text-slate-500 mt-2";
    ts.textContent = `Última actualización: ${fmt.relative(av.ts)} (${fmt.dt(av.ts)})`;
    list.appendChild(ts);
  }
}

function renderExtras(cur) {
  const el = $("#extras");
  el.innerHTML = "";
  const items = [];
  if (cur?.last_daf) {
    const label = cur.last_daf.type === "restablecimiento_daf" ? "DAF (restablecido)" : "DAF activo";
    items.push({ label: "Último DAF", value: label, sub: fmt.relative(cur.last_daf.ts) });
  }
  if (cur?.last_pronostico) {
    items.push({ label: "Pronóstico nocturno", value: "registrado", sub: fmt.relative(cur.last_pronostico.ts) });
  }
  items.push({ label: "Canal", value: "@EmpresaElectricaDeLaHabana", sub: "fuente única" });
  for (const it of items) {
    const d = document.createElement("div");
    d.className = "kpi";
    d.innerHTML = `<div class="label">${it.label}</div><div class="value text-base font-semibold">${it.value}</div><div class="sub">${it.sub || ""}</div>`;
    el.appendChild(d);
  }
}

function renderHoy(day) {
  if (!day || day.no_data) {
    $("#hoy-kpis").innerHTML = `<div class="text-slate-500">Sin datos para hoy.</div>`;
    return;
  }
  $("#hoy-kpis").innerHTML = kpiRow([
    { label: "Pico afectación", value: fmt.mw(day.peak_mw_affected), sub: day.peak_time ? `a las ${day.peak_time}` : "" },
    { label: "Tiempo interrumpido", value: fmt.hours(day.interruption_minutes), sub: "" },
    { label: "Emergencia", value: fmt.mw(day.emergency_mw), sub: "" },
    { label: "Averías", value: fmt.int(day.averias_total), sub: "transformadores/circuitos" },
  ]);
  const blocks = day.block_outage_minutes || {};
  drawChart("chart-hoy-bloques", "bar",
    Object.keys(blocks).map(b => `B${b}`),
    Object.values(blocks).map(m => +(m / 60).toFixed(2)),
    "Horas apagado");

  const muns = day.averias_count_by_municipio || {};
  const munEl = $("#hoy-municipios");
  munEl.innerHTML = "";
  const entries = Object.entries(muns).sort((a, b) => b[1] - a[1]);
  if (!entries.length) {
    munEl.innerHTML = `<div class="text-slate-500">Sin averías reportadas hoy.</div>`;
    return;
  }
  for (const [m, n] of entries) {
    const row = document.createElement("div");
    row.className = "flex justify-between";
    row.innerHTML = `<span>${escapeHtml(m)}</span><span class="font-semibold tabular-nums">${n}</span>`;
    munEl.appendChild(row);
  }
}

function renderSemana(week, history) {
  if (!week) { $("#semana-kpis").innerHTML = `<div class="text-slate-500">Sin datos semanales.</div>`; return; }
  $("#semana-kpis").innerHTML = kpiRow([
    { label: "Pico máximo semanal", value: fmt.mw(week.max_peak_mw), sub: "" },
    { label: "Pico promedio", value: fmt.mw(week.avg_peak_mw), sub: "" },
    { label: "Tiempo total", value: fmt.hours(week.total_interruption_minutes), sub: "interrumpido" },
    { label: "Averías", value: fmt.int(week.averias_total), sub: "última semana" },
  ]);
  const daily = (history?.daily_peak_mw_last_30d || []).slice(-7);
  drawChart("chart-semana-peak", "line",
    daily.map(d => fmt.date(d.date)),
    daily.map(d => d.peak_mw),
    "Pico MW");
  const dailyMins = (history?.daily_outage_minutes_last_30d || []).slice(-7);
  drawChart("chart-semana-mins", "bar",
    dailyMins.map(d => fmt.date(d.date)),
    dailyMins.map(d => +(d.minutes / 60).toFixed(2)),
    "Horas apagado");
}

function renderMes(month, history) {
  if (!month || month.no_data) {
    $("#mes-kpis").innerHTML = `<div class="text-slate-500">Sin datos para el mes actual.</div>`;
    return;
  }
  $("#mes-kpis").innerHTML = kpiRow([
    { label: "Pico máximo del mes", value: fmt.mw(month.max_peak_mw), sub: "" },
    { label: "Pico promedio", value: fmt.mw(month.avg_peak_mw), sub: "" },
    { label: "Tiempo total", value: fmt.hours(month.total_interruption_minutes), sub: "interrumpido" },
    { label: "Días con datos", value: fmt.int(month.dailies_count), sub: `mes ${month.month || ""}` },
  ]);
  const peak30 = history?.daily_peak_mw_last_30d || [];
  drawChart("chart-mes-peak", "line",
    peak30.map(d => fmt.date(d.date)),
    peak30.map(d => d.peak_mw),
    "Pico MW");
}

function renderHistorico(at, history) {
  if (!at) { $("#historico-kpis").innerHTML = `<div class="text-slate-500">Sin datos históricos.</div>`; return; }
  const senDays = at.sen_outage_days_total ?? history?.sen_outage_days_total ?? 0;
  const senCollapses = at.sen_collapse_total ?? history?.sen_collapse_total ?? 0;
  const senHrs = at.sen_outage_minutes_total != null ? (at.sen_outage_minutes_total / 60).toFixed(1) : "—";
  const dafTotal = at.daf_total ?? history?.daf_total ?? 0;
  $("#historico-kpis").innerHTML = kpiRow([
    { label: "Caídas totales del SEN", value: fmt.int(senCollapses), sub: `${senDays} días con caídas` },
    { label: "Horas caídas SEN", value: senHrs === "—" ? "—" : `${senHrs} h`, sub: "tiempo acumulado" },
    { label: "Eventos DAF", value: fmt.int(dafTotal), sub: "disparos por frecuencia (parciales)" },
    { label: "Récord pico", value: fmt.mw(at.max_peak_mw), sub: "MW máximo registrado" },
    { label: "Total interrumpido", value: fmt.hours(at.total_interruption_minutes), sub: "todo el histórico" },
    { label: "Averías totales", value: fmt.int(at.averias_total), sub: "" },
    { label: "Meses con datos", value: fmt.int(at.months_count), sub: "" },
  ]);

  // Per-CTE historical offline breakdown
  const cteEl = $("#cte-historico");
  if (cteEl) {
    const mins = history?.cte_offline_minutes_total || at.cte_offline_minutes_total || {};
    const days = history?.cte_offline_days_total || {};
    const entries = Object.entries(mins).sort((a,b) => b[1] - a[1]);
    cteEl.innerHTML = "";
    if (!entries.length) {
      cteEl.innerHTML = `<div class="text-slate-500">Sin datos históricos de unidades termoeléctricas.</div>`;
    } else {
      for (const [cte, m] of entries) {
        const d = (m / 1440).toFixed(1);
        const offlineDays = days[cte] ?? 0;
        const row = document.createElement("div");
        row.className = "flex justify-between";
        row.innerHTML = `<span>${escapeHtml(cteLabel(cte))}</span><span class="tabular-nums"><span class="font-semibold">${d}</span> d <span class="text-slate-500">· ${offlineDays} días con reporte</span></span>`;
        cteEl.appendChild(row);
      }
    }
  }
  const monthly = history?.monthly_max_peak_mw || [];
  drawChart("chart-monthly-peak", "line",
    monthly.map(m => m.month),
    monthly.map(m => m.max_peak_mw),
    "Pico mensual MW");
  const monthlyMins = history?.monthly_total_outage_minutes || [];
  drawChart("chart-monthly-mins", "bar",
    monthlyMins.map(m => m.month),
    monthlyMins.map(m => +(m.minutes / 60).toFixed(2)),
    "Horas apagado");
}

function kpiRow(items) {
  return items.map(it => `
    <div class="kpi">
      <div class="label">${it.label}</div>
      <div class="value">${it.value}</div>
      ${it.sub ? `<div class="sub">${it.sub}</div>` : ""}
    </div>
  `).join("");
}

function drawChart(canvasId, type, labels, values, datasetLabel) {
  const ctx = document.getElementById(canvasId);
  if (!ctx) return;
  // Wait for Chart.js to load
  if (typeof Chart === "undefined") { setTimeout(() => drawChart(canvasId, type, labels, values, datasetLabel), 100); return; }
  if (charts[canvasId]) charts[canvasId].destroy();
  const isDark = document.documentElement.classList.contains("dark") || matchMedia("(prefers-color-scheme: dark)").matches;
  const accent = "#10b981";
  charts[canvasId] = new Chart(ctx, {
    type,
    data: {
      labels,
      datasets: [{
        label: datasetLabel,
        data: values,
        borderColor: accent,
        backgroundColor: type === "bar" ? accent + "88" : accent + "33",
        tension: 0.2,
        fill: type === "line",
        pointRadius: type === "line" ? 2 : 0,
        borderWidth: 2,
      }],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { color: isDark ? "#94a3b8" : "#64748b", maxRotation: 0, autoSkip: true } },
        y: { ticks: { color: isDark ? "#94a3b8" : "#64748b" }, beginAtZero: true },
      },
    },
  });
}

const CTE_DISPLAY = {
  felton: "Lidio Ramón Pérez (Felton)",
  guiteras: "Antonio Guiteras",
  "maximo-gomez": "Máximo Gómez (Mariel)",
  cespedes: "Carlos M. de Céspedes (Cienfuegos)",
  nuevitas: "10 de Octubre (Nuevitas)",
  tallapiedra: "Otto Parellada (Tallapiedra)",
  guevara: "Ernesto Guevara (Santa Cruz)",
  rente: "Antonio Maceo (Renté)",
};
function cteLabel(id) {
  const fromCur = lastData?.current?.ctes?.find(c => c.id === id);
  if (fromCur?.name) return fromCur.name;
  return CTE_DISPLAY[id] || id;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// Dark mode: follow OS preference.
const applyDark = () => {
  const m = matchMedia("(prefers-color-scheme: dark)").matches;
  document.documentElement.classList.toggle("dark", m);
};
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", applyDark);
applyDark();

load();
setInterval(load, REFRESH_MS);
