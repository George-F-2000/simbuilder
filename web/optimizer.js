/* ---------------------------------------------------------------------------
   optimizer.js — the Optimizer tab.

   Fit the model's road load (tyre rolling-resistance scale, aero drag scale)
   to a real-vehicle log by replaying the car's pedal and brake open loop.
   Backend: optimizer/api.py through pywebview.api.optim_*. The page polls
   optim_status every 3 s while a study runs (the gym.js pattern); the
   backend pushes one msPipe.optimEvent when a study ends.

   Data policy: channel names come from the user's log and are saved by the
   backend in a local, gitignored file. Nothing here knows any real name.
--------------------------------------------------------------------------- */

const O = {
  state: null,       // optim_state()
  log: null,         // optim_inspect_log()
  map: {},           // role -> {name, unit, sign}
  windows: [],       // candidate windows from optim_find_windows
  selected: new Set(),
  trace: null,       // downsampled whole-log trace
  study: null,       // last optim_status().study
  poll: null,
  studyDir: null,
};

function oEsc(s) {
  return String(s === undefined || s === null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}
function oNum(id, def) {
  const el = $(id); if (!el) return def;
  const v = parseFloat(el.value); return Number.isFinite(v) ? v : def;
}
function oFmt(x, d) { return (x === null || x === undefined) ? "–" : Number(x).toFixed(d === undefined ? 3 : d); }
function oSecs(s) {
  if (s === null || s === undefined) return "–";
  s = Math.round(s); const m = Math.floor(s / 60), r = s % 60;
  return m ? `${m} min ${String(r).padStart(2, "0")} s` : `${r} s`;
}

/* ------------------------------------------------------------- state --- */

async function optimLoad() {
  if (!window.pywebview) {
    $("#optimHint").textContent = "The Optimizer runs inside the SimBuilder app.";
    return;
  }
  const st = await pywebview.api.optim_state();
  if (!st.ok) { $("#optimHint").textContent = "Optimizer unavailable: " + st.error; return; }
  O.state = st;
  const b = st.base_files || {}, d = st.deck_info || {};
  $("#optimSetup").innerHTML =
    `<b>Study folder:</b> ${oEsc(st.optim_dir)} <button id="btnOptimDir" class="ghost" ` +
    `title="Pick a local (non-synced) folder for study runs">Change…</button> &nbsp; ` +
    `<b>Base tyre:</b> ${b.tire_ok ? oEsc(b.tire.split(/[\\/]/).pop()) : "<span class='calib-worse'>not found</span>"} &nbsp; ` +
    `<b>Base aero:</b> ${b.aero_ok ? oEsc(b.aero.split(/[\\/]/).pop()) : "<span class='calib-worse'>not found</span>"} &nbsp; ` +
    `<span class="hint">(the Vehicle Builder's tyre/aero overrides win when set; deck lists ` +
    `${(d.tires || []).length} tyre and ${(d.aeros || []).length} aero file(s))</span>`;
  const bd = $("#btnOptimDir");
  if (bd) bd.onclick = async () => { await pywebview.api.optim_set_dir(); optimLoad(); };
  $("#optimHint").textContent = st.aliases_saved
    ? `${st.aliases_saved} saved channel mapping(s) in ${st.aliases_file.split(/[\\/]/).pop()}.`
    : "No channel mapping saved yet — pick a log and map its channels once.";
  optimRenderParams();
  optimRenderWeights();
  $("#optimWorkers").value = st.defaults.max_workers;
  optimRenderHistory(st.history || []);
  if (st.study) { O.study = st.study; O.studyDir = st.study.dir; optimRenderStudy(st.study); }
  optimSetBusy(!!st.running);
  if (st.running && !O.poll) O.poll = setInterval(optimTick, 3000);
  optimUpdateButtons();
}

function optimRenderParams() {
  const box = $("#optimParams");
  const p = O.state.params;
  box.innerHTML = "<p class='hint'><b>Tunables</b> — the complete list; everything else in the plant is locked</p>" +
    Object.entries(p).map(([k, m]) => `
    <div class="optim-param" title="${oEsc(m.tip)}">
      <label><input type="checkbox" id="optimOn_${k}" checked> <b>${oEsc(m.label)}</b></label>
      <span class="hint">${oEsc(m.tip)}</span>
      <label>min <input type="number" id="optimMin_${k}" value="${Math.max(m.min, m.default - 0.3).toFixed(2)}" min="${m.min}" max="${m.max}" step="${m.step}"></label>
      <label>max <input type="number" id="optimMax_${k}" value="${Math.min(m.max, m.default + 0.3).toFixed(2)}" min="${m.min}" max="${m.max}" step="${m.step}"></label>
      <span class="hint">allowed ${m.min}–${m.max}</span>
      <span class="hint">default ${m.default}</span>
    </div>`).join("");
}

function optimRenderWeights() {
  const w = O.state.weights;
  const labels = { speed: "vehicle speed", torque_front: "front motor torque",
                   torque_rear: "rear motor torque", pack_power: "pack power" };
  $("#optimWeights").innerHTML = Object.entries(labels).map(([k, l]) =>
    `<label class="calib-knob">${l} <input type="number" id="optimW_${k}" value="${w[k] !== undefined ? w[k] : 0}" min="0" max="5" step="0.1"></label>`).join("");
}

/* --------------------------------------------------------------- log --- */

async function optimPickLog() {
  const res = await pywebview.api.optim_pick_log();
  if (!res.ok) { if (!res.cancelled) $("#optimMapHint").textContent = "Could not open: " + res.error; return; }
  optimSetLog(res);
}

function optimSetLog(res) {
  O.log = res; O.map = res.map || {}; O.windows = []; O.selected = new Set(); O.trace = null;
  $("#optimLogName").textContent = `${res.name} — ${res.channels.length} channels` +
    (res.span ? `, ${oFmt(res.span[1] - res.span[0], 0)} s` : "");
  optimRenderMap();
  $("#optimMapHint").textContent = res.map_source === "saved"
    ? "Mapping restored from the saved aliases for this exact channel set."
    : res.map_source === "last" ? "Mapping copied from the last saved log — check it."
    : "Mapping is a GUESS from channel names — check every row, then Save.";
  $("#btnOptimSaveMap").disabled = false;
  $("#btnOptimFind").disabled = false;
  $("#btnOptimAddWin").disabled = false;
  optimRenderWindows();
  optimDrawTrace();
  optimUpdateButtons();
}

function optimRenderMap() {
  const t = $("#optimMap");
  if (!O.log) { t.innerHTML = "<tr><td class='hint'>Pick a log to map its channels.</td></tr>"; return; }
  const chans = O.log.channels;
  const opts = (sel) => `<option value="">— none —</option>` + chans.map(c =>
    `<option value="${oEsc(c.name)}"${c.name === sel ? " selected" : ""}>${oEsc(c.name)}${c.unit ? " [" + oEsc(c.unit) + "]" : ""}</option>`).join("");
  let html = "<thead><tr><th>role</th><th>channel in the log</th><th>unit</th><th>sign</th></tr></thead><tbody>";
  for (const r of O.state.roles) {
    const e = O.map[r.role] || {};
    const unitOpts = r.units.map(u => `<option value="${u}"${(e.unit || r.canonical) === u ? " selected" : ""}>${u}</option>`).join("");
    html += `<tr><td>${oEsc(r.label)}${r.required ? " <span class='req'>*</span>" : ""}</td>` +
      `<td><select id="optimCh_${r.role}">${opts(e.name)}</select></td>` +
      `<td><select id="optimUn_${r.role}">${unitOpts}</select></td>` +
      `<td>${r.kind === "power" || r.kind === "current" || r.kind === "torque"
        ? `<select id="optimSg_${r.role}"><option value="1"${(e.sign || 1) > 0 ? " selected" : ""}>+ as logged</option><option value="-1"${(e.sign || 1) < 0 ? " selected" : ""}>− inverted</option></select>`
        : ""}</td></tr>`;
  }
  t.innerHTML = html + "</tbody>";
  $$("#optimMap select").forEach(s => s.onchange = () => { O.map = optimReadMap(); optimUpdateButtons(); });
}

function optimReadMap() {
  const m = {};
  for (const r of O.state.roles) {
    const ch = $("#optimCh_" + r.role), un = $("#optimUn_" + r.role), sg = $("#optimSg_" + r.role);
    if (!ch || !ch.value) { m[r.role] = null; continue; }
    m[r.role] = { name: ch.value, unit: un ? un.value : r.canonical };
    if (sg) m[r.role].sign = parseInt(sg.value, 10);
  }
  return m;
}

async function optimSaveMap() {
  O.map = optimReadMap();
  const res = await pywebview.api.optim_save_map(O.log.path, O.map);
  $("#optimMapHint").textContent = res.ok
    ? "Mapping saved" + (res.problems && res.problems.length ? " (notes: " + res.problems.join("; ") + ")" : ".")
    : "Not saved: " + res.error;
  if (res.ok) O.log.map_source = "saved";
}

/* ----------------------------------------------------------- windows --- */

async function optimFind() {
  O.map = optimReadMap();
  $("#optimWinHint").textContent = "Scanning the log…";
  const res = await pywebview.api.optim_find_windows(O.log.path, O.map, {
    min_len_s: oNum("#optimWinMin", 20), max_len_s: oNum("#optimWinMax", 90),
    v_floor_kph: oNum("#optimWinFloor", 3), brake_free: $("#optimWinBrakeFree").checked });
  if (!res.ok) { $("#optimWinHint").textContent = "Could not scan: " + res.error; return; }
  O.windows = res.windows; O.trace = res.preview; O.span = res.span;
  O.selected = new Set(res.windows.slice(0, 3).map((_, i) => i));
  $("#optimWinHint").textContent = `${res.windows.length} candidate window(s)` +
    (res.notes && res.notes.length ? " — " + res.notes.join("; ") : "") +
    (!res.has.brake ? " — no brake channel mapped: brake replayed as 0" : "");
  optimRenderWindows(); optimDrawTrace(); optimUpdateButtons();
}

function optimAddWindow() {
  const t0 = oNum("#optimManT0", NaN), t1 = oNum("#optimManT1", NaN);
  if (!(t1 > t0 + 5)) { $("#optimWinHint").textContent = "Give t0 and t1 (at least 5 s apart)."; return; }
  O.windows.push({ t0, t1, dur_s: +(t1 - t0).toFixed(1), manual: true });
  O.selected.add(O.windows.length - 1);
  optimRenderWindows(); optimDrawTrace(); optimUpdateButtons();
}

function optimRenderWindows() {
  const box = $("#optimWindows");
  if (!O.windows.length) { box.innerHTML = "<p class='hint'>No windows yet — Find windows, or add one by hand.</p>"; return; }
  box.innerHTML = O.windows.map((w, i) => `
    <label class="optim-win"><input type="checkbox" data-i="${i}" ${O.selected.has(i) ? "checked" : ""}>
      <b>${oFmt(w.t0, 1)} – ${oFmt(w.t1, 1)} s</b> <span class="tag">${oFmt(w.dur_s, 0)} s</span>
      ${w.v0_kph !== undefined ? `<span class="tag">from ${oFmt(w.v0_kph, 0)} km/h, mean ${oFmt(w.v_mean_kph, 0)}, max ${oFmt(w.v_max_kph, 0)}</span>` : ""}
      ${w.tipins !== undefined ? `<span class="tag">${w.tipins} tip-in(s)</span>` : ""}
      ${w.brake_frac !== undefined && w.brake_frac !== null ? `<span class="tag">brake ${Math.round(w.brake_frac * 100)} %</span>` : ""}
      ${w.regen_frac !== undefined && w.regen_frac !== null ? `<span class="tag">regen ${Math.round(w.regen_frac * 100)} %</span>` : ""}
      ${w.manual ? "<span class='tag'>manual</span>" : ""}
    </label>`).join("");
  $$("#optimWindows input[type=checkbox]").forEach(cb => cb.onchange = () => {
    const i = parseInt(cb.dataset.i, 10);
    if (cb.checked) O.selected.add(i); else O.selected.delete(i);
    optimDrawTrace(); optimUpdateButtons();
  });
}

/* ------------------------------------------------------------ canvas --- */

function optimCanvas(id) {
  const cv = $(id); if (!cv) return null;
  const dpr = window.devicePixelRatio || 1;
  const w = cv.clientWidth || 800, h = cv.clientHeight || 220;
  if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) {
    cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr);
  }
  const ctx = cv.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const dark = document.body.classList.contains("dark");
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = dark ? "#171a1e" : "#fbfaf6"; ctx.fillRect(0, 0, w, h);
  return { ctx, w, h, dark, grid: dark ? "#2b3138" : "#e6e1d6", axis: dark ? "#8a929c" : "#6a7078" };
}

