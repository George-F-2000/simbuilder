/* ============================================================================
   results.js — the Results tab of SimBuilder: the campaign leaderboard.

   Python (results.py via Api.get_results) scans the runs folder and computes
   metrics per run; this file renders the sortable table and two comparison
   charts: Wh/km bars (color = EMS strategy) and the efficiency-vs-drivability
   scatter (the Pareto view). pywebview-only; a plain browser shows a hint.

   Depends on app.js helpers ($, escHtml). Loaded last.
   ========================================================================== */

let resRows = [];
let resSort = { key: "when", dir: -1 };

const RES_COLS = [
  ["name", "Run"], ["when", "When"], ["vehicle", "Vehicle"],
  ["serial", "Serial"], ["ems", "EMS"], ["cycle", "Cycle"],
  ["duration_s", "Sim s"], ["dist_km", "km"],
  ["energy_kwh", "kWh"], ["wh_per_km", "Wh/km"],
  ["soc_drop_pct", "ΔSOC %"], ["track_rmse_kph", "Track RMSE"],
  ["jerk_rms", "Jerk RMS"], ["chatter_per_min", "Chatter/min"],
  ["v_max_kph", "Vmax"],
];

const EMS_COLORS = {
  deck_default: "#5a6572", loss_optimal: "#1e7e34", rule: "#0b5ed7",
  fuzzy: "#7048b6", even: "#c47f17", single_motor: "#c0392b",
};
function emsColor(s) { return EMS_COLORS[s] || "#333333"; }

/* ---------------- data ---------------- */

async function refreshResults(force) {
  $("#resHint").textContent = "scanning runs…";
  try {
    const data = await pywebview.api.get_results(!!force);
    resRows = data.rows || [];
    $("#resRunsDir").textContent = "Runs folder: " + data.runs_dir;
    $("#resHint").textContent = resRows.length
      ? "" : "No runs with an MF4 found yet — run something first.";
    renderResultsTable();
    drawResultCharts();
    renderDrivability();
  } catch (e) {
    $("#resHint").textContent = "ERROR: " + e;
  }
}

/* ---------------- results sub-tabs ---------------- */

function switchResSub(name) {
  $$("#resSubtabs .subtab").forEach(b =>
    b.classList.toggle("active", b.dataset.sub === name));
  ["leaderboard", "drivability", "glossary"].forEach(s =>
    $("#sub-" + s).classList.toggle("hidden", s !== name));
  // CSV/refresh tools only make sense on the run-driven panels
  $(".subtab-tools").style.visibility = name === "glossary" ? "hidden" : "visible";
  if (name === "drivability") renderDrivability();
  if (name === "glossary") renderGlossary();
}
$$("#resSubtabs .subtab").forEach(b =>
  b.onclick = () => switchResSub(b.dataset.sub));

function resultsOnEnter() {
  if (!window.pywebview) {
    $("#resHint").textContent =
      "The Results tab reads your runs folder — available inside the " +
      "SimBuilder app.";
    return;
  }
  refreshResults(false);
}
window.resultsOnEnter = resultsOnEnter;

/* ---------------- table ---------------- */

function fmtCell(v) {
  if (v === undefined || v === null || v === "") return "—";
  return String(v);
}

