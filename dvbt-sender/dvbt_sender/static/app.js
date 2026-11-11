"use strict";

let cfg = null;
let running = false;
let saveTimer = null;
let channels = [];
const COLORS = ["--c1", "--c2", "--c3", "--c4", "--c5", "--c6"];
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];

async function api(method, path, body) {
  const r = await fetch(path, {
    method, headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail ? (typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail)) : r.statusText);
  return data;
}

const mbit = (b) => (b / 1e6).toFixed(2).replace(".", ",") + " Mbit/s";
const getPath = (obj, k) => k.split(".").reduce((o, x) => o[x], obj);
function setPath(obj, k, v) {
  const parts = k.split("."); const last = parts.pop();
  parts.reduce((o, x) => o[x], obj)[last] = v;
}
function parse(el) {
  const t = el.dataset.t;
  if (el.type === "checkbox") return el.checked;
  const v = el.value.trim();
  if (t === "int") return v === "" ? 0 : parseInt(v, 10);
  if (t === "intnull") return v === "" ? null : parseInt(v, 10);
  if (t === "float") return v === "" ? 0 : parseFloat(v);
  if (t === "mbit") return v === "" ? 0 : Math.round(parseFloat(v.replace(",", ".")) * 1e6);
  return el.value;
}
function show(el, v) {
  const t = el.dataset.t;
  if (el.type === "checkbox") el.checked = !!v;
  else if (t === "mbit") el.value = v ? (v / 1e6).toString() : "";
  else el.value = v === null || v === undefined ? "" : v;
}

// ---------------------------------------------------------------- Sender
function renderTx() {
  $$("[data-k]").forEach((el) => show(el, getPath(cfg, el.dataset.k)));
  $("#freq").value = (cfg.transmitter.frequency / 1e6).toString();
  syncChannel();
  const out = cfg.transmitter.output;
  $$(".o-hides").forEach((e) => (e.hidden = out !== "hides"));
  $$(".o-file").forEach((e) => (e.hidden = out !== "file"));
  $$(".o-udp").forEach((e) => (e.hidden = out !== "udp"));
}
function syncChannel() {
  const f = cfg.transmitter.frequency;
  const c = channels.find((x) => x.frequency === f && x.bandwidth === cfg.transmitter.bandwidth);
  $("#channel").value = c ? String(c.frequency) : "";
}

$$("[data-k]").forEach((el) => el.addEventListener("change", () => {
  setPath(cfg, el.dataset.k, parse(el));
  renderTx(); changed();
}));
$("#freq").addEventListener("change", (e) => {
  cfg.transmitter.frequency = Math.round(parseFloat(e.target.value) * 1e6);
  renderTx(); changed();
});
$("#channel").addEventListener("change", (e) => {
  const c = channels.find((x) => String(x.frequency) === e.target.value);
  if (c) { cfg.transmitter.frequency = c.frequency; cfg.transmitter.bandwidth = c.bandwidth; }
  renderTx(); changed();
});

async function toolOut(path) {
  const pre = $("#toolout");
  pre.hidden = false; pre.textContent = "…";
  try { pre.textContent = (await api("GET", path)).output; } catch (e) { pre.textContent = e.message; }
}
$("#devices").addEventListener("click", () => toolOut("/api/devices"));
$("#gainrange").addEventListener("click", async () => { await save(); toolOut("/api/gain-range"); });