function optimDrawTrace() {
  const c = optimCanvas("#optimTrace"); if (!c) return;
  const { ctx, w, h } = c;
  const padL = 46, padR = 46, padT = 10, padB = 24;
  if (!O.trace) {
    ctx.fillStyle = c.axis; ctx.font = "13px system-ui,sans-serif"; ctx.textAlign = "center";
    ctx.fillText("Find windows to see the whole log here", w / 2, h / 2); return;
  }
  const t = O.trace.t, v = O.trace.speed, p = O.trace.pedal;
  const t0 = t[0], t1 = t[t.length - 1] || t0 + 1;
  const vmax = Math.max(10, ...v) * 1.05;
  const X = x => padL + (x - t0) / (t1 - t0) * (w - padL - padR);
  const Yv = y => (h - padB) - y / vmax * (h - padT - padB);
  const Yp = y => (h - padB) - y / 105 * (h - padT - padB);
  // windows (shaded; selected darker)
  O.windows.forEach((win, i) => {
    ctx.fillStyle = O.selected.has(i) ? "rgba(11,110,153,0.28)" : "rgba(11,110,153,0.10)";
    ctx.fillRect(X(win.t0), padT, Math.max(2, X(win.t1) - X(win.t0)), h - padT - padB);
  });
  ctx.strokeStyle = c.grid; ctx.lineWidth = 1; ctx.strokeRect(padL, padT, w - padL - padR, h - padT - padB);
  ctx.fillStyle = c.axis; ctx.font = "10px system-ui,sans-serif"; ctx.textAlign = "right";
  for (let k = 0; k <= 4; k++) ctx.fillText((vmax * k / 4).toFixed(0), padL - 4, Yv(vmax * k / 4) + 3);
  ctx.textAlign = "left";
  for (let k = 0; k <= 4; k++) ctx.fillText((100 * k / 4).toFixed(0) + "%", w - padR + 4, Yp(100 * k / 4) + 3);
  ctx.textAlign = "center";
  for (let k = 0; k <= 6; k++) { const tv = t0 + (t1 - t0) * k / 6; ctx.fillText(tv.toFixed(0) + " s", X(tv), h - 6); }
  const line = (arr, Y, color, lw) => {
    ctx.strokeStyle = color; ctx.lineWidth = lw; ctx.beginPath();
    arr.forEach((y, i) => { const px = X(t[i]), py = Y(y); if (i) ctx.lineTo(px, py); else ctx.moveTo(px, py); });
    ctx.stroke();
  };
  line(p, Yp, c.dark ? "#8fb3c8" : "#9bb7c9", 1);
  if (O.trace.brake) line(O.trace.brake, Yp, "#c0392b", 1);
  line(v, Yv, c.dark ? "#f0f0f0" : "#1c2733", 1.4);
  ctx.fillStyle = c.axis; ctx.textAlign = "left";
  ctx.fillText("speed [km/h] (left), pedal / brake [%] (right); shaded = candidate windows, dark = selected", padL + 4, padT + 11);
}