function renderResultsTable() {
  const rows = [...resRows].sort((a, b) => {
    const x = a[resSort.key], y = b[resSort.key];
    if (x === undefined && y === undefined) return 0;
    if (x === undefined) return 1;
    if (y === undefined) return -1;
    return (x < y ? -1 : x > y ? 1 : 0) * resSort.dir;
  });

  let html = "<thead><tr>" + RES_COLS.map(([k, label]) =>
    `<th data-k="${k}">${label}${resSort.key === k ?
      (resSort.dir > 0 ? " ▲" : " ▼") : ""}</th>`).join("") +
    "<th></th></tr></thead><tbody>";

  for (const r of rows) {
    html += "<tr" + (r.error ? ' class="res-err"' : "") + ">";
    for (const [k] of RES_COLS) {
      let cell = fmtCell(r[k]);
      if (k === "serial" && r.serial) {
        const mark = r.serial_ok === undefined ? "" :
          (r.serial_ok ? " ✓" : " ⚠MISMATCH");
        cell = r.serial.replace("SN-", "") + mark;
      }
      if (k === "ems") {
        cell = `<span class="ems-dot" style="background:${emsColor(r.ems)}"></span>` +
          escHtml(r.ems || "");
        html += `<td>${cell}</td>`;
        continue;
      }
      html += `<td>${escHtml(cell)}</td>`;
    }
    html += `<td class="res-actions">
      <button class="ghost res-open" data-p="${escHtml(r.path)}" title="Open run folder">📂</button>
      <button class="ghost res-view" data-p="${escHtml(r.mf4)}" title="Open MF4 in viewer">📈</button>
    </td></tr>`;
    if (r.error) html += `<tr class="res-err"><td colspan="${RES_COLS.length + 1}">
      ⚠ ${escHtml(r.error)}</td></tr>`;
  }
  $("#resTable").innerHTML = html + "</tbody>";

  $$("#resTable th[data-k]").forEach(th => th.onclick = () => {
    const k = th.dataset.k;
    resSort = { key: k, dir: resSort.key === k ? -resSort.dir : 1 };
    renderResultsTable();
  });
  $$(".res-open").forEach(b => b.onclick = () => pywebview.api.open_path(b.dataset.p));
  $$(".res-view").forEach(b => b.onclick = () => pywebview.api.view_mf4(b.dataset.p));
}

/* ---------------- charts ---------------- */

function chartAxes(ctx, W, H, mL, mB, mT, mR) {
  ctx.clearRect(0, 0, W, H);
  ctx.strokeStyle = "#c9d1da";
  ctx.beginPath();
  ctx.moveTo(mL, mT); ctx.lineTo(mL, H - mB); ctx.lineTo(W - mR, H - mB);
  ctx.stroke();
}

function drawResultCharts() {
  const withEff = resRows.filter(r => r.wh_per_km !== undefined)
                         .sort((a, b) => a.wh_per_km - b.wh_per_km);
  drawBar(withEff);
  drawScatter(withEff);
  const strategies = [...new Set(resRows.map(r => r.ems))];
  $("#resLegend").innerHTML = strategies.map(s =>
    `<span class="ems-dot" style="background:${emsColor(s)}"></span>${escHtml(s)}&nbsp;&nbsp;`
  ).join("") + (withEff.length ? "" :
    "  (no runs with Wh/km yet — needs the BattPower channel: re-run or " +
    "reconvert older runs)");
}

function drawBar(rows) {
  const c = $("#resBar"), ctx = c.getContext("2d");
  const W = c.width, H = c.height, mL = 56, mB = 58, mT = 12, mR = 8;
  chartAxes(ctx, W, H, mL, mB, mT, mR);
  if (!rows.length) return;
  const vmax = Math.max(...rows.map(r => r.wh_per_km)) * 1.1;
  const bw = Math.min(70, (W - mL - mR) / rows.length * 0.7);
  ctx.font = "10px system-ui"; ctx.fillStyle = "#5a6572";
  ctx.textAlign = "right";
  for (let g = 0; g <= 4; g++) {
    const val = vmax * g / 4, y = H - mB - (H - mB - mT) * g / 4;
    ctx.fillText(val.toFixed(0), mL - 5, y + 3);
  }
  rows.forEach((r, i) => {
    const x = mL + (W - mL - mR) * (i + 0.5) / rows.length;
    const h = (H - mB - mT) * r.wh_per_km / vmax;
    ctx.fillStyle = emsColor(r.ems);
    ctx.fillRect(x - bw / 2, H - mB - h, bw, h);
    ctx.fillStyle = "#33404e"; ctx.textAlign = "center";
    ctx.fillText(r.wh_per_km.toFixed(0), x, H - mB - h - 4);
    ctx.save();
    ctx.translate(x, H - mB + 8); ctx.rotate(-Math.PI / 5);
    ctx.textAlign = "right";
    ctx.fillText(r.name.slice(0, 22), 0, 8);
    ctx.restore();
  });
  ctx.fillStyle = "#5a6572"; ctx.textAlign = "left";
  ctx.fillText("Wh/km (net, regen included) — lower is better", mL, 10);
}