// ---------------------------------------------------------------- Programme
function newProgram() {
  return { name: `Programm ${cfg.programs.length + 1}`, provider: "", enabled: true, source_type: "file",
    source: "", loop: true, throttle: false, video_format: "sd169", video_codec: "mpeg2",
    audio_codec: "mp2", audio_bitrate: 192000, video_bitrate: 0, service_id: 0 };
}
function renderPrograms() {
  const box = $("#programs");
  box.innerHTML = "";
  if (!cfg.programs.length) box.innerHTML = '<p class="muted">Noch kein Programm. Mit „+ Programm“ hinzufügen.</p>';
  cfg.programs.forEach((p, i) => {
    const el = $("#progtpl").content.firstElementChild.cloneNode(true);
    el.dataset.i = i;
    $$("[data-p]", el).forEach((inp) => {
      show(inp, p[inp.dataset.p]);
      inp.addEventListener("change", () => { p[inp.dataset.p] = parse(inp); updateProg(el, p); changed(); });
    });
    $(".del", el).onclick = () => { cfg.programs.splice(i, 1); renderPrograms(); changed(); };
    $(".up", el).onclick = () => { if (i > 0) { [cfg.programs[i - 1], cfg.programs[i]] = [cfg.programs[i], cfg.programs[i - 1]]; renderPrograms(); changed(); } };
    $(".down", el).onclick = () => { if (i < cfg.programs.length - 1) { [cfg.programs[i + 1], cfg.programs[i]] = [cfg.programs[i], cfg.programs[i + 1]]; renderPrograms(); changed(); } };
    $(".browse", el).onclick = () => browse(p, el);
    updateProg(el, p);
    box.appendChild(el);
  });
}
function updateProg(el, p) {
  el.classList.toggle("off", !p.enabled);
  $(".s-src", el).hidden = p.source_type === "testbild";
  $(".browse", el).hidden = p.source_type !== "file";
  $(".s-loop", el).hidden = !(p.source_type === "file" || (p.source_type === "url" && p.throttle));
  $(".s-throttle", el).hidden = p.source_type !== "url";
}
$("#addprog").onclick = () => { cfg.programs.push(newProgram()); renderPrograms(); changed(); };

// ---------------------------------------------------------------- Dateiauswahl
let browseTarget = null;
async function browse(p, el, path) {
  browseTarget = { p, el };
  const start = path ?? (p.source ? p.source.replace(/\/[^/]*$/, "") : "");
  let d;
  try { d = await api("GET", "/api/files?path=" + encodeURIComponent(start)); }
  catch { d = await api("GET", "/api/files"); }
  $("#bpath").textContent = d.path;
  const ul = $("#blist"); ul.innerHTML = "";
  const add = (label, extra, fn) => {
    const li = document.createElement("li");
    li.innerHTML = `<span></span><span class="muted"></span>`;
    li.firstChild.textContent = label; li.lastChild.textContent = extra;
    li.onclick = fn; ul.appendChild(li);
  };
  if (d.parent !== d.path) add("⬆ ..", "", () => browse(p, el, d.parent));
  d.entries.forEach((e) => {
    const full = d.path.replace(/\/$/, "") + "/" + e.name;
    if (e.dir) add("📁 " + e.name, "", () => browse(p, el, full));
    else add("🎞 " + e.name, (e.size / 1e6).toFixed(0) + " MB", () => {
      p.source = full;
      if (!p.name || /^Programm \d+$/.test(p.name)) p.name = e.name.replace(/\.[^.]+$/, "").slice(0, 30);
      $("#browser").close(); renderPrograms(); changed();
    });
  });
  if (!$("#browser").open) $("#browser").showModal();
}

// ---------------------------------------------------------------- Speichern, Plan
function changed() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(save, 300);
  $("#note").hidden = !running;
}
async function save() {
  clearTimeout(saveTimer);
  try {
    const r = await api("PUT", "/api/config", cfg);
    renderPlan(r.plan);
  } catch (e) { renderPlan({ ok: false, error: e.message }); }
  loadCommands();
}
function renderPlan(plan) {
  const bar = $("#bar"); bar.innerHTML = "";
  $("#warnings").innerHTML = "";
  if (!plan.ok) {
    $("#rate").innerHTML = `<span style="color:var(--err)"></span>`;
    $("#rate").firstChild.textContent = plan.error;
    return;
  }
  $("#rate").textContent = `Nutzrate des Kanals: ${mbit(plan.total_bitrate)} · belegt: ${mbit(plan.allocated)} · frei: ${mbit(plan.total_bitrate - plan.allocated)}`;
  plan.programs.forEach((p, k) => {
    const d = document.createElement("div");
    d.style.width = (100 * p.mux_bitrate / plan.total_bitrate) + "%";
    d.style.background = `var(${COLORS[k % COLORS.length]})`;
    d.textContent = p.name; d.title = `${p.name}: Video ${mbit(p.video_bitrate)}, gesamt ${mbit(p.mux_bitrate)}`;
    bar.appendChild(d);
    const el = $(`.prog[data-i="${p.index}"] .pinfo`);
    if (el) el.textContent = `SID ${p.service_id} · Video ${mbit(p.video_bitrate)}`;
  });
  plan.warnings.forEach((w) => { const li = document.createElement("li"); li.textContent = w; $("#warnings").appendChild(li); });
}
async function loadCommands() {
  try {
    const c = await api("POST", "/api/commands", cfg);
    const q = (a) => a.map((x) => (/^[\w\/.:=+@,-]+$/.test(x) ? x : `'${x.replace(/'/g, "'\\''")}'`)).join(" ");
    $("#cmds").textContent = [q(c.tsp), ...c.ffmpeg.map(q)].join("\n\n");
  } catch (e) { $("#cmds").textContent = e.message; }
}

