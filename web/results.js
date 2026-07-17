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
  } catch (e) {
    $("#resHint").textContent = "ERROR: " + e;
  }
}

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

/* ---------------- wiring ---------------- */

$("#btnResRefresh").onclick = () => refreshResults(false);
$("#btnResRecompute").onclick = () => refreshResults(true);
$("#btnResExport").onclick = async () => {
  const r = await pywebview.api.export_results_csv();
  if (r && r.path) $("#resHint").textContent = "exported: " + r.path;
};