function drawScatter(rows) {
  const c = $("#resScatter"), ctx = c.getContext("2d");
  const W = c.width, H = c.height, mL = 56, mB = 40, mT = 14, mR = 12;
  chartAxes(ctx, W, H, mL, mB, mT, mR);
  const pts = rows.filter(r => r.jerk_rms !== undefined);
  if (!pts.length) return;
  const xmax = Math.max(...pts.map(r => r.jerk_rms)) * 1.15 || 1;
  const ymax = Math.max(...pts.map(r => r.wh_per_km)) * 1.15 || 1;
  ctx.font = "10px system-ui"; ctx.fillStyle = "#5a6572";
  ctx.textAlign = "center";
  ctx.fillText("Jerk RMS (drivability — lower is smoother) →", mL + (W - mL - mR) / 2, H - 8);
  ctx.save(); ctx.translate(14, mT + (H - mT - mB) / 2); ctx.rotate(-Math.PI / 2);
  ctx.fillText("Wh/km →", 0, 0); ctx.restore();
  for (const r of pts) {
    const x = mL + (W - mL - mR) * r.jerk_rms / xmax;
    const y = H - mB - (H - mT - mB) * r.wh_per_km / ymax;
    ctx.fillStyle = emsColor(r.ems);
    ctx.beginPath(); ctx.arc(x, y, 6, 0, 2 * Math.PI); ctx.fill();
    ctx.fillStyle = "#33404e"; ctx.textAlign = "left";
    ctx.fillText(r.name.slice(0, 18), x + 8, y + 3);
  }
  ctx.fillStyle = "#5a6572"; ctx.textAlign = "left";
  ctx.fillText("bottom-left corner wins: efficient AND smooth", mL, 10);
}

/* ---------------- drivability sub-tab ---------------- */

const DRV_COLS = [
  ["name", "Run", ""], ["ems", "EMS", ""],
  ["jerk_rms", "Jerk RMS", "m/s³"], ["jerk_peak", "Jerk peak", "m/s³"],
  ["arm", "ARM", "m/s²"], ["t_arm", "tARM", "s"],
  ["accel_rms", "Accel RMS", "m/s²"], ["vdv", "VDV", "m/s¹·⁷⁵"],
  ["chatter_per_min", "Chatter", "/min"],
];

function renderDrivability() {
  const rows = [...resRows].filter(r => r.jerk_rms !== undefined)
    .sort((a, b) => (a.jerk_rms ?? 1e9) - (b.jerk_rms ?? 1e9));
  let html = "<thead><tr>" + DRV_COLS.map(([, label, unit]) =>
    `<th>${label}${unit ? `<span class="u">${unit}</span>` : ""}</th>`).join("") +
    "</tr></thead><tbody>";
  if (!rows.length) {
    html += `<tr><td colspan="${DRV_COLS.length}">No runs with an
      AccelerationChassis channel yet — run something, or Recompute all.</td></tr>`;
  }
  for (const r of rows) {
    html += "<tr>";
    for (const [k] of DRV_COLS) {
      if (k === "ems") {
        html += `<td><span class="ems-dot" style="background:${emsColor(r.ems)}"></span>${escHtml(r.ems || "")}</td>`;
      } else if (k === "name") {
        html += `<td class="drv-name">${escHtml(r.name || "")}</td>`;
      } else {
        html += `<td>${fmtCell(r[k])}</td>`;
      }
    }
    html += "</tr>";
  }
  $("#drvTable").innerHTML = html + "</tbody>";
  drawDrivabilityChart();
}