function optimDrawOverlay(series, meta) {
  const c = optimCanvas("#optimOverlay"); if (!c) return;
  const { ctx, w, h } = c;
  const roles = ["speed", "torque_front", "torque_rear", "pack_power", "pedal"].filter(r => series && series[r]);
  if (!roles.length) {
    ctx.fillStyle = c.axis; ctx.font = "13px system-ui,sans-serif"; ctx.textAlign = "center";
    ctx.fillText("Export a finished study to see the real-vs-model overlay", w / 2, h / 2); return;
  }
  const labels = { speed: "speed [km/h]", torque_front: "front torque [Nm]", torque_rear: "rear torque [Nm]",
                   pack_power: "pack power [kW]", pedal: "pedal [%]" };
  const padL = 56, padR = 12, padT = 8, padB = 18, gap = 10;
  const ph = (h - padT - padB - gap * (roles.length - 1)) / roles.length;
  roles.forEach((r, k) => {
    const s = series[r]; const top = padT + k * (ph + gap);
    const all = [].concat(s.model || [], s.ref || []).filter(Number.isFinite);
    let lo = Math.min(...all), hi = Math.max(...all);
    if (!(hi > lo)) { hi = lo + 1; } const m = (hi - lo) * 0.08; lo -= m; hi += m;
    if (lo > 0 && lo < (hi - lo) * 0.3) lo = 0;        // show the zero line when it is close
    const t0 = s.t[0], t1 = s.t[s.t.length - 1] || t0 + 1;
    const X = x => padL + (x - t0) / (t1 - t0) * (w - padL - padR);
    const Y = y => top + ph - (y - lo) / (hi - lo) * ph;
    ctx.strokeStyle = c.grid; ctx.lineWidth = 1; ctx.strokeRect(padL, top, w - padL - padR, ph);
    if (lo < 0 && hi > 0) { ctx.strokeStyle = c.axis; ctx.globalAlpha = 0.5; ctx.beginPath(); ctx.moveTo(padL, Y(0)); ctx.lineTo(w - padR, Y(0)); ctx.stroke(); ctx.globalAlpha = 1; }
    ctx.fillStyle = c.axis; ctx.font = "10px system-ui,sans-serif"; ctx.textAlign = "right";
    ctx.fillText(hi.toFixed(hi - lo > 20 ? 0 : 1), padL - 4, top + 9);
    ctx.fillText(lo.toFixed(hi - lo > 20 ? 0 : 1), padL - 4, top + ph - 1);
    ctx.textAlign = "left"; ctx.fillText(labels[r] || r, padL + 4, top + 10);
    const line = (arr, color, lw) => {
      if (!arr) return;
      ctx.strokeStyle = color; ctx.lineWidth = lw; ctx.beginPath();
      arr.forEach((y, i) => { const px = X(s.t[i]), py = Y(y); if (i) ctx.lineTo(px, py); else ctx.moveTo(px, py); });
      ctx.stroke();
    };
    line(s.ref, c.dark ? "#d0d0d0" : "#444444", 1.2);
    line(s.model, "#d9480f", 1.2);
    if (k === roles.length - 1) {
      ctx.fillStyle = c.axis; ctx.textAlign = "center";
      for (let j = 0; j <= 6; j++) { const tv = t0 + (t1 - t0) * j / 6; ctx.fillText(tv.toFixed(0) + " s", X(tv), h - 4); }
    }
  });
  ctx.fillStyle = c.axis; ctx.textAlign = "right"; ctx.font = "11px system-ui,sans-serif";
  ctx.fillText("grey = log, orange = tuned model" + (meta && meta.lag_s ? ` (model shifted by ${meta.lag_s} s)` : ""), w - padR - 4, padT + 10);
}