// ---------------------------------------------------------------- Start/Stopp, Status
$("#startstop").onclick = async () => {
  const btn = $("#startstop"); btn.disabled = true;
  try {
    if (running) await api("POST", "/api/stop");
    else { await save(); await api("POST", "/api/start"); }
    $("#error").hidden = true;
  } catch (e) { $("#error").textContent = e.message; $("#error").hidden = false; }
  btn.disabled = false;
  poll();
};
function fmtProgress(p) {
  if (!p || !p.out_time) return "";
  const parts = [`Zeit ${p.out_time.split(".")[0]}`];
  if (p.fps) parts.push(`${p.fps} fps`);
  if (p.speed) parts.push(`Tempo ${p.speed}`);
  if (p.bitrate && p.bitrate !== "N/A") parts.push(p.bitrate);
  return parts.join(" · ");
}
function procHtml(p) {
  const div = document.createElement("div"); div.className = "proc";
  div.innerHTML = `<div class="head"><b></b><span class="pill"></span><span class="muted pstat"></span></div>
    <details><summary>Protokoll</summary><pre></pre></details>`;
  $("b", div).textContent = p.name;
  const pill = $(".pill", div); pill.textContent = p.state + (p.restarts ? ` · ${p.restarts}× neu gestartet` : "");
  pill.classList.toggle("on", p.state === "läuft");
  $(".pstat", div).textContent = fmtProgress(p.progress);
  $("pre", div).textContent = p.log.join("\n");
  return div;
}
const openLogs = new Set();
async function poll() {
  let s;
  try { s = await api("GET", "/api/status"); } catch { return; }
  running = s.running;
  const st = $("#state");
  st.textContent = s.running ? "sendet" : (s.error ? "Fehler" : "gestoppt");
  st.className = "pill" + (s.running ? " on" : s.error ? " err" : "");
  const btn = $("#startstop");
  btn.textContent = s.running ? "Senden stoppen" : "Senden starten";
  btn.classList.toggle("stop", s.running);
  if (s.error) { $("#error").textContent = s.error; $("#error").hidden = false; }
  if (!s.running) $("#note").hidden = true;
  const box = $("#procs");
  $$("details", box).forEach((d, k) => (d.open ? openLogs.add(k) : openLogs.delete(k)));
  box.innerHTML = "";
  const list = [s.mux, ...s.encoders].filter(Boolean);
  if (!list.length) box.innerHTML = '<p class="muted">Der Sender ist aus.</p>';
  list.forEach((p, k) => { const el = procHtml(p); if (openLogs.has(k)) $("details", el).open = true; box.appendChild(el); });
}

// ---------------------------------------------------------------- Start
(async () => {
  channels = await api("GET", "/api/channels");
  channels.forEach((c) => {
    const o = document.createElement("option");
    o.value = String(c.frequency); o.textContent = `${c.name} · ${(c.frequency / 1e6).toFixed(1).replace(".0", "")} MHz`;
    $("#channel").appendChild(o);
  });
  cfg = await api("GET", "/api/config");
  renderTx(); renderPrograms();
  try { renderPlan(await api("POST", "/api/plan", cfg)); } catch {}
  loadCommands();
  const tools = await api("GET", "/api/tools");
  const missing = Object.entries(tools).filter(([k, v]) => !v && k !== "tshides").map(([k]) => k);
  if (missing.length) { $("#error").textContent = `Nicht gefunden: ${missing.join(", ")}. Bitte installieren.`; $("#error").hidden = false; }
  poll(); setInterval(poll, 2000);
})();