function drawDrivabilityChart() {
  const c = $("#drvScatter");
  if (!c || c.offsetParent === null) return;   // hidden: canvas won't paint
  const ctx = c.getContext("2d");
  const W = c.width, H = c.height, mL = 58, mB = 44, mT = 14, mR = 14;
  chartAxes(ctx, W, H, mL, mB, mT, mR);
  const pts = resRows.filter(r => r.jerk_rms !== undefined
    && r.chatter_per_min !== undefined);
  ctx.font = "10px system-ui"; ctx.fillStyle = "#5a6572"; ctx.textAlign = "center";
  ctx.fillText("Motor chatter (events/min) →", mL + (W - mL - mR) / 2, H - 8);
  ctx.save(); ctx.translate(14, mT + (H - mT - mB) / 2); ctx.rotate(-Math.PI / 2);
  ctx.fillText("Jerk RMS (m/s³) →", 0, 0); ctx.restore();
  if (!pts.length) return;
  const xmax = Math.max(...pts.map(r => r.chatter_per_min), 1) * 1.15;
  const ymax = Math.max(...pts.map(r => r.jerk_rms), 1) * 1.15;
  for (const r of pts) {
    const x = mL + (W - mL - mR) * r.chatter_per_min / xmax;
    const y = H - mB - (H - mT - mB) * r.jerk_rms / ymax;
    ctx.fillStyle = emsColor(r.ems);
    ctx.beginPath(); ctx.arc(x, y, 6, 0, 2 * Math.PI); ctx.fill();
    ctx.fillStyle = "#33404e"; ctx.textAlign = "left";
    ctx.fillText((r.name || "").slice(0, 18), x + 8, y + 3);
  }
  ctx.fillStyle = "#5a6572"; ctx.textAlign = "left";
  ctx.fillText("bottom-left wins: smooth AND no chatter", mL, 10);
}

/* ---------------- glossary ---------------- */