/* ------------------------------------------------------------- study --- */

function optimConfig() {
  const params = {};
  for (const k of Object.keys(O.state.params)) {
    if ($("#optimOn_" + k).checked) params[k] = { min: oNum("#optimMin_" + k), max: oNum("#optimMax_" + k) };
  }
  const weights = {};
  for (const k of ["speed", "torque_front", "torque_rear", "pack_power"]) weights[k] = oNum("#optimW_" + k, 0);
  return {
    name: $("#optimName").value || "roadload",
    log_path: O.log.path, channel_map: optimReadMap(),
    windows: [...O.selected].sort((a, b) => a - b).map(i => ({ t0: O.windows[i].t0, t1: O.windows[i].t1 })),
    params, weights,
    max_workers: Math.round(oNum("#optimWorkers", 6)),
    step_s: oNum("#optimStep", 1.0), hmax: oNum("#optimHmax", 0.01),
    settle_s: oNum("#optimSettle", 3), max_lag_s: oNum("#optimLag", 2),
    pedal_mode: $("#optimPedalMode").value,
    design: { grid: Math.round(oNum("#optimGrid", 3)), rounds: Math.round(oNum("#optimRounds", 2)) },
    base_payload: (typeof vehiclePayload === "function") ? vehiclePayload() : null,
  };
}

