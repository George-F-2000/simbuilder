/* ---------------------------------------------------------------------------
   dq.js — Drive Quality sub-tab (Results).

   Scores run MF4s against the EV Challenge targets exactly as the team's
   EVC_DriveQuality MATLAB app does: ARM (accel-vs-speed against banded
   target curves), tARM (transient jerk) and response delay, per tip-in
   pedal class. Every metric is reported on BOTH pedal axes — raw
   (commanded pedal) and mapped (real-car-equivalent via the calibration
   layer) — so a poor score can be attributed to the pedal interface or to
   the vehicle response, not confused between them.
   All computation is Python (drive_quality.py); this file is presentation.
--------------------------------------------------------------------------- */

let dqReports = [];

/* live.js keeps its own esc() module-private, so define one here. */
function dqEsc(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
                  .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function dqFmt(x, dp) {
  return (x === null || x === undefined) ? "—" : Number(x).toFixed(dp === undefined ? 3 : dp);
}

function dqPoints(score, max) {
  return (score === null || score === undefined) ? "—" : (score * max).toFixed(1) + " pts";
}

function renderDqScores() {
  const t = $("#dqScoreTable");
  if (!dqReports.length) {
    t.innerHTML = "<tr><td class='hint'>Nothing scored yet.</td></tr>";
    return;
  }
  let h = "<thead><tr><th>File</th><th>events</th>" +
          "<th>ARM raw</th><th>ARM mapped</th>" +
          "<th>tARM raw</th><th>tARM mapped</th>" +
          "<th>Delay raw</th><th>Delay mapped</th></tr></thead><tbody>";
  for (const r of dqReports) {
    if (r.error) {
      h += `<tr><td>${dqEsc(r.file || "?")}</td><td colspan="7" class="hint">${dqEsc(r.error)}</td></tr>`;
      continue;
    }
    const a = r.scores_raw, b = r.scores_mapped;
    h += `<tr><td>${dqEsc(r.file)}</td><td>${r.events.length}</td>` +
         `<td>${dqPoints(a.arm, 20)}</td><td><b>${dqPoints(b.arm, 20)}</b></td>` +
         `<td>${dqFmt(a.tarm, 2)}</td><td><b>${dqFmt(b.tarm, 2)}</b></td>` +
         `<td>${dqFmt(a.delay, 2)}</td><td><b>${dqFmt(b.delay, 2)}</b></td></tr>`;
  }
  t.innerHTML = h + "</tbody>";
}

function renderDqEvents() {
  const t = $("#dqEventTable");
  const rows = [];
  for (const r of dqReports) {
    for (const e of (r.events || [])) rows.push([r.file, e]);
  }
  if (!rows.length) {
    t.innerHTML = "<tr><td class='hint'>No tip-in events detected.</td></tr>";
    return;
  }
  let h = "<thead><tr><th>File</th><th>t (s)</th><th>from stop</th>" +
          "<th>pedal %</th><th>class raw</th><th>class mapped</th>" +
          "<th>delay (s)</th><th>tARM (m/s³)</th></tr></thead><tbody>";
  for (const [file, e] of rows) {
    const late = (e.delay_s !== null && e.delay_s > 0.3) ? ' class="warn"' : "";
    h += `<tr><td>${dqEsc(file)}</td><td>${dqFmt(e.t, 2)}</td>` +
         `<td>${e.from_stop ? "yes" : "no"}</td><td>${dqFmt(e.pedal_pct, 1)}</td>` +
         `<td>${e.class_raw}</td><td>${e.class_mapped}</td>` +
         `<td${late}>${dqFmt(e.delay_s, 2)}</td><td>${dqFmt(e.tarm_ms3, 2)}</td></tr>`;
  }
  t.innerHTML = h + "</tbody>";
}

function renderDqArm() {
  const cv = $("#dqArmChart");
  if (!cv || typeof drawPlot !== "function") return;
  /* drawPlot() contract (app.js): {x, y, color, label, dash:[on,off]} */
  const RUN_COLORS = ["#2457c5", "#c0463c", "#b5822a", "#6a4bbc", "#0f766e"];
  const series = [];
  let tMax = 60, n = 0;
  for (const r of dqReports) {
    for (const e of (r.events || [])) {
      const arm = e.arm_mapped || e.arm_raw;
      if (!arm || !arm.points_v || !arm.points_v.length) continue;
      const cls = e.arm_mapped ? e.class_mapped : e.class_raw;
      tMax = Math.max(tMax, arm.points_v[arm.points_v.length - 1]);
      series.push({ x: arm.points_v, y: arm.target, color: "#3fb27f",
                    dash: [5, 4], label: "target " + cls + "%" });
      series.push({ x: arm.points_v, y: arm.measured,
                    color: RUN_COLORS[n % RUN_COLORS.length],
                    label: dqFmt(e.pedal_pct, 0) + "% pedal" });
      n += 1;
    }
  }
  if (!series.length) {
    cv.getContext("2d").clearRect(0, 0, cv.width, cv.height);
    return;
  }
  drawPlot(cv, series, { tMax: tMax, yMax: 3.0,
                         title: "ARM — accel vs speed (m/s² vs km/h)" });
}

function renderDriveQuality() {
  renderDqScores();
  renderDqEvents();
  renderDqArm();
}
window.renderDriveQuality = renderDriveQuality;

async function dqScore(folder) {
  if (!window.pywebview) return;
  $("#dqHint").textContent = "Scoring…";
  try {
    const res = folder ? await pywebview.api.dq_score_folder()
                       : await pywebview.api.dq_score_file();
    if (!res || res.cancelled) { $("#dqHint").textContent = "Cancelled."; return; }
    dqReports = res.reports || [];
    $("#dqHint").textContent = dqReports.length +
      " file(s) scored against the EV Challenge targets.";
    renderDriveQuality();
  } catch (err) {
    $("#dqHint").textContent = "Could not score: " + err;
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const p = $("#btnDqPick"), f = $("#btnDqFolder");
  if (p) p.onclick = () => dqScore(false);
  if (f) f.onclick = () => dqScore(true);
});