const GLOSSARY = [
  ["Efficiency", [
    ["Wh/km", "Net battery energy per kilometre (∫BattPower dt ÷ distance). Regen is included, so it lowers the number. The efficiency headline; lower is better. Needs distance > 50 m to be meaningful."],
    ["kWh", "Net battery energy over the whole run (∫BattPower dt). Discharge positive, regen negative."],
    ["ΔSOC %", "Battery state-of-charge drop, start minus end. NOTE: the FMU's internal pack is small (~9 kWh), so ΔSOC is not the real vehicle's — trust the integrated kWh instead."],
    ["Wh/mi", "Wh/km × 1.609. The US convention; the real prototype measured ~420 Wh/mi on the trapezoidal test."],
  ]],
  ["Drivability", [
    ["Jerk RMS", "Root-mean-square of da/dt (rate of change of longitudinal acceleration), m/s³. The core ride-harshness metric — abrupt torque changes raise it. Lower is smoother."],
    ["Jerk peak", "Largest single |da/dt| in the run, m/s³. Catches the worst individual shock a smooth RMS can hide."],
    ["ARM", "Acceleration Response Magnitude — computed here as the 95th-percentile |longitudinal acceleration| (m/s²): how hard the vehicle responds, robust to outliers. ⚠ Best-effort definition — ARM/tARM are not standardised in public sources; confirm against your AVL/lab convention and this formula will be adjusted."],
    ["tARM", "Acceleration Response Time — computed here as the 10→90% rise time (s) of the strongest tip-in (largest sustained positive-acceleration event): how quickly torque builds. ⚠ Best-effort definition, same caveat as ARM."],
    ["Accel RMS", "RMS of longitudinal acceleration, m/s². A ride-comfort proxy (ISO-2631 uses a frequency-weighted acceleration; this is the unweighted form)."],
    ["VDV", "Vibration Dose Value, (∫a⁴ dt)^0.25, m/s¹·⁷⁵. Weights big transients more heavily than RMS — a standard whole-body discomfort measure."],
    ["Chatter/min", "Motor on/off transitions per minute (|EM torque| crossing 2 N·m). The classic loss-optimal-EMS drivability sin — a strategy that saves energy by rapidly toggling a motor feels bad. The drivability axis of the Pareto plot."],
  ]],
  ["Vehicle & provenance", [
    ["Serial (SN-…)", "A deterministic fingerprint (FNV-1a hash) of the entire vehicle spec — motors, gearing, mass, tire, pack, EMS, and every ⚡ checkbox. Same spec = same serial, always. Written into every MF4 as the VehicleSerial channel so a result can be matched to the exact car that made it."],
    ["Serial ✓ / ⚠MISMATCH", "Cross-check between the run's vehicle.json and the MF4's embedded VehicleSerial. ⚠ means the recorded config and the solved config disagree — do not trust that row."],
    ["Track RMSE", "For cycle runs (UDDS/HWFET): RMS speed error vs the target trace, km/h. Doubles as the VALIDITY GATE — above ~2 km/h the driver couldn't follow the cycle and the Wh/km is meaningless."],
    ["Vmax", "Peak vehicle speed reached in the run, km/h."],
  ]],
  ["Powertrain & EMS", [
    ["EMS strategy", "How combined torque demand is split between the two axles. deck_default (the model's own map), traction (ratio-aware, load-based baseline), loss_optimal (min electrical loss), rule/fuzzy/even/single_motor."],
    ["r_ch", "The torque-split map inside the motor FMU: fraction of the combined MOTOR-torque demand sent to the SECONDARY (rear) axle. 0 = front only, 0.5 = even MOTOR torque. Because the axles are geared 18:1 vs 9.59:1, an even WHEEL split is r_ch = 0.652, not 0.5."],
    ["traction split", "The ratio-aware baseline (added 2026-07-19): divides WHEEL torque by axle load including weight transfer, then converts to r_ch through the drive ratios, then clamps to each motor's real envelope. Fixes the front-axle over-drive the deck's own map caused."],
    ["Map is truth", "Per-motor toggle: when a full motor-data .mat is uploaded, use ITS measured torque envelope verbatim; the kW/N·m/rpm fields become display-only for that motor."],
    ["Map coverage %", "How much of the injected motor efficiency map is measured data vs synthetic fill. Uncovered (light-load) cells are filled with a scaled model — disclosed per run in the log."],
  ]],
  ["Run modes & numerics", [
    ["Deck as-is", "🏁 master toggle: run the model exactly as exported from MotionView, skipping every ⚡ override. For validating the stock model against real drive data."],
    ["Creep start", "The model cannot initialise at exactly v = 0, so scenarios floor the start speed at 0.9 km/h. The driver regulates to the demand immediately."],
    ["h_max", "Maximum solver time step, s. Floored at 10 ms — the model's validated resolution; finer isn't needed and coarser is flagged."],
    ["Deck default (EMS)", "Leaves the deck's built-in torque-split map untouched. NOTE: on this vehicle it over-drives the front axle on any acceleration — invalid for cycles; use the traction split."],
  ]],
];

function renderGlossary() {
  const filt = ($("#glossFilter").value || "").trim().toLowerCase();
  let html = "";
  for (const [group, items] of GLOSSARY) {
    const hits = items.filter(([term, def]) =>
      !filt || term.toLowerCase().includes(filt) || def.toLowerCase().includes(filt));
    if (!hits.length) continue;
    html += `<div class="gloss-group"><h3>${escHtml(group)}</h3>`;
    for (const [term, def] of hits) {
      html += `<div class="gloss-item"><dt>${escHtml(term)}</dt>
        <dd>${escHtml(def)}</dd></div>`;
    }
    html += "</div>";
  }
  $("#glossBody").innerHTML = html ||
    `<p class="hint">No terms match “${escHtml(filt)}”.</p>`;
}

/* ---------------- wiring ---------------- */

$("#glossFilter").oninput = renderGlossary;
$("#btnResRefresh").onclick = () => refreshResults(false);
$("#btnResRecompute").onclick = () => refreshResults(true);
$("#btnResExport").onclick = async () => {
  const r = await pywebview.api.export_results_csv();
  if (r && r.path) $("#resHint").textContent = "exported: " + r.path;
};