function optimUpdateButtons() {
  const running = !!(O.study && O.study.running);
  const ready = !!(O.log && O.selected.size > 0 && O.map.speed && O.map.pedal && !running);
  $("#btnOptimStart").disabled = !ready;
  $("#optimStartHint").textContent = running ? "A study is running."
    : !O.log ? "Pick a log first." : !(O.map.speed && O.map.pedal) ? "Map speed and pedal."
    : !O.selected.size ? "Select at least one window." : `${O.selected.size} window(s) selected.`;
  const done = O.study && !running && O.study.best;
  $("#btnOptimExport").disabled = !done;
  $("#btnOptimOpenBest").disabled = !(O.studyDir);
}

async function optimStart() {
  const cfg = optimConfig();
  if (!Object.keys(cfg.params).length) { $("#optimStartHint").textContent = "Enable at least one tunable."; return; }
  $("#btnOptimStart").disabled = true;
  const res = await pywebview.api.optim_start(cfg);
  if (!res.ok) { $("#optimStartHint").textContent = "Could not start: " + res.error; optimUpdateButtons(); return; }
  O.studyDir = res.dir; O.study = res.study;
  $("#optimStartHint").textContent = "Study started — you can leave this tab; the Live tab shows the solvers.";
  optimSetBusy(true);
  optimRenderStudy(res.study);
  if (O.poll) clearInterval(O.poll);
  O.poll = setInterval(optimTick, 3000);
}

async function optimTick() {
  const res = await pywebview.api.optim_status();
  if (!res.ok || !res.study) return;
  O.study = res.study; O.studyDir = res.study.dir;
  optimRenderStudy(res.study);
  if (!res.running) {
    clearInterval(O.poll); O.poll = null;
    optimSetBusy(false);
    $("#optimStartHint").textContent = "Study " + res.study.status + ". " +
      (res.study.best ? "Export the tuned model below." : "No successful candidate.");
    const st = await pywebview.api.optim_state();
    if (st.ok) optimRenderHistory(st.history || []);
    optimUpdateButtons();
  }
}

async function optimStop() {
  await pywebview.api.optim_stop();
  $("#optimStartHint").textContent = "Stopping — killing the running solvers…";
}

function optimSetBusy(running) {
  $("#btnOptimStop").style.display = running ? "" : "none";
  $("#btnOptimStart").disabled = running || $("#btnOptimStart").disabled;
  if (!running && O.poll) { clearInterval(O.poll); O.poll = null; }
}

function optimRenderStudy(s) {
  if (!s) return;
  const best = s.best;
  const tiles = [
    ["status", s.status + (s.running ? "" : "")],
    ["round", `${s.round} / ${s.rounds}`],
    ["jobs", `${s.jobs_done} / ${s.jobs_total}`],
    ["elapsed", oSecs(s.elapsed_s)],
    ["solvers", s.max_workers],
    ["best total", best ? oFmt(best.score, 4) : "–"],
  ];
  if (best) for (const [k, v] of Object.entries(best.params)) tiles.push([k, oFmt(v, 3)]);
  $("#optimStatus").innerHTML = tiles.map(([l, v]) =>
    `<div class="vtile"><div class="vv">${oEsc(v)}</div><div class="vl">${oEsc(l)}</div></div>`).join("");
  const pnames = Object.keys(s.params || {});
  let html = `<thead><tr><th>#</th><th>round</th>${pnames.map(p => `<th>${oEsc(p)}</th>`).join("")}` +
    `<th>windows</th><th>total</th><th>status</th></tr></thead><tbody>`;
  for (const c of s.candidates || []) {
    const isBest = best && c.id === best.id;
    const jobs = c.jobs.map(j => {
      const frac = j.status === "ok" ? 1 : (j.frac || 0);
      const cls = j.status === "failed" ? " failed" : (j.status === "running" ? " pulse" : "");
      const extra = j.status === "running" ? (j.eta_s !== undefined && j.eta_s !== null ? ` eta ${oSecs(j.eta_s)}` : "") +
        (j.ram_mb ? ` · ${j.ram_mb} MB` : "") : (j.status === "ok" && j.score ? ` ${oFmt(j.score.total, 3)}` : "");
      return `<span title="window ${j.window}: ${oEsc(j.status)}${j.error ? " — " + oEsc(j.error) : ""}">` +
        `<span class="progress-track"><span class="progress-fill${cls}" style="width:${Math.round(frac * 100)}%"></span></span>` +
        `<span class="hint">w${j.window}${extra}</span></span>`;
    }).join("<br>");
    html += `<tr class="${isBest ? "best" : ""}"><td>${c.id}${isBest ? " ★" : ""}</td><td>${oEsc(c.round)}</td>` +
      pnames.map(p => `<td>${oFmt(c.params[p], 3)}</td>`).join("") +
      `<td>${jobs}</td><td>${c.score === null || c.score === undefined ? "–" : (c.score >= 10 ? "failed" : oFmt(c.score, 4))}</td>` +
      `<td>${oEsc(c.status)}</td></tr>`;
  }
  $("#optimJobs").innerHTML = html + "</tbody>";
  const sf = s.surface;
  $("#optimSurface").textContent = sf
    ? `Response surface over ${sf.n} candidate(s) (R² ${sf.r2 !== undefined ? sf.r2 : "–"}); predicted minimum ` +
      Object.entries(s.surface_min || {}).map(([k, v]) => `${k} ${oFmt(v, 3)}`).join(", ") +
      (s.surface_min_pred !== undefined ? ` → total ≈ ${oFmt(s.surface_min_pred, 4)}` : "") +
      (s.message ? ` — ${s.message}` : "")
    : (s.message || "");
  // overlay window selector
  const sel = $("#optimOverlayWin");
  if (sel && sel.options.length !== (s.windows || []).length) {
    sel.innerHTML = (s.windows || []).map((w, i) => `<option value="${i}">${i}: ${oFmt(w.t0, 0)}–${oFmt(w.t1, 0)} s</option>`).join("");
  }
}

/* ------------------------------------------------------------ export --- */

async function optimExport() {
  $("#btnOptimExport").disabled = true;
  $("#optimExportInfo").textContent = "Converting the best candidate and writing the report…";
  const res = await pywebview.api.optim_export(O.studyDir, $("#optimRedact").checked);
  if (!res.ok) { $("#optimExportInfo").textContent = "Export failed: " + res.error; optimUpdateButtons(); return; }
  $("#optimExportInfo").innerHTML = `Tuned model in <b>${oEsc(res.best_dir)}</b>` +
    (res.export_dir ? ` — leaderboard copy ${oEsc(res.export_dir.split(/[\\/]/).pop())}` : "") +
    (res.figure ? " — overlay figure written" : "");
  optimUpdateButtons();
  optimLoadOverlay();
}

async function optimLoadOverlay() {
  if (!O.studyDir) return;
  const win = parseInt(($("#optimOverlayWin").value || "0"), 10);
  const res = await pywebview.api.optim_overlay(O.studyDir, win);
  if (!res.ok) { optimDrawOverlay(null); return; }
  optimDrawOverlay(res.series, { lag_s: res.lag_s });
}

/* ----------------------------------------------------------- history --- */

function optimRenderHistory(list) {
  const t = $("#optimHistory");
  if (!list.length) { t.innerHTML = "<tr><td class='hint'>No studies yet.</td></tr>"; return; }
  let html = "<thead><tr><th>study</th><th>status</th><th>candidates</th><th>best</th><th>elapsed</th><th></th></tr></thead><tbody>";
  list.forEach((s, i) => {
    const b = s.best ? Object.entries(s.best.params).map(([k, v]) => `${k} ${oFmt(v, 3)}`).join(", ") + ` → ${oFmt(s.best.score, 4)}` : "–";
    html += `<tr><td title="${oEsc(s.dir)}">${oEsc(s.name)}<br><span class="hint">${oEsc(s.dir.split(/[\\/]/).pop())}</span></td>` +
      `<td>${oEsc(s.status)}${s.exported ? " · exported" : ""}</td><td>${s.n_candidates}</td><td>${b}</td><td>${oSecs(s.elapsed_s)}</td>` +
      `<td><button class="ghost" data-dir="${oEsc(s.dir)}" data-act="load">Show</button> ` +
      `<button class="ghost" data-dir="${oEsc(s.dir)}" data-act="open">Open folder</button></td></tr>`;
  });
  t.innerHTML = html + "</tbody>";
  $$("#optimHistory button").forEach(b => b.onclick = async () => {
    if (b.dataset.act === "open") { await pywebview.api.optim_open(b.dataset.dir); return; }
    const res = await pywebview.api.optim_study(b.dataset.dir);
    if (res.ok) { O.study = res.state; O.study.running = false; O.studyDir = b.dataset.dir; optimRenderStudy(res.state); optimUpdateButtons(); optimLoadOverlay(); }
  });
}

/* ---------------------------------------------------------- assistant -- */

const A = { poll: null, state: null };

function agentRender(st) {
  const el = $("#agentLog"); if (!el) return;
  const lines = (st.transcript || []).map(e => {
    const tag = { user: "you", assistant: "assistant", tool: "→ tool", result: "← result", system: "·" }[e.role] || e.role;
    return `[${e.when}] ${tag}: ${e.text}`;
  });
  el.textContent = lines.join("\n") || "No conversation yet.";
  el.scrollTop = el.scrollHeight;
  $("#btnAgentStop").style.display = st.busy ? "" : "none";
  $("#btnAgentSend").disabled = !!st.busy;
}

async function agentLoad() {
  if (!window.pywebview) return;
  const st = await pywebview.api.agent_state();
  if (!st.ok) { $("#agentHint").textContent = "Assistant unavailable: " + st.error; return; }
  A.state = st;
  $("#agentGpu").value = st.gpu_layers;
  $("#agentHint").textContent = !st.runtime
    ? "llama-cpp-python is not installed in this environment; the assistant cannot run a model."
    : !st.model_ok ? "No model file yet — pick a GGUF (e.g. a 7B instruct model, Q4) to enable the assistant. " + st.runtime + "."
    : `Model: ${st.model_name} (${st.loaded ? "loaded" : "loads on first message"}), ${st.runtime}, ` +
      `${st.gpu_layers < 0 ? "all layers on GPU" : (st.gpu_layers ? st.gpu_layers + " GPU layers" : "CPU")}, context ${st.ctx}.`;
  agentRender(st);
  if (st.busy && !A.poll) A.poll = setInterval(agentTick, 2000);
}

async function agentTick() {
  const st = await pywebview.api.agent_tail();
  if (!st.ok) return;
  agentRender(st);
  if (!st.busy) { clearInterval(A.poll); A.poll = null; optimTick(); }
}

async function agentSend() {
  const inp = $("#agentInput");
  const text = inp.value.trim(); if (!text) return;
  const res = await pywebview.api.agent_send(text);
  if (!res.ok) { $("#agentHint").textContent = "Not sent: " + res.error; return; }
  inp.value = "";
  if (A.poll) clearInterval(A.poll);
  A.poll = setInterval(agentTick, 2000);
  agentTick();
}

/* ------------------------------------------------------------- wiring -- */

document.addEventListener("DOMContentLoaded", () => {
  const on = (id, fn) => { const el = $(id); if (el) el.onclick = fn; };
  on("#btnAgentModel", async () => { await pywebview.api.agent_pick_model(); agentLoad(); });
  on("#btnAgentReset", async () => { await pywebview.api.agent_reset(); agentLoad(); });
  on("#btnAgentStop", async () => { await pywebview.api.agent_stop(); });
  on("#btnAgentSend", agentSend);
  const ai = $("#agentInput"); if (ai) ai.onkeydown = (e) => { if (e.key === "Enter") agentSend(); };
  const ag = $("#agentGpu"); if (ag) ag.onchange = async () => { await pywebview.api.agent_set("llm_gpu_layers", parseInt(ag.value, 10)); agentLoad(); };
  on("#btnOptimPick", optimPickLog);
  on("#btnOptimSaveMap", optimSaveMap);
  on("#btnOptimFind", optimFind);
  on("#btnOptimAddWin", optimAddWindow);
  on("#btnOptimStart", optimStart);
  on("#btnOptimStop", optimStop);
  on("#btnOptimExport", optimExport);
  on("#btnOptimOpenBest", async () => { if (O.studyDir) await pywebview.api.optim_open(O.studyDir); });
  const sel = $("#optimOverlayWin"); if (sel) sel.onchange = optimLoadOverlay;
  if (window.msPipe) {
    window.msPipe.optimEvent = (e) => { if (!O.poll) optimTick(); };
  }
  window.addEventListener("resize", () => { optimDrawTrace(); });
});
window.optimizerOnEnter = () => { optimLoad(); agentLoad(); };
